"""
SOAP protocol patches for handling lxml encoding issues with QuickBooks Web Connector.

This module provides patched versions of Spyne's SOAP11 protocol and XML document
classes to handle the specific encoding declaration issues that occur when QBWC
sends XML with encoding declarations that lxml cannot process directly.
"""
import logging
from typing import Any, Optional, Union
import six as six_spyne
from lxml import etree

from spyne.protocol.soap import soap11
from spyne.util.xml import get_xml_as_object

logger = logging.getLogger(__name__)

class LxmlFriendlyXmlDocument:
    """
    Custom XML document parser that handles encoding declaration issues with lxml.
    
    This class provides a workaround for the lxml error:
    "Deserializing from unicode strings with encoding declaration is not supported by lxml."
    """
    
    def __init__(self):
        """Initialize the XML document parser."""
        logger.debug("LxmlFriendlyXmlDocument initialized")
    
    def parse_xml_string(self, xml_string: Union[str, bytes], validator: Optional[Any] = None) -> Any:
        """
        Parse XML string with encoding declaration handling.
        
        Args:
            xml_string: The XML content to parse
            validator: Optional validator (not used in this implementation)
            
        Returns:
            Parsed XML document object
              Raises:
            ValueError: If XML parsing fails after attempting fixes
        """
        logger.debug("LXML_PATCH: parse_xml_string called")
        logger.debug(f"LXML_PATCH: Input type: {type(xml_string)}")
          # Handle generator objects by converting to string
        if hasattr(xml_string, '__iter__') and not isinstance(xml_string, (str, bytes)):
            logger.debug("LXML_PATCH: Input is a generator/iterator, converting to string")
            # Handle both bytes and strings in the iterator
            parts = []
            for part in xml_string:
                if isinstance(part, bytes):
                    parts.append(part.decode('utf-8', errors='replace'))
                else:
                    parts.append(str(part))
            xml_string = ''.join(parts)
        
        if isinstance(xml_string, bytes):
            logger.debug("LXML_PATCH: Input is bytes, converting to string")
            xml_string = xml_string.decode('utf-8', errors='replace')
        
        logger.debug(f"LXML_PATCH: XML content preview: {xml_string[:200] if len(xml_string) > 200 else xml_string}...")
        
        try:
            # First attempt: try parsing as-is
            logger.debug("LXML_PATCH: Attempting direct parse")
            return get_xml_as_object(xml_string, validator)
        except ValueError as e:
            if "encoding declaration" in str(e):
                logger.debug("LXML_PATCH: Encoding declaration error detected, attempting fix")
                
                # Remove encoding declaration from XML string
                import re
                pattern = r'<\?xml\s+version\s*=\s*["\'][^"\']*["\']\s+encoding\s*=\s*["\'][^"\']*["\']\s*\?>'
                fixed_xml = re.sub(pattern, '<?xml version="1.0"?>', xml_string)
                
                if fixed_xml != xml_string:
                    logger.debug("LXML_PATCH: Removed encoding declaration, retrying parse")
                    logger.debug(f"LXML_PATCH: Fixed XML preview: {fixed_xml[:200]}...")
                    
                    try:
                        return get_xml_as_object(fixed_xml, validator)
                    except Exception as fix_error:
                        logger.error(f"LXML_PATCH: Parse failed even after encoding fix: {fix_error}")
                        raise
                else:
                    logger.debug("LXML_PATCH: No encoding declaration found to remove")
                    raise
            else:
                logger.error(f"LXML_PATCH: Non-encoding related parse error: {e}")
                raise
        except Exception as e:
            logger.error(f"LXML_PATCH: Unexpected error during XML parsing: {e}")
            raise


