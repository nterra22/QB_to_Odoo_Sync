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
            
            session_key = f"ticket_{int(datetime.now().timestamp())}_{strUserName}"
            
            today_date_str = datetime.now().strftime('%Y-%m-%d')
            # More robust date range, e.g., last 7 days or configurable
            # For now, sticking to today for simplicity in this phase
            # from_date_str = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d') 
            
            initial_tasks = [
                {
                    "type": QB_QUERY, 
                    "entity": CUSTOMER_QUERY, 
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {} # No specific params for full customer list initially
                },
                {
                    "type": QB_QUERY,
                    "entity": VENDOR_QUERY,
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {} # No specific params for full vendor list initially
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
                        "TxnDateRangeFilter": { # Filter by transaction date
                            "FromTxnDate": today_date_str, # Or from_date_str for a wider range
                            "ToTxnDate": today_date_str
                        },
                        "IncludeLineItems": "true",
                        # "PaidStatus": "NotPaidOnly" # Example: if you only want unpaid invoices
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": BILL_QUERY,
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        "TxnDateRangeFilter": {
                            "FromTxnDate": today_date_str,
                            "ToTxnDate": today_date_str
                        },
                        "IncludeLineItems": "true",
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": RECEIVEPAYMENT_QUERY,
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        "TxnDateRangeFilter": {
                            "FromTxnDate": today_date_str,
                            "ToTxnDate": today_date_str
                        }
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": CREDITMEMO_QUERY, # New
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        "TxnDateRangeFilter": {
                            "FromTxnDate": today_date_str,
                            "ToTxnDate": today_date_str
                        },
                        "IncludeLineItems": "true"
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": SALESORDER_QUERY, # New
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        "TxnDateRangeFilter": {
                            "FromTxnDate": today_date_str,
                            "ToTxnDate": today_date_str
                        },
                        "IncludeLineItems": "true"
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": PURCHASEORDER_QUERY, # New
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        "TxnDateRangeFilter": {
                            "FromTxnDate": today_date_str,
                            "ToTxnDate": today_date_str
                        },
                        "IncludeLineItems": "true"
                    }
                },
                {
                    "type": QB_QUERY,
                    "entity": JOURNALENTRY_QUERY, # New
                    "requestID": "1",
                    "iteratorID": None,
                    "params": {
                        "TxnDateRangeFilter": {
                            "FromTxnDate": today_date_str,
                            "ToTxnDate": today_date_str
                        },
                        "IncludeLineItems": "true" # JournalEntry lines are crucial
                    }
                }
                # TODO: Add tasks for SalesOrderQuery, PurchaseOrderQuery etc.
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
            
            return [session_key, ""] # Empty string for company file path, QBWC will fill it
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

        # Store company file and QBXML version info from QBWC
        session_data["company_file_name"] = strCompanyFileName
        session_data["qbxml_version"] = f"{qbXMLMajorVers}.{qbXMLMinorVers}"

        task_queue = session_data.get("task_queue", [])
        current_task_index = session_data.get("current_task_index", 0)

        if current_task_index >= len(task_queue):
            logger.info("All tasks completed for this session.")
            # Optionally, here you could trigger fetching changes from Odoo
            # and populate the queue with new tasks to send data to QB.
            # For now, we signal no more requests.
            return "" # No more requests

        current_task = task_queue[current_task_index]
        session_data["active_task"] = current_task # Store active task for receiveResponseXML

        xml_request = ""
        request_id_str = current_task.get("requestID", "1") # Default to "1"

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
      <MaxReturned>100</MaxReturned>
    </CustomerQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
                else:
                    logger.info("Starting new CustomerQueryRq.")
                    # params = current_task.get("params", {})
                    # active_status_filter = f"<ActiveStatus>{params['ActiveStatus']}</ActiveStatus>" if "ActiveStatus" in params else ""
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <CustomerQueryRq requestID="{request_id_str}">
      <!-- <ActiveStatus>ActiveOnly</ActiveStatus> -->
      <MaxReturned>100</MaxReturned>
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
      <MaxReturned>100</MaxReturned>
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
      <MaxReturned>100</MaxReturned>
    </VendorQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''

            elif entity == INVOICE_QUERY:
                params = current_task.get("params", {})
                txn_date_filter_xml = ""
                if "TxnDateRangeFilter" in params:
                    txn_date_filter_xml = f'''<TxnDateRangeFilter>
        <FromTxnDate>{params["TxnDateRangeFilter"]["FromTxnDate"]}</FromTxnDate>
        <ToTxnDate>{params["TxnDateRangeFilter"]["ToTxnDate"]}</ToTxnDate>
      </TxnDateRangeFilter>'''
                
                include_line_items_xml = f'''<IncludeLineItems>{params["IncludeLineItems"]}</IncludeLineItems>''' if "IncludeLineItems" in params else ""
                owner_id_xml = f'''<OwnerID>{params["OwnerID"]}</OwnerID>''' if "OwnerID" in params else ""

                if iterator_id:
                    logger.info(f"Continuing InvoiceQueryRq with iteratorID: {iterator_id}")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <InvoiceQueryRq requestID="{request_id_str}" iterator="Continue" iteratorID="{iterator_id}">
      <MaxReturned>100</MaxReturned> 
    </InvoiceQueryRq>
  </QBXMLMsgsRq>
