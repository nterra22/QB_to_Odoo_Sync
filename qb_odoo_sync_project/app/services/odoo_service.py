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
from ..utils.data_loader import get_account_map, get_field_mapping # Added get_field_mapping

# Hardcoded Odoo credentials
ODOO_URL = "https://nterra22-sounddecision-odoo-develop-20178686.dev.odoo.com"
ODOO_API_KEY = "e8188dcec4b36dbc1e89e4da17b989c7aae8e568"
ODOO_REQUEST_TIMEOUT = 30  # Hardcoded request timeout (in seconds)

def _odoo_rpc_call(model: str, method: str, args: List = None, domain: List = None, 
                   fields: List[str] = None, limit: int = None, **kwargs_rpc) -> Optional[Any]: # Renamed kwargs to avoid conflict
    """
    Make a standardized RPC call to Odoo.
    
    Args:
        model: Odoo model name (e.g., 'res.partner')
        method: Method to call (e.g., 'search_read', 'create')
        args: Arguments for the method
        domain: Search domain for search_read operations
        fields: Fields to return for search_read operations
        limit: Limit number of records returned
        **kwargs_rpc: Additional parameters for Odoo (e.g. context for RPC call itself)
        
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
            "args": args or [],
            "kwargs": kwargs_rpc # Pass through additional kwargs to Odoo
        },
        "id": int(datetime.now().timestamp())
    }
    
    # Add search_read specific parameters to "params" not "params.kwargs"
    if method == "search_read":
        # search_read uses a specific structure for its arguments
        # The first element of 'args' is the domain (if any)
        # Then kwargs like 'fields', 'limit', 'context' can be in the 'kwargs' part of the payload.params
        payload["params"]["args"] = [domain or []] # Domain is the first positional arg
        if fields:
            payload["params"]["kwargs"]['fields'] = fields
        if limit:
            payload["params"]["kwargs"]['limit'] = limit
    elif method == "create" or method == "write":
        # For create/write, args is typically a list of dictionaries (for create) or [ids, vals] (for write)
        # kwargs_rpc can contain 'context'
        pass # args are already in payload["params"]["args"]

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

def ensure_partner_exists(name: str, **kwargs) -> Optional[int]:
    """
    Ensure a partner exists in Odoo, creating if necessary.
    
    Args:
        name: Partner name
        **kwargs: Can include is_supplier (bool) and is_customer (bool)
        
    Returns:
        Partner ID or None on error
    """
    if not name or not name.strip():
        logger.warning("Empty partner name provided")
        return None
        
    name = name.strip()
    is_supplier = kwargs.get('is_supplier', False) # Check for supplier hint
    is_customer = kwargs.get('is_customer', True) # Default to customer

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
        "is_company": False,  # Assume individual unless specified, QB often doesn't distinguish well for this sync
        # "supplier_rank": 1 if is_supplier else 0, # Set rank based on hint
        # "customer_rank": 1 if is_customer else 0  # Set rank based on hint
    }
    # More sophisticated logic might be needed if a partner can be both
    # For now, if is_supplier is true, we prioritize that.
    # Odoo's ranks: 0 = not, >0 = is.
    if is_supplier:
        partner_data["supplier_rank"] = 1
    if is_customer: # Can be both
        partner_data["customer_rank"] = 1
    if not is_supplier and not is_customer: # Should not happen with current logic but as a fallback
        partner_data["customer_rank"] = 1 # Default to customer


    new_partner_id = _odoo_rpc_call("res.partner", "create", args=[partner_data])
    if new_partner_id:
        logger.info(f"Partner '{name}' created with ID: {new_partner_id}")
    
    return new_partner_id

def ensure_product_exists(model_code: str, description: str, 
                          sales_price: Optional[float] = None, 
                          purchase_cost: Optional[float] = None,
                          odoo_product_type: Optional[str] = None) -> Optional[int]:
    """
    Ensure a product exists in Odoo, creating or updating if necessary.
    Sales price and purchase cost from QB are considered source of truth.
    
    Args:
        model_code: Product internal reference/SKU (from QB Item Name/FullName)
        description: Product description/name
        sales_price: Optional sales price from QB
        purchase_cost: Optional purchase cost from QB
        odoo_product_type: Optional Odoo product type ('product', 'service', 'consu')
        
    Returns:
        Product ID (product.product) or None on error
    """
    if not model_code or not model_code.strip():
        logger.warning("Empty product model code provided")
        return None
        
    model_code = model_code.strip()
    description = description.strip() if description else model_code
    
    # Search for existing product by default_code (SKU)
    # We need product.template ID for some fields, and product.product ID for transactions.
    # Odoo typically creates a product.product for each product.template automatically unless variants are used.
    # For simplicity, we'll manage product.product and let Odoo handle the template.
    # Fields like list_price and standard_price can often be on product.template.
    
    products = _odoo_rpc_call(
        "product.product",
        "search_read", 
        domain=[("default_code", "=", model_code)],
        # Fetch fields from product.product and its related product.template
        fields=["id", "product_tmpl_id", "lst_price", "standard_price", "type"], 
        limit=1
    )

    product_id_to_update = None
    template_id_to_update = None
    update_values_product = {}
    update_values_template = {}

    if products:
        product_record = products[0]
        product_id = product_record["id"]
        template_id = product_record["product_tmpl_id"][0] if product_record.get("product_tmpl_id") else None # product_tmpl_id is a list [id, name]
        
        logger.info(f"Product '{model_code}' found with ID: {product_id} (Template ID: {template_id})")
        product_id_to_update = product_id
        template_id_to_update = template_id # We'll update the template for prices/type

        # Check and update sales price (lst_price on product.template)
        if sales_price is not None:
            # Need to read template's current lst_price if not directly on product.product
            current_template_data = _odoo_rpc_call("product.template", "read", args=[template_id_to_update], kwargs_rpc={"fields": ["lst_price", "type"]})
            current_sales_price = current_template_data[0]['lst_price'] if current_template_data and current_template_data[0] else None
            if sales_price != current_sales_price:
                logger.info(f"Updating Odoo product '{model_code}' (Template ID: {template_id_to_update}) sales price from {current_sales_price} to {sales_price}")
                update_values_template["lst_price"] = sales_price
        
        # Check and update purchase cost (standard_price on product.template or product.product)
        # standard_price is often on product.template but can be on product.product for variants.
        # For non-variant setups, it's usually on the template.
        if purchase_cost is not None:
            current_cost_price = product_record.get('standard_price') # product.product might have it
            if template_id_to_update and current_cost_price is None: # Fallback to template if not on product
                 current_template_data_cost = _odoo_rpc_call("product.template", "read", args=[template_id_to_update], kwargs_rpc={"fields": ["standard_price"]})
                 current_cost_price = current_template_data_cost[0]['standard_price'] if current_template_data_cost and current_template_data_cost[0] else None

            if purchase_cost != current_cost_price:
                logger.info(f"Updating Odoo product '{model_code}' (Template ID: {template_id_to_update}) cost price from {current_cost_price} to {purchase_cost}")
                # standard_price is critical, usually set on template for non-variant products
                update_values_template["standard_price"] = purchase_cost
        
        # Check and update product type (on product.template)
        if odoo_product_type:
            current_template_data_type = _odoo_rpc_call("product.template", "read", args=[template_id_to_update], kwargs_rpc={"fields": ["type"]})
            current_type = current_template_data_type[0]['type'] if current_template_data_type and current_template_data_type[0] else None
            if odoo_product_type != current_type:
                logger.info(f"Updating Odoo product '{model_code}' (Template ID: {template_id_to_update}) type from {current_type} to {odoo_product_type}")
                update_values_template["type"] = odoo_product_type

        if update_values_template and template_id_to_update:
            _odoo_rpc_call("product.template", "write", args=[[template_id_to_update], update_values_template])
            logger.info(f"Updated product.template {template_id_to_update} for '{model_code}'.")
        # No product.product specific fields to update in this logic yet, but structure is there.

        return product_id # Return existing product.product ID
    
    # Create new product if not found
    logger.info(f"Product '{model_code}' not found. Creating...")
    
    # Data for product.template
    product_template_data = {
        "name": description,
        "default_code": model_code,
        "type": odoo_product_type if odoo_product_type else "product",  # Default to 'product' (storable)
        "purchase_ok": True,
        "sale_ok": True,
        # "invoice_policy": "order", # Common default
        # "purchase_method": "purchase", # Common default
    }
    if sales_price is not None:
        product_template_data["lst_price"] = sales_price
    if purchase_cost is not None:
        product_template_data["standard_price"] = purchase_cost

    # Create the product.template first
    new_template_id = _odoo_rpc_call("product.template", "create", args=[product_template_data])
    
    if not new_template_id:
        logger.error(f"Failed to create product.template for '{model_code}'.")
        return None
    
    logger.info(f"Product template for '{model_code}' created with ID: {new_template_id}")

    # Odoo automatically creates a product.product when a product.template is made (unless variants involved)
    # We need to find that product.product to return its ID.
    created_products = _odoo_rpc_call(
        "product.product",
        "search_read",
        domain=[("product_tmpl_id", "=", new_template_id), ("default_code", "=", model_code)],
        fields=["id"],
        limit=1
    )

    if created_products:
        new_product_id = created_products[0]["id"]
        logger.info(f"Product '{model_code}' (product.product) created with ID: {new_product_id} linked to template {new_template_id}")
        return new_product_id
    else:
        # This case should be rare if Odoo is functioning normally.
        # Could happen if there's a delay or an issue with automated product.product creation.
        logger.error(f"Failed to find the auto-created product.product for template ID {new_template_id} and code '{model_code}'. Manual check in Odoo might be needed.")
        # As a fallback, we could try creating product.product directly, but it's better to rely on Odoo's standard behavior.
        # For now, return None as the specific product.product variant wasn't confirmed.
        return None

def ensure_account_exists(qb_account_full_name: str, account_type_hint: Optional[str] = None) -> Optional[int]:
    """
    Ensure an account exists in Odoo based on QB account crosswalk.
    
    Args:
        qb_account_full_name: Full QuickBooks account name
        account_type_hint: Optional Odoo account type (e.g. 'asset_receivable', 'income', 'expense') 
                           to help if crosswalk is missing type.
                           
    Returns:
        Account ID or None on error
    """
    if not qb_account_full_name:
        logger.warning("Empty QB account name provided")
        return None
        
    # Get mapping from crosswalk
    odoo_account_map = get_account_map(qb_account_full_name)
    if not odoo_account_map:
        logger.warning(f"QuickBooks account '{qb_account_full_name}' not found in crosswalk. Account type hint: {account_type_hint}")
        # TODO: Potentially try to create based on name and hint if allowed, or require crosswalk entry
        return None

    odoo_account_code = odoo_account_map.get("code")
    odoo_account_name = odoo_account_map.get("name")
    odoo_account_type_str = odoo_account_map.get("type") or account_type_hint # Use hint if crosswalk type is missing

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
        entry_data: Dictionary containing journal entry details:
            - 'ref': Reference for the journal entry
            - 'journal_id': Odoo journal ID
            - 'date': Date of the entry
            - 'line_ids': List of line data:
                [
                    (0, 0, {'account_id': acc_id, 'partner_id': partner_id, 'name': desc, 'debit': amount, 'credit': 0}),
                    (0, 0, {'account_id': acc_id, 'partner_id': partner_id, 'name': desc, 'debit': 0, 'credit': amount})
                ]
                
    Returns:
        Journal entry ID or None on error
    """
    required_fields = ['ref', 'journal_id', 'date', 'line_ids']
    if not all(field in entry_data for field in required_fields):
        logger.error(f"Missing required fields for journal entry creation. Provided: {entry_data.keys()}")
        return None
    
    if not entry_data['line_ids']:
        logger.error("Journal entry must have at least one line.")
        return None

    # Basic validation of debit/credit balance (optional, Odoo will also check)
    total_debit = sum(line[2].get('debit', 0) for line in entry_data['line_ids'] if len(line) > 2 and isinstance(line[2], dict))
    total_credit = sum(line[2].get('credit', 0) for line in entry_data['line_ids'] if len(line) > 2 and isinstance(line[2], dict))
    if round(total_debit, 2) != round(total_credit, 2):
        logger.warning(f"Journal entry lines are not balanced. Debit: {total_debit}, Credit: {total_credit}. Odoo might reject.")

    move_data = {
        'ref': entry_data['ref'],
        'journal_id': entry_data['journal_id'],
        'date': entry_data['date'],
        'line_ids': entry_data['line_ids']
    }
    
    logger.info(f"Attempting to create Odoo journal entry: {move_data}")
    move_id = _odoo_rpc_call(
        model="account.move",
        method="create",
        args=[move_data]
    )
    
    if move_id:
        logger.info(f"Successfully created Odoo journal entry with ID: {move_id}")
        # Optionally, post the journal entry
        # _odoo_rpc_call(model="account.move", method="action_post", args=[[move_id]])
        # logger.info(f"Posted journal entry {move_id}")
    else:
        logger.error("Failed to create Odoo journal entry.")
        
    return move_id


