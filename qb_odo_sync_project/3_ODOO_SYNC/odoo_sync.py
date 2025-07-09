import xmlrpc.client
import xml.etree.ElementTree as ET
import os
import logging

# Configuration for Odoo
ODOO_URL = 'https://nterra22-sounddecision-odoo-master-8977870.dev.odoo.com/'
ODOO_DB = 'nterra22-sounddecision-odoo-master-8977870'
ODOO_USER = 'it@wadic.net'
ODOO_API_KEY = 'c5f9aa88c5f89b4b8c61d36dda5f7ba106e3b702'

# Path to the inventory XML file
INVENTORY_XML_PATH = 'C:\\SD Code Files\\QB Odoo Sync\\QB_to_Odoo_Sync\\qb_odo_sync_project\\2_SD_MASTER_DATABASE\\inventory.xml'

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def connect_odoo():
    """Connects to the Odoo database."""
    try:
        common = xmlrpc.client.ServerProxy(f'{ODOO_URL}xmlrpc/2/common')
        uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_API_KEY, {})
        if not uid:
            logger.error("Odoo authentication failed.")
            return None, None
        logger.info("Odoo authentication successful.")
        models = xmlrpc.client.ServerProxy(f'{ODOO_URL}xmlrpc/2/object')
        return uid, models
    except Exception as e:
        logger.error(f"Error connecting to Odoo: {e}")
        return None, None

def get_odoo_inventory(uid, models):
    """Fetches inventory data from Odoo."""
    try:
        # Search for all products that are storable
        product_ids = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'search', [[('type', '=', 'product')]])

        # Read product data, including inventory fields
        products = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'read', [product_ids], {
                'fields': ['name', 'list_price', 'standard_price', 'description_sale', 'description_purchase', 'qty_available']
            })
        logger.info(f"Fetched {len(products)} products from Odoo.")
        return products
    except Exception as e:
        logger.error(f"Error fetching Odoo inventory: {e}")
        return []

def read_xml_inventory():
    """Reads inventory data from the local XML file."""
    xml_items = {}
    if not os.path.exists(INVENTORY_XML_PATH):
        logger.warning(f"Inventory XML file not found at {INVENTORY_XML_PATH}.")
        return xml_items
    try:
        tree = ET.parse(INVENTORY_XML_PATH)
        root = tree.getroot()
        # Assuming ItemInventoryRet is the relevant tag for inventory items
        for item in root.findall('.//ItemInventoryRet'):
            name = item.findtext('Name')
            if name:
                xml_items[name] = item
        logger.info(f"Read {len(xml_items)} items from XML file.")
        return xml_items
    except Exception as e:
        logger.error(f"Error reading XML inventory: {e}")
        return {}

