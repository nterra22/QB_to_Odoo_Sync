"""
QBXML builder utilities for QB Odoo Sync application.

Provides helpers to build QBXML requests for QuickBooks Web Connector.
"""
from typing import Dict, Any
from xml.sax.saxutils import escape
from ..logging_config import logger

def build_invoice_add_qbxml(odoo_invoice: Dict[str, Any]) -> str:
    """
    Build a QBXML InvoiceAdd request from an Odoo invoice dict.
    Args:
        odoo_invoice (dict): The Odoo invoice data, including line items.
    Returns:
        str: The QBXML InvoiceAdd request as a string.
    """
    customer_name = odoo_invoice.get('partner_id', [None, 'Unknown'])[1]
    txn_date = odoo_invoice.get("invoice_date")
    ref_number = odoo_invoice.get("name")
    memo = odoo_invoice.get("narration")

    invoice_lines_xml = ""
    for line in odoo_invoice.get('invoice_line_ids', []):
        # Extract product name from the tuple (e.g., (1, 'Product Name'))
        item_name = line.get('product_id', [None, ''])[1]
        if not item_name:
            logger.warning(f"Skipping invoice line with no product: {line}")
            continue

        description = line.get('name', '')
        quantity = line.get('quantity', 0)
        price = line.get('price_unit', 0.0)
        
        invoice_lines_xml += f"""
        <InvoiceLineAdd>
            <ItemRef><FullName>{escape(item_name)}</FullName></ItemRef>
            <Desc>{escape(description)}</Desc>
            <Quantity>{quantity}</Quantity>
            <Rate>{price}</Rate>
        </InvoiceLineAdd>
        """

    if not invoice_lines_xml:
        logger.warning(f"Invoice {ref_number} has no lines to add. Skipping QBXML generation.")
        return ""

    qbxml = f"""
<?xml version="1.0" encoding="utf-8"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <InvoiceAddRq>
      <InvoiceAdd>
        <CustomerRef>
          <FullName>{escape(customer_name)}</FullName>
        </CustomerRef>
        <TxnDate>{txn_date}</TxnDate>
        <RefNumber>{escape(ref_number or '')}</RefNumber>
        <Memo>{escape(memo or '')}</Memo>
        {invoice_lines_xml}
      </InvoiceAdd>
    </InvoiceAddRq>
  </QBXMLMsgsRq>
</QBXML>
"""
    return qbxml

def build_customer_add_qbxml(customer_data: Dict[str, Any]) -> str:
    """
    Builds a CustomerAddRq QBXML request from Odoo partner data.
    """
    name = customer_data.get('name', 'Unknown Customer')
    logger.info(f"Building CustomerAddRq for customer: {name}")
    
    # Safely extract possibly missing address parts
    street = customer_data.get("street", "") or ""
    street2 = customer_data.get("street2", "") or ""
    city = customer_data.get("city", "") or ""
    zip_code = customer_data.get("zip", "") or ""
    state_name = customer_data.get('state_id', [None, ''])[1] or ""
    country_name = customer_data.get('country_id', [None, ''])[1] or ""
    email = customer_data.get("email", "") or ""
    phone = customer_data.get("phone", "") or ""

    return f"""<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="13.0"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <CustomerAddRq>
      <CustomerAdd>
        <Name>{escape(name)}</Name>
        <BillAddress>
            <Addr1>{escape(street)}</Addr1>
            <Addr2>{escape(street2)}</Addr2>
            <City>{escape(city)}</City>
            <State>{escape(state_name)}</State>
            <PostalCode>{escape(zip_code)}</PostalCode>
            <Country>{escape(country_name)}</Country>
        </BillAddress>
        <Phone>{escape(phone)}</Phone>
        <Email>{escape(email)}</Email>
      </CustomerAdd>
    </CustomerAddRq>
  </QBXMLMsgsRq>
</QBXML>"""

def build_item_add_qbxml(item_data: Dict[str, Any]) -> str:
    """
    Builds an ItemServiceAddRq QBXML request from Odoo product data.
    Assumes a service item type for simplicity.
    """
    name = item_data.get('name', 'Unknown Item')
    price = item_data.get('list_price', '0.00')
    
    # In a real-world scenario, this should be mapped from Odoo's income account
    income_account = "Services" 
    
    logger.info(f"Building ItemServiceAddRq for item: {name}")
    
    return f"""<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="13.0"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <ItemServiceAddRq>
      <ItemServiceAdd>
        <Name>{escape(name)}</Name>
        <SalesOrPurchase>
            <Price>{price}</Price>
            <AccountRef>
                <FullName>{escape(income_account)}</FullName>
            </AccountRef>
        </SalesOrPurchase>
      </ItemServiceAdd>
    </ItemServiceAddRq>
  </QBXMLMsgsRq>
</QBXML>"""