def create_or_update_odoo_invoice(qb_invoice_data: Dict[str, Any]) -> Optional[int]:
    """
    Creates or updates an invoice in Odoo from QuickBooks data using field_mapping.json.
    """
    logger.info(f"Processing QB Invoice: Ref {qb_invoice_data.get('ref_number')}, Customer: {qb_invoice_data.get('customer_name')}, TxnID: {qb_invoice_data.get('qb_txn_id')}")
    logger.debug(f"Full QB Invoice data: {qb_invoice_data}")

    invoice_mapping = get_field_mapping("Invoices")
    if not invoice_mapping:
        logger.error("Invoice mapping not found in field_mapping.json. Cannot process invoice.")
        return None

    # Ensure customer (partner) exists
    customer_name = qb_invoice_data.get("customer_name")
    if not customer_name:
        logger.error("Customer name missing from QB invoice data.")
        return None
    
    odoo_partner_id = ensure_partner_exists(name=customer_name, is_customer=True, is_supplier=False)
    if not odoo_partner_id:
        logger.error(f"Failed to ensure Odoo partner for customer: {customer_name}.")
        return None

    # Determine Odoo journal
    # This might come from config or be a fixed value based on company setup
    # For now, let's assume a default journal name from field_mapping.json or hardcode
    default_journal_name = invoice_mapping.get("default_values", {}).get("journal_name", "Customer Invoices")
    sales_journal_id = ensure_journal_exists(default_journal_name)
    if not sales_journal_id:
        # Fallback: Try to find any sales journal if the default one is not found
        logger.warning(f"Default sales journal '{default_journal_name}' not found. Trying to find any sales journal.")
        journals = _odoo_rpc_call(
            "account.journal",
            "search_read",
            domain=[("type", "=", "sale")],
            fields=["id"],
            limit=1
        )
        if journals:
            sales_journal_id = journals[0]["id"]
            logger.info(f"Found sales journal '{journals[0]['name'] if journals[0].get('name') else 'ID: '+str(sales_journal_id)}' to use.")
        else:
            logger.error(f"Sales journal '{default_journal_name}' not found in Odoo, and no other sales journal available. Cannot create invoice.")
            return None

    # Prepare invoice lines
    invoice_lines_for_odoo = []
    for qb_line in qb_invoice_data.get("lines", []):
        product_id = None
        item_name = qb_line.get("item_name") # QBD Item Name (might be FullName)
        
        if item_name:
            # Attempt to find product by name (or default_code if mapping implies that)
            product_id = ensure_product_exists(model_code=item_name, description=qb_line.get("description", item_name))
            if not product_id:
                logger.warning(f"Could not ensure Odoo product for QB item '{item_name}'. Line description: '{qb_line.get('description')}'. Invoice line may be incomplete or use a generic product.")
                # TODO: Fallback to a generic "Sales" product or similar if configured

        # Determine account for the line. This is crucial.
        # Priority: 1. QB Line Account, 2. Item's Income Account (from QB, mapped), 3. Default Sales/Income Account
        line_account_name_qb = qb_line.get("account_name") # If QB provides account at line level (e.g. for non-item lines)
        odoo_line_account_id = None

        if line_account_name_qb:
            odoo_line_account_id = ensure_account_exists(line_account_name_qb, account_type_hint="income")
        elif product_id: # If product exists, try to get its income account from Odoo product.template
            product_template_info = _odoo_rpc_call(
                "product.product", "read", args=[product_id], kwargs_rpc={"fields": ["property_account_income_id", "product_tmpl_id"]}
            )
            if product_template_info and product_template_info[0].get("property_account_income_id"):
                odoo_line_account_id = product_template_info[0]["property_account_income_id"][0] # It's a tuple (id, name)
            elif product_template_info and product_template_info[0].get("product_tmpl_id"): # Check template
                 template_id = product_template_info[0]["product_tmpl_id"][0]
                 template_info_full = _odoo_rpc_call(
                    "product.template", "read", args=[template_id], kwargs_rpc={"fields": ["property_account_income_id"]}
                 )
                 if template_info_full and template_info_full[0].get("property_account_income_id"):
                     odoo_line_account_id = template_info_full[0]["property_account_income_id"][0]


        if not odoo_line_account_id:
            # Fallback to a default income account if no specific account found
            # This default should ideally be configurable or derived from journal
            default_income_account_name = "Sales" # Placeholder, should be from config or account_crosswalk
            logger.warning(f"Income account for line '{qb_line.get('description', item_name)}' not determined. Falling back to default '{default_income_account_name}'.")
            odoo_line_account_id = ensure_account_exists(default_income_account_name, account_type_hint="income")

        if not odoo_line_account_id:
            logger.error(f"Failed to determine or create income account for invoice line: '{qb_line.get('description', item_name)}'. Skipping line.")
            continue # Skip this line if account cannot be resolved

        line_data = {
            "product_id": product_id,
            "name": qb_line.get("description") or item_name or "N/A",
            "quantity": qb_line.get("quantity", 0.0),
            "price_unit": qb_line.get("rate", 0.0),
            "account_id": odoo_line_account_id,
            # "tax_ids": [] # Placeholder for tax mapping - complex, requires tax service
        }
        
        # TODO: Tax mapping. This is highly dependent on how taxes are set up in QB and Odoo.
        # qb_tax_code_ref = qb_line.get("tax_code_ref_full_name")
        # if qb_tax_code_ref:
        #   odoo_tax_ids = map_qb_tax_to_odoo(qb_tax_code_ref) # This function would need to be created
        #   if odoo_tax_ids:
        #       line_data["tax_ids"] = [(6, 0, odoo_tax_ids)]

        invoice_lines_for_odoo.append((0, 0, line_data))

    if not invoice_lines_for_odoo and qb_invoice_data.get("lines"): # Only warn if there were lines to process
        logger.warning(f"No lines could be processed for QB Invoice Ref {qb_invoice_data.get('ref_number')}. Invoice will not be created/updated if it has no lines.")
        # Depending on Odoo rules, an invoice with no lines might not be allowed.
        # For now, we'll let it try, Odoo will reject if invalid.

    # Prepare Odoo invoice payload using field_mapping.json
    odoo_invoice_payload = {
        "move_type": invoice_mapping.get("default_values", {}).get("move_type", "out_invoice"),
        "partner_id": odoo_partner_id,
        "journal_id": sales_journal_id,
        "invoice_line_ids": invoice_lines_for_odoo,
        # Add a custom field to store QB TxnID for future updates and preventing duplicates
        # This field needs to be created in Odoo on 'account.move' model (e.g., x_qb_txn_id)
        "x_qb_txn_id": qb_invoice_data.get("qb_txn_id") 
    }

    # Map fields from qb_invoice_data to odoo_invoice_payload based on field_mapping
    for mapping_item in invoice_mapping.get("fields", []):
        qbd_field_name = mapping_item["qbd_field"]
        odoo_field_name = mapping_item["odoo_field"]

        if qbd_field_name in qb_invoice_data:
            value = qb_invoice_data[qbd_field_name]
            # Basic transformations can be added here if needed (e.g., date formatting)
            if "date" in odoo_field_name and isinstance(value, str): # Ensure date format if necessary
                try:
                    # Assuming QB dates are YYYY-MM-DD. If not, parse and reformat.
                    datetime.strptime(value, "%Y-%m-%d") 
                except ValueError:
                    logger.warning(f"Date field {qbd_field_name} ('{value}') is not in YYYY-MM-DD format. Odoo might reject.")
            
            # Handle special cases like TermsRef_ListID mapping to invoice_payment_term_id
            if qbd_field_name == "TermsRef_ListID" and odoo_field_name == "invoice_payment_term_id":
                # This requires fetching Odoo's payment term ID based on QB's term name/ListID
                # For now, this is a placeholder. A robust solution needs a term mapping utility.
                pass  # Placeholder for term mapping

            elif odoo_field_name not in ["partner_id", "journal_id", "invoice_line_ids", "move_type", "x_qb_txn_id"]:
                odoo_invoice_payload[odoo_field_name] = value

    # Search for existing invoice in Odoo using QB TxnID
    existing_invoice_id = None
    if qb_invoice_data.get("qb_txn_id"):
        logger.info(f"Searching for existing Odoo invoice with x_qb_txn_id: {qb_invoice_data.get('qb_txn_id')}")
        existing_invoices = _odoo_rpc_call(
            model="account.move",
            method="search_read",
            domain=[("x_qb_txn_id", "=", qb_invoice_data.get("qb_txn_id")), ("move_type", "=", "out_invoice")],
            fields=["id"],
            limit=1
        )
        if existing_invoices:
            existing_invoice_id = existing_invoices[0]["id"]
            logger.info(f"Found existing Odoo invoice ID: {existing_invoice_id} for QB TxnID: {qb_invoice_data.get('qb_txn_id')}")

    if existing_invoice_id:
        update_payload = {k: v for k, v in odoo_invoice_payload.items() if k != "move_type"} # move_type cannot be changed

        # For lines, to replace all:
        if "invoice_line_ids" in update_payload:
            update_payload["invoice_line_ids"] = [(5, 0, 0)] + invoice_lines_for_odoo

        logger.info(f"Attempting to update Odoo invoice ID: {existing_invoice_id}")
        logger.debug(f"Odoo Invoice Update Payload: {update_payload}")
        success = _odoo_rpc_call(
            model="account.move",
            method="write",
            args=[[existing_invoice_id], update_payload]
        )
        if success:
            logger.info(f"Successfully updated Odoo invoice ID: {existing_invoice_id}")
            # Optionally, re-post the invoice if its state changed to 'draft'
            # current_state = _odoo_rpc_call("account.move", "read", args=[existing_invoice_id], kwargs_rpc={"fields": ["state"]})
            # if current_state and current_state[0]['state'] == 'draft':
            #    _odoo_rpc_call(model="account.move", method="action_post", args=[[existing_invoice_id]])
            #    logger.info(f"Posted updated invoice {existing_invoice_id}")
            return existing_invoice_id
        else:
            logger.error(f"Failed to update Odoo invoice ID: {existing_invoice_id}")
            return None
    else:
        # Create new invoice
        logger.info("Attempting to create new Odoo invoice.")
        logger.debug(f"Odoo Invoice Create Payload: {odoo_invoice_payload}")

        # Check if there are any lines, as Odoo might require lines for an invoice
        if not invoice_lines_for_odoo and qb_invoice_data.get("lines"): # If QB had lines but we processed none
            logger.error(f"No processable lines for new QB Invoice Ref {qb_invoice_data.get('ref_number')}. Creation aborted.")
            return None
        if not odoo_invoice_payload.get("invoice_line_ids"): # If payload has no lines at all
            logger.warning(f"Creating invoice {qb_invoice_data.get('ref_number')} with no lines. Odoo may reject this.")

        new_invoice_id = _odoo_rpc_call(
            model="account.move",
            method="create",
            args=[odoo_invoice_payload]
        )
        if new_invoice_id:
            logger.info(f"Successfully created Odoo invoice with ID: {new_invoice_id} for QB TxnID: {qb_invoice_data.get('qb_txn_id')}")
            # Post the newly created invoice
            _odoo_rpc_call(model="account.move", method="action_post", args=[[new_invoice_id]])
            logger.info(f"Posted newly created invoice {new_invoice_id}")
            return new_invoice_id
        else:
            logger.error(f"Failed to create Odoo invoice for QB Ref: {qb_invoice_data.get('ref_number')}")
            return None


