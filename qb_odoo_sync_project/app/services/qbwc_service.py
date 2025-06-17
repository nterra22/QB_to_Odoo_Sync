"""
QuickBooks Web Connector (QBWC) SOAP service implementation.

Implements the QBWC web service interface for communicating with QuickBooks
via the QuickBooks Web Connector application.
"""
from spyne import rpc, ServiceBase, Unicode, Iterable
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import logging
from typing import Dict, Any, Optional
import json
import inspect

# Remove import of MAX_JOURNAL_ENTRIES_PER_REQUEST from config
MAX_JOURNAL_ENTRIES_PER_REQUEST = 10  # Default value previously in config

# Define task types
QB_QUERY = "QB_QUERY"
# QB_ADD = "QB_ADD" # For Odoo to QB
# QB_MOD = "QB_MOD" # For Odoo to QB

# Define entities for QB queries
CUSTOMER_QUERY = "CustomerQuery"
VENDOR_QUERY = "VendorQuery"
INVOICE_QUERY = "InvoiceQuery"
BILL_QUERY = "BillQuery"
RECEIVEPAYMENT_QUERY = "ReceivePaymentQuery"
CREDITMEMO_QUERY = "CreditMemoQuery" # New
SALESORDER_QUERY = "SalesOrderQuery" # New
PURCHASEORDER_QUERY = "PurchaseOrderQuery" # New
JOURNALENTRY_QUERY = "JournalEntryQuery" # New
# ITEM_QUERY = "ItemQuery" # Example for future expansion

# Import Odoo service functions that will be used
from .odoo_service import (
    ensure_partner_exists, 
    ensure_product_exists, 
    ensure_account_exists,
    ensure_journal_exists,
    create_or_update_odoo_invoice,
    create_or_update_odoo_bill,
    create_or_update_odoo_payment,
    create_or_update_odoo_partner, # Added import
    create_or_update_odoo_credit_memo, # New
    create_or_update_odoo_sales_order, # New
    create_or_update_odoo_purchase_order, # New
    create_or_update_odoo_journal_entry # New
)
# from ..utils.data_loader import is_record_changed, update_sync_cache # Import cache functions

logger = logging.getLogger(__name__)

# Hardcoded QBWC credentials
QBWC_USERNAME = "admin"
QBWC_PASSWORD = "odoo123"

# QBWC Service State (for iterator management)
qbwc_session_state: Dict[str, Dict[str, Any]] = {}

SESSION_STATE_FILE = 'qbwc_session_state.json'

def load_qbwc_session_state():
    global qbwc_session_state
    try:
        with open(SESSION_STATE_FILE, 'r') as f:
            qbwc_session_state.clear()
            qbwc_session_state.update(json.load(f))
    except Exception:
        qbwc_session_state.clear()

def save_qbwc_session_state():
    try:
        with open(SESSION_STATE_FILE, 'w') as f:
            json.dump(qbwc_session_state, f, default=str)
    except Exception as e:
        logger.error(f"Failed to save QBWC session state: {e}")

# Load the session state from the file when the service module is loaded.
# This helps persist sessions across server restarts.
load_qbwc_session_state()

def _get_xml_text(element: Optional[ET.Element], default: Optional[str] = None) -> Optional[str]:
    """Safely get text from an XML element."""
    if element is not None and element.text is not None:
        return element.text.strip()
    return default

def _extract_text(element: Optional[ET.Element], path: str, default: Optional[str] = None) -> Optional[str]:
    """Safely extract text from an XML element by path."""
    if element is None:
        return default
    found_el = element.find(path)
    if found_el is not None and found_el.text:
        return found_el.text.strip()
    return default

def _extract_address_data(address_element: Optional[ET.Element], prefix: str) -> Dict[str, Any]:
    """Helper to extract address components."""
    data = {}
    if address_element is not None:
        data[f"{prefix}_Addr1"] = _extract_text(address_element, 'Addr1')
        data[f"{prefix}_Addr2"] = _extract_text(address_element, 'Addr2')
        data[f"{prefix}_Addr3"] = _extract_text(address_element, 'Addr3')
        data[f"{prefix}_Addr4"] = _extract_text(address_element, 'Addr4')
        data[f"{prefix}_Addr5"] = _extract_text(address_element, 'Addr5')
        data[f"{prefix}_City"] = _extract_text(address_element, 'City')
        data[f"{prefix}_State"] = _extract_text(address_element, 'State')
        data[f"{prefix}_PostalCode"] = _extract_text(address_element, 'PostalCode')
        data[f"{prefix}_Country"] = _extract_text(address_element, 'Country')
    return data

def _extract_transaction_data(txn_xml: ET.Element, is_sales_txn: bool) -> Dict[str, Any]:
    """
    Extracts common transaction data from QB XML Ret objects like Invoices,
    Credit Memos, Sales Orders, Purchase Orders, and Bills.
    """
    partner_ref_path = 'CustomerRef' if is_sales_txn else 'VendorRef'
    
    partner_full_name = _extract_text(txn_xml, f'{partner_ref_path}/FullName')
    partner_name_for_odoo = partner_full_name
    if partner_full_name and ':' in partner_full_name:
        partner_name_for_odoo = partner_full_name.split(':', 1)[0].strip()

    data = {
        "qb_txn_id": _extract_text(txn_xml, 'TxnID'),
        "ref_number": _extract_text(txn_xml, 'RefNumber'),
        "partner_name": partner_name_for_odoo,
        "original_partner_name": partner_full_name,
        "partner_list_id": _extract_text(txn_xml, f'{partner_ref_path}/ListID'),
        "txn_date": _extract_text(txn_xml, 'TxnDate'),
        "memo": _extract_text(txn_xml, 'Memo'),
        "lines": [],
        "expense_lines": [],
        "item_lines": []
    }

    # Common transaction fields
    data.update({
        "due_date": _extract_text(txn_xml, 'DueDate'),
        "amount_due": float(_extract_text(txn_xml, 'AmountDue', '0.0')),
        "subtotal": float(_extract_text(txn_xml, 'Subtotal', '0.0')),
        "applied_amount": float(_extract_text(txn_xml, 'AppliedAmount', '0.0')),
        "balance_remaining": float(_extract_text(txn_xml, 'BalanceRemaining', '0.0')),
    })
    if txn_xml.tag == 'InvoiceRet':
        data['is_paid'] = _extract_text(txn_xml, 'IsPaid') == 'true'
        data['sales_tax_total'] = float(_extract_text(txn_xml, 'SalesTaxTotal', '0.0'))

    # Item lines (for most transaction types)
    line_item_tag = txn_xml.tag.replace('Ret', 'LineRet')
    for line_xml in txn_xml.findall(f'.//{line_item_tag}'):
        line_data = {
            "item_name": _extract_text(line_xml, 'ItemRef/FullName'),
            "description": _extract_text(line_xml, 'Desc'),
            "quantity": float(_extract_text(line_xml, 'Quantity', '0.0')),
            "rate": float(_extract_text(line_xml, 'Rate', '0.0')),
            "cost": float(_extract_text(line_xml, 'Cost', '0.0')),
            "amount": float(_extract_text(line_xml, 'Amount', '0.0')),
        }
        data["item_lines"].append(line_data)

    # Expense lines (specifically for Bills)
    if txn_xml.tag == 'BillRet':
        for line_xml in txn_xml.findall('.//ExpenseLineRet'):
            expense_line_data = {
                "account_name": _extract_text(line_xml, 'AccountRef/FullName'),
                "amount": float(_extract_text(line_xml, 'Amount', '0.0')),
                "memo": _extract_text(line_xml, 'Memo'),
            }
            data["expense_lines"].append(expense_line_data)
            
    if data["item_lines"]:
        data["lines"] = data["item_lines"]

    return {k: v for k, v in data.items() if v is not None and v != []}

