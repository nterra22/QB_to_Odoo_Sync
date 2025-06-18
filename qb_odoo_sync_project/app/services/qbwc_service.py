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
from xml.sax.saxutils import escape

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

def _compute_overall_progress(session_data):
    """Overall sync percentage, capped at 99 until last task."""
    total = session_data.get("total_tasks") or len(session_data.get("task_queue", [])) or 1
    done = session_data.get("current_task_index", 0)
    if done >= total:
        return 100
    pct = int(done * 100 / total)
    return min(pct, 99)

def _get_xml_text(element: Optional[ET.Element], default: Optional[str] = None) -> Optional[str]:
    """Safely get text from an XML element."""
    if element is not None and element.text is not None:
        return element.text.strip()
    return default

def _extract_address_data(address_element: Optional[ET.Element], prefix: str) -> Dict[str, Any]:
    """Helper to extract address components."""
    data = {}
    if address_element is not None:
        data[f"{prefix}_Addr1"] = _get_xml_text(address_element.find('Addr1'))
        data[f"{prefix}_Addr2"] = _get_xml_text(address_element.find('Addr2'))
        data[f"{prefix}_Addr3"] = _get_xml_text(address_element.find('Addr3')) # QB can have Addr3, Addr4, Addr5
        data[f"{prefix}_Addr4"] = _get_xml_text(address_element.find('Addr4'))
        data[f"{prefix}_Addr5"] = _get_xml_text(address_element.find('Addr5'))
        data[f"{prefix}_City"] = _get_xml_text(address_element.find('City'))
        data[f"{prefix}_State"] = _get_xml_text(address_element.find('State'))
        data[f"{prefix}_PostalCode"] = _get_xml_text(address_element.find('PostalCode'))
        data[f"{prefix}_Country"] = _get_xml_text(address_element.find('Country'))
    return data

def _extract_customer_data_from_ret(customer_ret_xml: ET.Element) -> Dict[str, Any]:
    """Extracts detailed customer data from a CustomerRet XML element."""
    data = {
        "ListID": _get_xml_text(customer_ret_xml.find('ListID')),
        "Name": _get_xml_text(customer_ret_xml.find('Name')),
        "FullName": _get_xml_text(customer_ret_xml.find('FullName')),
        "CompanyName": _get_xml_text(customer_ret_xml.find('CompanyName')),
        "FirstName": _get_xml_text(customer_ret_xml.find('FirstName')),
        "LastName": _get_xml_text(customer_ret_xml.find('LastName')),
        "Email": _get_xml_text(customer_ret_xml.find('Email')),
        "Phone": _get_xml_text(customer_ret_xml.find('Phone')),
        "AltPhone": _get_xml_text(customer_ret_xml.find('AltPhone')),
        "Fax": _get_xml_text(customer_ret_xml.find('Fax')),
        "Contact": _get_xml_text(customer_ret_xml.find('Contact')), # Primary contact name
        "AltContact": _get_xml_text(customer_ret_xml.find('AltContact')),
        "Notes": _get_xml_text(customer_ret_xml.find('Notes')),
        "IsActive": _get_xml_text(customer_ret_xml.find('IsActive')) == 'true',
        "Sublevel": _get_xml_text(customer_ret_xml.find('Sublevel')),
        "ParentRef_ListID": _get_xml_text(customer_ret_xml.find('ParentRef/ListID')),
        "ParentRef_FullName": _get_xml_text(customer_ret_xml.find('ParentRef/FullName')),
        "CustomerTypeRef_ListID": _get_xml_text(customer_ret_xml.find('CustomerTypeRef/ListID')),
        "CustomerTypeRef_FullName": _get_xml_text(customer_ret_xml.find('CustomerTypeRef/FullName')),
        "TermsRef_ListID": _get_xml_text(customer_ret_xml.find('TermsRef/ListID')),
        "TermsRef_FullName": _get_xml_text(customer_ret_xml.find('TermsRef/FullName')),
        "SalesRepRef_ListID": _get_xml_text(customer_ret_xml.find('SalesRepRef/ListID')),
        "SalesRepRef_FullName": _get_xml_text(customer_ret_xml.find('SalesRepRef/FullName')),
        "Balance": _get_xml_text(customer_ret_xml.find('Balance')),
        "TotalBalance": _get_xml_text(customer_ret_xml.find('TotalBalance')),
        "JobStatus": _get_xml_text(customer_ret_xml.find('JobStatus')),
        # Add more fields as needed from CustomerRet
    }
    data.update(_extract_address_data(customer_ret_xml.find('BillAddress'), 'BillAddress'))
    data.update(_extract_address_data(customer_ret_xml.find('ShipAddress'), 'ShipAddress'))
    
    # Extract additional contacts if present (ContactsRet)
    # This part might need adjustment based on how you want to map multiple contacts in Odoo
    contacts_ret = customer_ret_xml.findall('ContactsRet')
    additional_contacts = []
    for contact_xml in contacts_ret:
        additional_contacts.append({
            "ListID": _get_xml_text(contact_xml.find('ListID')),
            "FirstName": _get_xml_text(contact_xml.find('FirstName')),
            "LastName": _get_xml_text(contact_xml.find('LastName')),
            "Salutation": _get_xml_text(contact_xml.find('Salutation')),
        })
    if additional_contacts:
        data["AdditionalContacts"] = additional_contacts

    # Filter out None values to keep the payload clean
    return {k: v for k, v in data.items() if v is not None}

