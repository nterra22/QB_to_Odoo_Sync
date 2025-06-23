"""
QBXML builder utilities for QB Odoo Sync application.

Provides helpers to build QBXML requests for QuickBooks Web Connector.
"""
from typing import Dict, Any
from xml.sax.saxutils import escape
from datetime import date
from ..logging_config import logger
from .data_loader import load_field_mapping, load_account_crosswalk

def build_invoice_add_qbxml(odoo_invoice: Dict[str, Any], qbxml_version: str = "13.0") -> str:
    """
    Build a QBXML InvoiceAdd request from an Odoo invoice dict.
    Uses proper field mapping and enhanced logging.
    Args:
        odoo_invoice (dict): The Odoo invoice data, including line items.
    Returns:
        str: The QBXML InvoiceAdd request as a string.
    """
    customer_name = odoo_invoice.get('partner_id', [None, 'Unknown'])[1]
    txn_date = odoo_invoice.get("invoice_date")
    ref_number = odoo_invoice.get("name")
    memo = odoo_invoice.get("narration")
    
    logger.info(f"Building InvoiceAddRq for invoice: {ref_number} (customer: {customer_name})")

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
    
    logger.info(f"Creating QB invoice for customer '{customer_name}' with {len(odoo_invoice.get('invoice_line_ids', []))} line items")

    qbxml = f"""
<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
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

def build_customer_add_qbxml(customer_data: Dict[str, Any], qbxml_version: str = "13.0") -> str:
    """
    Builds a CustomerAddRq QBXML request from Odoo partner data.
    Handles Company Name for business customers and First/Last Name for individuals.
    """
    name = customer_data.get('name', 'Unknown Customer')
    is_company = customer_data.get('is_company', False)
    logger.info(f"Building CustomerAddRq for customer: {name} (is_company: {is_company})")
    
    # Safely extract possibly missing address parts
    street = customer_data.get("street", "") or ""
    street2 = customer_data.get("street2", "") or ""
    city = customer_data.get("city", "") or ""
    zip_code = customer_data.get("zip", "") or ""
    state_name = customer_data.get('state_id', [None, ''])[1] or ""
    country_name = customer_data.get('country_id', [None, ''])[1] or ""
    email = customer_data.get("email", "") or ""
    phone = customer_data.get("phone", "") or ""
    
    # Build the customer fields based on whether it's a company or individual
    customer_fields = f"<Name>{escape(name)}</Name>"
    
    # Add Company Name field for business customers
    if is_company:
        # For companies, use the name as the company name
        company_name = customer_data.get('company_name') or name
        customer_fields += f"\n        <CompanyName>{escape(company_name)}</CompanyName>"
        logger.debug(f"Added CompanyName field: {company_name}")
    else:
        # For individuals, try to use first/last name if available
        firstname = customer_data.get('firstname', '') or ""
        lastname = customer_data.get('lastname', '') or ""
        
        if firstname:
            customer_fields += f"\n        <FirstName>{escape(firstname)}</FirstName>"
            logger.debug(f"Added FirstName field: {firstname}")
        if lastname:
            customer_fields += f"\n        <LastName>{escape(lastname)}</LastName>"
            logger.debug(f"Added LastName field: {lastname}")

    return f"""<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <CustomerAddRq>
      <CustomerAdd>
        {customer_fields}
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

