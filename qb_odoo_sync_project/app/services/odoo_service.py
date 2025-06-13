"""
Odoo service module for QB Odoo Sync application.

Handles all interactions with the Odoo ERP system including:
- Partner (customer/vendor) management
- Product management  
- Chart of accounts management
- Journal entry creation
"""
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List
from ..logging_config import logger
from ..utils.data_loader import get_account_map

# Hardcoded Odoo credentials
ODOO_URL = "https://nterra-sounddecision-odoo.odoo.com"
ODOO_API_KEY = "c5f9aa88c5f89b4b8c61d36dda5f7ba106e3b703"
ODOO_REQUEST_TIMEOUT = 30  # Hardcoded request timeout (in seconds)

def _odoo_rpc_call(model: str, method: str, args: List = None, domain: List = None, 
                   fields: List[str] = None, limit: int = None, **kwargs) -> Optional[Any]:
    """
    Make a standardized RPC call to Odoo.
    
    Args:
        model: Odoo model name (e.g., 'res.partner')
        method: Method to call (e.g., 'search_read', 'create')
        args: Arguments for the method
        domain: Search domain for search_read operations
        fields: Fields to return for search_read operations
        limit: Limit number of records returned
        **kwargs: Additional parameters
        
    Returns:
        Result from Odoo API or None on error
    """
    url = f"{ODOO_URL}/jsonrpc"
    
    # Build payload based on method type
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": model,
            "method": method,
            "args": args or []
        },
        "id": int(datetime.now().timestamp())
    }
    
    # Add search_read specific parameters
    if method == "search_read":
        if domain:
            payload["params"]["args"] = [domain]
        if fields:
            payload["params"]["fields"] = fields
        if limit:
            payload["params"]["limit"] = limit
    
    # Set up authentication headers
    headers = {"Content-Type": "application/json"}
    if ODOO_API_KEY:
        if ODOO_API_KEY.startswith("Bearer "):
            headers["Authorization"] = ODOO_API_KEY
        else:
            headers["X-Odoo-Api-Key"] = ODOO_API_KEY

    try:
        logger.debug(f"Odoo RPC Call: {model}.{method} with args: {args}")
        response = requests.post(
            url, 
            json=payload, 
            headers=headers, 
            timeout=ODOO_REQUEST_TIMEOUT
        )
        response.raise_for_status()
        
        response_json = response.json()
        if response_json.get("error"):
            logger.error(f"Odoo API error ({model}.{method}): {response_json['error']}")
            return None
            
        logger.info(f"Successfully connected to Odoo API and called {model}.{method}.")
        return response_json.get("result")
        
    except requests.exceptions.Timeout:
        logger.error(f"Odoo API call ({model}.{method}) timed out after {ODOO_REQUEST_TIMEOUT}s")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed for Odoo API ({model}.{method}): {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in Odoo RPC call ({model}.{method}): {e}", exc_info=True)
        return None

def ensure_partner_exists(name: str) -> Optional[int]:
    """
    Ensure a partner exists in Odoo, creating if necessary.
    
    Args:
        name: Partner name
        
    Returns:
        Partner ID or None on error
    """
    if not name or not name.strip():
        logger.warning("Empty partner name provided")
        return None
        
    name = name.strip()
    
    # Search for existing partner
    partners = _odoo_rpc_call(
        "res.partner", 
        "search_read",
        domain=[("name", "=", name)],
        fields=["id"],
        limit=1
    )
    
    if partners:
        partner_id = partners[0]["id"]
        logger.info(f"Partner '{name}' found with ID: {partner_id}")
        return partner_id
    
    # Create new partner
    logger.info(f"Partner '{name}' not found. Creating...")
    partner_data = {
        "name": name,
        "is_company": False,  # Assume individual unless specified
        "supplier_rank": 1,   # Can be both customer and supplier
        "customer_rank": 1
    }
    
    new_partner_id = _odoo_rpc_call("res.partner", "create", args=[partner_data])
    if new_partner_id:
        logger.info(f"Partner '{name}' created with ID: {new_partner_id}")
    
    return new_partner_id

def ensure_product_exists(model_code: str, description: str) -> Optional[int]:
    """
    Ensure a product exists in Odoo, creating if necessary.
    
    Args:
        model_code: Product internal reference/SKU
        description: Product description/name
        
    Returns:
        Product ID or None on error
    """
    if not model_code or not model_code.strip():
        logger.warning("Empty product model code provided")
        return None
        
    model_code = model_code.strip()
    description = description.strip() if description else model_code
    
    # Search for existing product
    products = _odoo_rpc_call(
        "product.product",
        "search_read", 
        domain=[("default_code", "=", model_code)],
        fields=["id"],
        limit=1
    )

    if products:
        product_id = products[0]["id"]
        logger.info(f"Product '{model_code}' found with ID: {product_id}")
        return product_id
    
    # Create new product
    logger.info(f"Product '{model_code}' not found. Creating...")
    product_data = {
        "name": description,
        "default_code": model_code,
        "type": "service",  # Assuming service type for QB sync
        "purchase_ok": True,
        "sale_ok": True
    }
    
    new_product_id = _odoo_rpc_call("product.product", "create", args=[product_data])
    if new_product_id:
        logger.info(f"Product '{model_code}' created with ID: {new_product_id}")
    
    return new_product_id

def ensure_account_exists(qb_account_full_name: str) -> Optional[int]:
    """
    Ensure an account exists in Odoo based on QB account crosswalk.
    
    Args:
        qb_account_full_name: Full QuickBooks account name
        
    Returns:
        Account ID or None on error
    """
    if not qb_account_full_name:
        logger.warning("Empty QB account name provided")
        return None
        
    # Get mapping from crosswalk
    odoo_account_map = get_account_map(qb_account_full_name)
    if not odoo_account_map:
        logger.warning(f"QuickBooks account '{qb_account_full_name}' not found in crosswalk")
        return None

    odoo_account_code = odoo_account_map.get("code")
    odoo_account_name = odoo_account_map.get("name")
    odoo_account_type_str = odoo_account_map.get("type")

    if not odoo_account_code:
        logger.warning(f"Odoo account code missing for QB account '{qb_account_full_name}' in crosswalk")
        return None

    # Search for existing account
    accounts = _odoo_rpc_call(
        "account.account",
        "search_read",
        domain=[("code", "=", odoo_account_code)],
        fields=["id", "name"],
        limit=1
    )

    if accounts:
        account_id = accounts[0]["id"]
        logger.info(f"Odoo Account '{odoo_account_code} - {accounts[0]['name']}' found with ID: {account_id}")
        return account_id
    
    # Account not found, attempt to create
    logger.info(f"Odoo Account with code '{odoo_account_code}' not found. Attempting to create")
    
    # Find account type
    if not odoo_account_type_str:
        logger.error(f"Account type not specified for QB account '{qb_account_full_name}'")
        return None
        
    account_types = _odoo_rpc_call(
        "account.account.type",
        "search_read",
        domain=[("name", "ilike", odoo_account_type_str)],
        fields=["id", "name"],
        limit=1
    )

    if not account_types:
        logger.error(f"Odoo account type '{odoo_account_type_str}' not found. Cannot create account")
        return None

    user_type_id = account_types[0]["id"]
    logger.info(f"Found account type '{account_types[0]['name']}' with ID {user_type_id}")

    # Create account
    account_data = {
        "code": odoo_account_code,
        "name": odoo_account_name or qb_account_full_name,
        "user_type_id": user_type_id,
        "reconcile": odoo_account_map.get("reconcile", False)
    }
    
    new_account_id = _odoo_rpc_call("account.account", "create", args=[account_data])
    if new_account_id:
        logger.info(f"Odoo Account '{odoo_account_code}' created with ID: {new_account_id}")
    
    return new_account_id

def ensure_journal_exists(journal_name: str) -> Optional[int]:
    """
    Find an Odoo journal by name.
    
    Args:
        journal_name: Journal name to search for
        
    Returns:
        Journal ID or None if not found
    """
    if not journal_name:
        logger.warning("Empty journal name provided")
        return None
        
    journals = _odoo_rpc_call(
        "account.journal",
        "search_read",
        domain=[("name", "=", journal_name), ("type", "in", ["general", "sale", "purchase"])],
        fields=["id", "name"],
        limit=1
    )
    
    if journals:
        journal_id = journals[0]["id"]
        logger.info(f"Odoo Journal '{journal_name}' found with ID: {journal_id}")
        return journal_id
    
    logger.warning(f"Odoo Journal '{journal_name}' not found")
    return None

def create_odoo_journal_entry(entry_data: Dict[str, Any]) -> Optional[int]:
    """
    Create a journal entry in Odoo.
    
    Args:
        entry_data: Dictionary containing journal entry data with keys:
            - ref: Reference/description
            - date: Entry date
            - journal_id: Odoo journal ID
            - line_ids: List of line dictionaries
            
    Returns:
        Created move ID or None on error
    """
    logger.info(f"Creating Odoo journal entry: {entry_data.get('ref', 'No reference')}")
    
    # Validate required fields
    if not entry_data.get("journal_id"):
        logger.error("Journal ID is required for journal entry creation")
        return None
        
    if not entry_data.get("line_ids"):
        logger.error("Line IDs are required for journal entry creation")
        return None
    
    # Build move data
    move_vals = {
        "journal_id": entry_data["journal_id"],
        "date": entry_data.get("date", datetime.now().strftime("%Y-%m-%d")),
        "ref": entry_data.get("ref", "QB Sync Entry"),
        "line_ids": []
    }
    
    # Process line data
    for line_data in entry_data["line_ids"]:
        if not line_data.get("account_id"):
            logger.warning(f"Skipping line without account_id: {line_data}")
            continue
            
        line_vals = (0, 0, {
            "account_id": line_data["account_id"],
            "name": line_data.get("name", "QB Sync Line"),
            "debit": line_data.get("debit", 0.0),
            "credit": line_data.get("credit", 0.0),
        })
        
        # Add optional fields
        if line_data.get("partner_id"):
            line_vals[2]["partner_id"] = line_data["partner_id"]
        if line_data.get("product_id"):
            line_vals[2]["product_id"] = line_data["product_id"]
            
        move_vals["line_ids"].append(line_vals)
    
    # Validate balanced entry
    total_debit = sum(line[2]["debit"] for line in move_vals["line_ids"])
    total_credit = sum(line[2]["credit"] for line in move_vals["line_ids"])
    
    if abs(total_debit - total_credit) > 0.01:  # Allow for small rounding differences
        logger.error(f"Journal entry is not balanced: Debit={total_debit}, Credit={total_credit}")
        return None
    
    # Create the journal entry
    new_move_id = _odoo_rpc_call("account.move", "create", args=[move_vals])
    
    if new_move_id:
        logger.info(f"Successfully created Odoo journal entry with ID: {new_move_id}")
        
        # Optionally post the journal entry
        # Uncomment the following lines if you want to auto-post entries
        # post_result = _odoo_rpc_call("account.move", "action_post", args=[[new_move_id]])
        # if post_result:
        #     logger.info(f"Journal entry {new_move_id} posted successfully")
    
    return new_move_id
