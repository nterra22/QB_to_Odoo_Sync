"""
QBXML builder utilities for QB Odoo Sync application.

Provides helpers to build QBXML requests for QuickBooks Web Connector.
"""
from typing import Dict, Any
from ..logging_config import logger

def build_invoice_add_qbxml(odoo_invoice: Dict[str, Any], field_mapping: Dict[str, Any]) -> str:
    """
    Build a QBXML InvoiceAdd request from an Odoo invoice dict using the field mapping.
    Args:
        odoo_invoice (dict): The Odoo invoice data.
        field_mapping (dict): The mapping from QB fields to Odoo fields (from field_mapping.json).
    Returns:
        str: The QBXML InvoiceAdd request as a string.
    """
    invoice_map = field_mapping.get("entities", {}).get("Invoices", {})
    if not invoice_map:
        logger.error("Invoice mapping not found in field_mapping.json. Cannot build QBXML.")
        return ""

    def get_val(qb_field):
        odoo_field = invoice_map.get(qb_field)
        return odoo_invoice.get(odoo_field) if odoo_field else None

    # Example: Map some common fields. Expand as needed.
    customer_name = get_val("CustomerRef")
    txn_date = get_val("TxnDate")
    ref_number = get_val("RefNumber")
    amount = get_val("Amount")
    memo = get_val("Memo")

    qbxml = f"""
<?xml version="1.0" encoding="utf-8"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <InvoiceAddRq>
      <InvoiceAdd>
        <CustomerRef>
          <FullName>{customer_name or ''}</FullName>
        </CustomerRef>
        <TxnDate>{txn_date or ''}</TxnDate>
        <RefNumber>{ref_number or ''}</RefNumber>
        <Memo>{memo or ''}</Memo>
        <!-- Add more fields and line items as needed -->
      </InvoiceAdd>
    </InvoiceAddRq>
  </QBXMLMsgsRq>
</QBXML>
"""
    return qbxml