def create_or_update_odoo_bill(qb_bill_data: Dict[str, Any]) -> Optional[int]:
    """
    Creates or updates a vendor bill in Odoo from QuickBooks data using field_mapping.json.
    """
    logger.info(f"Processing QB Bill: Ref {qb_bill_data.get('ref_number')}, Vendor: {qb_bill_data.get('vendor_name')}, TxnID: {qb_bill_data.get('qb_txn_id')}")
    logger.debug(f"Full QB Bill data: {qb_bill_data}")

    bill_mapping = get_field_mapping("Bills")
    if not bill_mapping:
        logger.error("Bill mapping not found in field_mapping.json. Cannot process bill.")
        return None

    # Ensure vendor (partner) exists
    vendor_name = qb_bill_data.get("vendor_name")
    if not vendor_name:
        logger.error("Vendor name missing from QB bill data.")
        return None
    
    odoo_partner_id = ensure_partner_exists(name=vendor_name, is_supplier=True, is_customer=False)
    if not odoo_partner_id:
        logger.error(f"Failed to ensure Odoo partner for vendor: {vendor_name}.")
        return None

    # Determine Odoo journal for vendor bills
    default_journal_name = bill_mapping.get("default_values", {}).get("journal_name", "Vendor Bills")
    purchase_journal_id = ensure_journal_exists(default_journal_name)
    if not purchase_journal_id:
        logger.warning(f"Default purchase journal '{default_journal_name}' not found. Trying to find any purchase journal.")
        journals = _odoo_rpc_call(
            "account.journal",
            "search_read",
            domain=[("type", "=", "purchase")],
            fields=["id", "name"],
            limit=1
        )
        if journals:
            purchase_journal_id = journals[0]["id"]
            logger.info(f"Found purchase journal '{journals[0].get('name', 'ID: '+str(purchase_journal_id))}' to use.")
        else:
            logger.error(f"Purchase journal '{default_journal_name}' not found in Odoo, and no other purchase journal available. Cannot create bill.")
            return None

    # Prepare bill lines
    bill_lines_for_odoo = []

    # Process Item Lines from QB Bill
    for qb_line in qb_bill_data.get("item_lines", []):
        product_id = None
        item_name = qb_line.get("item_name") # QBD Item Name/FullName
        
        if item_name:
            # Ensure product exists. Pass cost from bill line if available,
            # ensure_product_exists will use it if it needs to update the master cost.
            # For the transaction line itself, we'll use the cost from the bill line directly.
            product_id = ensure_product_exists(
                model_code=item_name, 
                description=qb_line.get("description", item_name),
                purchase_cost=qb_line.get("cost") # Pass cost to potentially update product master
            )
            if not product_id:
                logger.warning(f"Could not ensure Odoo product for QB item '{item_name}'. Line description: '{qb_line.get('description')}'. Bill line may be incomplete.")

        # Determine account for the item line.
        # Priority: 1. QB Line Account (if any), 2. Item's Expense Account (from QB, mapped), 3. Default Purchase/Expense Account
        line_account_name_qb = qb_line.get("account_name") 
        odoo_line_account_id = None

        if line_account_name_qb:
            odoo_line_account_id = ensure_account_exists(line_account_name_qb, account_type_hint="expense")
        elif product_id: # If product exists, try to get its expense account from Odoo product
            product_info = _odoo_rpc_call(
                "product.product", "read", args=[product_id], kwargs_rpc={"fields": ["property_account_expense_id", "product_tmpl_id"]}
            )
            if product_info and product_info[0].get("property_account_expense_id"):
                odoo_line_account_id = product_info[0]["property_account_expense_id"][0]
            elif product_info and product_info[0].get("product_tmpl_id"): # Check template
                 template_id = product_info[0]["product_tmpl_id"][0]
                 template_info_full = _odoo_rpc_call(
                    "product.template", "read", args=[template_id], kwargs_rpc={"fields": ["property_account_expense_id"]}
                 )
                 if template_info_full and template_info_full[0].get("property_account_expense_id"):
                     odoo_line_account_id = template_info_full[0]["property_account_expense_id"][0]


        if not odoo_line_account_id:
            default_expense_account_name = "Cost of Goods Sold" # Placeholder, should be from config or journal
            logger.warning(f"Expense account for item line '{qb_line.get('description', item_name)}' not determined. Falling back to default '{default_expense_account_name}'.")
            odoo_line_account_id = ensure_account_exists(default_expense_account_name, account_type_hint="expense")

        if not odoo_line_account_id:
            logger.error(f"Failed to determine or create expense account for bill item line: '{qb_line.get('description', item_name)}'. Skipping line.")
            continue

        line_data = {
            "product_id": product_id,
            "name": qb_line.get("description") or item_name or "N/A",
            "quantity": qb_line.get("quantity", 0.0),
            "price_unit": qb_line.get("cost", 0.0), # Use 'cost' from QB bill line for price_unit on vendor bill
            "account_id": odoo_line_account_id,
            # "tax_ids": [] # Placeholder for tax mapping
        }
        bill_lines_for_odoo.append((0, 0, line_data))

    # Process Expense Lines from QB Bill
    for qb_line in qb_bill_data.get("expense_lines", []):
        account_name_qb = qb_line.get("account_name")
        if not account_name_qb:
            logger.warning("Expense line missing account name. Skipping line.")
            continue
        
        odoo_line_account_id = ensure_account_exists(account_name_qb, account_type_hint="expense")
        if not odoo_line_account_id:
            logger.error(f"Failed to ensure Odoo account for QB expense account '{account_name_qb}'. Skipping line.")
            continue
            
        line_data = {
            # No product_id for pure expense lines unless you map them to a generic "Expense" service product
            "name": qb_line.get("memo") or account_name_qb, # Description for the line
            "quantity": 1, # Expense lines usually have quantity 1
            "price_unit": qb_line.get("amount", 0.0),
            "account_id": odoo_line_account_id,
            # "tax_ids": [] # Placeholder for tax mapping
        }
        bill_lines_for_odoo.append((0, 0, line_data))


    if not bill_lines_for_odoo and (qb_bill_data.get("item_lines") or qb_bill_data.get("expense_lines")):
        logger.warning(f"No lines could be processed for QB Bill Ref {qb_bill_data.get('ref_number')}. Bill will not be created/updated if it has no lines.")

    # Prepare Odoo bill payload
    odoo_bill_payload = {
        "move_type": bill_mapping.get("default_values", {}).get("move_type", "in_invoice"),
        "partner_id": odoo_partner_id,
        "journal_id": purchase_journal_id,
        "invoice_line_ids": bill_lines_for_odoo,
        "x_qb_txn_id": qb_bill_data.get("qb_txn_id") # Custom field for QB TxnID
    }

    # Map header fields from qb_bill_data to odoo_bill_payload
    for mapping_item in bill_mapping.get("fields", []):
        qbd_field_name = mapping_item["qbd_field"]
        odoo_field_name = mapping_item["odoo_field"]

        if qbd_field_name in qb_bill_data:
            value = qb_bill_data[qbd_field_name]
            if "date" in odoo_field_name and isinstance(value, str):
                try:
                    datetime.strptime(value, "%Y-%m-%d")
                except ValueError:
                    logger.warning(f"Date field {qbd_field_name} ('{value}') is not in YYYY-MM-DD format. Odoo might reject.")
            
            # Handle special cases like TermsRef_ListID mapping
            if qbd_field_name == "TermsRef_ListID" and odoo_field_name == "invoice_payment_term_id":
                # qb_term_name = qb_bill_data.get("terms_name") 
                # if qb_term_name:
                #   odoo_term_id = ensure_payment_term_exists(qb_term_name) # Helper needed
                #   if odoo_term_id: odoo_bill_payload[odoo_field_name] = odoo_term_id
                pass # Placeholder for term mapping

            elif odoo_field_name not in ["partner_id", "journal_id", "invoice_line_ids", "move_type", "x_qb_txn_id"]:
                 odoo_bill_payload[odoo_field_name] = value
    
    # Search for existing bill in Odoo using QB TxnID
    existing_bill_id = None
    if qb_bill_data.get("qb_txn_id"):
        logger.info(f"Searching for existing Odoo bill with x_qb_txn_id: {qb_bill_data.get('qb_txn_id')}")
        existing_bills = _odoo_rpc_call(
            model="account.move",
            method="search_read",
            domain=[("x_qb_txn_id", "=", qb_bill_data.get("qb_txn_id")), ("move_type", "=", "in_invoice")],
            fields=["id"],
            limit=1
        )
        if existing_bills:
            existing_bill_id = existing_bills[0]["id"]
            logger.info(f"Found existing Odoo bill ID: {existing_bill_id} for QB TxnID: {qb_bill_data.get('qb_txn_id')}")

    if existing_bill_id:
        # Update existing bill
        update_payload = {k: v for k, v in odoo_bill_payload.items() if k != "move_type"}
        if "invoice_line_ids" in update_payload:
             update_payload["invoice_line_ids"] = [(5, 0, 0)] + bill_lines_for_odoo # Replace all lines
        
        logger.info(f"Attempting to update Odoo bill ID: {existing_bill_id}")
        logger.debug(f"Odoo Bill Update Payload: {update_payload}")
        success = _odoo_rpc_call(
            model="account.move",
            method="write",
            args=[[existing_bill_id], update_payload]
        )
        if success:
            logger.info(f"Successfully updated Odoo bill ID: {existing_bill_id}")
            # current_state = _odoo_rpc_call("account.move", "read", args=[existing_bill_id], kwargs_rpc={"fields": ["state"]})
            # if current_state and current_state[0]['state'] == 'draft':
            #    _odoo_rpc_call(model="account.move", method="action_post", args=[[existing_bill_id]])
            #    logger.info(f"Posted updated bill {existing_bill_id}")
            return existing_bill_id
        else:
            logger.error(f"Failed to update Odoo bill ID: {existing_bill_id}")
            return None
    else:
        # Create new bill
        logger.info("Attempting to create new Odoo bill.")
        logger.debug(f"Odoo Bill Create Payload: {odoo_bill_payload}")

        if not bill_lines_for_odoo and (qb_bill_data.get("item_lines") or qb_bill_data.get("expense_lines")):
             logger.error(f"No processable lines for new QB Bill Ref {qb_bill_data.get('ref_number')}. Creation aborted.")
             return None
        if not odoo_bill_payload.get("invoice_line_ids"):
            logger.warning(f"Creating bill {qb_bill_data.get('ref_number')} with no lines. Odoo may reject this.")

        new_bill_id = _odoo_rpc_call(
            model="account.move",
            method="create",
            args=[odoo_bill_payload]
        )
        if new_bill_id:
            logger.info(f"Successfully created Odoo bill with ID: {new_bill_id} for QB TxnID: {qb_bill_data.get('qb_txn_id')}")
            _odoo_rpc_call(model="account.move", method="action_post", args=[[new_bill_id]])
            logger.info(f"Posted newly created bill {new_bill_id}")
            return new_bill_id
        else:
            logger.error(f"Failed to create Odoo bill for QB Ref: {qb_bill_data.get('ref_number')}")
            return None

