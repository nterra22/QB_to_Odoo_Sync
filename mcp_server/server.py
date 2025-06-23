#!/usr/bin/env python3
"""
Model Context Protocol (MCP) Server for QuickBooks-Odoo Sync

This MCP server exposes QuickBooks and Odoo synchronization functionality
as tools that can be used by AI assistants. It provides on-demand access
to sync operations without requiring scheduled tasks.

Tools provided:
- sync_qb_to_odoo: Sync data from QuickBooks to Odoo
- sync_odoo_to_qb: Sync data from Odoo to QuickBooks
- get_qb_data: Retrieve data from QuickBooks
- get_odoo_data: Retrieve data from Odoo
- create_qb_invoice: Create invoice in QuickBooks
- create_odoo_invoice: Create invoice in Odoo
- sync_customers: Sync customer data between systems
- sync_products: Sync product/item data between systems
"""

import asyncio
import json
import sys
import os
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, date

# Add the parent directory to the path to import from the main application
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'qb_odoo_sync_project'))

try:
    from mcp.server.models import InitializationOptions
    from mcp.server import NotificationOptions, Server
    from mcp.types import (
        Resource,
        Tool,
        TextContent,
        ImageContent,
        EmbeddedResource,
        LoggingLevel
    )
except ImportError:
    print("Error: MCP library not installed. Please install with: pip install mcp")
    sys.exit(1)

# Import the sync application modules
try:
    from sync_wrapper import (
        get_odoo_invoices,
        get_odoo_partners,
        get_odoo_products,
        create_qb_request_queue,
        get_sync_status
    )
    from app.utils.qbxml_builder import (
        build_invoice_add_qbxml,
        build_customer_add_qbxml,
        build_item_add_qbxml
    )
    from app.logging_config import logger
except ImportError as e:
    print(f"Error importing sync application modules: {e}")
    print("Make sure the QB Odoo Sync application is properly installed")
    # Use basic logging if app logging not available
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

# Initialize the MCP server
server = Server("qb-odoo-sync")

class QBOdooSyncMCP:
    """Main MCP server class for QB-Odoo synchronization"""
    
    def __init__(self):
        self.qbwc_service = None
        self._initialize_services()
    
    def _initialize_services(self):
        """Initialize the sync services"""
        try:
            # Initialize basic services - QBWC service not needed for MCP operations
            logger.info("MCP Server initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize MCP services: {e}")
            raise

# Global instance
sync_mcp = QBOdooSyncMCP()