def build_item_add_qbxml(item_data: Dict[str, Any], qbxml_version: str = "13.0") -> str:
    """
    Builds an ItemInventoryAddRq QBXML request from Odoo product data.
    Uses account_crosswalk.json for proper income, COGS, and asset account mapping.
    """
    name = item_data.get('name', 'Unknown Item')
    logger.info(f"Building ItemInventoryAddRq for item: {name}")

    # Load mapping files
    field_mapping = load_field_mapping().get('product.product', {})
    account_crosswalk = load_account_crosswalk()

    # --- Helper function for account mapping ---
    def get_qb_account(odoo_account_field: str, default_qb_account: str, account_type: str) -> str:
        odoo_account = item_data.get(odoo_account_field)
        if not odoo_account:
            logger.warning(f"Odoo account field '{odoo_account_field}' not found for item '{name}'. Using default: {default_qb_account}")
            return default_qb_account

        odoo_account_name = odoo_account[1] if isinstance(odoo_account, (list, tuple)) and len(odoo_account) > 1 else str(odoo_account)

        for qb_name, details in account_crosswalk.items():
            if isinstance(details, dict) and details.get('name') == odoo_account_name:
                logger.debug(f"Mapped Odoo account '{odoo_account_name}' to QB account '{qb_name}' for item '{name}'.")
                return qb_name
        
        logger.warning(f"No QB mapping found for Odoo account '{odoo_account_name}'. Searching for a default of type '{account_type}'.")
        # Fallback to first account of the same type
        for qb_name, details in account_crosswalk.items():
             if isinstance(details, dict) and details.get('type') == account_type:
                 logger.debug(f"Using fallback QB account '{qb_name}' for item '{name}'.")
                 return qb_name

        logger.error(f"No fallback account of type '{account_type}' found in crosswalk. Using hardcoded default: {default_qb_account}")
        return default_qb_account

    # --- Map Fields ---
    sales_desc = item_data.get(field_mapping.get('SalesDesc', 'description'), '')
    sales_price = item_data.get(field_mapping.get('SalesPrice', 'list_price'), '0.00')
    purchase_desc = item_data.get(field_mapping.get('PurchaseDesc', 'description'), '')
    purchase_cost = item_data.get(field_mapping.get('PurchaseCost', 'standard_price'), '0.00')
    quantity_on_hand = item_data.get(field_mapping.get('QuantityOnHand', 'qty_available'), 0)
    reorder_point = item_data.get(field_mapping.get('ReorderPoint', 'reordering_min_qty'), 0)
    barcode = item_data.get(field_mapping.get('BarCodeValue', 'barcode'), '')

    # --- Map Accounts ---
    income_account = get_qb_account('property_account_income_id', 'Sales', 'Income')
    cogs_account = get_qb_account('property_account_expense_id', 'Cost of Goods Sold', 'Cost of Goods Sold')
    asset_account = get_qb_account('property_stock_valuation_account_id', 'Inventory Asset', 'Inventory')

    # --- Get current date for inventory ---
    inventory_date = date.today().isoformat()

    # --- Build QBXML ---
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{qbxml_version}"?>
<QBXML>
  <QBXMLMsgsRq onError="stopOnError">
    <ItemInventoryAddRq>
      <ItemInventoryAdd>
        <Name>{escape(name)}</Name>
        <IsActive>true</IsActive>
        {f'<BarCode><BarCodeValue>{escape(barcode)}</BarCodeValue></BarCode>' if barcode else ''}
        <SalesDesc>{escape(sales_desc)}</SalesDesc>
        <SalesPrice>{sales_price}</SalesPrice>
        <IncomeAccountRef>
          <FullName>{escape(income_account)}</FullName>
        </IncomeAccountRef>
        <PurchaseDesc>{escape(purchase_desc)}</PurchaseDesc>
        <PurchaseCost>{purchase_cost}</PurchaseCost>
        <COGSAccountRef>
          <FullName>{escape(cogs_account)}</FullName>
        </COGSAccountRef>
        <AssetAccountRef>
          <FullName>{escape(asset_account)}</FullName>
        </AssetAccountRef>
        <ReorderPoint>{reorder_point}</ReorderPoint>
        <QuantityOnHand>{quantity_on_hand}</QuantityOnHand>
        <InventoryDate>{inventory_date}</InventoryDate>
      </ItemInventoryAdd>
    </ItemInventoryAddRq>
  </QBXMLMsgsRq>
</QBXML>"""

    logger.info(f"Generated ItemInventoryAddRq for item: {name}")
    return xml