def _extract_vendor_data_from_ret(vendor_ret_xml: ET.Element) -> Dict[str, Any]:
    """Extracts detailed vendor data from a VendorRet XML element."""
    data = {
        "ListID": _get_xml_text(vendor_ret_xml.find('ListID')),
        "TimeModifiedQB": _get_xml_text(vendor_ret_xml.find('TimeModified')),
        "Name": _get_xml_text(vendor_ret_xml.find('Name')),
        "FullName": _get_xml_text(vendor_ret_xml.find('FullName')),
        "CompanyName": _get_xml_text(vendor_ret_xml.find('CompanyName')),
        "FirstName": _get_xml_text(vendor_ret_xml.find('FirstName')),
        "LastName": _get_xml_text(vendor_ret_xml.find('LastName')),
        "Email": _get_xml_text(vendor_ret_xml.find('Email')),
        "Phone": _get_xml_text(vendor_ret_xml.find('Phone')),
        "IsActive": _get_xml_text(vendor_ret_xml.find('IsActive')) == 'true',
        # Add more fields as needed from VendorRet
    }
    data.update(_extract_address_data(vendor_ret_xml.find('VendorAddress'), 'VendorAddress'))
    # Filter out None values to keep the payload clean
    return {k: v for k, v in data.items() if v is not None}

# Helper function to extract text from XML element, with logging
def _extract_text(xml_element: ET.Element, xpath: str) -> str:
    try:
        result = xml_element.findtext(xpath)
        return result.strip() if result else ""
    except Exception as e:
        logger.warning(f"Error extracting text for xpath '{xpath}': {e}")
        return ""

def _get_customer_filter_xml(self):
        """Builds XML for customer name filter based on config."""
        customer_name_filter = self.config.get("CUSTOMER_NAME_FILTER")
        if customer_name_filter:
            logging.info(f"Filtering customers with name starting with: {customer_name_filter}")
            return f"<NameFilter><MatchCriterion>StartsWith</MatchCriterion><Name>{escape(customer_name_filter)}</Name></NameFilter>"
        return ""

def _get_vendor_filter_xml(self):
        """Builds XML for vendor name filter based on config."""
        vendor_name_filter = self.config.get("VENDOR_NAME_FILTER")
        if vendor_name_filter:
            logging.info(f"Filtering vendors with name starting with: {vendor_name_filter}")
            return f"<NameFilter><MatchCriterion>StartsWith</MatchCriterion><Name>{escape(vendor_name_filter)}</Name></NameFilter>"
        return ""

def _get_txn_date_filter_xml(params: Dict[str, Any]) -> str:
    """Helper to build TxnDateRangeFilter XML."""
    if "TxnDateRangeFilter" in params and params["TxnDateRangeFilter"].get("FromTxnDate"):
        from_date = params["TxnDateRangeFilter"]["FromTxnDate"]
        to_date = params["TxnDateRangeFilter"].get("ToTxnDate")
        xml = f"<TxnDateRangeFilter><FromTxnDate>{from_date}</FromTxnDate>"
        if to_date:
            xml += f"<ToTxnDate>{to_date}</ToTxnDate>"
        xml += "</TxnDateRangeFilter>"
        return xml
    return ""

def _get_include_line_items_xml(params: Dict[str, Any]) -> str:
    """Helper to build IncludeLineItems XML."""
    if "IncludeLineItems" in params:
        return f'<IncludeLineItems>{params["IncludeLineItems"]}</IncludeLineItems>'
    return ""

# New generic transaction data extractor
def _extract_transaction_data(txn_xml_element: ET.Element, txn_type: str) -> Dict[str, Any]:
    data = {
        "qb_txn_id": _extract_text(txn_xml_element, 'TxnID'),
        "ref_number": _extract_text(txn_xml_element, 'RefNumber'),
        "txn_date": _extract_text(txn_xml_element, 'TxnDate'),
        "memo": _extract_text(txn_xml_element, 'Memo'),
        "qbd_object_type": txn_type,
        "lines": []
    }

    if txn_type in ["Invoice", "CreditMemo", "SalesOrder"]: # Customer-based transactions
        data["customer_name"] = _extract_text(txn_xml_element, 'CustomerRef/FullName')
        data["due_date"] = _extract_text(txn_xml_element, 'DueDate') # Common for Invoices, CreditMemos
        data["subtotal"] = float(_extract_text(txn_xml_element, 'Subtotal') or 0.0)
        # Add more fields specific to these types as needed (e.g., SalesTaxTotal, AppliedAmount for Invoice)

    elif txn_type in ["Bill", "PurchaseOrder"]: # Vendor-based transactions
        data["vendor_name"] = _extract_text(txn_xml_element, 'VendorRef/FullName')
        data["due_date"] = _extract_text(txn_xml_element, 'DueDate') # Common for Bills
        data["amount_due"] = float(_extract_text(txn_xml_element, 'AmountDue') or 0.0) # For Bill

    # Line item extraction (simplified, needs to be specific per transaction type)
    # This is a basic structure; specific line types (InvoiceLineRet, CreditMemoLineRet, etc.) need detailed parsing
    
    line_ret_name_map = {
        "Invoice": "InvoiceLineRet",
        "CreditMemo": "CreditMemoLineRet",
        "SalesOrder": "SalesOrderLineRet",
        "PurchaseOrder": "PurchaseOrderLineRet",
        # Bills have ExpenseLineRet and ItemLineRet, handled separately if needed or generalized
    }

    line_ret_name = line_ret_name_map.get(txn_type)

    if line_ret_name:
        for line_xml in txn_xml_element.findall(f'.//{line_ret_name}'):
            line_data = {
                "item_name": _extract_text(line_xml, 'ItemRef/FullName'),
                "description": _extract_text(line_xml, 'Desc'),
                "quantity": float(_extract_text(line_xml, 'Quantity') or 0.0),
                "rate": float(_extract_text(line_xml, 'Rate') or 0.0), # Price level for sales, Cost for POs
                "amount": float(_extract_text(line_xml, 'Amount') or 0.0),
                # Add other common line fields: SalesTaxCodeRef, ClassRef, etc.
            }
            if txn_type == "PurchaseOrder": # POs use Cost instead of Rate for unit price
                line_data["cost"] = float(_extract_text(line_xml, 'Cost') or 0.0)

            data["lines"].append(line_data)
    
    # Special handling for Bill lines (Expense and Item)
    if txn_type == "Bill":
        data["expense_lines"] = []
        data["item_lines"] = []
        for line_xml in txn_xml_element.findall('.//ExpenseLineRet'):
            data["expense_lines"].append({
                "account_name": _extract_text(line_xml, 'AccountRef/FullName'),
                "amount": float(_extract_text(line_xml, 'Amount') or 0.0),
                "memo": _extract_text(line_xml, 'Memo'),
            })
        for line_xml in txn_xml_element.findall('.//ItemLineRet'):
             data["item_lines"].append({
                "item_name": _extract_text(line_xml, 'ItemRef/FullName'),
                "description": _extract_text(line_xml, 'Desc'),
                "quantity": float(_extract_text(line_xml, 'Quantity') or 0.0),
                "cost": float(_extract_text(line_xml, 'Cost') or 0.0),
                "amount": float(_extract_text(line_xml, 'Amount') or 0.0),
            })


    logger.debug(f"Extracted QB {txn_type} Data for TxnID {data.get('qb_txn_id')}: {data}")
    return data

