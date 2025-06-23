"""
Wrapper functions for QB-Odoo sync operations.

This module provides simplified interfaces to the main sync application
functionality, handling missing functions and providing fallbacks.
"""

import sys
import os
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

# Add the main project to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'qb_odoo_sync_project'))

try:
    from app.logging_config import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

def get_odoo_invoices(limit: int = 10, domain: List = None) -> List[Dict[str, Any]]:
    """
    Retrieve invoices from Odoo with error handling.
    
    Args:
        limit: Maximum number of invoices to retrieve
        domain: Search domain filters
        
    Returns:
        List of invoice dictionaries
    """
    try:
        # Import here to handle potential import errors
        from app.services.odoo_service import _get_odoo_uid
        import xmlrpc.client
        
        uid = _get_odoo_uid()
        if not uid:
            raise Exception("Failed to authenticate with Odoo")
        
        # Odoo connection details (should be configured)
        ODOO_URL = "https://nterra22-sounddecision-odoo-develop-20178686.dev.odoo.com"
        ODOO_DB = "nterra22-sounddecision-odoo-develop-20178686"
        ODOO_API_KEY = "e8188dcec4b36dbc1e89e4da17b989c7aae8e568"
        
        models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object', allow_none=True)
        
        # Build search domain
        search_domain = domain if domain else []
        
        # Search for invoices
        invoice_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'account.move', 'search',
            [search_domain],
            {'limit': limit}
        )
        
        if not invoice_ids:
            return []
        
        # Read invoice data
        invoices = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'account.move', 'read',
            [invoice_ids],
            {'fields': ['name', 'partner_id', 'invoice_date', 'amount_total', 'state', 'invoice_line_ids', 'narration']}
        )
        
        # Read invoice lines for each invoice
        for invoice in invoices:
            if invoice.get('invoice_line_ids'):
                line_data = models.execute_kw(
                    ODOO_DB, uid, ODOO_API_KEY,
                    'account.move.line', 'read',
                    [invoice['invoice_line_ids']],
                    {'fields': ['product_id', 'name', 'quantity', 'price_unit', 'price_subtotal']}
                )
                invoice['invoice_line_ids'] = line_data
        
        logger.info(f"Retrieved {len(invoices)} invoices from Odoo")
        return invoices
        
    except Exception as e:
        logger.error(f"Error retrieving Odoo invoices: {e}")
        return []

def get_odoo_partners(limit: int = 10, domain: List = None) -> List[Dict[str, Any]]:
    """
    Retrieve partners from Odoo with error handling.
    
    Args:
        limit: Maximum number of partners to retrieve
        domain: Search domain filters
        
    Returns:
        List of partner dictionaries
    """
    try:
        from app.services.odoo_service import _get_odoo_uid
        import xmlrpc.client
        
        uid = _get_odoo_uid()
        if not uid:
            raise Exception("Failed to authenticate with Odoo")
        
        ODOO_URL = "https://nterra22-sounddecision-odoo-develop-20178686.dev.odoo.com"
        ODOO_DB = "nterra22-sounddecision-odoo-develop-20178686"
        ODOO_API_KEY = "e8188dcec4b36dbc1e89e4da17b989c7aae8e568"
        
        models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object', allow_none=True)
        
        search_domain = domain if domain else []
        
        partner_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'res.partner', 'search',
            [search_domain],
            {'limit': limit}
        )
        
        if not partner_ids:
            return []
        
        partners = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'res.partner', 'read',
            [partner_ids],
            {'fields': ['name', 'is_company', 'street', 'street2', 'city', 'zip', 'state_id', 'country_id', 'phone', 'email']}
        )
        
        logger.info(f"Retrieved {len(partners)} partners from Odoo")
        return partners
        
    except Exception as e:
        logger.error(f"Error retrieving Odoo partners: {e}")
        return []

def get_odoo_products(limit: int = 10, domain: List = None) -> List[Dict[str, Any]]:
    """
    Retrieve products from Odoo with error handling.
    
    Args:
        limit: Maximum number of products to retrieve
        domain: Search domain filters
        
    Returns:
        List of product dictionaries
    """
    try:
        from app.services.odoo_service import _get_odoo_uid
        import xmlrpc.client
        
        uid = _get_odoo_uid()
        if not uid:
            raise Exception("Failed to authenticate with Odoo")
        
        ODOO_URL = "https://nterra22-sounddecision-odoo-develop-20178686.dev.odoo.com"
        ODOO_DB = "nterra22-sounddecision-odoo-develop-20178686"
        ODOO_API_KEY = "e8188dcec4b36dbc1e89e4da17b989c7aae8e568"
        
        models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object', allow_none=True)
        
        search_domain = domain if domain else []
        
        product_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'search',
            [search_domain],
            {'limit': limit}
        )
        
        if not product_ids:
            return []
        
        products = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'read',
            [product_ids],
            {'fields': [
                'name', 'description', 'list_price', 'standard_price', 
                'qty_available', 'sale_ok', 'purchase_ok', 'barcode',
                'property_account_income_id', 'property_account_expense_id',
                'property_stock_valuation_account_id'
            ]}
        )
        
        logger.info(f"Retrieved {len(products)} products from Odoo")
        return products
        
    except Exception as e:
        logger.error(f"Error retrieving Odoo products: {e}")
        return []

def create_qb_request_queue(qbxml: str, request_type: str = "ADD") -> Dict[str, Any]:
    """
    Queue a QBXML request for processing by QuickBooks Web Connector.
    
    Args:
        qbxml: The QBXML request string
        request_type: Type of request (ADD, MOD, QUERY)
        
    Returns:
        Dictionary with queue status
    """
    try:
        # In a real implementation, this would add to a request queue
        # that the QBWC service would process
        queue_item = {
            "id": f"req_{datetime.now().timestamp()}",
            "qbxml": qbxml,
            "request_type": request_type,
            "status": "queued",
            "created_at": datetime.now().isoformat()
        }
        
        # For demo purposes, we'll just return the queue item
        # In production, this would be stored in a database or file
        logger.info(f"Queued QB request: {queue_item['id']}")
        return queue_item
        
    except Exception as e:
        logger.error(f"Error queuing QB request: {e}")
        return {"error": str(e)}

def get_sync_status() -> Dict[str, Any]:
    """
    Get the current sync status between QB and Odoo.
    
    Returns:
        Dictionary with sync status information
    """
    try:
        # Read session state if it exists
        session_file = os.path.join(
            os.path.dirname(__file__), 
            '..', 
            'qbwc_session_state.json'
        )
        
        status = {
            "last_sync": None,
            "qbwc_connected": False,
            "odoo_connected": False,
            "pending_requests": 0
        }
        
        if os.path.exists(session_file):
            try:
                with open(session_file, 'r') as f:
                    session_data = json.load(f)
                    status.update(session_data)
            except Exception as e:
                logger.warning(f"Could not read session state: {e}")
        
        # Test Odoo connection
        try:
            from app.services.odoo_service import _get_odoo_uid
            uid = _get_odoo_uid()
            status["odoo_connected"] = bool(uid)
        except:
            status["odoo_connected"] = False
        
        return status
        
    except Exception as e:
        logger.error(f"Error getting sync status: {e}")
        return {"error": str(e)}
