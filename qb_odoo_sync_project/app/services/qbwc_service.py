"""
QuickBooks Web Connector (QBWC) SOAP service implementation.

Implements the QBWC web service interface for communicating with QuickBooks
via the QuickBooks Web Connector application.
"""
from spyne import rpc, ServiceBase, Unicode, Iterable
from datetime import datetime
import xml.etree.ElementTree as ET
import logging
from typing import Dict, Any, Optional

# Remove import of MAX_JOURNAL_ENTRIES_PER_REQUEST from config
MAX_JOURNAL_ENTRIES_PER_REQUEST = 10  # Default value previously in config

from .odoo_service import (
    ensure_partner_exists, 
    ensure_product_exists, 
    ensure_account_exists,
    create_odoo_journal_entry,
    ensure_journal_exists
)

logger = logging.getLogger(__name__)

# Hardcoded QBWC credentials
QBWC_USERNAME = "admin"
QBWC_PASSWORD = "odoo123"

# QBWC Service State (for iterator management)
qbwc_session_state: Dict[str, Dict[str, Any]] = {}

class QBWCService(ServiceBase):
    """QuickBooks Web Connector SOAP service implementation."""
    
    @rpc(Unicode, Unicode, _returns=Iterable(Unicode))
    def authenticate(ctx, strUserName, strPassword):
        """
        Authenticate QBWC connection.
        
        Returns:
            List containing [ticket, company_file_name] or ["", error_code]
        """
        logger.info(f"QBWC Service: authenticate called. UserName: {strUserName}")
        
        if strUserName == QBWC_USERNAME and strPassword == QBWC_PASSWORD:
            logger.info("Authentication successful")
            
            # Create unique session key
            session_key = f"ticket_{int(datetime.now().timestamp())}_{strUserName}"
            qbwc_session_state[session_key] = {
                "iteratorID": None,
                "remaining": 0,
                "last_error": "No error",
                "created_at": datetime.now()
            }
            
            return [session_key, ""]  # Return ticket and empty company file filter
        else:
            logger.warning(f"Authentication failed for user: {strUserName}")
            return ["", "nvu"]  # nvu = Not Valid User

    @rpc(Unicode, Unicode, Unicode, Unicode, Unicode, Unicode, _returns=Unicode)
    def sendRequestXML(ctx, ticket, strHCPResponse, strCompanyFileName, 
                      qbXMLCountry, qbXMLMajorVers, qbXMLMinorVers):
        """
        Generate QBXML request for QuickBooks.
        
        Returns:
            QBXML request string or empty string if no request needed
        """
        logger.info(f"QBWC Service: sendRequestXML called. Ticket: {ticket}, "
                   f"Company: {strCompanyFileName}, QBXML: {qbXMLMajorVers}.{qbXMLMinorVers}")
        
        # Validate session
        session_data = qbwc_session_state.get(ticket)
        if not session_data:
            logger.error(f"sendRequestXML: Invalid ticket {ticket}")
            return ""
        
        iterator_id = session_data.get("iteratorID")
        today_date = datetime.now().strftime('%Y-%m-%d')
        
        # Build XML request
        if iterator_id:
            # Continue existing query
            xml_request = QBWCService._build_continue_request(
                QBWCService, qbXMLMajorVers, qbXMLMinorVers, iterator_id
            )
            logger.info(f"Continuing GeneralJournalQueryRq with iteratorID: {iterator_id}")
        else:
            # Start new query
            xml_request = QBWCService._build_initial_request(
                QBWCService, qbXMLMajorVers, qbXMLMinorVers, today_date
            )
            logger.info(f"Starting new GeneralJournalQueryRq for date: {today_date}")
        
        logger.debug(f"Sending QBXML request: {xml_request}")
        return xml_request
    
    def _build_initial_request(self, major_vers: str, minor_vers: str, date: str) -> str:
        """Build initial QBXML request."""
        return f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{major_vers}.{minor_vers}"?>
<QBXML>
    <QBXMLMsgsRq onError="stopOnError">
        <GeneralJournalQueryRq requestID="1">
            <TxnDateRangeFilter>
                <FromTxnDate>{date}</FromTxnDate>
                <ToTxnDate>{date}</ToTxnDate>
            </TxnDateRangeFilter>
            <IncludeLineItems>true</IncludeLineItems>
            <MaxReturned>{MAX_JOURNAL_ENTRIES_PER_REQUEST}</MaxReturned>
        </GeneralJournalQueryRq>
    </QBXMLMsgsRq>