# New specific extractor for Journal Entries
def _extract_journal_entry_data(je_xml_element: ET.Element) -> Dict[str, Any]:
    data = {
        "qb_txn_id": _extract_text(je_xml_element, 'TxnID'),
        "ref_number": _extract_text(je_xml_element, 'RefNumber'),
        "txn_date": _extract_text(je_xml_element, 'TxnDate'),
        "memo": _extract_text(je_xml_element, 'Memo'), # Top-level memo
        "qbd_object_type": "JournalEntry",

        "lines": []
    }

    for line_xml in je_xml_element.findall('.//JournalCreditLine'):
        line_data = {
            "type": "Credit",
            "account_name": _extract_text(line_xml, 'AccountRef/FullName'),
            "amount": float(_extract_text(line_xml, 'Amount') or 0.0),
            "memo": _extract_text(line_xml, 'Memo'), # Line-level memo
            "entity_name": _extract_text(line_xml, 'EntityRef/FullName'), # Customer, Vendor, Employee, Other Name
            # Add ClassRef if needed
        }
        data["lines"].append(line_data)

    for line_xml in je_xml_element.findall('.//JournalDebitLine'):
        line_data = {
            "type": "Debit",
            "account_name": _extract_text(line_xml, 'AccountRef/FullName'),
            "amount": float(_extract_text(line_xml, 'Amount') or 0.0),
            "memo": _extract_text(line_xml, 'Memo'), # Line-level memo
            "entity_name": _extract_text(line_xml, 'EntityRef/FullName'),
        }
        data["lines"].append(line_data)
    
    logger.debug(f"Extracted QB Journal Entry Data for TxnID {data.get('qb_txn_id')}: {data}")
    return data

