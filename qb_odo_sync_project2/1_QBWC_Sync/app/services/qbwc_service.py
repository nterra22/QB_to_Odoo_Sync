"""
QuickBooks Web Connector (QBWC) SOAP service implementation.

This service handles bi-directional inventory sync between QuickBooks and PostgreSQL database.
It extracts inventory from QuickBooks and stores it in a master PostgreSQL database with
unique sync keys for each record.
"""
from spyne import rpc, ServiceBase, Unicode, Iterable, Integer
import logging
import os
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# Hardcoded QBWC credentials
QBWC_USERNAME = "admin"
QBWC_PASSWORD = "odoo123"

class QBWCService(ServiceBase):
    """QuickBooks Web Connector SOAP service for QB ↔ PostgreSQL inventory sync."""
    
    def _compare_and_generate_mod_request(self, xml_item, qb_item):
        """
        Compares an item from the local XML with an item from QuickBooks.
        If they are different, it generates an ItemInventoryModRq XML string.
        """
        mod_spec = []
        
        # Field mapping: use QuickBooks field names directly
        fields = [
            'Name',
            'SalesDesc',
            'SalesPrice',
            'PurchaseDesc',
            'PurchaseCost',
            'IsActive',
            'ManufacturerPartNumber'
        ]

        for field in fields:
            xml_val = xml_item.findtext(field)
            qb_val = qb_item.findtext(field)
            if xml_val is not None and xml_val != qb_val:
                mod_spec.append(f"<{field}>{xml_val}</{field}>")

        # Reference fields to compare.
        ref_fields = ['ParentRef', 'SalesTaxCodeRef', 'IncomeAccountRef', 'COGSAccountRef', 'AssetAccountRef']
        for field in ref_fields:
            xml_val = xml_item.findtext(f'./{field}/FullName')
            qb_val = qb_item.findtext(f'./{field}/FullName')
            if xml_val is not None and xml_val != qb_val:
                mod_spec.append(f"<{field}><FullName>{xml_val}</FullName></{field}>")

        if not mod_spec:
            return None

        list_id = qb_item.findtext('ListID')
        edit_sequence = qb_item.findtext('EditSequence')

        if not edit_sequence:
            logger.warning(f"Cannot generate ModRq for item {list_id} because EditSequence is missing from QB data.")
            return None

        return f"""<ItemInventoryModRq>
    <ItemInventoryMod>
        <ListID>{list_id}</ListID>
        <EditSequence>{edit_sequence}</EditSequence>
        {''.join(mod_spec)}
    </ItemInventoryMod>
</ItemInventoryModRq>"""

    @rpc(Unicode, Unicode, _returns=Iterable(Unicode))
    def authenticate(self, strUserName, strPassword):
        """Authenticate QBWC connection and create session."""
        logger.info(f"QBWC authenticate called: {strUserName}")
        if strUserName == QBWC_USERNAME and strPassword == QBWC_PASSWORD:
            return ["ticket-12345", ""]
        else:
            return ["", "nvu"]

    @rpc(Unicode, Unicode, Unicode, Unicode, Unicode, Unicode, _returns=Unicode)
    def sendRequestXML(self, ticket, strHCPResponse, strCompanyFileName, qbXMLCountry, qbXMLMajorVers, qbXMLMinorVers):
        logger.info("QBWC sendRequestXML called for two-way sync.")
        import xml.etree.ElementTree as ET
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '2_SD_MASTER_DATABASE')
        xml_file_path = os.path.join(output_dir, 'inventory.xml')
        xml_items = {}
        qb_items = {}
        qbxml_requests = []
        root = None

        # Parse XML file for local inventory
        if os.path.exists(xml_file_path):
            try:
                tree = ET.parse(xml_file_path)
                root = tree.getroot()
                for item in root.findall('.//ItemInventoryRet'):
                    list_id = item.findtext('ListID')
                    if list_id:
                        xml_items[list_id] = item
            except Exception as e:
                logger.error(f"Error parsing local inventory.xml: {e}")
                # fallback: create a new root
                root = ET.Element("QBXMLMsgsRs")
        else:
            # If no file exists, create a basic XML structure
            root = ET.Element("QBXMLMsgsRs")

        # Parse strHCPResponse for QB inventory
        if strHCPResponse:
            try:
                qb_root = ET.fromstring(strHCPResponse)
                for item in qb_root.findall('.//ItemInventoryRet'):
                    list_id = item.findtext('ListID')
                    if list_id:
                        qb_items[list_id] = item
            except Exception as e:
                logger.error(f"Error parsing QB inventory from strHCPResponse: {e}")

        # For each XML item that has no ListID, generate an add request
        for item in root.findall('.//ItemInventoryRet'):
            list_id = item.findtext('ListID')
            if not list_id or not list_id.strip():
                name = item.findtext('Name')
                sales_price = item.findtext('SalesPrice') or '0.00'
                add_request = f"""<ItemInventoryAddRq>\n    <ItemInventoryAdd>\n        <Name>{name}</Name>\n        <IsActive>true</IsActive>\n        <SalesPrice>{sales_price}</SalesPrice>\n        <IncomeAccountRef>\n            <FullName>Merchandise Sales</FullName>\n        </IncomeAccountRef>\n        <COGSAccountRef>\n            <FullName>Cost of Goods Sold</FullName>\n        </COGSAccountRef>\n        <AssetAccountRef>\n            <FullName>Inventory Asset</FullName>\n        </AssetAccountRef>\n    </ItemInventoryAdd>\n</ItemInventoryAddRq>"""
                qbxml_requests.append(add_request)
          # Compare items and generate modification requests
        if qb_items:
            for list_id, xml_item in xml_items.items():
                if list_id in qb_items:
                    qb_item = qb_items[list_id]
                    mod_request = self._compare_and_generate_mod_request(xml_item, qb_item)
                    if mod_request:
                        qbxml_requests.append(mod_request)

        if not qbxml_requests:
            logger.info("No new or modified items to send to QB. Sending ItemInventoryQueryRq.")
            # Check session state for iterator paging
            import json
            session_state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'qbwc_session_state.json')
            if os.path.exists(session_state_path):
                with open(session_state_path, 'r') as f:
                    session_state = json.load(f)
            else:
                session_state = {"iteratorID": None, "iteratorRemainingCount": 0}

            iteratorID = session_state.get("iteratorID")
            iteratorRemainingCount = session_state.get("iteratorRemainingCount", 0)

            if iteratorID and iteratorRemainingCount > 0:
                qbxml = f'''<?xml version="1.0" encoding="utf-8"?>\n<?qbxml version="13.0"?>\n<QBXML>\n    <QBXMLMsgsRq onError="stopOnError">\n        <ItemInventoryQueryRq requestID="1" iterator="Continue" iteratorID="{iteratorID}">\n            <MaxReturned>100</MaxReturned>\n        </ItemInventoryQueryRq>\n    </QBXMLMsgsRq>\n</QBXML>\n'''
                logger.info(f"Continuing inventory query with iteratorID={iteratorID}, remaining={iteratorRemainingCount}")
            else:
                qbxml = """<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<?qbxml version=\"13.0\"?>\n<QBXML>\n    <QBXMLMsgsRq onError=\"stopOnError\">\n        <ItemInventoryQueryRq requestID=\"1\" iterator=\"Start\">\n            <MaxReturned>100</MaxReturned>\n        </ItemInventoryQueryRq>\n    </QBXMLMsgsRq>\n</QBXML>\n"""
                logger.info("Starting new inventory query with iterator=Start")
            return qbxml
        else:
            logger.info(f"Sending {len(qbxml_requests)} add/mod requests to QB.")
            requests = "\n".join(qbxml_requests)
            qbxml = f'''<?xml version="1.0" encoding="utf-8"?>\n<?qbxml version="13.0"?>\n<QBXML>\n    <QBXMLMsgsRq onError="stopOnError">\n        {requests}\n    </QBXMLMsgsRq>\n</QBXML>\n'''
            return qbxml

    @rpc(Unicode, Unicode, Unicode, Unicode, _returns=Integer)
    def receiveResponseXML(self, ticket, response, hresult, message):
        logger.info("QBWC receiveResponseXML called")
        try:
            if hresult:
                logger.error(f"QBWC receiveResponseXML error. HRESULT: {hresult}, Message: {message}")
                return -1
            if not response:
                logger.info("Empty response from QB, assuming session is done.")
                return 100

            logger.info(f"Received response from QB: {response[:1000]}...")
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '2_SD_MASTER_DATABASE')
            output_file = os.path.join(output_dir, 'inventory.xml')

            # --- Refactored full sync logic: accumulate all items in memory, write XML at the end ---
            import json
            session_state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'qbwc_session_state.json')
            iteratorRemainingCount = 0
            is_full_sync = False
            # Use a class attribute to accumulate items in memory during a full sync
            if not hasattr(self, '_fullsync_items'):
                self._fullsync_items = None

            response_root = ET.fromstring(response)
            query_rs = response_root.find('.//ItemInventoryQueryRs')
            iteratorID = None
            if query_rs is not None:
                iteratorID = query_rs.get('iteratorID')
                iteratorRemainingCount = int(query_rs.get('iteratorRemainingCount', '0'))
                if iteratorID:
                    is_full_sync = True
            # Reset iteratorID if done
            if not iteratorID or iteratorRemainingCount == 0:
                iteratorID = None
                iteratorRemainingCount = 0
            with open(session_state_path, 'w') as f:
                json.dump({"iteratorID": iteratorID, "iteratorRemainingCount": iteratorRemainingCount}, f)

            if is_full_sync:
                # Accumulate all items in memory (dict)
                if self._fullsync_items is None:
                    self._fullsync_items = {}
                for item in response_root.findall('.//ItemInventoryRet'):
                    list_id = item.findtext('ListID')
                    if list_id:
                        self._fullsync_items[list_id] = ET.tostring(item, encoding='unicode')
                logger.info(f"Accumulated {len(self._fullsync_items)} items so far in full sync.")
                if iteratorRemainingCount == 0:
                    # Write all items to inventory.xml
                    xml_root = ET.Element("QBXML")
                    msgs_rs = ET.SubElement(xml_root, "QBXMLMsgsRs")
                    query_rs_in_xml = ET.SubElement(msgs_rs, "ItemInventoryQueryRs", requestID="1", statusCode="0", statusSeverity="Info", statusMessage="Status OK")
                    for item_xml in self._fullsync_items.values():
                        item_elem = ET.fromstring(item_xml)
                        query_rs_in_xml.append(item_elem)
                    tree = ET.ElementTree(xml_root)
                    tree.write(output_file, encoding='utf-8', xml_declaration=True)
                    logger.info(f"Full sync complete. Wrote {len(self._fullsync_items)} items to {output_file}")
                    self._fullsync_items = None
            else:
                # Incremental update logic (existing code)
                if not os.path.exists(output_file):
                    logger.info(f"inventory.xml not found at {output_file}, creating it.")
                    xml_root = ET.Element("QBXML")
                    msgs_rs = ET.SubElement(xml_root, "QBXMLMsgsRs")
                    query_rs_in_xml = ET.SubElement(msgs_rs, "ItemInventoryQueryRs", requestID="1", statusCode="0", statusSeverity="Info", statusMessage="Status OK")
                    tree = ET.ElementTree(xml_root)
                else:
                    tree = ET.parse(output_file)
                    xml_root = tree.getroot()
                    msgs_rs = xml_root.find('QBXMLMsgsRs')
                    if msgs_rs is None:
                        msgs_rs = ET.SubElement(xml_root, 'QBXMLMsgsRs')
                    query_rs_in_xml = msgs_rs.find('ItemInventoryQueryRs')
                    if query_rs_in_xml is None:
                        query_rs_in_xml = ET.SubElement(msgs_rs, 'ItemInventoryQueryRs', requestID="1", statusCode="0", statusSeverity="Info", statusMessage="Status OK")

                # Handle AddRs and ModRs: update or replace items in XML
                def replace_element_content(old_element, new_element):
                    old_element.clear()
                    old_element.text = new_element.text
                    old_element.tail = new_element.tail
                    for k, v in new_element.items():
                        old_element.set(k, v)
                    for child in new_element:
                        old_element.append(child)

                for add_rs in response_root.findall('.//ItemInventoryAddRs'):
                    if add_rs.get('statusCode') == '0':
                        item_ret = add_rs.find('ItemInventoryRet')
                        if item_ret is not None:
                            name = item_ret.findtext('Name')
                            for item_in_xml in query_rs_in_xml.findall('ItemInventoryRet'):
                                if item_in_xml.findtext('Name') == name and not item_in_xml.findtext('ListID'):
                                    replace_element_content(item_in_xml, item_ret)
                                    logger.info(f"Updated new item '{name}' with full data from QB.")
                                    break

                for mod_rs in response_root.findall('.//ItemInventoryModRs'):
                    if mod_rs.get('statusCode') == '0':
                        item_ret = mod_rs.find('ItemInventoryRet')
                        if item_ret is not None:
                            list_id = item_ret.findtext('ListID')
                            for item_in_xml in query_rs_in_xml.findall('ItemInventoryRet'):
                                if item_in_xml.findtext('ListID') == list_id:
                                    replace_element_content(item_in_xml, item_ret)
                                    logger.info(f"Updated modified item '{item_ret.findtext('Name')}' with new data from QB.")
                                    break
                    else:
                        logger.error(f"Failed to modify item in QB. Code: {mod_rs.get('statusCode')}, Message: {mod_rs.get('statusMessage')}")

                tree.write(output_file, encoding='utf-8', xml_declaration=True)
                logger.info(f"Successfully processed response and updated {output_file}")

        except ET.ParseError as e:
            logger.error(f"XML ParseError in receiveResponseXML: {e}. Response was: {response}")
            return -1
        except Exception as e:
            logger.error(f"Failed to process QB response: {e}", exc_info=True)
            return -1

        # Return 0 if more work, 100 if done
        if iteratorRemainingCount > 0:
            logger.info(f"More inventory to fetch, iteratorRemainingCount={iteratorRemainingCount}. Returning 0 to QBWC.")
            return 0
        else:
            logger.info("All inventory fetched. Returning 100 to QBWC.")
            return 100

    @rpc(Unicode, _returns=Unicode)
    def getLastError(self, ticket):
        """Get last error for session."""
        logger.info("QBWC getLastError called")
        return "No error. QBWC handshake successful."
    
    @rpc(Unicode, Unicode, Unicode, _returns=Unicode)
    def connectionError(self, ticket, hresult, message):
        """Handle connection errors."""
        logger.error(f"QBWC connection error. Ticket: {ticket}, HRESULT: {hresult}, Message: {message}")
        return "done"
    
    @rpc(Unicode, _returns=Unicode)
    def closeConnection(self, ticket):
        """Close QBWC connection and cleanup session."""
        logger.info(f"Closing QBWC connection for ticket: {ticket}")
        return "OK"
    
    @rpc(_returns=Unicode)
    def serverVersion(self):
        """Return server version."""
        return "1.0.0"
    
    @rpc(Unicode, _returns=Unicode)  
    def clientVersion(self, strVersion):
        """Handle client version check."""
        logger.info(f"QBWC client version: {strVersion}")
        return ""