</QBXML>'''
                else:
                    logger.info(f"Starting new InvoiceQueryRq for date: {params.get('TxnDateRangeFilter', {}).get('FromTxnDate', 'N/A')}.")
                    xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{session_data["qbxml_version"]}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <InvoiceQueryRq requestID="{request_id_str}">
      {txn_date_filter_xml}
      {include_line_items_xml}
      {owner_id_xml}
      <MaxReturned>100</MaxReturned> 
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
                txn_date_filter_xml = get_txn_date_filter_xml(params)
                include_line_items_xml = get_include_line_items_xml(params)
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
                txn_date_filter_xml = get_txn_date_filter_xml(params)
                include_line_items_xml = get_include_line_items_xml(params)
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
  </QBXMLMsgsRq>
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
  </QBXMLMsgsRq>
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
</QBXML>'''

        # Add other QB_QUERY entity types (Vendor, Item, etc.) here in the future
        # Add QB_ADD, QB_MOD task types here in the future for Odoo to QB sync

        logger.debug(f"Sending QBXML request for task type {current_task['type']}, entity {current_task.get('entity', 'N/A')}: {xml_request}")
        return xml_request

    @rpc(Unicode, Unicode, Unicode, Unicode, _returns=Unicode)
    def receiveResponseXML(self, ticket, response, hresult, message):
        logger.debug("Method receiveResponseXML called")
        logger.info(f"QBWC Service: receiveResponseXML called. Ticket: {ticket}")
        # Log first 1000 chars of response for brevity in general logs
        logger.debug(f"Received QBXML response (first 1000 chars): {response[:1000] if response else 'Empty response'}")
        if len(response) > 1000:
            logger.debug("Full QBXML response is longer and logged separately if detailed debug is enabled for XML.")

        session_data = qbwc_session_state.get(ticket)
        if not session_data:
            logger.error(f"receiveResponseXML: Invalid ticket {ticket}")
            return "0" # Error or no progress

        active_task = session_data.get("active_task")
        if not active_task:
            logger.error("receiveResponseXML: No active task found for this session.")
            return "0"

        progress = 0 # Default progress

        try:
            if not response:
                logger.warning(f"Received empty response for task: {active_task}")
                # Consider this an end of this step or an error
                active_task["iteratorID"] = None # Clear iterator
                session_data["current_task_index"] += 1 # Move to next task
                progress = 100 # Mark this step as complete
                return str(progress)

            root = ET.fromstring(response)
            
            # Generic response processing based on active_task type and entity
            if active_task["type"] == QB_QUERY:
                entity = active_task["entity"]
                
                if entity == CUSTOMER_QUERY:
                    customer_query_rs = root.find('.//CustomerQueryRs')
                    if customer_query_rs is not None:
                        status_code = customer_query_rs.get('statusCode', 'unknown')
                        status_message = customer_query_rs.get('statusMessage', 'N/A')
                        logger.info(f"CustomerQueryRs status: {status_code} - {status_message}")

                        if status_code == '0': # Success
                            customers = customer_query_rs.findall('.//CustomerRet')
                            logger.info(f"Received {len(customers)} customers in this response.")
                            for cust in customers:
                                list_id = cust.find('ListID')
                                name_elem = cust.find('Name')
                                
                                customer_name = name_elem.text if name_elem is not None and name_elem.text else None
                                
                                if customer_name:
                                    logger.info(f"  Processing Customer: {customer_name} (ListID: {list_id.text if list_id is not None else 'N/A'})")
                                    try:
                                        # TODO: Enhance ensure_partner_exists to take more details from 'cust' element if needed
                                        odoo_partner_id = ensure_partner_exists(name=customer_name)
                                        if odoo_partner_id:
                                            logger.info(f"    Ensured Odoo partner for '{customer_name}' exists with ID: {odoo_partner_id}")
                                        else:
                                            logger.warning(f"    Could not ensure Odoo partner for '{customer_name}'.")
                                    except Exception as e:
                                        logger.error(f"    Error processing customer '{customer_name}' for Odoo: {e}", exc_info=True)
                                else:
                                    logger.warning(f"  Skipping customer with missing name (ListID: {list_id.text if list_id is not None else 'N/A'}).")

                            iterator_id = customer_query_rs.get("iteratorID")
                            iterator_remaining_count = customer_query_rs.get("iteratorRemainingCount")
                            
                            if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1) # Increment requestID for next iteration call
                                # Progress can be estimated if total is known, otherwise 50% if iterating
                                progress = 50 
                                logger.info(f"Customer iteration continues. IteratorID: {iterator_id}, Remaining: {iterator_remaining_count}")
                            else:
                                logger.info("Customer iteration complete or no iterator.")
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1 # Move to next task
                                progress = 100
                        else:
                            logger.error(f"CustomerQueryRs failed with statusCode: {status_code}, message: {status_message}")
                            session_data["last_error"] = f"CustomerQuery Error: {status_message}"
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1 # Move to next task, even on error
                            progress = 100 
                    else:
                        logger.warning("Could not find CustomerQueryRs in the response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = 100

                elif entity == VENDOR_QUERY:
                    vendor_query_rs = root.find('.//VendorQueryRs')
                    if vendor_query_rs is not None:
                        status_code = vendor_query_rs.get('statusCode', 'unknown')
                        status_message = vendor_query_rs.get('statusMessage', 'N/A')
                        logger.info(f"VendorQueryRs status: {status_code} - {status_message}")

                        if status_code == '0': # Success
                            vendors = vendor_query_rs.findall('.//VendorRet')
                            logger.info(f"Received {len(vendors)} vendors in this response.")
                            for vend in vendors:
                                list_id_elem = vend.find('ListID')
                                name_elem = vend.find('Name')
                                vendor_name = name_elem.text if name_elem is not None and name_elem.text else None
                                if vendor_name:
                                    logger.info(f"  Processing Vendor: {vendor_name} (ListID: {list_id_elem.text if list_id_elem is not None else 'N/A'})")
                                    try:
                                        # Using ensure_partner_exists for vendors too.
                                        # Might need a specific ensure_vendor_exists if Odoo distinction is critical (e.g. supplier flags)
                                        odoo_vendor_id = ensure_partner_exists(name=vendor_name, is_supplier=True) # Pass is_supplier hint
                                        if odoo_vendor_id:
                                            logger.info(f"    Ensured Odoo partner (vendor) for '{vendor_name}' exists with ID: {odoo_vendor_id}")
                                        else:
                                            logger.warning(f"    Could not ensure Odoo partner (vendor) for '{vendor_name}'.")
                                    except Exception as e:
                                        logger.error(f"    Error processing vendor '{vendor_name}' for Odoo: {e}", exc_info=True)
                                else:
                                    logger.warning(f"  Skipping vendor with missing name (ListID: {list_id_elem.text if list_id_elem is not None else 'N/A'}).")
                            
                            iterator_id = vendor_query_rs.get("iteratorID")
                            iterator_remaining_count = vendor_query_rs.get("iteratorRemainingCount")
                            
                            if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50 
                                logger.info(f"Vendor iteration continues. IteratorID: {iterator_id}, Remaining: {iterator_remaining_count}")
                            else:
                                logger.info("Vendor iteration complete or no iterator.")
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1 
                                progress = 100
                        else:
                            logger.error(f"VendorQueryRs failed with statusCode: {status_code}, message: {status_message}")
                            session_data["last_error"] = f"VendorQuery Error: {status_message}"
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1 
                            progress = 100 
                    else:
                        logger.warning("Could not find VendorQueryRs in the response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = 100

                elif entity == INVOICE_QUERY:
                    invoice_query_rs = root.find('.//InvoiceQueryRs')
                    if invoice_query_rs is not None:
                        status_code = invoice_query_rs.get('statusCode', 'unknown')
                        status_message = invoice_query_rs.get('statusMessage', 'N/A')
                        logger.info(f"InvoiceQueryRs status: {status_code} - {status_message}")

                        if status_code == '0': # Success
                            invoices = invoice_query_rs.findall('.//InvoiceRet')
                            logger.info(f"Received {len(invoices)} invoices in this response.")
                            for inv_xml in invoices:
                                txn_id_elem = inv_xml.find('TxnID')
                                ref_number_elem = inv_xml.find('RefNumber')
                                customer_ref_full_name_elem = inv_xml.find('CustomerRef/FullName')
                                txn_date_elem = inv_xml.find('TxnDate')
                                due_date_elem = inv_xml.find('DueDate')
                                memo_elem = inv_xml.find('Memo')
                                bill_address_elem = inv_xml.find('BillAddress') # For more complete customer data if needed
                                ship_address_elem = inv_xml.find('ShipAddress')
                                is_paid_elem = inv_xml.find('IsPaid')
                                subtotal_elem = inv_xml.find('Subtotal')
                                sales_tax_total_elem = inv_xml.find('SalesTaxTotal')
                                applied_amount_elem = inv_xml.find('AppliedAmount') # For payments applied
                                balance_remaining_elem = inv_xml.find('BalanceRemaining')


                                qb_invoice_data = {
                                    "qb_txn_id": txn_id_elem.text if txn_id_elem is not None else None,
                                    "ref_number": ref_number_elem.text if ref_number_elem is not None else None,
                                    "customer_name": customer_ref_full_name_elem.text if customer_ref_full_name_elem is not None else None,
                                    "txn_date": txn_date_elem.text if txn_date_elem is not None else None,
                                    "due_date": due_date_elem.text if due_date_elem is not None else None,
                                    "memo": memo_elem.text if memo_elem is not None else None,
                                    "is_paid": is_paid_elem.text == 'true' if is_paid_elem is not None else False,
                                    "subtotal": float(subtotal_elem.text) if subtotal_elem is not None and subtotal_elem.text else 0.0,
                                    "sales_tax_total": float(sales_tax_total_elem.text) if sales_tax_total_elem is not None and sales_tax_total_elem.text else 0.0,
                                    "applied_amount": float(applied_amount_elem.text) if applied_amount_elem is not None and applied_amount_elem.text else 0.0,
                                    "balance_remaining": float(balance_remaining_elem.text) if balance_remaining_elem is not None and balance_remaining_elem.text else 0.0,
                                    "lines": []
                                }
                                
                                logger.info(f"  Processing Invoice TxnID: {qb_invoice_data['qb_txn_id']}, Ref: {qb_invoice_data['ref_number']}")

                                if not qb_invoice_data["customer_name"]:
                                    logger.warning(f"    Invoice {qb_invoice_data['qb_txn_id']} has no customer name. Skipping Odoo processing for this invoice.")
                                    continue

                                for line_xml in inv_xml.findall('.//InvoiceLineRet'):
                                    item_ref_full_name_elem = line_xml.find('ItemRef/FullName')
                                    desc_elem = line_xml.find('Desc')
                                    quantity_elem = line_xml.find('Quantity')
                                    rate_elem = line_xml.find('Rate')
                                    amount_elem = line_xml.find('Amount')
                                    # TODO: Extract SalesTaxCodeRef, OverrideItemAccountRef if needed for Odoo mapping

                                    line_data = {
                                        "item_name": item_ref_full_name_elem.text if item_ref_full_name_elem is not None else None,
                                        "description": desc_elem.text if desc_elem is not None else None,
                                        "quantity": float(quantity_elem.text) if quantity_elem is not None and quantity_elem.text else 0.0,
                                        "rate": float(rate_elem.text) if rate_elem is not None and rate_elem.text else 0.0,
                                        "amount": float(amount_elem.text) if amount_elem is not None and amount_elem.text else 0.0,
                                    }
                                    qb_invoice_data["lines"].append(line_data)
                                
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
                            
                            if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50 
                                logger.info(f"Invoice iteration continues. IteratorID: {iterator_id}, Remaining: {iterator_remaining_count}")
                            else:
                                logger.info("Invoice iteration complete or no iterator.")
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1 # Move to next task
                                progress = 100
                        else:
                            logger.error(f"InvoiceQueryRs failed with statusCode: {status_code}, message: {status_message}")
                            session_data["last_error"] = f"InvoiceQuery Error: {status_message}"
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = 100
                    else:
                        logger.warning("Could not find InvoiceQueryRs in the response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = 100
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
                                txn_id_elem = bill_xml.find('TxnID')
                                vendor_ref_full_name_elem = bill_xml.find('VendorRef/FullName')
                                ref_number_elem = bill_xml.find('RefNumber') # Vendor Bill No.
                                txn_date_elem = bill_xml.find('TxnDate')
                                due_date_elem = bill_xml.find('DueDate')
                                amount_due_elem = bill_xml.find('AmountDue')
                                memo_elem = bill_xml.find('Memo')

                                qb_bill_data = {
                                    "qb_txn_id": txn_id_elem.text if txn_id_elem is not None else None,
                                    "vendor_name": vendor_ref_full_name_elem.text if vendor_ref_full_name_elem is not None else None,
                                    "ref_number": ref_number_elem.text if ref_number_elem is not None else None,
                                    "txn_date": txn_date_elem.text if txn_date_elem is not None else None,
                                    "due_date": due_date_elem.text if due_date_elem is not None else None,
                                    "amount_due": float(amount_due_elem.text) if amount_due_elem is not None and amount_due_elem.text else 0.0,
                                    "memo": memo_elem.text if memo_elem is not None else None,
                                    "expense_lines": [],
                                    "item_lines": [] # QB Bills can have both expense and item lines
                                }
                                logger.info(f"  Processing Bill TxnID: {qb_bill_data['qb_txn_id']}, Ref: {qb_bill_data['ref_number']}")

                                if not qb_bill_data["vendor_name"]:
                                    logger.warning(f"    Bill {qb_bill_data['qb_txn_id']} has no vendor name. Skipping Odoo processing.")
                                    continue

                                for line_xml in bill_xml.findall('.//ExpenseLineRet'):
                                    account_ref_full_name_elem = line_xml.find('AccountRef/FullName')
                                    amount_elem = line_xml.find('Amount')
                                    memo_elem = line_xml.find('Memo') # Line memo
                                    # TODO: CustomerRef, BillableStatus for job costing if needed
                                    expense_line_data = {
                                        "account_name": account_ref_full_name_elem.text if account_ref_full_name_elem is not None else None,
                                        "amount": float(amount_elem.text) if amount_elem is not None and amount_elem.text else 0.0,
                                        "memo": memo_elem.text if memo_elem is not None else None,
                                    }
                                    qb_bill_data["expense_lines"].append(expense_line_data)

                                for line_xml in bill_xml.findall('.//ItemLineRet'):
                                    item_ref_full_name_elem = line_xml.find('ItemRef/FullName')
                                    desc_elem = line_xml.find('Desc') # Usually copied from item
                                    quantity_elem = line_xml.find('Quantity')
                                    cost_elem = line_xml.find('Cost')
                                    amount_elem = line_xml.find('Amount')
                                    # TODO: CustomerRef, BillableStatus for job costing
                                    item_line_data = {
                                        "item_name": item_ref_full_name_elem.text if item_ref_full_name_elem is not None else None,
                                        "description": desc_elem.text if desc_elem is not None else None,
                                        "quantity": float(quantity_elem.text) if quantity_elem is not None and quantity_elem.text else 0.0,
                                        "cost": float(cost_elem.text) if cost_elem is not None and cost_elem.text else 0.0,
                                        "amount": float(amount_elem.text) if amount_elem is not None and amount_elem.text else 0.0,
                                    }
                                    qb_bill_data["item_lines"].append(item_line_data)
                                
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
                            if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50
                            else:
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                                progress = 100
                        else:
                            logger.error(f"BillQueryRs failed: {status_message}")
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = 100
                    else:
                        logger.warning("Could not find BillQueryRs in response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = 100

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
                                txn_id_elem = payment_xml.find('TxnID')
                                customer_ref_full_name_elem = payment_xml.find('CustomerRef/FullName')
                                txn_date_elem = payment_xml.find('TxnDate')
                                ref_number_elem = payment_xml.find('RefNumber') # Check / Pmt #
                                total_amount_elem = payment_xml.find('TotalAmount')
                                memo_elem = payment_xml.find('Memo')
                                # PaymentMethodRef, DepositToAccountRef might be useful

                                qb_payment_data = {
                                    "qb_txn_id": txn_id_elem.text if txn_id_elem is not None else None,
                                    "customer_name": customer_ref_full_name_elem.text if customer_ref_full_name_elem is not None else None,
                                    "txn_date": txn_date_elem.text if txn_date_elem is not None else None,
                                    "ref_number": ref_number_elem.text if ref_number_elem is not None else None,
                                    "total_amount": float(total_amount_elem.text) if total_amount_elem is not None and total_amount_elem.text else 0.0,
                                    "memo": memo_elem.text if memo_elem is not None else None,
                                    "applied_to_txns": []
                                }
                                logger.info(f"  Processing Payment TxnID: {qb_payment_data['qb_txn_id']}, Ref: {qb_payment_data['ref_number']}")

                                if not qb_payment_data["customer_name"]:
                                    logger.warning(f"    Payment {qb_payment_data['qb_txn_id']} has no customer name. Skipping Odoo processing.")
                                    continue
                                
                                # AppliedToTxnRet shows which invoices/charges the payment is applied to
                                for applied_txn_xml in payment_xml.findall('.//AppliedToTxnRet'):
                                    applied_txn_id_elem = applied_txn_xml.find('TxnID') # TxnID of the Invoice
                                    payment_amount_elem = applied_txn_xml.find('PaymentAmount')
                                    # DiscountAmount, DiscountAccountRef if discounts are used
                                    applied_data = {
                                        "applied_qb_invoice_txn_id": applied_txn_id_elem.text if applied_txn_id_elem is not None else None,
                                        "payment_amount": float(payment_amount_elem.text) if payment_amount_elem is not None and payment_amount_elem.text else 0.0
                                    }
                                    qb_payment_data["applied_to_txns"].append(applied_data)
                                
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
                            if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50
                            else:
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                                progress = 100
                        else:
                            logger.error(f"ReceivePaymentQueryRs failed: {status_message}")
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = 100
                    else:
                        logger.warning("Could not find ReceivePaymentQueryRs in response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = 100

                elif entity == CREDITMEMO_QUERY: # New
                    credit_memo_query_rs = root.find('.//CreditMemoQueryRs')
                    if credit_memo_query_rs is not None:
                        status_code = credit_memo_query_rs.get('statusCode', 'unknown')
                        status_message = credit_memo_query_rs.get('statusMessage', 'N/A')
                        logger.info(f"CreditMemoQueryRs status: {status_code} - {status_message}")

                        if status_code == '0': # Success
                            credit_memos = credit_memo_query_rs.findall('.//CreditMemoRet')
                            logger.info(f"Received {len(credit_memos)} credit memos in this response.")
                            for cm_xml in credit_memos:
                                qb_cm_data = _extract_transaction_data(cm_xml, "CreditMemo") # Generic extractor
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
                            if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50
                            else:
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                                progress = 100
                        else:
                            logger.error(f"CreditMemoQueryRs failed: {status_message}")
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = 100
                    else:
                        logger.warning("Could not find CreditMemoQueryRs in response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = 100
                
                elif entity == SALESORDER_QUERY: # New
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
                            if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50
                            else:
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                                progress = 100
                        else:
                            logger.error(f"SalesOrderQueryRs failed: {status_message}")
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = 100
                    else:
                        logger.warning("Could not find SalesOrderQueryRs in response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = 100

                elif entity == PURCHASEORDER_QUERY: # New
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
                            if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50
                            else:
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                                progress = 100
                        else:
                            logger.error(f"PurchaseOrderQueryRs failed: {status_message}")
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = 100
                    else:
                        logger.warning("Could not find PurchaseOrderQueryRs in response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = 100

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
                                qb_je_data = _extract_journal_entry_data(je_xml) # Specific extractor for JEs
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
                            if iterator_id and iterator_remaining_count and int(iterator_remaining_count) > 0:
                                active_task["iteratorID"] = iterator_id
                                active_task["requestID"] = str(int(active_task.get("requestID", "0")) + 1)
                                progress = 50
                            else:
                                active_task["iteratorID"] = None
                                session_data["current_task_index"] += 1
                                progress = 100
                        else:
                            logger.error(f"JournalEntryQueryRs failed: {status_message}")
                            active_task["iteratorID"] = None
                            session_data["current_task_index"] += 1
                            progress = 100
                    else:
                        logger.warning("Could not find JournalEntryQueryRs in response.")
                        active_task["iteratorID"] = None
                        session_data["current_task_index"] += 1
                        progress = 100

                # Add processing for other QB_QUERY entity responses here (e.g. ItemQueryRs)
            
            # Add processing for QB_ADD_RS, QB_MOD_RS etc. in the future

        except ET.ParseError as e:
            logger.error(f"Error parsing XML response for task {active_task}: {e}. Response snippet: {response[:500] if response else 'Empty'}")
            entity_name_for_error = active_task.get('entity', 'unknown task') if active_task else 'unknown task'
            session_data["last_error"] = f"XML Parse Error in receiveResponseXML for {entity_name_for_error}"
            if active_task:
                active_task["iteratorID"] = None # Stop iteration on parse error
            session_data["current_task_index"] += 1 # Try to move to next task
            return "0" # Error
        except Exception as e:
            logger.error(f"Unexpected error processing response for task {active_task}: {e}", exc_info=True)
            entity_name_for_error = active_task.get('entity', 'unknown task') if active_task else 'unknown task'
            session_data["last_error"] = f"Unexpected error in receiveResponseXML for {entity_name_for_error}"
            if active_task:
                active_task["iteratorID"] = None
            session_data["current_task_index"] += 1
            return "0" # Error
            
        # Determine overall progress if all tasks in the current queue are done
        if session_data["current_task_index"] >= len(session_data.get("task_queue", [])):
            logger.info("All tasks in the current queue are processed.")
            # Here, we could decide to fetch from Odoo and repopulate the task queue,
            # or if that was the last step, truly be 100% done for this QBWC update session.
            # For now, if queue is exhausted, this cycle is 100% done.
            progress = 100
        elif progress != 50 : # If not iterating, and not 100% done with all tasks, calculate intermediate progress
            # Simple progress: percentage of tasks completed.
            # This might not be what QBWC expects if it wants progress for the *current* request.
            # The 'progress' returned should ideally be for the current step QBWC is waiting on.
            # If a task is 100% done (like a non-iterated query, or last iteration),
            # and there are more tasks, QBWC will call sendRequestXML again immediately.
            # So, returning 100 for a completed task is fine.
            pass


        logger.info(f"receiveResponseXML returning progress: {progress}% for task: {active_task.get('entity', 'N/A')}")
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

# Helper function to extract text from XML element, with logging
def _extract_text(xml_element: ET.Element, xpath: str) -> str:
    try:
        result = xml_element.findtext(xpath)
        return result.strip() if result else ""
    except Exception as e:
        logger.warning(f"Error extracting text for xpath '{xpath}': {e}")
        return ""