def _extract_payment_data(payment_xml_element: ET.Element) -> Dict[str, Any]:
    """Extracts detailed payment data from a ReceivePaymentRet XML element."""
    data = {
        "qb_txn_id": _get_xml_text(payment_xml_element.find('TxnID')),
        "customer_name": _get_xml_text(payment_xml_element.find('CustomerRef/FullName')),
        "txn_date": _get_xml_text(payment_xml_element.find('TxnDate')),
        "ref_number": _get_xml_text(payment_xml_element.find('RefNumber')),
        "total_amount": float(_get_xml_text(payment_xml_element.find('TotalAmount'), '0.0') or 0.0),
        "memo": _get_xml_text(payment_xml_element.find('Memo')),
        "applied_to_txns": []
    }
    
    for applied_txn_xml in payment_xml_element.findall('.//AppliedToTxnRet'):
        applied_data = {
            "applied_qb_invoice_txn_id": _get_xml_text(applied_txn_xml.find('TxnID')),
            "payment_amount": float(_get_xml_text(applied_txn_xml.find('PaymentAmount'), '0.0') or 0.0)
        }
        data["applied_to_txns"].append(applied_data)
        
    return data

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
                    "params": { # "TxnDateRangeFilter" removed
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
                },
                # TODO: Add tasks for fetching data from Odoo to send to QB (QB_ADD, QB_MOD types)
            ]

            qbwc_session_state[session_key] = {
                "task_queue": initial_tasks,
                "current_task_index": 0, # Pointer to the current task in the queue
                "total_tasks": len(initial_tasks),  # NEW: Store total task count
                "last_error": "No error",
                "created_at": datetime.now(),
                "company_file_name": None, # Will be set by QBWC
                "qbxml_version": None # Will be set by QBWC
            }
            save_qbwc_session_state()
            
            return [session_key, ""] # Empty string for company file path, QBWC will fill it
        else:
            logger.warning(f"Authentication failed for user: {strUserName}")
            return ["", "nvu"]

    @rpc(Unicode, Unicode, Unicode, Unicode, Unicode, Unicode, _returns=Unicode)
    def sendRequestXML(self, ticket, strHCPResponse, strCompanyFileName, 
                      qbXMLCountry, qbXMLMajorVers, qbXMLMinorVers):
        
        logger.debug("Method sendRequestXML called")
        logger.info(f"sendRequestXML invoked with ticket: {ticket}")

        session_data = qbwc_session_state.get(ticket)
        logger.info(f"sendRequestXML: Retrieved session_data exists: {session_data is not None}")

        if not session_data:
            logger.error(f"sendRequestXML: Invalid ticket {ticket}. No session data found.")
            return ""

        # Store company file and QBXML version info from QBWC
        session_data["company_file_name"] = strCompanyFileName
        session_data["qbxml_version"] = f"{qbXMLMajorVers}.{qbXMLMinorVers}"
        logger.info(f"sendRequestXML: CompanyFileName='{strCompanyFileName}', QBXMLVersion='{session_data['qbxml_version']}'")

        task_queue = session_data.get("task_queue", [])
        current_task_index = session_data.get("current_task_index", 0)
        logger.info(f"sendRequestXML: Task Queue length: {len(task_queue)}")
        logger.info(f"sendRequestXML: Current Task Index: {current_task_index}")

        if current_task_index >= len(task_queue):
            logger.info("sendRequestXML: All tasks completed for this session or task queue is empty initially.")
            return ""

        current_task = task_queue[current_task_index]
        logger.info(f"sendRequestXML: Processing task: {current_task}")
        session_data["active_task"] = current_task
        save_qbwc_session_state()

        xml_request = ""
        request_id_str = current_task.get("requestID", "1") # Default to "1"

        if current_task["type"] == QB_QUERY:
            entity = current_task["entity"]
            iterator_id = current_task.get("iteratorID")
            qbxml_version = session_data.get("qbxml_version", "13.0") # Default to 13.0 if not set

            if entity == CUSTOMER_QUERY:
                if iterator_id:
                    logger.info(f"Continuing CustomerQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <CustomerQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>50</MaxReturned>
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
      <MaxReturned>50</MaxReturned>
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
      <MaxReturned>50</MaxReturned>
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
      <MaxReturned>50</MaxReturned>
    </VendorQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''

            elif entity == INVOICE_QUERY:
                params = current_task.get("params", {})
                
                # Ensure we fetch all invoices by setting a wide date range
                modified_date_filter_xml = '<ModifiedDateRangeFilter><FromModifiedDate>1980-01-01</FromModifiedDate></ModifiedDateRangeFilter>'

                include_line_items_xml = f'''<IncludeLineItems>{params["IncludeLineItems"]}</IncludeLineItems>''' if "IncludeLineItems" in params else ""

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
                    logger.info("Starting new InvoiceQueryRq with a wide date filter.")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <InvoiceQueryRq requestID="{request_id_str}">
      {modified_date_filter_xml}
      {include_line_items_xml}
      <MaxReturned>10</MaxReturned> 
    </InvoiceQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
            elif entity == BILL_QUERY:
                params = current_task.get("params", {})
                txn_date_filter_xml = _get_txn_date_filter_xml(params)
                include_line_items_xml = _get_include_line_items_xml(params)

                if iterator_id:
                    logger.info(f"Continuing BillQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <BillQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>50</MaxReturned> 
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
      <MaxReturned>50</MaxReturned> 
    </BillQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
            elif entity == RECEIVEPAYMENT_QUERY:
                params = current_task.get("params", {})
                txn_date_filter_xml = _get_txn_date_filter_xml(params)
                
                if iterator_id:
                    logger.info(f"Continuing ReceivePaymentQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <ReceivePaymentQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>50</MaxReturned>
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
      <MaxReturned>50</MaxReturned>
    </ReceivePaymentQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''

            elif entity == CREDITMEMO_QUERY: # New
                params = current_task.get("params", {})
                txn_date_filter_xml = _get_txn_date_filter_xml(params)
                include_line_items_xml = _get_include_line_items_xml(params)
                if iterator_id:
                    logger.info(f"Continuing CreditMemoQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <CreditMemoQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>50</MaxReturned>
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
      <MaxReturned>50</MaxReturned>
    </CreditMemoQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
            elif entity == SALESORDER_QUERY: # New
                params = current_task.get("params", {})
                txn_date_filter_xml = _get_txn_date_filter_xml(params)
                include_line_items_xml = _get_include_line_items_xml(params)
                if iterator_id:
                    logger.info(f"Continuing SalesOrderQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <SalesOrderQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>50</MaxReturned>
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
      <MaxReturned>50</MaxReturned>
    </SalesOrderQueryRq>
  </QBXML>
</QBXML>'''
            elif entity == PURCHASEORDER_QUERY: # New
                params = current_task.get("params", {})
                txn_date_filter_xml = _get_txn_date_filter_xml(params)
                include_line_items_xml = _get_include_line_items_xml(params)
                if iterator_id:
                    logger.info(f"Continuing PurchaseOrderQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <PurchaseOrderQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>50</MaxReturned>
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
      <MaxReturned>50</MaxReturned>
    </PurchaseOrderQueryRq>
  </QBXML>
</QBXML>'''
            elif entity == JOURNALENTRY_QUERY: # New
                params = current_task.get("params", {})
                txn_date_filter_xml = _get_txn_date_filter_xml(params)
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
  </QBXML>
</QBXML>'''

        # Add other QB_QUERY entity types (Vendor, Item, etc.) here in the future
        # Add QB_ADD, QB_MOD task types here in the future for Odoo to QB sync

        logger.debug(f"Sending QBXML request for task type {current_task['type']}, entity {current_task.get('entity', 'N/A')}")
        logger.info(f"Generated XML request (first 500 chars): {xml_request[:500] if xml_request else 'EMPTY REQUEST'}")
        return xml_request

    @rpc(Unicode, Unicode, Unicode, Unicode, _returns=Unicode)
    def receiveResponseXML(self, ticket, response, hresult, message):
        
        logger.debug("Method receiveResponseXML called")
        logger.info(f"QBWC Service: receiveResponseXML called. Ticket: {ticket}")

        session_data = qbwc_session_state.get(ticket)
        if not session_data:
            logger.error(f"receiveResponseXML: Invalid ticket {ticket}. No session data found.")
            return "0"  # Error

        active_task = session_data.get("active_task")
        if not active_task:
            logger.error(f"receiveResponseXML: No active task found for ticket {ticket}.")
            return "0"  # Error

        logger.debug(f"Received QBXML response (first 1000 chars): {response[:1000] if response else 'Empty response'}")

        if hresult:
            logger.error(f"receiveResponseXML received an error from QBWC. HRESULT: {hresult}, Message: {message}")
            session_data["last_error"] = f"QBWC Error: {message}"
            session_data["current_task_index"] += 1
            save_qbwc_session_state()
            return "0"

        progress = 0
        try:
            if not response:
                logger.warning(f"Received empty response for task: {active_task}. This may be normal if the query returned no data.")
                session_data["current_task_index"] += 1
                logger.info(f"Incremented current_task_index to {session_data['current_task_index']} after empty response.")
                progress = _compute_overall_progress(session_data)
                save_qbwc_session_state()
                return str(progress)

            root = ET.fromstring(response)
            
            if active_task["type"] == QB_QUERY:
                entity = active_task["entity"]
                
                if entity == CUSTOMER_QUERY:
                    customer_query_rs = root.find('.//CustomerQueryRs')
                    if customer_query_rs is not None:
                        status_code = customer_query_rs.get('statusCode', 'unknown')
                        status_message = customer_query_rs.get('statusMessage', 'N/A')
                        logger.info(f"CustomerQueryRs status: {status_code} - {status_message}")

                        if status_code == '0':
                            customers = customer_query_rs.findall('.//CustomerRet')
                            logger.info(f"Received {len(customers)} customers in this response.")
                            for cust_xml in customers:
                                qb_customer_data = _extract_customer_data_from_ret(cust_xml)
                                customer_list_id = qb_customer_data.get('ListID')
                                
                                if not customer_list_id:
                                    logger.warning("Customer record found with no ListID. Skipping.")
                                    continue

                                # Check if the customer is a job (sub-customer)
                                if qb_customer_data.get('ParentRef_ListID'):
                                    job_full_name = qb_customer_data.get('FullName', customer_list_id)
                                    logger.info(f"QB record '{job_full_name}' (ListID: {customer_list_id}) is a job. Skipping Odoo partner creation.")
                                    continue

                                customer_name_for_log = qb_customer_data.get("Name", qb_customer_data.get("FullName", f"ListID: {customer_list_id}"))

                                if qb_customer_data:
                                    logger.info(f"  Processing Customer: {customer_name_for_log} (ListID: {customer_list_id})")
                                    logger.debug(f"    Extracted QB Customer Data: {qb_customer_data}")
                                    try:
                                        odoo_partner_id = create_or_update_odoo_partner(qb_customer_data, is_supplier=False)
                                        if odoo_partner_id:
                                            logger.info(f"    Successfully processed customer '{customer_name_for_log}' for Odoo. Odoo Partner ID: {odoo_partner_id}")
                                        else:
                                            logger.warning(f"    Could not create or update Odoo partner for '{customer_name_for_log}' (it might have been skipped if it's a job, or an error occurred).")
                                    except Exception as e:
                                        logger.error(f"    Error processing customer '{customer_name_for_log}' for Odoo: {e}", exc_info=True)
                                else:
                                    logger.warning(f"  Skipping customer with missing/empty data (ListID: {customer_list_id}).")

                            iterator_id = customer_query_rs.get("iteratorID")
                            iterator_remaining_count = customer_query_rs.get("iteratorRemainingCount")
                            
                            if iterator_id and int(iterator_remaining_count or '0') > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50 
                                logger.info(f"Customer iteration continues. IteratorID: {iterator_id}, Remaining: {iterator_remaining_count}")
                            else:
                                logger.info("Customer iteration complete or no iterator.")
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                        else:
                            logger.error(f"CustomerQueryRs failed with statusCode: {status_code}, message: {status_message}")
                            session_data["last_error"] = f"CustomerQuery Error: {status_message}"
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                    else:
                        logger.warning("Could not find CustomerQueryRs in the response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1

                elif entity == VENDOR_QUERY:
                    vendor_query_rs = root.find('.//VendorQueryRs')
                    if vendor_query_rs is not None:
                        status_code = vendor_query_rs.get('statusCode', 'unknown')
                        status_message = vendor_query_rs.get('statusMessage', 'N/A')
                        logger.info(f"VendorQueryRs status: {status_code} - {status_message}")

                        if status_code == '0':
                            vendors = vendor_query_rs.findall('.//VendorRet')
                            logger.info(f"Received {len(vendors)} vendors in this response.")
                            for vend_xml in vendors:
                                qb_vendor_data = _extract_vendor_data_from_ret(vend_xml)
                                vendor_list_id = qb_vendor_data.get('ListID')
                                vendor_name = qb_vendor_data.get('Name')

                                if not vendor_list_id:
                                    logger.warning("Vendor record found with no ListID. Skipping.")
                                    continue

                                if vendor_name:
                                    logger.info(f"  Processing Vendor: {vendor_name} (ListID: {vendor_list_id})")
                                    try:
                                        odoo_vendor_id = create_or_update_odoo_partner(qb_vendor_data, is_supplier=True)

                                        if odoo_vendor_id:
                                            logger.info(f"    Successfully processed vendor '{vendor_name}' for Odoo. Odoo Partner ID: {odoo_vendor_id}")
                                        else:
                                            logger.warning(f"    Could not create or update Odoo partner (vendor) for '{vendor_name}'.")
                                    except Exception as e:
                                        logger.error(f"    Error processing vendor '{vendor_name}' for Odoo: {e}", exc_info=True)
                                else:
                                    logger.warning(f"  Skipping vendor with missing name (ListID: {vendor_list_id}).")
                            

                            iterator_id = vendor_query_rs.get("iteratorID")
                            iterator_remaining_count = vendor_query_rs.get("iteratorRemainingCount")
                            
                            if iterator_id and int(iterator_remaining_count or '0') > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50 
                                logger.info(f"Vendor iteration continues. IteratorID: {iterator_id}, Remaining: {iterator_remaining_count}")
                            else:
                                logger.info("Vendor iteration complete or no iterator.")
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1 
                        else:
                            logger.error(f"VendorQueryRs failed with statusCode: {status_code}, message: {status_message}")
                            session_data["last_error"] = f"VendorQuery Error: {status_message}"
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1 
                    else:
                        logger.warning("Could not find VendorQueryRs in the response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1

                elif entity == INVOICE_QUERY:
                    invoice_query_rs = root.find('.//InvoiceQueryRs')
                    if invoice_query_rs is not None:
                        status_code = invoice_query_rs.get('statusCode', 'unknown')
                        status_message = invoice_query_rs.get('statusMessage', 'N/A')
                        logger.info(f"InvoiceQueryRs status: {status_code} - {status_message}")

                        if status_code == '0':
                            invoices = invoice_query_rs.findall('.//InvoiceRet')
                            logger.info(f"Received {len(invoices)} invoices in this response.")
                            for inv_xml in invoices:
                                qb_invoice_data = _extract_transaction_data(inv_xml, "Invoice")
                                
                                if not qb_invoice_data.get("qb_txn_id"):
                                    logger.warning("Invoice record found with no TxnID. Skipping.")
                                    continue

                                original_qb_customer_name = _get_xml_text(inv_xml.find('CustomerRef/FullName'))
                                if original_qb_customer_name and ':' in original_qb_customer_name:
                                    parent_customer_name_from_job_string = original_qb_customer_name.split(':')[0].strip()
                                    logger.info(f"Invoice {qb_invoice_data['qb_txn_id']} is for job '{original_qb_customer_name}'. Attempting to assign to parent customer '{parent_customer_name_from_job_string}'.")
                                    qb_invoice_data["customer_name"] = parent_customer_name_from_job_string
                                
                                logger.info(f"  Processing Invoice TxnID: {qb_invoice_data['qb_txn_id']}, Ref: {qb_invoice_data.get('ref_number')}")

                                if not qb_invoice_data.get("customer_name"):
                                    logger.warning(f"    Invoice {qb_invoice_data['qb_txn_id']} has no customer name. Skipping Odoo processing for this invoice.")
                                    continue
                                
                                try:
                                    odoo_invoice_id = create_or_update_odoo_invoice(qb_invoice_data)
                                    if odoo_invoice_id:
                                        logger.info(f"    Successfully processed Invoice {qb_invoice_data['qb_txn_id']} for Odoo (Odoo ID: {odoo_invoice_id}).")
                                    else:
                                        logger.warning(f"    Invoice {qb_invoice_data['qb_txn_id']} processed for Odoo but no Odoo ID returned (may indicate create/update issue or placeholder).")
                                except Exception as e:
                                    logger.error(f"    Error processing Invoice {qb_invoice_data['qb_txn_id']} for Odoo: {e}", exc_info=True)

                            iterator_id = invoice_query_rs.get("iteratorID")
                            iterator_remaining_count = invoice_query_rs.get("iteratorRemainingCount")
                            
                            if iterator_id and int(iterator_remaining_count or '0') > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50 
                                logger.info(f"Invoice iteration continues. IteratorID: {iterator_id}, Remaining: {iterator_remaining_count}")
                            else:
                                logger.info("Invoice iteration complete or no iterator.")
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                        else:
                            logger.error(f"InvoiceQueryRs failed with statusCode: {status_code}, message: {status_message}")
                            session_data["last_error"] = f"InvoiceQuery Error: {status_message}"
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                    else:
                        logger.warning("Could not find InvoiceQueryRs in the response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
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
                                qb_bill_data = _extract_transaction_data(bill_xml, "Bill")

                                if not qb_bill_data.get("qb_txn_id"):
                                    logger.warning("Bill record found with no TxnID. Skipping.")
                                    continue

                                logger.info(f"  Processing Bill TxnID: {qb_bill_data['qb_txn_id']}, Ref: {qb_bill_data.get('ref_number')}")

                                if not qb_bill_data.get("vendor_name"):
                                    logger.warning(f"    Bill {qb_bill_data['qb_txn_id']} has no vendor name. Skipping Odoo processing.")
                                    continue
                                
                                try:
                                    odoo_bill_id = create_or_update_odoo_bill(qb_bill_data)
                                    if odoo_bill_id:
                                        logger.info(f"    Successfully processed Bill {qb_bill_data['qb_txn_id']} for Odoo (Odoo ID: {odoo_bill_id}).")
                                    else:
                                        logger.warning(f"    Bill {qb_bill_data['qb_txn_id']} processed for Odoo but no Odoo ID returned.")
                                except Exception as e:
                                    logger.error(f"    Error processing Bill {qb_bill_data['qb_txn_id']} for Odoo: {e}", exc_info=True)

                            iterator_id = bill_query_rs.get("iteratorID")
                            iterator_remaining_count = bill_query_rs.get("iteratorRemainingCount")
                            if iterator_id and int(iterator_remaining_count or '0') > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50
                                logger.info(f"Bill iteration continues. IteratorID: {iterator_id}, Remaining: {iterator_remaining_count}")
                            else:
                                logger.info("Bill iteration complete or no iterator.")
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                        else:
                            logger.error(f"BillQueryRs failed: {status_message}")
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                    else:
                        logger.warning("Could not find BillQueryRs in response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1

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
                                qb_payment_data = _extract_payment_data(payment_xml)

                                if not qb_payment_data.get("qb_txn_id"):
                                    logger.warning("Payment record found with no TxnID. Skipping.")
                                    continue
                                
                                logger.info(f"  Processing Payment TxnID: {qb_payment_data['qb_txn_id']}, Ref: {qb_payment_data.get('ref_number')}")

                                if not qb_payment_data.get("customer_name"):
                                    logger.warning(f"    Payment {qb_payment_data['qb_txn_id']} has no customer name. Skipping Odoo processing.")
                                    continue
                                
                                try:
                                    odoo_payment_id = create_or_update_odoo_payment(qb_payment_data)
                                    if odoo_payment_id:
                                        logger.info(f"    Successfully processed Payment {qb_payment_data['qb_txn_id']} for Odoo (Odoo ID: {odoo_payment_id}).")
                                    else:
                                        logger.warning(f"    Payment {qb_payment_data['qb_txn_id']} processed for Odoo but no Odoo ID returned.")
                                except Exception as e:
                                    logger.error(f"    Error processing Payment {qb_payment_data['qb_txn_id']} for Odoo: {e}", exc_info=True)
                            

                            iterator_id = payment_query_rs.get("iteratorID")
                            iterator_remaining_count = payment_query_rs.get("iteratorRemainingCount")
                            if iterator_id and int(iterator_remaining_count or '0') > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50
                            else:
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                        else:
                            logger.error(f"ReceivePaymentQueryRs failed: {status_message}")
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                    else:
                        logger.warning("Could not find ReceivePaymentQueryRs in response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1

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
                                qb_cm_data = _extract_transaction_data(cm_xml, "CreditMemo")

                                if not qb_cm_data.get("qb_txn_id"):
                                    logger.warning("Credit Memo record found with no TxnID. Skipping.")
                                    continue
                                
                                logger.info(f"  Processing Credit Memo TxnID: {qb_cm_data.get('qb_txn_id')}, Ref: {qb_cm_data.get('ref_number')}")
                                try:
                                    odoo_cm_id = create_or_update_odoo_credit_memo(qb_cm_data)
                                    if odoo_cm_id:
                                        logger.info(f"    Successfully processed Credit Memo {qb_cm_data.get('qb_txn_id')} for Odoo (Odoo ID: {odoo_cm_id}).")
                                    else:
                                        logger.warning(f"    Credit Memo {qb_cm_data.get('qb_txn_id')} processed for Odoo but no Odoo ID returned.")
                                except Exception as e:
                                    logger.error(f"    Error processing Credit Memo {qb_cm_data.get('qb_txn_id')} for Odoo: {e}", exc_info=True)
                            

                            iterator_id = credit_memo_query_rs.get("iteratorID")
                            iterator_remaining_count = credit_memo_query_rs.get("iteratorRemainingCount")
                            if iterator_id and int(iterator_remaining_count or '0') > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50
                            else:
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                        else:
                            logger.error(f"CreditMemoQueryRs failed: {status_message}")
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                    else:
                        logger.warning("Could not find CreditMemoQueryRs in response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                
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
                                qb_so_data = _extract_transaction_data(so_xml, "SalesOrder")

                                if not qb_so_data.get("qb_txn_id"):
                                    logger.warning("Sales Order record found with no TxnID. Skipping.")
                                    continue
                                
                                logger.info(f"  Processing Sales Order TxnID: {qb_so_data.get('qb_txn_id')}, Ref: {qb_so_data.get('ref_number')}")
                                try:
                                    odoo_so_id = create_or_update_odoo_sales_order(qb_so_data)
                                    if odoo_so_id:
                                        logger.info(f"    Successfully processed Sales Order {qb_so_data.get('qb_txn_id')} for Odoo (Odoo ID: {odoo_so_id}).")
                                    else:
                                        logger.warning(f"    Sales Order {qb_so_data.get('qb_txn_id')} processed for Odoo but no Odoo ID returned.")
                                except Exception as e:
                                    logger.error(f"    Error processing Sales Order {qb_so_data.get('qb_txn_id')} for Odoo: {e}", exc_info=True)
                            

                            iterator_id = sales_order_query_rs.get("iteratorID")
                            iterator_remaining_count = sales_order_query_rs.get("iteratorRemainingCount")
                            if iterator_id and int(iterator_remaining_count or '0') > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50
                            else:
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                        else:
                            logger.error(f"SalesOrderQueryRs failed: {status_message}")
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                    else:
                        logger.warning("Could not find SalesOrderQueryRs in response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1

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
                                qb_po_data = _extract_transaction_data(po_xml, "PurchaseOrder")

                                if not qb_po_data.get("qb_txn_id"):
                                    logger.warning("Purchase Order record found with no TxnID. Skipping.")
                                    continue
                                
                                logger.info(f"  Processing Purchase Order TxnID: {qb_po_data.get('qb_txn_id')}, Ref: {qb_po_data.get('ref_number')}")
                                try:
                                    odoo_po_id = create_or_update_odoo_purchase_order(qb_po_data)
                                    if odoo_po_id:
                                        logger.info(f"    Successfully processed Purchase Order {qb_po_data.get('qb_txn_id')} for Odoo (Odoo ID: {odoo_po_id}).")
                                    else:
                                        logger.warning(f"    Purchase Order {qb_po_data.get('qb_txn_id')} processed for Odoo but no Odoo ID returned.")
                                except Exception as e:
                                    logger.error(f"    Error processing Purchase Order {qb_po_data.get('qb_txn_id')} for Odoo: {e}", exc_info=True)
                            

                            iterator_id = purchase_order_query_rs.get("iteratorID")
                            iterator_remaining_count = purchase_order_query_rs.get("iteratorRemainingCount")
                            if iterator_id and int(iterator_remaining_count or '0') > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50
                            else:
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                        else:
                            logger.error(f"PurchaseOrderQueryRs failed: {status_message}")
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                    else:
                        logger.warning("Could not find PurchaseOrderQueryRs in response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1

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
                                qb_je_data = _extract_journal_entry_data(je_xml)

                                if not qb_je_data.get("qb_txn_id"):
                                    logger.warning("Journal Entry record found with no TxnID. Skipping.")
                                    continue
                                
                                logger.info(f"  Processing Journal Entry TxnID: {qb_je_data.get('qb_txn_id')}, Ref: {qb_je_data.get('ref_number')}")
                                try:
                                    odoo_je_id = create_or_update_odoo_journal_entry(qb_je_data)
                                    if odoo_je_id:
                                        logger.info(f"    Successfully processed Journal Entry {qb_je_data.get('qb_txn_id')} for Odoo (Odoo ID: {odoo_je_id}).")
                                    else:
                                        logger.warning(f"    Journal Entry {qb_je_data.get('qb_txn_id')} processed for Odoo but no Odoo ID returned.")
                                except Exception as e:
                                    logger.error(f"    Error processing Journal Entry {qb_je_data.get('qb_txn_id')} for Odoo: {e}", exc_info=True)
                            

                            iterator_id = journal_entry_query_rs.get("iteratorID")
                            iterator_remaining_count = journal_entry_query_rs.get("iteratorRemainingCount")
                            if iterator_id and int(iterator_remaining_count or '0') > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50
                            else:
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                        else:
                            logger.error(f"JournalEntryQueryRs failed: {status_message}")
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                    else:
                        logger.warning("Could not find JournalEntryQueryRs in response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1

        except ET.ParseError as e:
            logger.error(f"Error parsing XML response for task {active_task}: {e}. Response snippet: {response[:500] if response else 'Empty'}")
            entity_name_for_error = active_task.get('entity', 'unknown task') if active_task else 'unknown task'
            session_data["last_error"] = f"XML Parse Error in receiveResponseXML for {entity_name_for_error}"
            if active_task:
                active_task["iteratorID"] = None
            session_data["current_task_index"] += 1
            save_qbwc_session_state()
            return "0"
        except Exception as e:
            logger.error(f"Unexpected error processing response for task {active_task}: {e}", exc_info=True)
            entity_name_for_error = active_task.get('entity', 'unknown task') if active_task else 'unknown task'
            session_data["last_error"] = f"Unexpected error in receiveResponseXML for {entity_name_for_error}"
            if active_task:
                active_task["iteratorID"] = None
            session_data["current_task_index"] += 1
            save_qbwc_session_state()
            return "0"
            
        # --- Refactored Progress Calculation ---
        final_progress = 0
        
        # Step 1: Check if we are in the middle of an iteration for the current task.
        # The 'progress' variable would have been set to 50 inside the try block.
        if progress == 50:
            final_progress = 50
            logger.info(f"**PROGRESS_LOGIC: Continuation of an iterator detected. Progress set to 50%.")
        else:
            # Step 2: If not iterating, calculate progress based on completed tasks.
            final_progress = _compute_overall_progress(session_data)
            logger.info(f"**PROGRESS_LOGIC: No iterator. Calculated progress is {final_progress}%.");

        # Step 3: Final check. If the index is at the end, it's 100%. This overrides previous calculations.
        if session_data["current_task_index"] >= len(session_data.get("task_queue", [])):
            final_progress = 100
            logger.info(f"**PROGRESS_LOGIC: Task queue is now complete. Overriding progress to 100%.");

        save_qbwc_session_state()
        logger.info(f"receiveResponseXML: Task index is now: {session_data['current_task_index']}/{len(session_data.get('task_queue', []))}")
        logger.info(f"receiveResponseXML FINAL return value: {final_progress}% for task: {active_task.get('entity', 'N/A') if active_task else 'N/A'}")
        return str(final_progress)

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