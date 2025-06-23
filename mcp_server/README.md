# QuickBooks-Odoo Sync MCP Server

This Model Context Protocol (MCP) server exposes the QuickBooks-Odoo synchronization functionality as tools that can be used by AI assistants. It allows AI to perform on-demand sync operations without requiring scheduled tasks.

## Features

The MCP server provides the following tools:

### Data Retrieval Tools
- `get_odoo_invoices` - Retrieve invoices from Odoo with filtering options
- `get_odoo_partners` - Retrieve customer/partner data from Odoo
- `get_odoo_products` - Retrieve product/item data from Odoo

### QuickBooks Creation Tools
- `create_qb_invoice` - Generate QBXML to create invoices in QuickBooks
- `create_qb_customer` - Generate QBXML to create customers in QuickBooks
- `create_qb_item` - Generate QBXML to create inventory items in QuickBooks

### Sync Tools
- `sync_qb_to_odoo` - Initiate sync from QuickBooks to Odoo
- `build_qbxml` - Generate custom QBXML for various operations

## Installation

1. **Install MCP library**:
   ```bash
   pip install mcp
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the MCP client** (e.g., Claude Desktop):
   Add the following to your MCP configuration file:
   ```json
   {
     "mcpServers": {
       "qb-odoo-sync": {
         "command": "python",
         "args": ["c:\\SD Code Files\\QB Odoo Sync\\QB_to_Odoo_Sync\\mcp_server\\server.py"],
         "env": {
           "PYTHONPATH": "c:\\SD Code Files\\QB Odoo Sync\\QB_to_Odoo_Sync\\qb_odoo_sync_project"
         }
       }
     }
   }
   ```

## Usage Examples

### Get Recent Invoices from Odoo
```json
{
  "tool": "get_odoo_invoices",
  "arguments": {
    "limit": 5,
    "date_from": "2024-01-01"
  }
}
```

### Create a QuickBooks Invoice from Odoo Data
```json
{
  "tool": "create_qb_invoice",
  "arguments": {
    "odoo_invoice_id": 123,
    "qbxml_version": "13.0"
  }
}
```

### Search for Customers
```json
{
  "tool": "get_odoo_partners",
  "arguments": {
    "name_search": "Acme Corp",
    "is_company": true,
    "limit": 10
  }
}
```

### Generate Custom QBXML
```json
{
  "tool": "build_qbxml",
  "arguments": {
    "operation": "customer_add",
    "data": {
      "name": "New Customer",
      "is_company": true,
      "street": "123 Main St",
      "city": "Anytown",
      "zip": "12345"
    }
  }
}
```

## Architecture

The MCP server acts as a bridge between AI assistants and your QB-Odoo sync application:

```
AI Assistant ←→ MCP Server ←→ QB-Odoo Sync App ←→ QuickBooks/Odoo
```

### Key Components

1. **server.py** - Main MCP server implementation
2. **sync_wrapper.py** - Wrapper functions for sync operations
3. **requirements.txt** - Python dependencies
4. **mcp_config.json** - Example MCP client configuration

### How It Works

1. AI assistant calls MCP tools through the protocol
2. MCP server validates parameters and calls sync application functions
3. Sync application interacts with Odoo via XML-RPC and generates QBXML for QuickBooks
4. Results are returned to the AI assistant as JSON

## Limitations

1. **QuickBooks Integration**: The MCP server can generate QBXML but still requires QuickBooks Web Connector to be running to actually execute requests in QuickBooks.

2. **Real-time Sync**: Some operations (like `sync_qb_to_odoo`) initiate requests but may require the scheduled sync process to complete the operation.

3. **Authentication**: Uses the same Odoo credentials as the main application. Ensure these are properly configured.

## Security Considerations

- The MCP server has access to both QuickBooks and Odoo data
- Ensure proper authentication and authorization when exposing this to AI assistants
- Consider running in a controlled environment with appropriate network restrictions
- Log all operations for audit purposes

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure the main QB-Odoo sync application is properly installed and the PYTHONPATH is set correctly.

2. **Odoo Connection**: Verify Odoo URL, database name, and API key in the configuration.

3. **QBXML Generation**: Check that required data fields are present in Odoo records.

### Debugging

Enable detailed logging by setting the log level:
```python
import logging
logging.getLogger().setLevel(logging.DEBUG)
```

## Development

To extend the MCP server with additional tools:

1. Add new tool definitions in `handle_list_tools()`
2. Implement tool handlers in `handle_call_tool()`
3. Add corresponding wrapper functions in `sync_wrapper.py`
4. Update this README with usage examples

## License

This MCP server follows the same license as the main QB-Odoo sync application.
