from odoo import http
from odoo.http import request
import logging
import os
import xml.etree.ElementTree as ET
import json
from spyne import rpc, ServiceBase
from spyne.protocol.soap import Soap11
from spyne.protocol.qbxml import QBXMLMessage
from spyne.model.primitive import Unicode, Integer
from spyne.model.complex import Array, ComplexModel
from spyne.protocol.qbxml import QBXML

_logger = logging.getLogger(__name__)

class QBWCService(ServiceBase):
    @rpc(Unicode, Unicode, Unicode, Unicode, _returns=Unicode)
    def sendRequestXML(self, ticket, db, username, password):
        _logger.info("QBWC sendRequestXML called")
        qbxml_requests = []
        session_state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'qbwc_session_state.json')
        if os.path.exists(session_state_path):
            with open(session_state_path, 'r') as f:
                session_state = json.load(f)
        else:
            session_state = {"iteratorID": None, "iteratorRemainingCount": 0}

        iteratorID = session_state.get("iteratorID")
        iteratorRemainingCount = session_state.get("iteratorRemainingCount", 0)

        if iteratorID and iteratorRemainingCount > 0:
            qbxml = f'''<?xml version="1.0" encoding="utf-8"?>\n<?qbxml version="13.0"?>\n<QBXML>\n    <QBXMLMsgsRq onError="stopOnError">\n        <ItemInventoryQueryRq requestID="1" iterator="Continue" iteratorID="{iteratorID}">\n            <MaxReturned>100</MaxReturned>\n        </ItemInventoryQueryRq>\n    </QBXMLMsgsRq>\n</QBXML>\n'''
            _logger.info(f"Continuing inventory query with iteratorID={iteratorID}, remaining={iteratorRemainingCount}")
            return qbxml
        else:
            qbxml = """<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<?qbxml version=\"13.0\"?>\n<QBXML>\n    <QBXMLMsgsRq onError=\"stopOnError\">\n        <ItemInventoryQueryRq requestID=\"1\" iterator=\"Start\">\n            <MaxReturned>100</MaxReturned>\n        </ItemInventoryQueryRq>\n    </QBXMLMsgsRq>\n</QBXML>\n"""
            _logger.info("Starting new inventory query with iterator=Start")
            return qbxml

    @rpc(Unicode, Unicode, Unicode, Unicode, _returns=Integer)
    def receiveResponseXML(self, ticket, response, hresult, message):
        _logger.info("QBWC receiveResponseXML called")
        if hresult:
            _logger.error(f"QBWC receiveResponseXML error. HRESULT: {hresult}, Message: {message}")
            return -1
        if not response:
            _logger.info("Empty response from QB, assuming session is done.")
            return 100
        
        _logger.info(f"Received response from QB: {response[:1000]}...")
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '2_SD_MASTER_DATABASE')
        output_file = os.path.join(output_dir, 'inventory.xml')

        try:
            response_root = ET.fromstring(response)
            
            if not os.path.exists(output_file):
                _logger.info(f"inventory.xml not found at {output_file}, creating it.")
                xml_root = ET.Element("QBXML")
                msgs_rs = ET.SubElement(xml_root, "QBXMLMsgsRs")
                ET.SubElement(msgs_rs, "ItemInventoryQueryRs", requestID="1", statusCode="0", statusSeverity="Info", statusMessage="Status OK")
                tree = ET.ElementTree(xml_root)
            else:
                tree = ET.parse(output_file)
                xml_root = tree.getroot()

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
                        for item_in_xml in xml_root.findall('.//ItemInventoryRet'):
                            if item_in_xml.findtext('Name') == name and not item_in_xml.findtext('ListID'):
                                replace_element_content(item_in_xml, item_ret)
                                _logger.info(f"Updated new item '{name}' with full data from QB.")
                                break
            
            for mod_rs in response_root.findall('.//ItemInventoryModRs'):
                if mod_rs.get('statusCode') == '0':
                    item_ret = mod_rs.find('ItemInventoryRet')
                    if item_ret is not None:
                        list_id = item_ret.findtext('ListID')
                        for item_in_xml in xml_root.findall('.//ItemInventoryRet'):
                            if item_in_xml.findtext('ListID') == list_id:
                                replace_element_content(item_in_xml, item_ret)
                                _logger.info(f"Updated modified item '{item_ret.findtext('Name')}' with new data from QB.")
                                break
                else:
                    _logger.error(f"Failed to modify item in QB. Code: {mod_rs.get('statusCode')}, Message: {mod_rs.get('statusMessage')}")

            query_rs = response_root.find('.//ItemInventoryQueryRs')
            if query_rs is not None and query_rs.get('statusCode') == '0':
                
                query_rs_in_xml = xml_root.find('.//ItemInventoryQueryRs')
                if query_rs_in_xml is None:
                    msgs_rs = xml_root.find('QBXMLMsgsRs')
                    if msgs_rs is None:
                        msgs_rs = ET.SubElement(xml_root, 'QBXMLMsgsRs')
                    query_rs_in_xml = ET.SubElement(msgs_rs, 'ItemInventoryQueryRs')

                for k, v in query_rs.items():
                    query_rs_in_xml.set(k, v)

                xml_items_map = {item.findtext('ListID'): item for item in query_rs_in_xml.findall('ItemInventoryRet')}
                qb_items_map = {item.findtext('ListID'): item for item in query_rs.findall('ItemInventoryRet')}

                for list_id, item_from_qb in qb_items_map.items():
                    if list_id in xml_items_map:
                        xml_item = xml_items_map[list_id]
                        qb_edit_seq = item_from_qb.findtext('EditSequence')
                        xml_edit_seq = xml_item.findtext('EditSequence')
                        if qb_edit_seq != xml_edit_seq:
                            replace_element_content(xml_item, item_from_qb)
                            _logger.info(f"Updating item in XML from QB changes: {item_from_qb.findtext('Name')}")
                    else:
                        query_rs_in_xml.append(item_from_qb)
                        _logger.info(f"Adding new item from QB to XML: {item_from_qb.findtext('Name')}")

                for list_id, item_in_xml in list(xml_items_map.items()):
                    if list_id not in qb_items_map:
                        query_rs_in_xml.remove(item_in_xml)
                        _logger.info(f"Removed item from XML (deleted in QB): {item_in_xml.findtext('Name')}")

            tree.write(output_file, encoding='utf-8', xml_declaration=True)
            _logger.info(f"Successfully processed response and updated {output_file}")

        except ET.ParseError as e:
            _logger.error(f"XML ParseError in receiveResponseXML: {e}. Response was: {response}")
            return -1
        except Exception as e:
            _logger.error(f"Failed to process QB response: {e}", exc_info=True)
            return -1

        # After processing response, update iterator state
        session_state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'qbwc_session_state.json')
        try:
            response_root = ET.fromstring(response)
            query_rs = response_root.find('.//ItemInventoryQueryRs')
            iteratorID = None
            iteratorRemainingCount = 0
            if query_rs is not None:
                iteratorID = query_rs.get('iteratorID')
                iteratorRemainingCount = int(query_rs.get('iteratorRemainingCount', '0'))
            with open(session_state_path, 'w') as f:
                json.dump({"iteratorID": iteratorID, "iteratorRemainingCount": iteratorRemainingCount}, f)
        except Exception as e:
            _logger.error(f"Failed to update iterator state: {e}", exc_info=True)

        return 100

    @rpc(Unicode, _returns=Unicode)
    def getLastError(self, ticket):
        pass