def _extract_journal_entry_data(journal_xml: ET.Element) -> Dict[str, Any]:
    """Extracts detailed data from a JournalEntryRet XML element."""
    data = {
        "qb_txn_id": _extract_text(journal_xml, 'TxnID'),
        "txn_date": _extract_text(journal_xml, 'TxnDate'),
        "ref_number": _extract_text(journal_xml, 'RefNumber'),
        "memo": _extract_text(journal_xml, 'Memo'),
        "lines": []
    }

    for line_xml in journal_xml.findall('.//JournalCreditLine'):
        line_data = {
            "type": "credit",
            "account_name": _extract_text(line_xml, 'AccountRef/FullName'),
            "amount": float(_extract_text(line_xml, 'Amount', '0.0')),
            "memo": _extract_text(line_xml, 'Memo'),
            "entity_name": _extract_text(line_xml, 'EntityRef/FullName'),
        }
        data["lines"].append(line_data)

    for line_xml in journal_xml.findall('.//JournalDebitLine'):
        line_data = {
            "type": "debit",
            "account_name": _extract_text(line_xml, 'AccountRef/FullName'),
            "amount": float(_extract_text(line_xml, 'Amount', '0.0')),
            "memo": _extract_text(line_xml, 'Memo'),
            "entity_name": _extract_text(line_xml, 'EntityRef/FullName'),
        }
        data["lines"].append(line_data)
        
    return {k: v for k, v in data.items() if v is not None and v != []}