def write_xml_inventory(xml_items):
    """Writes updated inventory data back to the XML file, pretty-printed."""
    # Create a basic XML structure if it doesn't exist
    if not os.path.exists(INVENTORY_XML_PATH) or not ET.parse(INVENTORY_XML_PATH).getroot().find('.//ItemInventoryQueryRs'):
         root = ET.Element("QBXML")
         msgs_rs = ET.SubElement(root, "QBXMLMsgsRs")
         ET.SubElement(msgs_rs, "ItemInventoryQueryRs", requestID="1", statusCode="0", statusSeverity="Info", statusMessage="Status OK")
         tree = ET.ElementTree(root)
    else:
        tree = ET.parse(INVENTORY_XML_PATH)
        root = tree.getroot()

    query_rs = root.find('.//ItemInventoryQueryRs')
    if query_rs is None:
         msgs_rs = root.find('QBXMLMsgsRs')
         if msgs_rs is None:
             msgs_rs = ET.SubElement(root, 'QBXMLMsgsRs')
         query_rs = ET.SubElement(msgs_rs, 'ItemInventoryQueryRs')

    # Clear existing ItemInventoryRet elements to replace with updated ones
    for item in query_rs.findall('ItemInventoryRet'):
        query_rs.remove(item)

    # Add all items from the updated xml_items dictionary
    for name, item_element in xml_items.items():
        query_rs.append(item_element)

    # Pretty-print the XML with each field on its own line
    def indent(elem, level=0):
        i = "\n" + level * "    "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "    "
            for child in elem:
                indent(child, level + 1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    indent(root)
    try:
        tree.write(INVENTORY_XML_PATH, encoding='utf-8', xml_declaration=True)
        logger.info(f"Successfully wrote {len(xml_items)} items to XML file (pretty-printed).")
    except Exception as e:
        logger.error(f"Error writing XML inventory: {e}")

def sync_odoo_to_xml():
    """Syncs inventory data from Odoo to the XML file."""
    logger.info("Starting Odoo to XML sync.")
    uid, models = connect_odoo()
    if not uid or not models:
        return

    odoo_products = get_odoo_inventory(uid, models)
    xml_items = read_xml_inventory()

    updated_xml_items = {}

    for odoo_product in odoo_products:
        odoo_name = odoo_product.get('name')
        if not odoo_name:
            logger.warning(f"Skipping Odoo product with no name: {odoo_product}")
            continue

        # Find matching item in XML by name
        xml_item = xml_items.get(odoo_name)

        def get_or_create(element, tag, default=None):
            child = element.find(tag)
            if child is None:
                child = ET.Element(tag)
                if default is not None:
                    child.text = str(default)
                element.append(child)
            return child

        def set_or_create(element, tag, value, default=None):
            child = element.find(tag)
            if child is None:
                child = ET.Element(tag)
                element.append(child)
            child.text = str(value) if value is not None else (str(default) if default is not None else '')
            return child

        # Helper to generate a random ListID/EditSequence if missing
        import uuid, datetime
        def gen_id():
            return str(uuid.uuid4())
        def now_qbxml():
            return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S-04:00')

        if xml_item is not None:
            logger.info(f"Updating XML item '{odoo_name}' from Odoo.")
            # Update or create all required fields
            set_or_create(xml_item, 'Name', odoo_name)
            set_or_create(xml_item, 'FullName', odoo_name)  # Could be improved for subitems
            set_or_create(xml_item, 'IsActive', 'true')
            set_or_create(xml_item, 'Sublevel', '0')
            set_or_create(xml_item, 'SalesDesc', odoo_product.get('description_sale'))
            set_or_create(xml_item, 'SalesPrice', odoo_product.get('list_price', 0.0))
            set_or_create(xml_item, 'PurchaseDesc', odoo_product.get('description_purchase'))
            set_or_create(xml_item, 'PurchaseCost', odoo_product.get('standard_price', 0.0))
            set_or_create(xml_item, 'QuantityOnHand', odoo_product.get('qty_available', 0))
            set_or_create(xml_item, 'AverageCost', odoo_product.get('standard_price', 0.0))
            set_or_create(xml_item, 'QuantityOnOrder', '0')
            set_or_create(xml_item, 'QuantityOnSalesOrder', '0')
            set_or_create(xml_item, 'ManufacturerPartNumber', odoo_product.get('default_code', ''))
            # IDs and timestamps: preserve if present, else generate
            set_or_create(xml_item, 'ListID', xml_item.findtext('ListID') or gen_id())
            set_or_create(xml_item, 'TimeCreated', xml_item.findtext('TimeCreated') or now_qbxml())
            set_or_create(xml_item, 'TimeModified', now_qbxml())
            set_or_create(xml_item, 'EditSequence', xml_item.findtext('EditSequence') or gen_id())
            # Account refs
            def set_account_ref(parent, tag, listid, fullname):
                acc = parent.find(tag)
                if acc is None:
                    acc = ET.Element(tag)
                    parent.append(acc)
                set_or_create(acc, 'ListID', listid)
                set_or_create(acc, 'FullName', fullname)
            set_account_ref(xml_item, 'IncomeAccountRef', '80000007-1750251562', 'Merchandise Sales')
            set_account_ref(xml_item, 'COGSAccountRef', '80000021-1750251775', 'Cost of Goods Sold')
            set_account_ref(xml_item, 'AssetAccountRef', '80000020-1750251775', 'Inventory Asset')
            # SalesTaxCodeRef
            set_account_ref(xml_item, 'SalesTaxCodeRef', '80000001-1750251552', 'Tax')
            # ParentRef (optional, only if subitem)
            # ...existing code...
            updated_xml_items[odoo_name] = xml_item
        else:
            logger.info(f"Adding new item '{odoo_name}' from Odoo to XML.")
            new_item_element = ET.Element('ItemInventoryRet')
            set_or_create(new_item_element, 'ListID', gen_id())
            set_or_create(new_item_element, 'TimeCreated', now_qbxml())
            set_or_create(new_item_element, 'TimeModified', now_qbxml())
            set_or_create(new_item_element, 'EditSequence', gen_id())
            set_or_create(new_item_element, 'Name', odoo_name)
            set_or_create(new_item_element, 'FullName', odoo_name)
            set_or_create(new_item_element, 'IsActive', 'true')
            set_or_create(new_item_element, 'Sublevel', '0')
            set_or_create(new_item_element, 'SalesDesc', odoo_product.get('description_sale'))
            set_or_create(new_item_element, 'SalesPrice', odoo_product.get('list_price', 0.0))
            set_or_create(new_item_element, 'PurchaseDesc', odoo_product.get('description_purchase'))
            set_or_create(new_item_element, 'PurchaseCost', odoo_product.get('standard_price', 0.0))
            set_or_create(new_item_element, 'QuantityOnHand', odoo_product.get('qty_available', 0))
            set_or_create(new_item_element, 'AverageCost', odoo_product.get('standard_price', 0.0))
            set_or_create(new_item_element, 'QuantityOnOrder', '0')
            set_or_create(new_item_element, 'QuantityOnSalesOrder', '0')
            set_or_create(new_item_element, 'ManufacturerPartNumber', odoo_product.get('default_code', ''))
            # Account refs
            def add_account_ref(parent, tag, listid, fullname):
                acc = ET.SubElement(parent, tag)
                ET.SubElement(acc, 'ListID').text = listid
                ET.SubElement(acc, 'FullName').text = fullname
            add_account_ref(new_item_element, 'IncomeAccountRef', '80000007-1750251562', 'Merchandise Sales')
            add_account_ref(new_item_element, 'COGSAccountRef', '80000021-1750251775', 'Cost of Goods Sold')
            add_account_ref(new_item_element, 'AssetAccountRef', '80000020-1750251775', 'Inventory Asset')
            add_account_ref(new_item_element, 'SalesTaxCodeRef', '80000001-1750251552', 'Tax')
            # ParentRef (optional, only if subitem)
            # ...existing code...
            updated_xml_items[odoo_name] = new_item_element

    # Include items from the original XML that were not in Odoo (they might be only in QB)
    for name, xml_item in xml_items.items():
        if name not in updated_xml_items:
            updated_xml_items[name] = xml_item

    write_xml_inventory(updated_xml_items)
    logger.info("Odoo to XML sync finished.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'odoo2xml':
        sync_odoo_to_xml()
    else:
        logger.info("Running Odoo→XML sync.")
        sync_odoo_to_xml()