</QBXML>'''
    
    def _build_continue_request(self, major_vers: str, minor_vers: str, iterator_id: str) -> str:
        """Build continuation QBXML request."""
        return f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{major_vers}.{minor_vers}"?>
<QBXML>
    <QBXMLMsgsRq onError="stopOnError">
        <GeneralJournalQueryRq iterator="Continue" iteratorID="{iterator_id}">
            <MaxReturned>{MAX_JOURNAL_ENTRIES_PER_REQUEST}</MaxReturned>
        </GeneralJournalQueryRq>
    </QBXMLMsgsRq>
</QBXML>'''

    @rpc(Unicode, Unicode, Unicode, Unicode, _returns=Unicode)
    def receiveResponseXML(ctx, ticket, response, hresult, message):
        """
        Process QBXML response from QuickBooks.
        
        Returns:
            Progress percentage as string ("0" for error, "100" for complete)
        """
        logger.info(f"QBWC Service: receiveResponseXML called. Ticket: {ticket}")
        
        session_data = qbwc_session_state.get(ticket)
        if not session_data:
            logger.error(f"receiveResponseXML: Invalid ticket {ticket}")
            return "0"

        # Check for QuickBooks errors
        if hresult:
            error_msg = f"QuickBooks error: HRESULT={hresult}, Message={message}"
            logger.error(error_msg)
            session_data.update({
                "last_error": error_msg,
                "iteratorID": None,
                "remaining": 0
            })
            return "0"

        try:
            return QBWCService._process_qb_response(ctx, ticket, response, session_data)
        except Exception as e:
            error_msg = f"Error processing QB response: {e}"
            logger.exception(error_msg)
            session_data["last_error"] = error_msg
            return "0"

    def _process_qb_response(self, ticket: str, response: str, session_data: Dict) -> str:
        """Process QuickBooks XML response and sync to Odoo."""
        logger.debug(f"Processing QB response (length: {len(response)})")
        
        root = ET.fromstring(response)
        
        # Find and validate the query response
        query_response_node = root.find(".//GeneralJournalQueryRs")
        if query_response_node is None:
            logger.error("GeneralJournalQueryRs node not found in response")
            session_data["last_error"] = "Invalid QB response format"
            return "0"

        # Check query status
        status_code = query_response_node.get('statusCode', '0')
        if status_code != '0':
            status_message = query_response_node.get('statusMessage', 'Unknown error')
            error_msg = f"QuickBooks query error: Code {status_code}, Message: {status_message}"
            logger.error(error_msg)
            session_data.update({
                "last_error": error_msg,
                "iteratorID": None,
                "remaining": 0
            })
            return "0"

        # Process journal entries
        processed_count = self._sync_journal_entries(query_response_node)
        
        # Handle iterator continuation
        return self._handle_iterator_response(query_response_node, session_data, processed_count)

    def _sync_journal_entries(self, query_response_node) -> int:
        """Sync journal entries from QB response to Odoo."""
        processed_count = 0
        
        for txn in query_response_node.findall("GeneralJournalTxnRet"):
            try:
                txn_id = txn.findtext("TxnID", "N/A")
                logger.info(f"Processing QB TxnID: {txn_id}")
                
                # Build Odoo journal entry structure
                odoo_entry = self._build_odoo_entry(txn)
                
                if odoo_entry and odoo_entry.get("line_ids"):
                    # Get or create default journal
                    if not odoo_entry.get("journal_id"):
                        journal_id = ensure_journal_exists("General Journal")
                        if journal_id:
                            odoo_entry["journal_id"] = journal_id
                        else:
                            logger.warning(f"No journal found for entry {txn_id}, skipping")
                            continue
                    
                    # Create the journal entry in Odoo
                    new_move_id = create_odoo_journal_entry(odoo_entry)
                    if new_move_id:
                        logger.info(f"Successfully created Odoo journal entry {new_move_id} for QB TxnID {txn_id}")
                        processed_count += 1
                    else:
                        logger.error(f"Failed to create Odoo journal entry for QB TxnID {txn_id}")
                else:
                    logger.warning(f"No valid lines for QB TxnID {txn_id}")
                    
            except Exception as e:
                logger.error(f"Error processing transaction {txn_id}: {e}", exc_info=True)
                continue
        
        return processed_count

    def _build_odoo_entry(self, txn) -> Optional[Dict[str, Any]]:
        """Build Odoo journal entry data from QB transaction."""
        odoo_entry = {
            "ref": txn.findtext("RefNumber", "QB Sync Entry"),
            "date": txn.findtext("TxnDate", datetime.now().strftime("%Y-%m-%d")),
            "journal_id": None,  # Will be set by caller
            "line_ids": []
        }
        
        # Process debit and credit lines
        for line_tag in ["JournalDebitLine", "JournalCreditLine"]:
            for line in txn.findall(f".//{line_tag}"):
                line_data = self._process_journal_line(line, line_tag)
                if line_data:
                    odoo_entry["line_ids"].append(line_data)
        
        return odoo_entry if odoo_entry["line_ids"] else None

    def _process_journal_line(self, line, line_tag: str) -> Optional[Dict[str, Any]]:
        """Process individual journal line from QB."""
        account_full_name = line.findtext("AccountRef/FullName")
        entity_full_name = line.findtext("EntityRef/FullName")
        memo = line.findtext("Memo", "")
        amount_str = line.findtext("Amount", "0.0")
        
        # Validate and parse amount
        try:
            amount = float(amount_str)
        except ValueError:
            logger.error(f"Invalid amount '{amount_str}' in journal line")
            return None
        
        # Get Odoo account
        if not account_full_name:
            logger.warning("Missing AccountRef/FullName in journal line")
            return None
            
        account_id = ensure_account_exists(account_full_name)
        if not account_id:
            logger.warning(f"Could not map QB account '{account_full_name}' to Odoo")
            return None
        
        # Get Odoo partner (optional)
        partner_id = None
        if entity_full_name:
            partner_id = ensure_partner_exists(entity_full_name)
        
        # Build line data
        return {
            "account_id": account_id,
            "partner_id": partner_id,
            "name": memo or "QB Sync Line",
            "debit": amount if line_tag == "JournalDebitLine" else 0.0,
            "credit": amount if line_tag == "JournalCreditLine" else 0.0,
        }

    def _handle_iterator_response(self, query_response_node, session_data: Dict, processed_count: int) -> str:
        """Handle QB iterator response and determine next action."""
        new_iterator_id = query_response_node.get("iteratorID")
        remaining_count_str = query_response_node.get("iteratorRemainingCount", "0")
        
        try:
            remaining_count = int(remaining_count_str)
        except ValueError:
            logger.warning(f"Invalid iteratorRemainingCount: '{remaining_count_str}'")
            remaining_count = 0
        
        # Update session state
        session_data.update({
            "iteratorID": new_iterator_id if remaining_count > 0 else None,
            "remaining": remaining_count,
            "last_error": "No error"
        })
        
        # Determine response
        if new_iterator_id and remaining_count > 0:
            if processed_count > 0:
                # Calculate rough progress percentage
                progress = min(99, max(1, int((processed_count / (remaining_count + processed_count)) * 100)))
                logger.info(f"Continuing iterator. Processed: {processed_count}, Remaining: {remaining_count}, Progress: {progress}%")
                return str(progress)
            else:
                logger.info("Iterator indicates more data but no entries processed this batch")
                return "100"
        else:
            logger.info(f"Sync complete. Total processed in this batch: {processed_count}")
            return "100"

    @rpc(Unicode, _returns=Unicode)
    def getLastError(ctx, ticket):
        """Get the last error message for a session."""
        logger.info(f"QBWC Service: getLastError called. Ticket: {ticket}")
        
        session_data = qbwc_session_state.get(ticket)
        if session_data:
            error = session_data.get("last_error", "No error recorded")
            logger.info(f"Returning last error for ticket {ticket}: {error}")
            return error
        
        logger.warning(f"getLastError: Invalid ticket {ticket}")
        return "Error: Invalid session ticket"

    @rpc(Unicode, Unicode, Unicode, _returns=Unicode)
    def connectionError(ctx, ticket, hresult, message):
        """Handle connection errors from QBWC."""
        error_msg = f"Connection error for ticket {ticket}: HRESULT={hresult}, Message={message}"
        logger.error(error_msg)
        
        session_data = qbwc_session_state.get(ticket)
        if session_data:
            session_data.update({
                "iteratorID": None,
                "remaining": 0,
                "last_error": f"Connection Error: {message}"
            })
        
        return "done"

    @rpc(Unicode, _returns=Unicode)
    def closeConnection(ctx, ticket):
        """Close and cleanup a QBWC session."""
        logger.info(f"QBWC Service: closeConnection called. Ticket: {ticket}")
        
        if ticket in qbwc_session_state:
            session_info = qbwc_session_state[ticket]
            duration = datetime.now() - session_info.get("created_at", datetime.now())
            logger.info(f"Session {ticket} closed after {duration}")
            del qbwc_session_state[ticket]
        else:
            logger.warning(f"closeConnection: Ticket {ticket} not found")
        
        return "OK"