def create_or_update_odoo_payment(qb_payment_data: Dict[str, Any]) -> Optional[int]:
    """
    Placeholder: Creates or reconciles a payment in Odoo from QuickBooks data.
    This is complex due to matching payments to invoices.
    """
    logger.info(f"Received QB Payment data for Odoo processing: TxnID {qb_payment_data.get('qb_txn_id')}, Customer: {qb_payment_data.get('customer_name')}")
    logger.debug(f"Full QB Payment data: {qb_payment_data}")

    customer_name = qb_payment_data.get("customer_name")
    if not customer_name:
        logger.error("Cannot process payment: Customer name is missing from QB data.")
        return None

    odoo_partner_id = ensure_partner_exists(name=customer_name, is_customer=True, is_supplier=False)
    if not odoo_partner_id:
        logger.error(f"Failed to ensure Odoo partner for customer: {customer_name}. Cannot process payment.")
        return None
    logger.info(f"Ensured Odoo partner ID {odoo_partner_id} for customer '{customer_name}'.")

    # TODO: Determine Odoo journal for customer payments (e.g., "Bank" or "Cash" journal)
    # payment_journal_id = ensure_journal_exists("Bank") # Or based on QB PaymentMethodRef/DepositToAccountRef mapping
    # if not payment_journal_id:
    #     logger.error("Payment journal not found in Odoo. Cannot create payment.")
    #     return None
    
    # TODO: Logic for creating account.payment record in Odoo.
    # This involves:
    # 1. Creating the payment record itself.
    # 2. Reconciling it against the Odoo invoices that correspond to qb_payment_data["applied_to_txns"].
    #    - This requires finding the Odoo invoice IDs based on the qb_invoice_txn_id.
    #      (Requires storing QB TxnID in Odoo invoices or a reliable mapping).

    odoo_payment_payload = {
        "partner_id": odoo_partner_id,
        "date": qb_payment_data.get("txn_date"), # Payment date
        "amount": qb_payment_data.get("total_amount"),
        # "journal_id": payment_journal_id,
        "payment_type": "inbound", # Payment received from customer
        "partner_type": "customer",
        "ref": qb_payment_data.get("ref_number") or qb_payment_data.get("qb_txn_id"), # Payment reference
        # "qb_txn_id_custom_field": qb_payment_data.get("qb_txn_id")
    }

    logger.info(f"TODO: Actual Odoo 'account.payment' create call for QB Payment TxnID: {qb_payment_data.get('qb_txn_id')}")
    logger.debug(f"Odoo Payment Payload (Conceptual): {odoo_payment_payload}")
    
    # new_odoo_payment_id = _odoo_rpc_call("account.payment", "create", args=[odoo_payment_payload])
    # if new_odoo_payment_id:
    #    logger.info(f"Successfully created Odoo payment with ID: {new_odoo_payment_id}")
    #    # TODO: Post the payment:
    #    # _odoo_rpc_call("account.payment", "action_post", args=[[new_odoo_payment_id]])
    #    # TODO: Reconcile the payment against invoices. This is the hard part.
    #    # It might involve finding open Odoo invoices for the partner,
    #    # matching them based on qb_payment_data["applied_to_txns"], and then using
    #    # Odoo's reconciliation mechanisms.
    #    # For example, after posting, the payment might be in 'posted' state, and its move lines
    #    # (receivable line) would need to be reconciled with invoice receivable lines.
    #    # This often involves `action_reconcile` on the payment or directly creating `account.partial.reconcile`.
    #    logger.info(f"TODO: Reconcile Odoo payment {new_odoo_payment_id} against corresponding invoices.")
    #    return new_odoo_payment_id
    # else:
    #    logger.error(f"Failed to create Odoo payment for QB TxnID: {qb_payment_data.get('qb_txn_id')}")
    #    return None

    return 91011 # Placeholder ID