def _extract_customer_data_from_ret(customer_ret_xml: ET.Element) -> Dict[str, Any]:
    """Extracts detailed customer data from a CustomerRet XML element."""
    data = {
        "ListID": _extract_text(customer_ret_xml, 'ListID'),
        "Name": _extract_text(customer_ret_xml, 'Name'),
        "FullName": _extract_text(customer_ret_xml, 'FullName'),
        "CompanyName": _extract_text(customer_ret_xml, 'CompanyName'),
        "FirstName": _extract_text(customer_ret_xml, 'FirstName'),
        "LastName": _extract_text(customer_ret_xml, 'LastName'),
        "Email": _extract_text(customer_ret_xml, 'Email'),
        "Phone": _extract_text(customer_ret_xml, 'Phone'),
        "AltPhone": _extract_text(customer_ret_xml, 'AltPhone'),
        "Fax": _extract_text(customer_ret_xml, 'Fax'),
        "Contact": _extract_text(customer_ret_xml, 'Contact'),
        "AltContact": _extract_text(customer_ret_xml, 'AltContact'),
        "Notes": _extract_text(customer_ret_xml, 'Notes'),
        "IsActive": _extract_text(customer_ret_xml, 'IsActive') == 'true',
        "Sublevel": _extract_text(customer_ret_xml, 'Sublevel'),
        "ParentRef_ListID": _extract_text(customer_ret_xml, 'ParentRef/ListID'),
        "ParentRef_FullName": _extract_text(customer_ret_xml, 'ParentRef/FullName'),
        "CustomerTypeRef_ListID": _extract_text(customer_ret_xml, 'CustomerTypeRef/ListID'),
        "CustomerTypeRef_FullName": _extract_text(customer_ret_xml, 'CustomerTypeRef/FullName'),
        "TermsRef_ListID": _extract_text(customer_ret_xml, 'TermsRef/ListID'),
        "TermsRef_FullName": _extract_text(customer_ret_xml, 'TermsRef/FullName'),
        "SalesRepRef_ListID": _extract_text(customer_ret_xml, 'SalesRepRef/ListID'),
        "SalesRepRef_FullName": _extract_text(customer_ret_xml, 'SalesRepRef/FullName'),
        "Balance": _extract_text(customer_ret_xml, 'Balance'),
        "TotalBalance": _extract_text(customer_ret_xml, 'TotalBalance'),
        "JobStatus": _extract_text(customer_ret_xml, 'JobStatus'),
    }
    data.update(_extract_address_data(customer_ret_xml.find('BillAddress'), 'BillAddress'))
    data.update(_extract_address_data(customer_ret_xml.find('ShipAddress'), 'ShipAddress'))
    
    # Extract additional contacts if present (ContactsRet)
    # This part might need adjustment based on how you want to map multiple contacts in Odoo
    contacts_ret = customer_ret_xml.findall('ContactsRet')
    additional_contacts = []
    for contact_xml in contacts_ret:
        additional_contacts.append({
            "ListID": _extract_text(contact_xml, 'ListID'),
            "FirstName": _extract_text(contact_xml, 'FirstName'),
            "LastName": _extract_text(contact_xml, 'LastName'),
            "Salutation": _extract_text(contact_xml, 'Salutation'),
        })
    if additional_contacts:
        data["AdditionalContacts"] = additional_contacts

    # Filter out None values to keep the payload clean
    return {k: v for k, v in data.items() if v is not None}

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
            
            session_key = f"ticket_{int(datetime.now().timestamp())}_{strUserName}"
            
            initial_tasks = [
                {
                    "type": QB_QUERY, 
                    "entity": CUSTOMER_QUERY, 
                    "requestID": "1",
                    "iteratorID": None,
                    "params": { 
                        "ModifiedDateRangeFilter": { # Keep this for customers
                            "FromModifiedDate": "1980-01-01" 
                        }
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": VENDOR_QUERY,
                    "requestID": "1",
                    "iteratorID": None,
                    "params": { # Keep this for vendors
                        "ModifiedDateRangeFilter": {
                            "FromModifiedDate": "1980-01-01"
                        }
                    }
                },
                # { # Example for ItemQuery if added later
                #     "type": QB_QUERY,
                #     "entity": ITEM_QUERY,
                #     "requestID": "1",
                #     "iteratorID": None,
                #     "params": {}
                # },
                {
                    "type": QB_QUERY,
                    "entity": INVOICE_QUERY,
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        "IncludeLineItems": "true" # No date filter, fetch all
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": BILL_QUERY,
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        # "TxnDateRangeFilter" removed
                        "IncludeLineItems": "true",
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": RECEIVEPAYMENT_QUERY,
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        # "TxnDateRangeFilter" removed
                        # IncludeLineItems is added in sendRequestXML for this query type
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": CREDITMEMO_QUERY, 
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        # "TxnDateRangeFilter" removed
                        "IncludeLineItems": "true"
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": SALESORDER_QUERY, 
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        # "TxnDateRangeFilter" removed
                        "IncludeLineItems": "true"
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": PURCHASEORDER_QUERY, 
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        # "TxnDateRangeFilter" removed
                        "IncludeLineItems": "true"
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": JOURNALENTRY_QUERY, 
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        # "TxnDateRangeFilter" removed
                        "IncludeLineItems": "true" 
                    }
                }
                # TODO: Add tasks for fetching data from Odoo to send to QB (QB_ADD, QB_MOD types)
            ]

            qbwc_session_state[session_key] = {
                "task_queue": initial_tasks,
                "current_task_index": 0, # Pointer to the current task in the queue
                "last_error": "No error",
                "created_at": datetime.now(),
                "company_file_name": None, # Will be set by QBWC
                "qbxml_version": None # Will be set by QBWC
            }
            save_qbwc_session_state()
            
            return [session_key, ""] # Empty string for company file path, QBWC will fill it
        else:
            logger.warning(f"Authentication failed for user: {strUserName}")
            return ["", "nvu"]    @rpc(Unicode, Unicode, Unicode, Unicode, Unicode, Unicode, _returns=Unicode)
    def sendRequestXML(self, ticket, strHCPResponse, strCompanyFileName, 
                      qbXMLCountry, qbXMLMajorVers, qbXMLMinorVers):
        
        logger.debug("Method sendRequestXML called")
        logger.info(f"sendRequestXML invoked with ticket: {ticket}")

        # Enhanced session validation
        session_data = qbwc_session_state.get(ticket)
        
        if not session_data:
            logger.error(f"sendRequestXML: Invalid or expired ticket {ticket}. No session data found.")
            # Store error for getLastError
            qbwc_session_state[ticket] = {
                "last_error": f"Invalid or expired session ticket: {ticket}",
                "created_at": datetime.now()
            }
            save_qbwc_session_state()
            return "" # Return empty string to signal no more requests

        # Check if session is too old (older than 1 hour)
        session_age = datetime.now() - session_data.get("created_at", datetime.now())
        if session_age > timedelta(hours=1):
            logger.warning(f"sendRequestXML: Session {ticket} is too old ({session_age}). Cleaning up.")
            session_data["last_error"] = f"Session expired after {session_age}"
            save_qbwc_session_state()
            return ""

        logger.info(f"sendRequestXML: Retrieved valid session_data for ticket: {ticket}")

        # Store company file and QBXML version info from QBWC
        session_data["company_file_name"] = strCompanyFileName
        session_data["qbxml_version"] = f"{qbXMLMajorVers}.{qbXMLMinorVers}"
        session_data["last_activity"] = datetime.now()  # Track last activity
        logger.info(f"sendRequestXML: CompanyFileName='{strCompanyFileName}', QBXMLVersion='{session_data['qbxml_version']}'")

        task_queue = session_data.get("task_queue", [])
        current_task_index = session_data.get("current_task_index", 0)
        logger.info(f"sendRequestXML: Task Queue (length {len(task_queue)}), Current Task Index: {current_task_index}")

        if current_task_index >= len(task_queue):
            logger.info("sendRequestXML: All tasks completed for this session.")
            return "" # No more requests

        current_task = task_queue[current_task_index]
        session_data["active_task"] = current_task
        save_qbwc_session_state()

        # Validate and build XML request
        try:
            xml_request = self._build_xml_request(current_task, session_data)
            logger.debug(f"Built XML request: {xml_request[:500]}...")  # Log first 500 chars
            return xml_request
        except Exception as e:
            logger.error(f"Error building XML request: {e}", exc_info=True)
            session_data["last_error"] = f"XML generation error: {str(e)}"
            save_qbwc_session_state()
            return ""

    def _build_xml_request(self, current_task, session_data):
        """Build and validate XML request for the current task."""
        xml_request = ""
        request_id_str = current_task.get("requestID", "1")
        qbxml_version = session_data.get("qbxml_version", "13.0")

        if current_task["type"] == QB_QUERY:
            entity = current_task["entity"]
            iterator_id = current_task.get("iteratorID")
            qbxml_version = session_data.get("qbxml_version", "13.0") # Default to 13.0 if not set

            # Helper to build TxnDateRangeFilter XML
            def get_txn_date_filter_xml(params):
                if "TxnDateRangeFilter" in params:
                    return f'''<TxnDateRangeFilter>
        <FromTxnDate>{params["TxnDateRangeFilter"]["FromTxnDate"]}</FromTxnDate>
        <ToTxnDate>{params["TxnDateRangeFilter"]["ToTxnDate"]}</ToTxnDate>
      </TxnDateRangeFilter>'''
                return ""

            # Helper to build IncludeLineItems XML
            def get_include_line_items_xml(params):
                if "IncludeLineItems" in params:
                    return f'''<IncludeLineItems>{params["IncludeLineItems"]}</IncludeLineItems>'''
                return ""

            if entity == CUSTOMER_QUERY:
                if iterator_id:
                    logger.info(f"Continuing CustomerQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <CustomerQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>20</MaxReturned>
    </CustomerQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
                else:
                    logger.info("Starting new CustomerQueryRq.")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <CustomerQueryRq requestID="{request_id_str}">
      <!-- <ActiveStatus>ActiveOnly</ActiveStatus> -->
      <MaxReturned>20</MaxReturned>
    </CustomerQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
            
            elif entity == VENDOR_QUERY:
                if iterator_id:
                    logger.info(f"Continuing VendorQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <VendorQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>20</MaxReturned>
    </VendorQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
                else:
                    logger.info("Starting new VendorQueryRq.")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <VendorQueryRq requestID="{request_id_str}">
      <!-- <ActiveStatus>ActiveOnly</ActiveStatus> -->
      <MaxReturned>20</MaxReturned>
    </VendorQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''

            elif entity == INVOICE_QUERY:
                params = current_task.get("params", {})
                # Remove date filter XML generation
                modified_date_filter_xml = ""
                txn_date_filter_xml = ""

                include_line_items_xml = f'''<IncludeLineItems>{params["IncludeLineItems"]}</IncludeLineItems>''' if "IncludeLineItems" in params else ""
                owner_id_xml = f'''<OwnerID>{params["OwnerID"]}</OwnerID>''' if "OwnerID" in params else ""

                if iterator_id:
                    logger.info(f"Continuing InvoiceQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <InvoiceQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>10</MaxReturned> 
    </InvoiceQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
                else:
                    logger.info("Starting new InvoiceQueryRq without date filters.")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <InvoiceQueryRq requestID="{request_id_str}">
      {include_line_items_xml}
      {owner_id_xml}
      <MaxReturned>10</MaxReturned> 
    </InvoiceQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
            elif entity == BILL_QUERY:
                params = current_task.get("params", {})
                txn_date_filter_xml = ""
                if "TxnDateRangeFilter" in params:
                    txn_date_filter_xml = f'''<TxnDateRangeFilter>
        <FromTxnDate>{params["TxnDateRangeFilter"]["FromTxnDate"]}</FromTxnDate>
        <ToTxnDate>{params["TxnDateRangeFilter"]["ToTxnDate"]}</ToTxnDate>
      </TxnDateRangeFilter>'''
                include_line_items_xml = f'''<IncludeLineItems>{params["IncludeLineItems"]}</IncludeLineItems>''' if "IncludeLineItems" in params else ""

                if iterator_id:
                    logger.info(f"Continuing BillQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <BillQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>20</MaxReturned> 
    </BillQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
                else:
                    logger.info(f"Starting new BillQueryRq for date: {params.get('TxnDateRangeFilter', {}).get('FromTxnDate', 'N/A')}.")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <BillQueryRq requestID="{request_id_str}">
      {txn_date_filter_xml}
      {include_line_items_xml}
      <MaxReturned>20</MaxReturned> 
    </BillQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
            elif entity == RECEIVEPAYMENT_QUERY:
                params = current_task.get("params", {})
                txn_date_filter_xml = ""
                if "TxnDateRangeFilter" in params:
                    txn_date_filter_xml = f'''<TxnDateRangeFilter>
                        <FromTxnDate>{params["TxnDateRangeFilter"]["FromTxnDate"]}</FromTxnDate>
                        <ToTxnDate>{params["TxnDateRangeFilter"]["ToTxnDate"]}</ToTxnDate>
                    </TxnDateRangeFilter>'''
                
                if iterator_id:
                    logger.info(f"Continuing ReceivePaymentQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <ReceivePaymentQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>20</MaxReturned>
    </ReceivePaymentQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
                else:
                    logger.info(f"Starting new ReceivePaymentQueryRq for date: {params.get('TxnDateRangeFilter', {}).get('FromTxnDate', 'N/A')}.")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <ReceivePaymentQueryRq requestID="{request_id_str}">
      {txn_date_filter_xml}
      <IncludeLineItems>true</IncludeLineItems> <!-- To see which invoices are paid -->
      <MaxReturned>20</MaxReturned>
    </ReceivePaymentQueryRq>
  </QBXML>
</QBXML>'''

            elif entity == CREDITMEMO_QUERY: # New
                params = current_task.get("params", {})
                txn_date_filter_xml = get_txn_date_filter_xml(params)
                include_line_items_xml = get_include_line_items_xml(params)
                if iterator_id:
                    logger.info(f"Continuing CreditMemoQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <CreditMemoQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>20</MaxReturned>
    </CreditMemoQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
                else:
                    logger.info(f"Starting new CreditMemoQueryRq for date: {params.get('TxnDateRangeFilter', {}).get('FromTxnDate', 'N/A')}.")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <CreditMemoQueryRq requestID="{request_id_str}">
      {txn_date_filter_xml}
      {include_line_items_xml}
      <MaxReturned>20</MaxReturned>
    </CreditMemoQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
            elif entity == SALESORDER_QUERY: # New
                params = current_task.get("params", {})
                txn_date_filter_xml = get_txn_date_filter_xml(params)
                include_line_items_xml = get_include_line_items_xml(params)
                if iterator_id:
                    logger.info(f"Continuing SalesOrderQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <SalesOrderQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>20</MaxReturned>
    </SalesOrderQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
                else:
                    logger.info(f"Starting new SalesOrderQueryRq for date: {params.get('TxnDateRangeFilter', {}).get('FromTxnDate', 'N/A')}.")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <SalesOrderQueryRq requestID="{request_id_str}">
      {txn_date_filter_xml}
      {include_line_items_xml}
      <MaxReturned>20</MaxReturned>
    </SalesOrderQueryRq>
  </QBXML>
</QBXML>'''
            elif entity == PURCHASEORDER_QUERY: # New
                params = current_task.get("params", {})
                txn_date_filter_xml = get_txn_date_filter_xml(params)
                include_line_items_xml = get_include_line_items_xml(params)
                if iterator_id:
                    logger.info(f"Continuing PurchaseOrderQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <PurchaseOrderQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>20</MaxReturned>
    </PurchaseOrderQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
                else:
                    logger.info(f"Starting new PurchaseOrderQueryRq for date: {params.get('TxnDateRangeFilter', {}).get('FromTxnDate', 'N/A')}.")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <PurchaseOrderQueryRq requestID="{request_id_str}">
      {txn_date_filter_xml}
      {include_line_items_xml}
      <MaxReturned>20</MaxReturned>
    </PurchaseOrderQueryRq>
  </QBXML>
</QBXML>'''
            elif entity == JOURNALENTRY_QUERY: # New
                params = current_task.get("params", {})
                txn_date_filter_xml = get_txn_date_filter_xml(params)
                # IncludeLineItems is typically true for Journal Entries by default in QB, but explicit is good.
                include_line_items_xml = f'''<IncludeLineItems>true</IncludeLineItems>'''

                if iterator_id:
                    logger.info(f"Continuing JournalEntryQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <JournalEntryQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>{MAX_JOURNAL_ENTRIES_PER_REQUEST}</MaxReturned> 
    </JournalEntryQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
                else:
                    logger.info(f"Starting new JournalEntryQueryRq for date: {params.get('TxnDateRangeFilter', {}).get('FromTxnDate', 'N/A')}.")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <JournalEntryQueryRq requestID="{request_id_str}">
      {txn_date_filter_xml}
      {include_line_items_xml}
      <MaxReturned>{MAX_JOURNAL_ENTRIES_PER_REQUEST}</MaxReturned> 
    </JournalEntryQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''        # Add other QB_QUERY entity types (Vendor, Item, etc.) here in the future
        # Add QB_ADD, QB_MOD task types here in the future for Odoo to QB sync

        # Validate XML before returning
        if xml_request:
            try:
                # Parse the XML to ensure it's well-formed
                ET.fromstring(xml_request)
                logger.debug(f"XML validation successful for {current_task.get('entity', 'unknown')} request")
            except ET.ParseError as e:
                logger.error(f"Generated XML is malformed: {e}")
                logger.error(f"Malformed XML content: {xml_request}")
                raise Exception(f"XML validation failed: {e}")
        
        logger.debug(f"Sending QBXML request for task type {current_task['type']}, entity {current_task.get('entity', 'N/A')}: {xml_request[:200]}...")
        return xml_request    @rpc(Unicode, Unicode, Unicode, Unicode, _returns=Unicode)
    def receiveResponseXML(self, ticket, response, hresult, message):
        """
        Process the XML response from QuickBooks.
        """
        self._log_method_call(inspect.currentframe().f_code.co_name)
        logger.info(f"receiveResponseXML called with ticket: {ticket}")

        session_data = qbwc_session_state.get(ticket)
        if not session_data:
            logger.error(f"Invalid ticket {ticket}. Session not found.")
            return "0"

        active_task = session_data.get("active_task")
        if not active_task:
            logger.error("No active task found for the session.")
            # This can happen if receiveResponseXML is called unexpectedly.
            # We can either return an error or just ignore it.
            return "0"

        progress = 0
        total_tasks = len(session_data.get("task_queue", []))

        try:
            if not response:
                logger.warning("Received an empty response from QuickBooks. This may happen if the query returns no data.")
                # This is not necessarily an error, so we move to the next task.
                session_data["current_task_index"] += 1
                progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                save_qbwc_session_state()
                return str(progress)

            # Validate response XML
            try:
                root = ET.fromstring(response)
            except ET.ParseError as e:
                logger.error(f"Failed to parse QuickBooks response XML: {e}")
                logger.error(f"Malformed response: {response[:500]}...")
                session_data["last_error"] = f"QuickBooks returned malformed XML: {str(e)}"
                save_qbwc_session_state()
                return "0"  # Signal error to QBWC
            
            entity = active_task.get("entity")

            if entity == CUSTOMER_QUERY:
                customer_query_rs = root.find('.//CustomerQueryRs')
                if customer_query_rs is not None:
                    status_code = customer_query_rs.get('statusCode', 'unknown')
                    status_message = customer_query_rs.get('statusMessage', 'N/A')
                    logger.info(f"CustomerQueryRs status: {status_code} - {status_message}")

                    if status_code == '0':
                        customers = customer_query_rs.findall('.//CustomerRet')
                        logger.info(f"Received {len(customers)} customers in this response.")
                        for customer_xml in customers:
                            try:
                                qb_customer_data = _extract_customer_data_from_ret(customer_xml)
                                logger.info(f"  Processing Customer ListID: {qb_customer_data.get('ListID')}, Name: {qb_customer_data.get('FullName')}")
                                odoo_partner_id = create_or_update_odoo_partner(qb_customer_data)
                                if odoo_partner_id:
                                    logger.info(f"    Successfully processed customer {qb_customer_data.get('FullName')} for Odoo (Odoo ID: {odoo_partner_id}).")
                                else:
                                    logger.warning(f"    Customer {qb_customer_data.get('FullName')} processed but no Odoo ID returned.")
                            except Exception as e:
                                list_id_for_error = _extract_text(customer_xml, 'ListID', 'N/A')
                                logger.error(f"    Error processing Customer {list_id_for_error} for Odoo: {e}", exc_info=True)

                        iterator_id = customer_query_rs.get("iteratorID")
                        iterator_remaining_count = customer_query_rs.get("iteratorRemainingCount")
                        if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                            active_task["iteratorID"] = iterator_id
                            active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                            progress = 50  # Indicate that this task is ongoing
                        else:
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                    else:
                        logger.error(f"CustomerQueryRs failed: {status_message}")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                else:
                    logger.warning("Could not find CustomerQueryRs in response.")
                    active_task["iteratorID"] = None
                    session_data["current_task_index"] += 1
                    progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100

            elif entity == VENDOR_QUERY:
                vendor_query_rs = root.find('.//VendorQueryRs')
                if vendor_query_rs is not None:
                    status_code = vendor_query_rs.get('statusCode', 'unknown')
                    status_message = vendor_query_rs.get('statusMessage', 'N/A')
                    logger.info(f"VendorQueryRs status: {status_code} - {status_message}")

                    if status_code == '0':
                        vendors = vendor_query_rs.findall('.//VendorRet')
                        logger.info(f"Received {len(vendors)} vendors in this response.")
                        for vendor_xml in vendors:
                            try:
                                # Assuming _extract_customer_data_from_ret can also process VendorRet structure
                                qb_vendor_data = _extract_customer_data_from_ret(vendor_xml)
                                logger.info(f"  Processing Vendor ListID: {qb_vendor_data.get('ListID')}, Name: {qb_vendor_data.get('FullName')}")
                                odoo_partner_id = create_or_update_odoo_partner(qb_vendor_data, is_vendor=True)
                                if odoo_partner_id:
                                    logger.info(f"    Successfully processed vendor {qb_vendor_data.get('FullName')} for Odoo (Odoo ID: {odoo_partner_id}).")
                                else:
                                    logger.warning(f"    Vendor {qb_vendor_data.get('FullName')} processed but no Odoo ID returned.")
                            except Exception as e:
                                list_id_for_error = _extract_text(vendor_xml, 'ListID', 'N/A')
                                logger.error(f"    Error processing Vendor {list_id_for_error} for Odoo: {e}", exc_info=True)

                        iterator_id = vendor_query_rs.get("iteratorID")
                        iterator_remaining_count = vendor_query_rs.get("iteratorRemainingCount")
                        if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                            active_task["iteratorID"] = iterator_id
                            active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                            progress = 50
                        else:
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                    else:
                        logger.error(f"VendorQueryRs failed: {status_message}")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                else:
                    logger.warning("Could not find VendorQueryRs in response.")
                    active_task["iteratorID"] = None
                    session_data["current_task_index"] += 1
                    progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100

            elif entity == INVOICE_QUERY:
                invoice_query_rs = root.find('.//InvoiceQueryRs')
                if invoice_query_rs is not None:
                    status_code = invoice_query_rs.get('statusCode', 'unknown')
                    status_message = invoice_query_rs.get('statusMessage', 'N/A')
                    logger.info(f"InvoiceQueryRs status: {status_code} - {status_message}")

                    if status_code == '0':
                        invoices = invoice_query_rs.findall('.//InvoiceRet')
                        logger.info(f"Received {len(invoices)} invoices in this response.")
                        for invoice_xml in invoices:
                            try:
                                qb_invoice_data = _extract_transaction_data(invoice_xml, is_sales_txn=True)
                                logger.info(f"  Processing Invoice TxnID: {qb_invoice_data.get('qb_txn_id')}, Ref: {qb_invoice_data.get('ref_number')}")

                                if not qb_invoice_data.get("partner_name"):
                                    logger.warning(f"    Invoice {qb_invoice_data.get('qb_txn_id')} has no customer name. Skipping Odoo processing.")
                                    continue
                                
                                odoo_invoice_id = create_or_update_odoo_invoice(qb_invoice_data)
                                if odoo_invoice_id:
                                    logger.info(f"    Successfully processed Invoice {qb_invoice_data.get('qb_txn_id')} for Odoo (Odoo ID: {odoo_invoice_id}).")
                                else:
                                    logger.warning(f"    Invoice {qb_invoice_data.get('qb_txn_id')} processed for Odoo but no Odoo ID returned (may indicate create/update issue or placeholder).")
                            except Exception as e:
                                txn_id_for_error = _extract_text(invoice_xml, 'TxnID', 'N/A')
                                logger.error(f"    Error processing Invoice {txn_id_for_error} for Odoo: {e}", exc_info=True)

                        iterator_id = invoice_query_rs.get("iteratorID")
                        iterator_remaining_count = invoice_query_rs.get("iteratorRemainingCount")
                        
                        if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                            active_task["iteratorID"] = iterator_id
                            active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                            progress = 50 
                            logger.info(f"Invoice iteration continues. IteratorID: {iterator_id}, Remaining: {iterator_remaining_count}")
                        else:
                            logger.info("Invoice iteration complete or no iterator.")
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                    else:
                        logger.error(f"InvoiceQueryRs failed with statusCode: {status_code}, message: {status_message}")
                        session_data["last_error"] = f"InvoiceQuery Error: {status_message}"
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                else:
                    logger.warning("Could not find InvoiceQueryRs in the response.")
                    active_task["iteratorID"] = None
                    session_data["current_task_index"] += 1
                    progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
            elif entity == BILL_QUERY:
                bill_query_rs = root.find('.//BillQueryRs')
                if bill_query_rs is not None:
                    status_code = bill_query_rs.get('statusCode', 'unknown')
                    status_message = bill_query_rs.get('statusMessage', 'N/A')
                    logger.info(f"BillQueryRs status: {status_code} - {status_message}")

                    if status_code == '0':
                        bills = bill_query_rs.findall('.//BillRet')
                        logger.info(f"Received {len(bills)} bills in this response.")
                        for bill_xml in bills:
                            try:
                                qb_bill_data = _extract_transaction_data(bill_xml, is_sales_txn=False)
                                logger.info(f"  Processing Bill TxnID: {qb_bill_data.get('qb_txn_id')}, Ref: {qb_bill_data.get('ref_number')}")

                                if not qb_bill_data.get("partner_name"):
                                    logger.warning(f"    Bill {qb_bill_data.get('qb_txn_id')} has no vendor name. Skipping Odoo processing.")
                                    continue

                                odoo_bill_id = create_or_update_odoo_bill(qb_bill_data)
                                if odoo_bill_id:
                                    logger.info(f"    Successfully processed Bill {qb_bill_data.get('qb_txn_id')} for Odoo (Odoo ID: {odoo_bill_id}).")
                                else:
                                    logger.warning(f"    Bill {qb_bill_data.get('qb_txn_id')} processed for Odoo but no Odoo ID returned.")
                            except Exception as e:
                                txn_id_for_error = _extract_text(bill_xml, 'TxnID', 'N/A')
                                logger.error(f"    Error processing Bill {txn_id_for_error} for Odoo: {e}", exc_info=True)

                        iterator_id = bill_query_rs.get("iteratorID")
                        iterator_remaining_count = bill_query_rs.get("iteratorRemainingCount")
                        if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                            active_task["iteratorID"] = iterator_id
                            active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                            progress = 50
                        else:
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                    else:
                        logger.error(f"BillQueryRs failed: {status_message}")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                else:
                    logger.warning("Could not find BillQueryRs in response.")
                    active_task["iteratorID"] = None
                    session_data["current_task_index"] += 1
                    progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100

            elif entity == RECEIVEPAYMENT_QUERY:
                payment_query_rs = root.find('.//ReceivePaymentQueryRs')
                if payment_query_rs is not None:
                    status_code = payment_query_rs.get('statusCode', 'unknown')
                    status_message = payment_query_rs.get('statusMessage', 'N/A')
                    logger.info(f"ReceivePaymentQueryRs status: {status_code} - {status_message}")

                    if status_code == '0':
                        payments = payment_query_rs.findall('.//ReceivePaymentRet')
                        logger.info(f"Received {len(payments)} payments in this response.")
                        for payment_xml in payments:
                            try:
                                qb_payment_data = {
                                    "qb_txn_id": _extract_text(payment_xml, 'TxnID'),
                                    "customer_name": _extract_text(payment_xml, 'CustomerRef/FullName'),
                                    "txn_date": _extract_text(payment_xml, 'TxnDate'),
                                    "ref_number": _extract_text(payment_xml, 'RefNumber'),
                                    "total_amount": float(_extract_text(payment_xml, 'TotalAmount', '0.0')),
                                    "memo": _extract_text(payment_xml, 'Memo'),
                                    "applied_to_txns": []
                                }
                                logger.info(f"  Processing Payment TxnID: {qb_payment_data['qb_txn_id']}, Ref: {qb_payment_data['ref_number']}")

                                if not qb_payment_data["customer_name"]:
                                    logger.warning(f"    Payment {qb_payment_data['qb_txn_id']} has no customer name. Skipping Odoo processing.")
                                    continue
                                
                                for applied_txn_xml in payment_xml.findall('.//AppliedToTxnRet'):
                                    applied_data = {
                                        "applied_qb_invoice_txn_id": _extract_text(applied_txn_xml, 'TxnID'),
                                        "payment_amount": float(_extract_text(applied_txn_xml, 'PaymentAmount', '0.0'))
                                    }
                                    qb_payment_data["applied_to_txns"].append(applied_data)
                                
                                odoo_payment_id = create_or_update_odoo_payment(qb_payment_data)
                                if odoo_payment_id:
                                    logger.info(f"    Successfully processed Payment {qb_payment_data['qb_txn_id']} for Odoo (Odoo ID: {odoo_payment_id}).")
                                else:
                                    logger.warning(f"    Payment {qb_payment_data['qb_txn_id']} processed for Odoo but no Odoo ID returned.")
                            except Exception as e:
                                txn_id_for_error = _extract_text(payment_xml, 'TxnID', 'N/A')
                                logger.error(f"    Error processing Payment {txn_id_for_error} for Odoo: {e}", exc_info=True)
                        
                        iterator_id = payment_query_rs.get("iteratorID")
                        iterator_remaining_count = payment_query_rs.get("iteratorRemainingCount")
                        if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                            active_task["iteratorID"] = iterator_id
                            active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                            progress = 50
                        else:
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                    else:
                        logger.error(f"ReceivePaymentQueryRs failed: {status_message}")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                else:
                    logger.warning("Could not find ReceivePaymentQueryRs in response.")
                    active_task["iteratorID"] = None
                    session_data["current_task_index"] += 1
                    progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100

            elif entity == CREDITMEMO_QUERY:
                credit_memo_query_rs = root.find('.//CreditMemoQueryRs')
                if credit_memo_query_rs is not None:
                    status_code = credit_memo_query_rs.get('statusCode', 'unknown')
                    status_message = credit_memo_query_rs.get('statusMessage', 'N/A')
                    logger.info(f"CreditMemoQueryRs status: {status_code} - {status_message}")

                    if status_code == '0':
                        credit_memos = credit_memo_query_rs.findall('.//CreditMemoRet')
                        logger.info(f"Received {len(credit_memos)} credit memos in this response.")
                        for cm_xml in credit_memos:
                            try:
                                qb_cm_data = _extract_transaction_data(cm_xml, is_sales_txn=True)
                                logger.info(f"  Processing Credit Memo TxnID: {qb_cm_data.get('qb_txn_id')}, Ref: {qb_cm_data.get('ref_number')}")
                                odoo_cm_id = create_or_update_odoo_credit_memo(qb_cm_data)
                                if odoo_cm_id:
                                    logger.info(f"    Successfully processed Credit Memo {qb_cm_data.get('qb_txn_id')} for Odoo (Odoo ID: {odoo_cm_id}).")
                                else:
                                    logger.warning(f"    Credit Memo {qb_cm_data.get('qb_txn_id')} processed for Odoo but no Odoo ID returned.")
                            except Exception as e:
                                txn_id_for_error = _extract_text(cm_xml, 'TxnID', 'N/A')
                                logger.error(f"    Error processing Credit Memo {txn_id_for_error} for Odoo: {e}", exc_info=True)
                        
                        iterator_id = credit_memo_query_rs.get("iteratorID")
                        iterator_remaining_count = credit_memo_query_rs.get("iteratorRemainingCount")
                        if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                            active_task["iteratorID"] = iterator_id
                            active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                            progress = 50
                        else:
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                    else:
                        logger.error(f"CreditMemoQueryRs failed: {status_message}")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                else:
                    logger.warning("Could not find CreditMemoQueryRs in response.")
                    active_task["iteratorID"] = None
                    session_data["current_task_index"] += 1
                    progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
            
            elif entity == SALESORDER_QUERY:
                sales_order_query_rs = root.find('.//SalesOrderQueryRs')
                if sales_order_query_rs is not None:
                    status_code = sales_order_query_rs.get('statusCode', 'unknown')
                    status_message = sales_order_query_rs.get('statusMessage', 'N/A')
                    logger.info(f"SalesOrderQueryRs status: {status_code} - {status_message}")

                    if status_code == '0': 
                        sales_orders = sales_order_query_rs.findall('.//SalesOrderRet')
                        logger.info(f"Received {len(sales_orders)} sales orders in this response.")
                        for so_xml in sales_orders:
                            try:
                                qb_so_data = _extract_transaction_data(so_xml, is_sales_txn=True)
                                logger.info(f"  Processing Sales Order TxnID: {qb_so_data.get('qb_txn_id')}, Ref: {qb_so_data.get('ref_number')}")
                                odoo_so_id = create_or_update_odoo_sales_order(qb_so_data)
                                if odoo_so_id:
                                    logger.info(f"    Successfully processed Sales Order {qb_so_data.get('qb_txn_id')} for Odoo (Odoo ID: {odoo_so_id}).")
                                else:
                                    logger.warning(f"    Sales Order {qb_so_data.get('qb_txn_id')} processed for Odoo but no Odoo ID returned.")
                            except Exception as e:
                                txn_id_for_error = _extract_text(so_xml, 'TxnID', 'N/A')
                                logger.error(f"    Error processing Sales Order {txn_id_for_error} for Odoo: {e}", exc_info=True)
                        
                        iterator_id = sales_order_query_rs.get("iteratorID")
                        iterator_remaining_count = sales_order_query_rs.get("iteratorRemainingCount")
                        if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                            active_task["iteratorID"] = iterator_id
                            active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                            progress = 50
                        else:
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                    else:
                        logger.error(f"SalesOrderQueryRs failed: {status_message}")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                else:
                    logger.warning("Could not find SalesOrderQueryRs in response.")
                    active_task["iteratorID"] = None
                    session_data["current_task_index"] += 1
                    progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100

            elif entity == PURCHASEORDER_QUERY:
                purchase_order_query_rs = root.find('.//PurchaseOrderQueryRs')
                if purchase_order_query_rs is not None:
                    status_code = purchase_order_query_rs.get('statusCode', 'unknown')
                    status_message = purchase_order_query_rs.get('statusMessage', 'N/A')
                    logger.info(f"PurchaseOrderQueryRs status: {status_code} - {status_message}")

                    if status_code == '0':
                        purchase_orders = purchase_order_query_rs.findall('.//PurchaseOrderRet')
                        logger.info(f"Received {len(purchase_orders)} purchase orders in this response.")
                        for po_xml in purchase_orders:
                            try:
                                qb_po_data = _extract_transaction_data(po_xml, is_sales_txn=False)
                                logger.info(f"  Processing Purchase Order TxnID: {qb_po_data.get('qb_txn_id')}, Ref: {qb_po_data.get('ref_number')}")
                                odoo_po_id = create_or_update_odoo_purchase_order(qb_po_data)
                                if odoo_po_id:
                                    logger.info(f"    Successfully processed Purchase Order {qb_po_data.get('qb_txn_id')} for Odoo (Odoo ID: {odoo_po_id}).")
                                else:
                                    logger.warning(f"    Purchase Order {qb_po_data.get('qb_txn_id')} processed for Odoo but no Odoo ID returned.")
                            except Exception as e:
                                txn_id_for_error = _extract_text(po_xml, 'TxnID', 'N/A')
                                logger.error(f"    Error processing Purchase Order {txn_id_for_error} for Odoo: {e}", exc_info=True)
                        
                        iterator_id = purchase_order_query_rs.get("iteratorID")
                        iterator_remaining_count = purchase_order_query_rs.get("iteratorRemainingCount")
                        if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                            active_task["iteratorID"] = iterator_id
                            active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                            progress = 50
                        else:
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                    else:
                        logger.error(f"PurchaseOrderQueryRs failed: {status_message}")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                else:
                    logger.warning("Could not find PurchaseOrderQueryRs in response.")
                    active_task["iteratorID"] = None
                    session_data["current_task_index"] += 1
                    progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100

            elif entity == JOURNALENTRY_QUERY: # New
                journal_entry_query_rs = root.find('.//JournalEntryQueryRs')
                if journal_entry_query_rs is not None:
                    status_code = journal_entry_query_rs.get('statusCode', 'unknown')
                    status_message = journal_entry_query_rs.get('statusMessage', 'N/A')
                    logger.info(f"JournalEntryQueryRs status: {status_code} - {status_message}")

                    if status_code == '0':
                        journal_entries = journal_entry_query_rs.findall('.//JournalEntryRet')
                        logger.info(f"Received {len(journal_entries)} journal entries in this response.")
                        for je_xml in journal_entries:
                            try:
                                qb_je_data = _extract_journal_entry_data(je_xml)
                                logger.info(f"  Processing Journal Entry TxnID: {qb_je_data.get('qb_txn_id')}, Ref: {qb_je_data.get('ref_number')}")
                                odoo_je_id = create_or_update_odoo_journal_entry(qb_je_data)
                                if odoo_je_id:
                                    logger.info(f"    Successfully processed Journal Entry {qb_je_data.get('qb_txn_id')} for Odoo (Odoo ID: {odoo_je_id}).")
                                else:
                                    logger.warning(f"    Journal Entry {qb_je_data.get('qb_txn_id')} processed for Odoo but no Odoo ID returned.")
                            except Exception as e:
                                txn_id_for_error = _extract_text(je_xml, 'TxnID', 'N/A')
                                logger.error(f"    Error processing Journal Entry {txn_id_for_error} for Odoo: {e}", exc_info=True)
                        
                        iterator_id = journal_entry_query_rs.get("iteratorID")
                        iterator_remaining_count = journal_entry_query_rs.get("iteratorRemainingCount")
                        if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                            active_task["iteratorID"] = iterator_id
                            active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                            progress = 50
                        else:
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                    else:
                        logger.error(f"JournalEntryQueryRs failed: {status_message}")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100
                else:
                    logger.warning("Could not find JournalEntryQueryRs in response.")
                    active_task["iteratorID"] = None
                    session_data["current_task_index"] += 1
                    progress = int(session_data["current_task_index"] * 100 / total_tasks) if total_tasks > 0 else 100

        except ET.ParseError as e:
            logger.error(f"Error parsing XML response for task {active_task}: {e}. Response snippet: {response[:500] if response else 'Empty'}")
            entity_name_for_error = active_task.get('entity', 'unknown task') if active_task else 'unknown task'
            session_data["last_error"] = f"XML Parse Error in receiveResponseXML for {entity_name_for_error}"
            if active_task:
                active_task["iteratorID"] = None
            session_data["current_task_index"] += 1
            save_qbwc_session_state()
            return "0" # Return 0 to indicate an error to QBWC
        except Exception as e:
            logger.error(f"Unexpected error processing response for task {active_task}: {e}", exc_info=True)
            entity_name_for_error = active_task.get('entity', 'unknown task') if active_task else 'unknown task'
            session_data["last_error"] = f"Unexpected error in receiveResponseXML for {entity_name_for_error}"
            if active_task:
                active_task["iteratorID"] = None
            session_data["current_task_index"] += 1
            save_qbwc_session_state()
            return "0" # Return 0 to indicate an error to QBWC
            
        if session_data.get("current_task_index", 0) >= len(session_data.get("task_queue", [])):
            logger.info("All tasks in the current queue are processed.")
            progress = 100
        
        save_qbwc_session_state()
        logger.info(f"receiveResponseXML returning progress: {progress}% for task: {active_task.get('entity', 'N/A')}")
        return str(progress)    @rpc(Unicode, _returns=Unicode)
    def getLastError(self, ticket):
        logger.debug("Method getLastError called")
        """Get the last error message for a session."""
        logger.info(f"QBWC Service: getLastError called. Ticket: {ticket}")
        
        session_data = qbwc_session_state.get(ticket)
        if session_data:
            error_msg = session_data.get("last_error", "No error")
            logger.info(f"Returning error for ticket {ticket}: {error_msg}")
            return error_msg
        
        # Check if this is a ticket we created for invalid sessions
        if ticket and ticket.startswith("ticket_"):
            logger.warning(f"Session ticket {ticket} not found in active sessions")
            return "QBWC Error: Session expired or invalid. Please restart the update process."
        
        logger.warning(f"Invalid ticket format: {ticket}")
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
            save_qbwc_session_state()
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
