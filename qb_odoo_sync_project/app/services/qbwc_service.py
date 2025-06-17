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

    @rpc(_returns=Unicode)
    def serverVersion(ctx):
        """Returns the server version."""
        logger.info("serverVersion called.")
        return "1.0.0"

    @rpc(Unicode, _returns=Unicode)
    def clientVersion(ctx, strVersion):
        """
        Receives the client version and can return an error to prevent connection.
        Returning an empty string means the client version is supported.
        """
        logger.info(f"clientVersion called with version: {strVersion}")
        # Here you could add logic to check the version if needed.
        # For now, we accept any version.
        return ""

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
                        "ModifiedDateRangeFilter": {
                            "FromModifiedDate": "1980-01-01" 
                        }
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": VENDOR_QUERY,
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        "ModifiedDateRangeFilter": {
                            "FromModifiedDate": "1980-01-01"
                        }
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": INVOICE_QUERY,
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        "ModifiedDateRangeFilter": {
                            "FromModifiedDate": "1980-01-01"
                        }
                    }
                }
            ]
            
            qbwc_session_state[session_key] = {
                "ticket": session_key,
                "username": strUserName,
                "company_file_name": "", 
                "tasks": initial_tasks,
                "current_task_index": 0,
                "last_error": None,
                "qbxml_version": "13.0" 
            }
            
            save_qbwc_session_state()
            
            # Return ticket and empty string for company file (QBWC will use the open one)
            return [session_key, ""]
        else:
            logger.warning("Authentication failed")
            # NVu: An empty string ticket indicates failure, QBWC will not proceed
            return ["", "nvu"]

    @rpc(Unicode, Unicode, Unicode, Unicode, Unicode, Unicode, _returns=Unicode)
    def sendRequestXML(self, ticket, strHCPResponse, strCompanyFileName, qbXMLCountry, qbXMLMajorVers, qbXMLMinorVers):
        """
        This web method is called by QBWC to request an XML request.
        """
        logger.info("sendRequestXML called.")
        
        session_data = qbwc_session_state.get(ticket)
        if not session_data:
            logger.error("Invalid ticket received in sendRequestXML.")
            return ""

        # Store company file and QBXML version info in session
        if strCompanyFileName:
            session_data["company_file_name"] = strCompanyFileName
        session_data["qbxml_version"] = f"{qbXMLMajorVers}.{qbXMLMinorVers}"

        current_task_index = session_data.get("current_task_index", 0)
        tasks = session_data.get("tasks", [])

        if current_task_index >= len(tasks):
            logger.info("All tasks completed for this session.")
            return "" # Return empty string to signify no more requests

        current_task = tasks[current_task_index]
        
        # Build the XML request for the current task
        request_xml = self._build_xml_request(current_task, session_data)
        
        logger.debug(f"Built XML Request for task {current_task['entity']}:\n{request_xml}")
        
        return request_xml

    @rpc(Unicode, Unicode, Unicode, Unicode, _returns=int)
    def receiveResponseXML(self, ticket, response, hresult, message):
        """
        Receives the response from QuickBooks for the last request.
        """
        logger.info("receiveResponseXML called.")
        # ... (rest of the method implementation)
        return 0 # Placeholder

    @rpc(Unicode, _returns=Unicode)
    def getLastError(self, ticket):
        """
        Returns the last error message for a given ticket.
        """
        logger.info("getLastError called.")
        session_data = qbwc_session_state.get(ticket)
        if session_data and session_data.get("last_error"):
            return session_data["last_error"]
        return "No error."

    @rpc(Unicode, _returns=Unicode)
    def closeConnection(self, ticket):
        """
        Called by QBWC when the connection is about to be closed.
        """
        logger.info("closeConnection called.")
        if ticket in qbwc_session_state:
            del qbwc_session_state[ticket]
            save_qbwc_session_state()
        return "OK"