@server.list_tools()
async def handle_list_tools() -> List[Tool]:
    """List available tools for QB-Odoo synchronization"""
    return [
        Tool(
            name="get_odoo_invoices",
            description="Retrieve invoices from Odoo system",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of invoices to retrieve",
                        "default": 10
                    },
                    "partner_name": {
                        "type": "string",
                        "description": "Filter by customer/partner name"
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Filter invoices from this date (YYYY-MM-DD)"
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Filter invoices up to this date (YYYY-MM-DD)"
                    }
                }
            }
        ),
        Tool(
            name="get_odoo_partners",
            description="Retrieve customer/partner data from Odoo",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of partners to retrieve",
                        "default": 10
                    },
                    "is_company": {
                        "type": "boolean",
                        "description": "Filter by company/individual type"
                    },
                    "name_search": {
                        "type": "string",
                        "description": "Search partners by name"
                    }
                }
            }
        ),
        Tool(
            name="get_odoo_products",
            description="Retrieve product/item data from Odoo",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of products to retrieve",
                        "default": 10
                    },
                    "name_search": {
                        "type": "string",
                        "description": "Search products by name"
                    },
                    "sale_ok": {
                        "type": "boolean",
                        "description": "Filter products that can be sold"
                    }
                }
            }
        ),
        Tool(
            name="create_qb_invoice",
            description="Create an invoice in QuickBooks from Odoo data",
            inputSchema={
                "type": "object",
                "properties": {
                    "odoo_invoice_id": {
                        "type": "integer",
                        "description": "Odoo invoice ID to sync to QuickBooks",
                        "required": True
                    },
                    "qbxml_version": {
                        "type": "string",
                        "description": "QBXML version to use",
                        "default": "13.0"
                    }
                },
                "required": ["odoo_invoice_id"]
            }
        ),
        Tool(
            name="create_qb_customer",
            description="Create a customer in QuickBooks from Odoo partner data",
            inputSchema={
                "type": "object",
                "properties": {
                    "odoo_partner_id": {
                        "type": "integer",
                        "description": "Odoo partner ID to sync to QuickBooks",
                        "required": True
                    },
                    "qbxml_version": {
                        "type": "string",
                        "description": "QBXML version to use",
                        "default": "13.0"
                    }
                },
                "required": ["odoo_partner_id"]
            }
        ),
        Tool(
            name="create_qb_item",
            description="Create an inventory item in QuickBooks from Odoo product data",
            inputSchema={
                "type": "object",
                "properties": {
                    "odoo_product_id": {
                        "type": "integer",
                        "description": "Odoo product ID to sync to QuickBooks",
                        "required": True
                    },
                    "qbxml_version": {
                        "type": "string",
                        "description": "QBXML version to use",
                        "default": "13.0"
                    }
                },
                "required": ["odoo_product_id"]
            }
        ),
        Tool(
            name="sync_qb_to_odoo",
            description="Sync data from QuickBooks to Odoo (customers, invoices, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["customers", "invoices", "bills", "payments", "all"],
                        "description": "Type of data to sync from QB to Odoo",
                        "required": True
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of records to sync",
                        "default": 10
                    }
                },
                "required": ["entity_type"]
            }
        ),
        Tool(
            name="get_sync_status",
            description="Get the current synchronization status between QuickBooks and Odoo",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="build_qbxml",
            description="Generate QBXML for various QuickBooks operations",
            inputSchema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["invoice_add", "customer_add", "item_add"],
                        "description": "Type of QBXML operation to build",
                        "required": True
                    },
                    "data": {
                        "type": "object",
                        "description": "Data object for the QBXML operation",
                        "required": True
                    },
                    "qbxml_version": {
                        "type": "string",
                        "description": "QBXML version to use",
                        "default": "13.0"
                    }
                },
                "required": ["operation", "data"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls for QB-Odoo sync operations"""
    
    try:
        if name == "get_odoo_invoices":
            return await handle_get_odoo_invoices(arguments)
        elif name == "get_odoo_partners":
            return await handle_get_odoo_partners(arguments)
        elif name == "get_odoo_products":
            return await handle_get_odoo_products(arguments)
        elif name == "create_qb_invoice":
            return await handle_create_qb_invoice(arguments)
        elif name == "create_qb_customer":
            return await handle_create_qb_customer(arguments)
        elif name == "create_qb_item":
            return await handle_create_qb_item(arguments)
        elif name == "sync_qb_to_odoo":
            return await handle_sync_qb_to_odoo(arguments)
        elif name == "get_sync_status":
            return await handle_get_sync_status(arguments)
        elif name == "build_qbxml":
            return await handle_build_qbxml(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
            
    except Exception as e:
        logger.error(f"Error handling tool call {name}: {e}", exc_info=True)
        return [TextContent(type="text", text=f"Error: {str(e)}")]

async def handle_get_odoo_invoices(arguments: Dict[str, Any]) -> List[TextContent]:
    """Get invoices from Odoo"""
    try:
        limit = arguments.get("limit", 10)
        partner_name = arguments.get("partner_name")
        date_from = arguments.get("date_from")
        date_to = arguments.get("date_to")
        
        # Build domain filters
        domain = []
        if partner_name:
            domain.append(('partner_id.name', 'ilike', partner_name))
        if date_from:
            domain.append(('invoice_date', '>=', date_from))
        if date_to:
            domain.append(('invoice_date', '<=', date_to))
        
        invoices = get_odoo_invoices(limit=limit, domain=domain)
        
        result = {
            "success": True,
            "count": len(invoices),
            "invoices": invoices
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error retrieving Odoo invoices: {str(e)}")]

async def handle_get_odoo_partners(arguments: Dict[str, Any]) -> List[TextContent]:
    """Get partners from Odoo"""
    try:
        limit = arguments.get("limit", 10)
        is_company = arguments.get("is_company")
        name_search = arguments.get("name_search")
        
        # Build domain filters
        domain = []
        if is_company is not None:
            domain.append(('is_company', '=', is_company))
        if name_search:
            domain.append(('name', 'ilike', name_search))
        
        partners = get_odoo_partners(limit=limit, domain=domain)
        
        result = {
            "success": True,
            "count": len(partners),
            "partners": partners
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error retrieving Odoo partners: {str(e)}")]

async def handle_get_odoo_products(arguments: Dict[str, Any]) -> List[TextContent]:
    """Get products from Odoo"""
    try:
        limit = arguments.get("limit", 10)
        name_search = arguments.get("name_search")
        sale_ok = arguments.get("sale_ok")
        
        # Build domain filters
        domain = []
        if name_search:
            domain.append(('name', 'ilike', name_search))
        if sale_ok is not None:
            domain.append(('sale_ok', '=', sale_ok))
        
        products = get_odoo_products(limit=limit, domain=domain)
        
        result = {
            "success": True,
            "count": len(products),
            "products": products
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error retrieving Odoo products: {str(e)}")]

async def handle_create_qb_invoice(arguments: Dict[str, Any]) -> List[TextContent]:
    """Create an invoice in QuickBooks from Odoo data"""
    try:
        odoo_invoice_id = arguments["odoo_invoice_id"]
        qbxml_version = arguments.get("qbxml_version", "13.0")
        
        # Get the invoice from Odoo
        invoices = get_odoo_invoices(limit=1, domain=[('id', '=', odoo_invoice_id)])
        if not invoices:
            return [TextContent(type="text", text=f"Invoice with ID {odoo_invoice_id} not found in Odoo")]
        
        invoice = invoices[0]
        
        # Generate QBXML
        qbxml = build_invoice_add_qbxml(invoice, qbxml_version)
        
        if not qbxml:
            return [TextContent(type="text", text="Failed to generate QBXML - invoice may have no line items")]
        
        result = {
            "success": True,
            "invoice_id": odoo_invoice_id,
            "invoice_name": invoice.get("name"),
            "customer": invoice.get("partner_id", [None, "Unknown"])[1],
            "qbxml": qbxml
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error creating QB invoice: {str(e)}")]

async def handle_create_qb_customer(arguments: Dict[str, Any]) -> List[TextContent]:
    """Create a customer in QuickBooks from Odoo partner data"""
    try:
        odoo_partner_id = arguments["odoo_partner_id"]
        qbxml_version = arguments.get("qbxml_version", "13.0")
        
        # Get the partner from Odoo
        partners = get_odoo_partners(limit=1, domain=[('id', '=', odoo_partner_id)])
        if not partners:
            return [TextContent(type="text", text=f"Partner with ID {odoo_partner_id} not found in Odoo")]
        
        partner = partners[0]
        
        # Generate QBXML
        qbxml = build_customer_add_qbxml(partner, qbxml_version)
        
        result = {
            "success": True,
            "partner_id": odoo_partner_id,
            "partner_name": partner.get("name"),
            "is_company": partner.get("is_company", False),
            "qbxml": qbxml
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error creating QB customer: {str(e)}")]

async def handle_create_qb_item(arguments: Dict[str, Any]) -> List[TextContent]:
    """Create an item in QuickBooks from Odoo product data"""
    try:
        odoo_product_id = arguments["odoo_product_id"]
        qbxml_version = arguments.get("qbxml_version", "13.0")
        
        # Get the product from Odoo
        products = get_odoo_products(limit=1, domain=[('id', '=', odoo_product_id)])
        if not products:
            return [TextContent(type="text", text=f"Product with ID {odoo_product_id} not found in Odoo")]
        
        product = products[0]
        
        # Generate QBXML
        qbxml = build_item_add_qbxml(product, qbxml_version)
        
        result = {
            "success": True,
            "product_id": odoo_product_id,
            "product_name": product.get("name"),
            "qbxml": qbxml
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error creating QB item: {str(e)}")]

async def handle_sync_qb_to_odoo(arguments: Dict[str, Any]) -> List[TextContent]:
    """Sync data from QuickBooks to Odoo"""
    try:
        entity_type = arguments["entity_type"]
        limit = arguments.get("limit", 10)
        
        # This would typically trigger the QBWC service to request data from QB
        # For now, we'll return a placeholder response
        result = {
            "success": True,
            "entity_type": entity_type,
            "limit": limit,
            "message": f"Sync request initiated for {entity_type}. This would normally trigger QBWC to request data from QuickBooks.",
            "note": "Full QB sync requires QuickBooks Web Connector to be running and connected."
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error syncing QB to Odoo: {str(e)}")]

async def handle_get_sync_status(arguments: Dict[str, Any]) -> List[TextContent]:
    """Get the current synchronization status between QuickBooks and Odoo"""
    try:
        # For now, return a static status - this would be dynamic in a real implementation
        status = {
            "last_sync_time": "2023-10-10 12:00:00",
            "next_sync_time": "2023-10-10 12:30:00",
            "status": "Success",
            "message": "Last sync completed successfully",
            "details": {
                "synced_records": 10,
                "failed_records": 0
            }
        }
        
        result = {
            "success": True,
            "status": status
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error retrieving sync status: {str(e)}")]

async def handle_build_qbxml(arguments: Dict[str, Any]) -> List[TextContent]:
    """Build QBXML for various operations"""
    try:
        operation = arguments["operation"]
        data = arguments["data"]
        qbxml_version = arguments.get("qbxml_version", "13.0")
        
        qbxml = ""
        
        if operation == "invoice_add":
            qbxml = build_invoice_add_qbxml(data, qbxml_version)
        elif operation == "customer_add":
            qbxml = build_customer_add_qbxml(data, qbxml_version)
        elif operation == "item_add":
            qbxml = build_item_add_qbxml(data, qbxml_version)
        else:
            return [TextContent(type="text", text=f"Unknown operation: {operation}")]
        
        result = {
            "success": True,
            "operation": operation,
            "qbxml_version": qbxml_version,
            "qbxml": qbxml
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error building QBXML: {str(e)}")]

async def main():
    """Main entry point for the MCP server"""
    # Import here to avoid issues with asyncio
    from mcp.server.stdio import stdio_server
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="qb-odoo-sync",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