class PatchedSoap11(soap11.Soap11):
    """
    Patched version of Spyne's Soap11 protocol class.
    
    This class overrides the create_in_document method to use our custom
    LxmlFriendlyXmlDocument parser instead of the default lxml parser.
    """
    
    def __init__(self, app=None, validator=None, xml_declaration=True, cleanup_namespaces=True):
        """
        Initialize the patched SOAP11 protocol.
        
        Args:
            app: Spyne application instance
            validator: Validator type ('lxml', 'soft', etc.)
            xml_declaration: Whether to include XML declaration in output
            cleanup_namespaces: Whether to cleanup namespaces
        """
        logger.debug(f"PatchedSoap11 __init__: Entry. validator={validator}")
        
        # Initialize xml_document_type first to avoid AttributeError
        self.xml_document_type = None
        
        # Call parent constructor
        super().__init__(app, validator=validator, xml_declaration=xml_declaration, 
                        cleanup_namespaces=cleanup_namespaces)
        
        # Log what the parent constructor set up
        logger.debug(f"PatchedSoap11 __init__: After super().__init__")
        logger.debug(f"  self.validator: {getattr(self, 'validator', 'NOT_SET')}")
        logger.debug(f"  self.xml_document_type: {getattr(self, 'xml_document_type', 'NOT_SET')}")
        
        # Override xml_document_type if validator is 'lxml' or if we want to force our patch
        if validator == 'lxml' or not hasattr(self, 'xml_document_type') or self.xml_document_type is None:
            logger.debug("PatchedSoap11 __init__: Setting custom xml_document_type")
            self.xml_document_type = LxmlFriendlyXmlDocument
            
            # Ensure validator is set to 'lxml' if it wasn't already
            if not hasattr(self, 'validator') or self.validator is None:
                self.validator = 'lxml'
                
        logger.info(f"PatchedSoap11 __init__: Initialization complete")
        logger.info(f"  Final validator: {getattr(self, 'validator', 'NOT_SET')}")
        logger.info(f"  Final xml_document_type: {getattr(self, 'xml_document_type', 'NOT_SET')}")
    
    def create_in_document(self, ctx, in_string_charset=None):
        """
        Create input document using our custom XML parser.
        
        Args:
            ctx: Spyne context object
            in_string_charset: Input string character set
        """
        logger.debug("PATCHED_SOAP11_CREATE_IN_DOC: Entry")
        
        # Get the input string from context
        S = ctx.in_string
        logger.debug(f"PATCHED_SOAP11_CREATE_IN_DOC: Input string type: {type(S)}")
        
        if isinstance(S, bytes):
            logger.debug(f"PATCHED_SOAP11_CREATE_IN_DOC: S (bytes) length: {len(S)}")
            logger.debug(f"PATCHED_SOAP11_CREATE_IN_DOC: S (bytes) preview: {S[:150]}")
        elif isinstance(S, six_spyne.string_types):
            logger.debug(f"PATCHED_SOAP11_CREATE_IN_DOC: S (string) length: {len(S)}")
            logger.debug(f"PATCHED_SOAP11_CREATE_IN_DOC: S (string) preview: {S[:150]}")
        else:
            logger.debug(f"PATCHED_SOAP11_CREATE_IN_DOC: S (unknown type) preview: {str(S)[:150]}")
        
        # Ensure xml_document_type is available
        if not hasattr(self, 'xml_document_type') or self.xml_document_type is None:
            logger.warning("PATCHED_SOAP11_CREATE_IN_DOC: xml_document_type not set, using default")
            self.xml_document_type = LxmlFriendlyXmlDocument
            
        logger.debug(f"PATCHED_SOAP11_CREATE_IN_DOC: xml_document_type is {self.xml_document_type}")
        
        # Use the validator from the instance
        effective_validator = getattr(self, 'validator', 'lxml')
        logger.debug(f"PATCHED_SOAP11_CREATE_IN_DOC: effective_validator is {effective_validator}")
        
        try:
            # Create an instance of our custom XML document parser
            logger.debug("PATCHED_SOAP11_CREATE_IN_DOC: Creating xml_document_type instance")
            xml_doc_instance = self.xml_document_type()
            
            # Use our custom parser
            logger.debug("PATCHED_SOAP11_CREATE_IN_DOC: Calling custom parse_xml_string")
            ctx.in_document = xml_doc_instance.parse_xml_string(S, validator=effective_validator)
            
            logger.debug("PATCHED_SOAP11_CREATE_IN_DOC: Successfully created in_document")
            
        except Exception as e:
            logger.error(f"PATCHED_SOAP11_CREATE_IN_DOC: Error creating in_document: {e}", exc_info=True)
            raise
