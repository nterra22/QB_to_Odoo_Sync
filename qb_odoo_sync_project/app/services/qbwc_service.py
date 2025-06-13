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

    def _log_method_call(self, ctx):
        if ctx and hasattr(ctx, 'descriptor') and ctx.descriptor and hasattr(ctx.descriptor, 'name'):
            logger.debug("Method %s called", ctx.descriptor.name)
        else:
            logger.debug("A QBWCService method was called, but context or descriptor was not as expected.")
    @rpc(Unicode, Unicode, _returns=Iterable(Unicode))
    def authenticate(self, strUserName, strPassword):
        logger.debug("Method authenticate called")
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
            
            return [session_key, ""]
        else:
            logger.warning(f"Authentication failed for user: {strUserName}")
            return ["", "nvu"]

    @rpc(Unicode, Unicode, Unicode, Unicode, Unicode, Unicode, _returns=Unicode)
    def sendRequestXML(self, ticket, strHCPResponse, strCompanyFileName, 
                      qbXMLCountry, qbXMLMajorVers, qbXMLMinorVers):
        logger.debug("Method sendRequestXML called")
        session_data = qbwc_session_state.get(ticket)
        if not session_data:
            logger.error(f"sendRequestXML: Invalid ticket {ticket}")
            return "" # Return empty string if no valid session

        # Get current date in YYYY-MM-DD format
        today_date_str = datetime.now().strftime('%Y-%m-%d')
        
        xml_request = ""

        # Check for active invoice iterator
        invoice_iterator_id = session_data.get("invoice_iterator_id")

        if invoice_iterator_id:
            logger.info(f"Continuing InvoiceQueryRq with iteratorID: {invoice_iterator_id}")
            xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbXMLMajorVers}.{qbXMLMinorVers}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <InvoiceQueryRq requestID="2" iterator="Continue" iteratorID="{invoice_iterator_id}">
      <MaxReturned>100</MaxReturned> 
    </InvoiceQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
        else:
            # No active iterator, or previous query type completed. Start new InvoiceQuery.
            logger.info(f"Starting new InvoiceQueryRq for date: {today_date_str}")
            session_data["current_query_type"] = "Invoice" # Mark current query type
            xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbXMLMajorVers}.{qbXMLMinorVers}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <InvoiceQueryRq requestID="1">
      <TxnDateRangeFilter>
        <FromTxnDate>{today_date_str}</FromTxnDate>
        <ToTxnDate>{today_date_str}</ToTxnDate>
      </TxnDateRangeFilter>
      <IncludeLineItems>true</IncludeLineItems>
      <OwnerID>0</OwnerID> 
    </InvoiceQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
            # Clear any previous iterator ID for safety if we are starting a new query type
            if "invoice_iterator_id" in session_data:
                del session_data["invoice_iterator_id"]
        
        logger.debug(f"Sending QBXML request: {xml_request}")
        return xml_request

    @rpc(Unicode, Unicode, Unicode, Unicode, _returns=Unicode)
    def receiveResponseXML(self, ticket, response, hresult, message):
        logger.debug("Method receiveResponseXML called")
        logger.info(f"QBWC Service: receiveResponseXML called. Ticket: {ticket}")
        logger.debug(f"Received QBXML response: {response}") # Log the full response for debugging

        session_data = qbwc_session_state.get(ticket)
        if not session_data:
            logger.error(f"receiveResponseXML: Invalid ticket {ticket}")
            return "0" # Error or no progress

        current_query = session_data.get("current_query_type")
        progress = 0

        if current_query == "Invoice":
            try:
                if not response:
                    logger.warning("Received empty response for InvoiceQuery.")
                    # Consider this an end of this step or an error
                    if "invoice_iterator_id" in session_data:
                        del session_data["invoice_iterator_id"]
                    if "current_query_type" in session_data:
                        del session_data["current_query_type"]
                    return "100" # Or some error code if appropriate

                root = ET.fromstring(response)
                invoice_query_rs = root.find('.//InvoiceQueryRs')

                if invoice_query_rs is not None:
                    status_code = invoice_query_rs.get('statusCode', 'unknown')
                    status_message = invoice_query_rs.get('statusMessage', 'N/A')
                    logger.info(f"InvoiceQueryRs status: {status_code} - {status_message}")

                    if status_code == '0': # Success
                        # Process invoices here if needed in the future
                        # For now, just log them
                        invoices = invoice_query_rs.findall('.//InvoiceRet')
                        logger.info(f"Received {len(invoices)} invoices in this response.")
                        for inv in invoices:
                            txn_id = inv.find('TxnID')
                            ref_number = inv.find('RefNumber')
                            logger.info(f"  Invoice TxnID: {txn_id.text if txn_id is not None else 'N/A'}, RefNumber: {ref_number.text if ref_number is not None else 'N/A'}")

                        iterator_id = invoice_query_rs.get("iteratorID")
                        iterator_remaining_count_str = invoice_query_rs.get("iteratorRemainingCount")
                        
                        if iterator_id and iterator_remaining_count_str and int(iterator_remaining_count_str) > 0:
                            session_data["invoice_iterator_id"] = iterator_id
                            # Simple progress: 50% if iterating, 100% if done with this batch but more might come.
                            # A more accurate progress would require knowing total count beforehand.
                            progress = 50 
                            logger.info(f"Invoice iteration continues. IteratorID: {iterator_id}, Remaining: {iterator_remaining_count_str}")
                        else:
                            logger.info("Invoice iteration complete or no iterator.")
                            if "invoice_iterator_id" in session_data:
                                del session_data["invoice_iterator_id"]
                            # We could clear current_query_type here or set it to the next one
                            # For this test, we'll assume we are done with Invoices for now.
                            if "current_query_type" in session_data:
                                del session_data["current_query_type"]
                            progress = 100
                    else:
                        logger.error(f"InvoiceQueryRs failed with statusCode: {status_code}, message: {status_message}")
                        session_data["last_error"] = f"InvoiceQuery Error: {status_message}"
                        if "invoice_iterator_id" in session_data:
                            del session_data["invoice_iterator_id"]
                        if "current_query_type" in session_data:
                            del session_data["current_query_type"]
                        progress = 100 # Indicate this step is done, but with an error logged
                else:
                    logger.warning("Could not find InvoiceQueryRs in the response.")
                    # Clear iterator and query type as we don't know the state
                    if "invoice_iterator_id" in session_data:
                        del session_data["invoice_iterator_id"]
                    if "current_query_type" in session_data:
                        del session_data["current_query_type"]
                    progress = 100 # Or an error state
            except ET.ParseError as e:
                logger.error(f"Error parsing XML response: {e}")
                session_data["last_error"] = "XML Parse Error in receiveResponseXML"
                if "invoice_iterator_id" in session_data:
                    del session_data["invoice_iterator_id"]
                if "current_query_type" in session_data:
                    del session_data["current_query_type"]
                return "0" # Error
        else:
            logger.info("Received response for an unknown or completed query type.")
            # If no current_query_type is set, or it's not "Invoice", assume 100% done for whatever previous step was.
            progress = 100
            
        return str(progress)

    @rpc(Unicode, _returns=Unicode)
    def getLastError(self, ticket):
        logger.debug("Method getLastError called")
        """Get the last error message for a session."""
        logger.info(f"QBWC Service: getLastError called. Ticket: {ticket}")
        
        session_data = qbwc_session_state.get(ticket)
        if session_data:
            return session_data.get("last_error", "No error")
        return "Error: Invalid session ticket"

    @rpc(Unicode, Unicode, Unicode, _returns=Unicode)
    def connectionError(self, ticket, hresult, message):
        logger.debug("Method connectionError called")
        """Handle connection errors."""
        logger.error(f"QBWC Service: connectionError called. Ticket: {ticket}, Error: {message}")
        
        # Update session state
        if ticket in qbwc_session_state:
            qbwc_session_state[ticket]["last_error"] = f"Connection error: {message}"
        
        return "done"

    @rpc(Unicode, _returns=Unicode)
    def closeConnection(self, ticket):
        logger.debug("Method closeConnection called")
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

    @rpc(_returns=Unicode)
    def serverVersion(self):
        """Return server version information."""
        logger.debug("Method serverVersion called")
        return "1.0.0"
    
    @rpc(Unicode, _returns=Unicode)  
    def clientVersion(self, strVersion):
        """Handle client version information."""
        logger.debug("Method clientVersion called")
        logger.info(f"QBWC Service: clientVersion called with version: {strVersion}")
        # Return empty string to indicate version is supported
        return ""
