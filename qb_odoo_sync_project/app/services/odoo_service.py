"""
Odoo service module for QB Odoo Sync application.

Handles all interactions with the Odoo ERP system including:
- Partner (customer/vendor) management
- Product management  
- Chart of accounts management
- Journal entry creation
"""
import xmlrpc.client # Added import
# import requests # Keep for potential future use or other integrations
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from dateutil.parser import isoparse
from pytz import timezone
from ..logging_config import logger
# Ensure this path is correct based on your project structure
from ..utils.data_loader import get_field_mapping # Corrected import

# --- Odoo Connection Configuration ---
ODOO_URL = "https://nterra22-sounddecision-odoo-develop-20178686.dev.odoo.com"
ODOO_DB = "nterra22-sounddecision-odoo-develop-20178686"
ODOO_USERNAME = "it@wadic.net" # Make sure this is the correct username for the API key
ODOO_API_KEY = "e8188dcec4b36dbc1e89e4da17b989c7aae8e568"
ODOO_REQUEST_TIMEOUT = 60  # Increased timeout
# --- End Odoo Connection Configuration ---

_cached_uid = None
FIELD_MAPPING = None 

def _load_mappings(): 
    global FIELD_MAPPING
    FIELD_MAPPING = get_field_mapping() # Use the new getter
    if not FIELD_MAPPING:
        logger.error("Field mapping could not be loaded. Service may not function correctly.")
    else:
        logger.info(f"Field mapping loaded successfully in odoo_service: {list(FIELD_MAPPING.keys()) if isinstance(FIELD_MAPPING, dict) else 'Not a dict'}")


_load_mappings() # Load mappings when the module is imported

def _get_odoo_uid() -> Optional[int]:
    """Authenticates with Odoo and returns the UID."""
    try:
        common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common', allow_none=True)
        uid = common.login(ODOO_DB, ODOO_USERNAME, ODOO_API_KEY)
        if uid:
            logger.info(f"Successfully authenticated with Odoo. UID: {uid}")
            return uid
        else:
            logger.error("Odoo authentication failed. No UID returned. Check credentials and DB name.")
            return None
    except xmlrpc.client.Fault as e:
        logger.error(f"Odoo RPC Fault during login: {e.faultCode} - {e.faultString}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during Odoo login: {e}")
        return None

def get_odoo_uid_cached() -> Optional[int]:
    """Returns a cached Odoo UID, authenticating if necessary."""
    global _cached_uid
    if _cached_uid is None:
        _cached_uid = _get_odoo_uid()
    return _cached_uid

def _odoo_rpc_call(model: str, method: str, args_list: List = None, kwargs_dict: Dict = None) -> Optional[Any]:
    """
    Make a standardized XML-RPC call to Odoo using 'execute_kw'.

    Args:
        model: Odoo model name (e.g., 'res.partner')
        method: Method to call (e.g., 'search_read', 'create', 'write')
        args_list: Positional arguments for the Odoo method (e.g., [[domain_list]] for search, [[id], {values}] for write)
        kwargs_dict: Keyword arguments for the Odoo method (e.g., {'fields': [...], 'limit': ...} for search_read)
    
    Returns:
        Result from Odoo API or None on error
    """
    uid = get_odoo_uid_cached()
    if not uid:
        logger.error("Cannot perform Odoo RPC call: Authentication failed or UID not available.")
        return None

    try:
        models_proxy = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object', allow_none=True)
        
        params_for_execute_kw = [ODOO_DB, uid, ODOO_API_KEY, model, method]
        
        if args_list is not None:
            params_for_execute_kw.append(args_list)
        else:
            params_for_execute_kw.append([]) # Must provide an empty list if no positional args
        
        if kwargs_dict is not None:
            params_for_execute_kw.append(kwargs_dict)

        logger.debug(f"Odoo XML-RPC call: model='{model}', method='{method}', args='{args_list}', kwargs='{kwargs_dict}'")
        
        result = models_proxy.execute_kw(*params_for_execute_kw)
        
        logger.debug(f"Odoo RPC call to {model}.{method} successful. Result snippet: {str(result)[:200]}...")
        return result
    except xmlrpc.client.Fault as e:
        logger.error(f"Odoo RPC Fault for {model}.{method}: {e.faultCode} - {e.faultString}")
        global _cached_uid
        if "AccessDenied" in e.faultString or "Session expired" in e.faultString or "Invalid user credentials" in e.faultString:
             _cached_uid = None
             logger.info("Cleared cached Odoo UID due to potential session/access issue.")
        return None
    except Exception as e: 
        logger.error(f"Unexpected error during Odoo RPC call for {model}.{method}: {e}", exc_info=True)
        return None

# --- Partner (Customer/Vendor) Management ---\r
def find_partner_by_ref(ref: str, company_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Finds a partner by their 'ref' (QuickBooks ListID)."""
    domain = [('ref', '=', ref)]
    if company_id:
        domain.append(('company_id', '=', company_id))
    
    partners = _odoo_rpc_call(
        model='res.partner',
        method='search_read',
        args_list=[domain],
        kwargs_dict={'fields': ['id', 'name', 'email', 'phone', 'mobile', 'street', 'street2', 'city', 'state_id', 'zip', 'country_id', 'is_company', 'parent_id', 'type', 'vat', 'company_id', 'customer_rank', 'supplier_rank'], 'limit': 1}
    )
    if partners:
        return partners[0]
    return None

def find_partner_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Finds a partner by their name (tries both 'FirstName LastName' and 'LastName, FirstName' formats)."""
    if not name or not name.strip():
        return None
    name = name.strip()
    possible_names = [name]
    if ',' in name:
        last, first = [part.strip() for part in name.split(',', 1)]
        possible_names.append(f"{first} {last}")
    elif ' ' in name:
        parts = name.split()
        if len(parts) >= 2:
            first = parts[0]
            last = ' '.join(parts[1:])
            possible_names.append(f"{last}, {first}")
    for test_name in possible_names:
        partners = _odoo_rpc_call(
            "res.partner",
            "search_read",
            args_list=[[['name', '=', test_name]]],
            kwargs_dict={"fields": ["id", "name", "ref"], "limit": 1}
        )
        if partners:
            return partners[0]
    return None

def ensure_partner_exists(name: str, **kwargs) -> Optional[int]:
    """
    Ensure a partner exists in Odoo, creating if necessary.
    Checks for duplicates using both 'FirstName LastName' and 'LastName, FirstName' formats.
    
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

    # Try to split name for both formats
    possible_names = [name]
    if ',' in name:
        # QuickBooks format: 'LastName, FirstName' -> Odoo: 'FirstName LastName'
        last, first = [part.strip() for part in name.split(',', 1)]
        possible_names.append(f"{first} {last}")
    elif ' ' in name:
        # Odoo format: 'FirstName LastName' -> QuickBooks: 'LastName, FirstName'
        parts = name.split()
        if len(parts) >= 2:
            first = parts[0]
            last = ' '.join(parts[1:])
            possible_names.append(f"{last}, {first}")

    # Search for existing partner by all possible name formats
    for test_name in possible_names:
        partners = _odoo_rpc_call(
            "res.partner",
            "search_read",
            args_list=[[['name', '=', test_name]]],
            kwargs_dict={"fields": ["id"], "limit": 1}
        )
        if partners:
            partner_id = partners[0]["id"]
            logger.info(f"Partner '{test_name}' found with ID: {partner_id}")
            return partner_id

    # Create new partner
    logger.info(f"Partner '{name}' not found. Creating...")
    partner_data = {
        "name": name,
        "is_company": False,  # Always create as individual
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


    try:
        new_partner_id = _odoo_rpc_call("res.partner", "create", args_list=[partner_data])
        if new_partner_id:
            logger.info(f"Partner '{name}' created with ID: {new_partner_id}")
        else:
            logger.error(f"Failed to create partner '{name}'. Odoo returned no ID.")
        return new_partner_id
    except Exception as e:
        logger.error(f"Exception while creating partner '{name}': {e}", exc_info=True)
        return None

# --- START OF REORGANIZED AND FIXED PARTNER AND PRODUCT LOGIC ---
def get_odoo_country_id(country_identifier: str) -> Optional[int]:
    """
    Finds an Odoo country ID by its name or code.
    Args:
        country_identifier: Country name (e.g., "United States") or code (e.g., "US").
    Returns:
        Odoo country ID or None.
    """
    if not country_identifier:
        return None
    
    # Search by code first (more reliable)
    countries_by_code = _odoo_rpc_call(
        "res.country", "search_read",
        args_list=[[("code", "=", country_identifier.upper())]],
        kwargs_dict={"fields": ["id"], "limit": 1}
    )
    if countries_by_code:
        return countries_by_code[0]["id"]

    # Search by name if code search fails
    countries_by_name = _odoo_rpc_call(
        "res.country", "search_read",
        args_list=[[("name", "ilike", country_identifier)]],
        kwargs_dict={"fields": ["id"], "limit": 1}
    )
    if countries_by_name:
        return countries_by_name[0]["id"]
    
    logger.warning(f"Odoo country not found for identifier: {country_identifier}")
    return None

def get_odoo_state_id(state_identifier: str, country_code: Optional[str] = None) -> Optional[int]:
    """
    Finds an Odoo state ID by its name or code, optionally filtered by country.
    Args:
        state_identifier: State name (e.g., "California") or code (e.g., "CA").
        country_code: Optional Odoo country code (e.g., "US") to narrow down search.
    Returns:
        Odoo state ID or None.
    """
    if not state_identifier:
        return None

    domain = []
    # Try to match by code first
    if len(state_identifier) <= 3: # Heuristic: short identifiers are likely codes
         domain.append(("code", "=", state_identifier.upper()))
    else: # Longer identifiers are likely names
        domain.append(("name", "ilike", state_identifier))

    if country_code:
        country_id = get_odoo_country_id(country_code)
        if country_id:
            domain.append(("country_id", "=", country_id))
        else:
            logger.warning(f"Cannot filter state by country code '{country_code}' as country was not found.")

    states = _odoo_rpc_call(
        "res.country.state", "search_read",
        args_list=[domain],
        kwargs_dict={"fields": ["id"], "limit": 1}
    )
    if states:
        return states[0]["id"]
    
    # If initial search failed and we had a country filter, try without it as a fallback
    if country_code and not states:
        logger.info(f"State '{state_identifier}' not found with country filter '{country_code}'. Retrying without country filter.")
        domain_no_country = [item for item in domain if item[0] != "country_id"]
        states_no_country = _odoo_rpc_call(
            "res.country.state", "search_read",
            args_list=[domain_no_country],
            kwargs_dict={"fields": ["id"], "limit": 1}
        )
        if states_no_country:
            return states_no_country[0]["id"]

    logger.warning(f"Odoo state not found for identifier: {state_identifier} (Country: {country_code or 'any'})")
    return None

def get_odoo_partner_category_ids(category_names: List[str]) -> List[int]:
    """Finds Odoo partner category IDs (tags) by their names.
    
    NOTE: Partner categories are ignored as per configuration.
    This function always returns an empty list to skip category assignment.
    """
    if not category_names:
        return []
    
    sanitized_names = [name.strip() for name in category_names if name and name.strip()]
    if not sanitized_names:
        return []

    # Log that we're ignoring categories but don't warn
    logger.debug(f"Ignoring partner categories as configured: {sanitized_names}")
    
    # Always return empty list to skip category assignment
    return []

def get_odoo_payment_term_id(payment_term_name: str) -> Optional[int]:
    """Finds an Odoo payment term ID by its name.
    
    Always returns the ID for "Due on Receipt" payment term as default.
    If that term doesn't exist, will try to find or create it.
    """
    # Always default to "Due on Receipt"
    default_term_name = "Due on Receipt"
    
    # First, try to find "Due on Receipt" term
    terms = _odoo_rpc_call(
        "account.payment.term", "search_read",
        args_list=[[("name", "=", default_term_name)]],
        kwargs_dict={"fields": ["id"], "limit": 1}
    )
    
    if terms:
        logger.debug(f"Using default payment term '{default_term_name}' (ID: {terms[0]['id']}) instead of '{payment_term_name}'")
        return terms[0]["id"]
    
    # If "Due on Receipt" doesn't exist, try case-insensitive search
    terms_ilike = _odoo_rpc_call(
        "account.payment.term", "search_read",
        args_list=[[("name", "ilike", default_term_name)]],
        kwargs_dict={"fields": ["id"], "limit": 1}
    )
    
    if terms_ilike:
        logger.debug(f"Found default payment term using 'ilike' for '{default_term_name}' (ID: {terms_ilike[0]['id']}) instead of '{payment_term_name}'")
        return terms_ilike[0]["id"]
    
    # If we still can't find it, look for "Immediate Payment" as fallback
    immediate_terms = _odoo_rpc_call(
        "account.payment.term", "search_read",
        args_list=[[("name", "ilike", "Immediate Payment")]],
        kwargs_dict={"fields": ["id"], "limit": 1}
    )
    
    if immediate_terms:
        logger.debug(f"Using 'Immediate Payment' as fallback payment term (ID: {immediate_terms[0]['id']}) instead of '{payment_term_name}'")
        return immediate_terms[0]["id"]
    
    # Last resort: return None and let Odoo use its default
    logger.warning(f"Could not find default payment term '{default_term_name}' or 'Immediate Payment'. Odoo will use its system default.")
    return None

def create_or_update_odoo_partner(qb_customer_data: Dict[str, Any], is_supplier: bool = False) -> Optional[int]:
    """
    Creates or updates a partner in Odoo from QuickBooks customer data.
    Uses field_mapping.json for mapping QB fields to Odoo fields.
    Handles creation of new partners and updates to existing ones based on partner name (not ListID).
    If ParentRef_ListID is present in qb_customer_data, it's a job and will be skipped.
    Args:
        qb_customer_data: Dictionary containing data from QB CustomerRet or VendorRet.
        is_supplier: Boolean flag, True if the data is for a vendor.
    """
    logger.info(f"Processing QB Partner Data: Name='{qb_customer_data.get('Name', 'N/A')}', FullName='{qb_customer_data.get('FullName', 'N/A')}', ListID='{qb_customer_data.get('ListID', 'N/A')}', IsSupplier='{is_supplier}'")

    # Check if this is a job (has a ParentRef_ListID). If so, skip creating/updating it as a partner.
    # This check is primarily for customer records that are jobs.
    # Vendors typically don't have ParentRef_ListID in the same way.
    if not is_supplier and qb_customer_data.get("ParentRef_ListID"):
        logger.info(f"QB record '{qb_customer_data.get('FullName', qb_customer_data.get('Name', 'N/A'))}' (ListID: {qb_customer_data.get('ListID')}) is a job (has ParentRef_ListID). Skipping partner creation/update in Odoo.")
        return None # Indicates skipped

    if not FIELD_MAPPING:
        logger.error("Field mapping not loaded. Cannot process partner.")
        return None

    customer_mapping_config = FIELD_MAPPING.get("entities", {}).get("Customers")
    if not customer_mapping_config:
        logger.error("Customer mapping configuration not found in field_mapping.json.")
        return None

    qb_list_id = qb_customer_data.get("ListID")
    if not qb_list_id:
        logger.error("QuickBooks ListID missing from customer data. Cannot reliably find or create partner.")
        return None

    odoo_partner_id = None
    existing_partner_data = find_partner_by_name(qb_customer_data.get("Name"))

    if existing_partner_data:
        odoo_partner_id = existing_partner_data["id"]
        logger.info(f"Found existing Odoo partner ID: {odoo_partner_id} for Name: {qb_customer_data.get('Name')}")
    else:
        logger.info(f"No existing Odoo partner found for Name: {qb_customer_data.get('Name')}. Will attempt to create.")

    odoo_payload = {}
    
    # 1. Handle Name and Company Type (is_company, type)
    raw_name = qb_customer_data.get("Name")
    if not raw_name or not raw_name.strip():
        logger.error(f"QB Customer data for ListID {qb_customer_data.get('ListID')} is missing 'Name' or 'Name' is empty. Cannot process partner.")
        return None
    
    # Determine initial is_company status
    is_company = True # Default
    if "IsPerson" in qb_customer_data:
        is_company = not qb_customer_data["IsPerson"]

    if ',' in raw_name:
        parts = [p.strip() for p in raw_name.split(',', 1)]
        if len(parts) == 2:
            last_name, first_name = parts
            odoo_payload["name"] = f"{first_name} {last_name}"
            # If name is "LastName, FirstName", it's usually an individual.
            # Override is_company only if IsPerson is not present or contradicts.
            if "IsPerson" not in qb_customer_data: # If IsPerson was not provided, assume individual
                 is_company = False
            # If IsPerson was provided, its value for is_company is already set.
        else: # Malformed "LastName, FirstName"
            odoo_payload["name"] = raw_name
            # is_company remains as determined by IsPerson or default
    else: # CompanyName or "FirstName LastName"
        odoo_payload["name"] = raw_name
        # is_company remains as determined by IsPerson or default

    # If ParentRef_ListID exists, this is a contact (child), so it's not a company itself. This overrides previous.
    if qb_customer_data.get("ParentRef_ListID"):
        is_company = False
    
    odoo_payload["is_company"] = is_company
    if not is_company:
        odoo_payload["type"] = "contact"

    # 2. Iterate through mapped fields from field_mapping.json
    for mapping_rule in customer_mapping_config.get("fields", []):
        qb_field = mapping_rule["qbd_field"]
        odoo_field = mapping_rule["odoo_field"]
        
        # Skip fields handled manually or invalid for direct mapping
        if odoo_field in ["external_id", "first_name", "last_name", "name"]: # 'name' is already set
            continue 
        
        if qb_field not in qb_customer_data:
            continue # Skip if QB data doesn't have this field
            
        qb_value = qb_customer_data[qb_field]
        
        # Skip if QB value is None or an empty string after stripping
        if qb_value is None or (isinstance(qb_value, str) and not qb_value.strip()):
            logger.debug(f"Skipping QB field '{qb_field}' for Odoo field '{odoo_field}' due to empty/None value.")
            continue

        # Skip complex relational fields that require creating other records (e.g., child_ids.street for shipping addresses)
        # SIMPLIFIED: Do not warn or log about child_ids or complex fields, just skip them silently
        if "." in odoo_field:
            continue

        # Special handling for relational fields requiring ID lookups
        if odoo_field == "parent_id": # qb_field is typically "ParentRef_ListID"
            parent_list_id = str(qb_value) 
            if parent_list_id:
                parent_partner_data = find_partner_by_ref(parent_list_id)
                if parent_partner_data:
                    odoo_payload[odoo_field] = parent_partner_data["id"]
                else:
                    logger.warning(f"Parent partner with QB ListID {parent_list_id} not found in Odoo for child {odoo_payload.get('name')}. Cannot set parent_id.")
            continue 

        elif odoo_field == "country_id": # qb_field is typically "BillAddress_Country"
            country_odoo_id = get_odoo_country_id(str(qb_value))
            if country_odoo_id: 
                odoo_payload[odoo_field] = country_odoo_id
            else:
                logger.warning(f"Country '{qb_value}' not found in Odoo. Skipping country_id for partner {odoo_payload.get('name')}.")
            continue

        elif odoo_field == "state_id": # qb_field is typically "BillAddress_State"
            country_code_for_state = None
            # Try to get country code from already resolved country_id in payload (if BillAddress_Country was mapped to country_id)
            if "country_id" in odoo_payload and isinstance(odoo_payload["country_id"], int):
                country_data = _odoo_rpc_call("res.country", "read", args_list=[[odoo_payload["country_id"]]], kwargs_dict={"fields": ["code"]})
                if country_data and isinstance(country_data, list) and country_data[0].get("code"):
                     country_code_for_state = country_data[0].get("code")
            # Fallback: try to get country from QB data if BillAddress_Country is available and current field is BillAddress_State
            elif qb_field == "BillAddress_State" and "BillAddress_Country" in qb_customer_data:
                 country_code_for_state = str(qb_customer_data["BillAddress_Country"])
            
            state_odoo_id = get_odoo_state_id(str(qb_value), country_code_for_state)
            if state_odoo_id: 
                odoo_payload[odoo_field] = state_odoo_id
            else:
                logger.warning(f"State '{qb_value}' (Country: {country_code_for_state or 'any'}) not found in Odoo. Skipping state_id for partner {odoo_payload.get('name')}.")
            continue
            
        elif odoo_field == "category_id": # qb_field is "CustomerTypeRef_FullName"
            # Odoo's category_id on res.partner is a Many2many field for tags (res.partner.category)
            category_name = str(qb_value)
            if category_name:
                category_ids = get_odoo_partner_category_ids([category_name]) # QB usually provides one type here
                if category_ids:
                    # For M2M, use Odoo's special command (6, 0, [IDs]) to replace existing tags
                    odoo_payload[odoo_field] = [(6, 0, category_ids)] 
            continue

        elif odoo_field == "property_payment_term_id": # qb_field is "TermsRef_FullName"
            payment_term_name = str(qb_value)
            if payment_term_name:
                payment_term_id = get_odoo_payment_term_id(payment_term_name)
                if payment_term_id:
                    odoo_payload[odoo_field] = payment_term_id
            continue
        
        # Default: Add to payload if not specially handled
        odoo_payload[odoo_field] = qb_value

    # 3. Set 'active' status (if mapped qbd_field "IsActive" to odoo_field "active", it's handled by loop)
    if "active" not in odoo_payload: # If not mapped via loop
        if "IsActive" in qb_customer_data:
            odoo_payload["active"] = qb_customer_data["IsActive"]
        else:
            odoo_payload["active"] = True # Default to active if not specified

    # 4. Set customer/supplier ranks
    customer_defaults = customer_mapping_config.get("default_values", {})
    
    # Determine if it's a customer based on QB data (for CustomerRet) or if not a supplier
    # For CustomerRet, 'IsActive' implies it's a customer.
    # For VendorRet, it's not a customer unless explicitly stated or handled by dual roles in QB.
    is_actually_customer = not is_supplier # If it's from CustomerQuery, it's a customer.

    if "customer_rank" not in odoo_payload:
        if is_actually_customer:
            odoo_payload["customer_rank"] = customer_defaults.get("customer_rank", 1)
        else: # If it's a vendor, set customer_rank to 0 unless QB data indicates it's also a customer
            # This part might need more sophisticated logic if a QB Vendor can also be a Customer
            # For now, if is_supplier is true, customer_rank is 0 by default.
            odoo_payload["customer_rank"] = 0 

    if "supplier_rank" not in odoo_payload:
        if is_supplier:
            odoo_payload["supplier_rank"] = customer_defaults.get("supplier_rank", 1) # Default for vendors
        else:
            odoo_payload["supplier_rank"] = 0


    # 5. Ensure 'ref' is set for linking with QB ListID
    odoo_payload["ref"] = qb_list_id
    
    logger.debug(f"Final Odoo partner payload for '{odoo_payload.get('name')}' (ListID: {qb_list_id}): {odoo_payload}")

    # 6. Perform Odoo RPC Call (Create or Update)
    if odoo_partner_id: # Update existing partner
        # Odoo's 'write' method takes a list of IDs and a dict of values.
        # 'ref' can be included; Odoo handles it.
        if not odoo_payload: 
            logger.info(f"No changes to update for partner {odoo_payload.get('name')} (ID: {odoo_partner_id}).")
            return odoo_partner_id

        logger.info(f"Attempting to update Odoo partner ID: {odoo_partner_id} with data: {odoo_payload}")
        success = _odoo_rpc_call("res.partner", "write", args_list=[[odoo_partner_id], odoo_payload])
        
        if success: # Odoo's write usually returns True on success
            logger.info(f"Successfully updated Odoo partner ID: {odoo_partner_id}")
            return odoo_partner_id
        else:
            logger.error(f"Failed to update Odoo partner ID: {odoo_partner_id}. Payload: {odoo_payload}")
            return None 
    else: # Create new partner
        # Optional: Check for duplicates by name/parent before creating if ListID is new
        search_domain_dup = [('name', '=', odoo_payload.get('name'))]
        if odoo_payload.get('parent_id'):
            search_domain_dup.append(('parent_id', '=', odoo_payload.get('parent_id')))
        
        if odoo_payload.get('name'): # Only search if name is present
            existing_by_name_no_ref = _odoo_rpc_call("res.partner", "search", args_list=[search_domain_dup], kwargs_dict={'limit': 1})
            if existing_by_name_no_ref:
                logger.warning(
                    f"A partner with name '{odoo_payload.get('name')}' "
                    f"{('and parent ID ' + str(odoo_payload.get('parent_id'))) if odoo_payload.get('parent_id') else ''} "
                    f"already exists in Odoo with ID {existing_by_name_no_ref[0]} but has no matching QB ListID '{qb_list_id}'. "
                    f"Review for potential duplicates. Proceeding with creation for ListID: {qb_list_id}."
                )

        logger.info(f"Attempting to create new Odoo partner with data: {odoo_payload}")
        new_partner_id_result = _odoo_rpc_call("res.partner", "create", args_list=[odoo_payload]) 
        
        if new_partner_id_result and isinstance(new_partner_id_result, int):
            logger.info(f"Successfully created new Odoo partner with ID: {new_partner_id_result} for QB ListID: {qb_list_id}")
            return new_partner_id_result
        else:
            logger.error(f"Failed to create new Odoo partner for QB ListID: {qb_list_id}, Name: {odoo_payload.get('name')}. Payload: {odoo_payload}. Result: {new_partner_id_result}")
            return None

def ensure_product_exists(model_code: str, description: str, 
                          sales_price: Optional[float] = None, 
                          purchase_cost: Optional[float] = None,
                          odoo_product_type: Optional[str] = None) -> Optional[int]:
    """
    Ensure a product exists in Odoo, creating or updating if necessary.
    Sales price and purchase cost from QB are considered source of truth.
    """
    if not model_code or not model_code.strip():
        logger.warning("Empty product model code provided")
        return None
        
    model_code = model_code.strip()
    description = description.strip() if description else model_code
    
    # If model_code contains a colon, extract only the part after the colon for default_code
    if ':' in model_code:
        model_code = model_code.split(':', 1)[1].strip()

    products = _odoo_rpc_call(
        "product.product",
        "search_read", 
        args_list=[[("default_code", "=", model_code)]],
        kwargs_dict={"fields": ["id", "product_tmpl_id", "lst_price", "standard_price", "type"], "limit": 1}
    )

    template_id_to_update = None 
    update_values_template = {} 

    if products:
        product_record = products[0]
        product_id = product_record["id"]
        template_id_tuple = product_record.get("product_tmpl_id")
        template_id_to_update = template_id_tuple[0] if template_id_tuple else None
        
        logger.info(f"Product '{model_code}' found with ID: {product_id} (Template ID: {template_id_to_update})")

        if template_id_to_update: 
            if sales_price is not None:
                current_template_data = _odoo_rpc_call("product.template", "read", args_list=[[template_id_to_update]], kwargs_dict={"fields": ["lst_price"]})
                current_sales_price = current_template_data[0]['lst_price'] if current_template_data and current_template_data[0] else None
                if sales_price != current_sales_price:
                    logger.info(f"Updating Odoo product '{model_code}' (Template ID: {template_id_to_update}) sales price from {current_sales_price} to {sales_price}")
                    update_values_template["lst_price"] = sales_price
            
            if purchase_cost is not None:
                current_template_data_cost = _odoo_rpc_call("product.template", "read", args_list=[[template_id_to_update]], kwargs_dict={"fields": ["standard_price"]})
                current_cost_price = current_template_data_cost[0]['standard_price'] if current_template_data_cost and current_template_data_cost[0] else None
                if purchase_cost != current_cost_price:
                    logger.info(f"Updating Odoo product '{model_code}' (Template ID: {template_id_to_update}) cost price from {current_cost_price} to {purchase_cost}")
                    update_values_template["standard_price"] = purchase_cost
            
            if odoo_product_type:
                current_template_data_type = _odoo_rpc_call("product.template", "read", args_list=[[template_id_to_update]], kwargs_dict={"fields": ["type"]})
                current_type = current_template_data_type[0]['type'] if current_template_data_type and current_template_data_type[0] else None
                if odoo_product_type != current_type:
                    logger.info(f"Updating Odoo product '{model_code}' (Template ID: {template_id_to_update}) type from {current_type} to {odoo_product_type}")
                    update_values_template["type"] = odoo_product_type
            
            if update_values_template:
                _odoo_rpc_call("product.template", "write", args_list=[[template_id_to_update], update_values_template])
                logger.info(f"Updated product.template {template_id_to_update} for '{model_code}'.")
        else:
            logger.warning(f"Product '{model_code}' (ID: {product_id}) found but has no associated product.template. Cannot update price/cost/type. Check data integrity in Odoo.")

        return product_id
    
    logger.info(f"Product '{model_code}' not found. Creating...")
    
    product_template_data = {
        "name": description,
        "default_code": model_code,
        "type": odoo_product_type if odoo_product_type else "product",
        "purchase_ok": True,
        "sale_ok": True,
    }
    if sales_price is not None:
        product_template_data["lst_price"] = sales_price
    if purchase_cost is not None:
        product_template_data["standard_price"] = purchase_cost

    new_template_id = _odoo_rpc_call("product.template", "create", args_list=[product_template_data])
    
    if not new_template_id:
        logger.error(f"Failed to create product.template for '{model_code}'.")
        return None
    
    logger.info(f"Product template for '{model_code}' created with ID: {new_template_id}")

    created_products = _odoo_rpc_call(
        "product.product",
        "search_read",
        args_list=[[("product_tmpl_id", "=", new_template_id), ("default_code", "=", model_code)]], 
        kwargs_dict={"fields": ["id"], "limit": 1}
    )

    if created_products:
        new_product_id = created_products[0]["id"]
        logger.info(f"Product '{model_code}' (product.product) created with ID: {new_product_id} linked to template {new_template_id}")
        return new_product_id
    else:
        logger.error(f"Failed to find the auto-created product.product for template ID {new_template_id} and code '{model_code}'. This can happen with variants or if creation is delayed. Manual check in Odoo might be needed.")
        fallback_products = _odoo_rpc_call(
            "product.product", "search_read",
            args_list=[[("product_tmpl_id", "=", new_template_id)]],
            kwargs_dict={"fields": ["id"], "limit": 1}
        )
        if fallback_products:
            new_product_id = fallback_products[0]["id"]
            logger.info(f"Product '{model_code}' (product.product) created with ID: {new_product_id} (found via fallback search) linked to template {new_template_id}")
            return new_product_id
        else:
            logger.error(f"Fallback search also failed to find product.product for template ID {new_template_id}.")
            return None
# --- END OF REORGANIZED AND FIXED PARTNER AND PRODUCT LOGIC ---

# --- Account Crosswalk Helper ---
_account_crosswalk_data = None

def load_account_crosswalk():
    global _account_crosswalk_data
    if _account_crosswalk_data is None: # Load only once
        # _account_crosswalk_data = load_json_data("account_crosswalk.json") # This was the error source
        # Corrected: Use the loader from app.utils.data_loader
        from ..utils.data_loader import load_account_crosswalk as util_load_account_crosswalk
        util_load_account_crosswalk() # This will populate the _account_crosswalk_data in data_loader
        
        # Now, get the loaded data from data_loader's cache
        from ..utils.data_loader import get_account_map as util_get_account_map # Need a way to get all data or use its functions
        # This is a bit tricky as data_loader caches internally.
        # For now, we'll rely on data_loader's internal cache and use its get_account_map.
        # If we need the whole dict here, data_loader needs a function to return it.
        # For now, this function will just ensure it's loaded in data_loader.
        logger.info("Ensured account crosswalk data is loaded via data_loader.")


def get_account_map(qb_account_full_name: str) -> Optional[Dict[str, Any]]:
    # global _account_crosswalk_data # Not needed if using data_loader's functions
    # if _account_crosswalk_data is None:
    #     load_account_crosswalk() # Ensures it's loaded in data_loader

    # Use the getter from data_loader directly
    from ..utils.data_loader import get_account_map as util_get_account_map
    return util_get_account_map(qb_account_full_name)

    # if not isinstance(_account_crosswalk_data, list):
    #     logger.error("Account crosswalk data is not a list, cannot search.")
    #     return None

    # for mapping in _account_crosswalk_data:
    #     if isinstance(mapping, dict) and mapping.get("qb_account_full_name") == qb_account_full_name:
    #         return {
    #             "code": mapping.get("odoo_code"),
    #             "name": mapping.get("odoo_name"),
    #             "type": mapping.get("odoo_type"), 
    #             "reconcile": mapping.get("odoo_reconcile", False)
    #         }
    # return None

load_account_crosswalk() # Call this to ensure data_loader loads it on module import

# --- Field Mapping Loader ---
# FIELD_MAPPING is already loaded by _load_mappings() at the top of the file.
# The load_field_mapping function here can be removed if _load_mappings handles it.

# def load_field_mapping():
#     global FIELD_MAPPING
#     if FIELD_MAPPING is None:
#         # FIELD_MAPPING = load_json_data("field_mapping.json") # This was the error source
#         # Corrected: Use the loader from app.utils.data_loader
#         from ..utils.data_loader import load_field_mapping as util_load_field_mapping
#         util_load_field_mapping() # This populates _field_mapping_data in data_loader
        
#         from ..utils.data_loader import get_field_mapping as util_get_field_mapping
#         FIELD_MAPPING = util_get_field_mapping() # Get the loaded data

#         if FIELD_MAPPING is None:
#             logger.error("Field mapping data (field_mapping.json) could not be loaded or is empty.")
#             FIELD_MAPPING = {} # Initialize as empty dict if loading fails
#         else:
#             logger.info("Field mapping data loaded successfully.")

# load_field_mapping() # This is redundant if _load_mappings() at the top works.
# --- End Account Crosswalk Helper ---


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
        logger.warning("Empty QB account name provided to ensure_account_exists")
        return None
        
    odoo_account_map = get_account_map(qb_account_full_name)
    if not odoo_account_map:
        logger.warning(f"QuickBooks account '{qb_account_full_name}' not found in crosswalk. Account type hint: {account_type_hint}")
        return None

    odoo_account_code = odoo_account_map.get("code")
    odoo_account_name = odoo_account_map.get("name")
    # 'type' from crosswalk is the name of an account.account.type record
    odoo_account_type_name = odoo_account_map.get("type") or account_type_hint 

    if not odoo_account_code:
        logger.warning(f"Odoo account code missing for QB account '{qb_account_full_name}' in crosswalk")
        return None

    accounts = _odoo_rpc_call(
        model="account.account",
        method="search_read",
        args_list=[[("code", "=", odoo_account_code)]], # Corrected
        kwargs_dict={"fields": ["id", "name"], "limit": 1} # Corrected
    )

    if accounts:
        account_id = accounts[0]["id"]
        logger.info(f"Odoo Account '{odoo_account_code} - {accounts[0]['name']}' found with ID: {account_id}")
        return account_id
    
    logger.info(f"Odoo Account with code '{odoo_account_code}' not found. Attempting to create")
    
    if not odoo_account_type_name:
        logger.error(f"Odoo account type name not specified for QB account '{qb_account_full_name}' (from crosswalk or hint). Cannot create account.")
        return None
        
    account_types = _odoo_rpc_call(
        model="account.account.type",
        method="search_read",
        args_list=[[("name", "ilike", odoo_account_type_name)]], # Corrected
        kwargs_dict={"fields": ["id", "name"], "limit": 1} # Corrected
    )

    if not account_types:
        logger.error(f"Odoo account type '{odoo_account_type_name}' not found. Cannot create account '{odoo_account_code}'")
        return None

    user_type_id = account_types[0]["id"]
    logger.info(f"Found Odoo account type '{account_types[0]['name']}' with ID {user_type_id} for creating account '{odoo_account_code}'")

    account_data = {
        "code": odoo_account_code,
        "name": odoo_account_name or qb_account_full_name, 
        "user_type_id": user_type_id,
        "reconcile": odoo_account_map.get("reconcile", False)
    }
    
    new_account_id = _odoo_rpc_call("account.account", "create", args_list=[account_data])
    if new_account_id:
        logger.info(f"Odoo Account '{odoo_account_code}' created with ID: {new_account_id}")
    else:
        logger.error(f"Failed to create Odoo account '{odoo_account_code}'.")
    
    return new_account_id

def ensure_journal_exists(journal_name: str, journal_type_list: Optional[List[str]] = None) -> Optional[int]:
    """
    Find an Odoo journal by name, optionally filtered by a list of types.
    
    Args:
        journal_name: Journal name to search for.
        journal_type_list: Optional list of journal types (e.g., ['general', 'sale', 'purchase']).
                           If None, defaults to ['general', 'sale', 'purchase', 'bank', 'cash'].
        
    Returns:
        Journal ID or None if not found
    """
    if not journal_name:
        logger.warning("Empty journal name provided to ensure_journal_exists")
        return None
    
    domain = [("name", "=", journal_name)] # Corrected
    
    if journal_type_list:
        domain.append(("type", "in", journal_type_list)) # Corrected
    else:
        domain.append(("type", "in", ["general", "sale", "purchase", "bank", "cash"])) # Corrected
        
    journals = _odoo_rpc_call(
        model="account.journal",
        method="search_read",
        args_list=[domain], # Corrected
        kwargs_dict={"fields": ["id", "name", "type"], "limit": 1} # Corrected
    )
    
    if journals:
        journal_id = journals[0]["id"]
        logger.info(f"Odoo Journal '{journal_name}' (Type: {journals[0]['type']}) found with ID: {journal_id}")
        return journal_id
    
    logger.warning(f"Odoo Journal '{journal_name}' (Types searched: {journal_type_list or 'default'}) not found")
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
        args_list=[move_data]
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

    invoice_mapping = FIELD_MAPPING.get("entities", {}).get("Invoices")
    if not invoice_mapping:
        logger.error("Invoice mapping not found in field_mapping.json. Cannot process invoice.")
        return None

    # Only import invoices created today based on the QBWC-recognized 'TxnDate' field.
    txn_date = qb_invoice_data.get("TxnDate") or qb_invoice_data.get("txn_date")
    logger.debug(f"Raw TxnDate from QB: '{txn_date}' (type: {type(txn_date)})")

    if not txn_date or not str(txn_date).strip():
        logger.info("Skipping invoice: TxnDate missing or empty.")
        return None

    try:
        # Try YYYY-MM-DD (QBXML standard)
        txn_dt = datetime.strptime(str(txn_date), "%Y-%m-%d")
    except ValueError:
        try:
            # Fallback to dateutil.parser.isoparse for strict ISO-8601
            txn_dt = isoparse(str(txn_date))
        except Exception as e:
            logger.error(f"Could not parse TxnDate '{txn_date}' as YYYY-MM-DD or ISO: {e}")
            return None

    # Convert txn_dt to Bermuda (Atlantic/Bermuda) timezone for correct "today" comparison
    bermuda_tz = timezone("Atlantic/Bermuda")
    if txn_dt.tzinfo is None:
        txn_dt = bermuda_tz.localize(txn_dt)
    else:
        txn_dt = txn_dt.astimezone(bermuda_tz)

    txn_day = txn_dt.date()
    bermuda_today = datetime.now(bermuda_tz).date()
    if txn_day != bermuda_today:
        logger.info(f"Skipping invoice with TxnDate {txn_day} (not today's date in Bermuda).")
        return None

    # Ensure customer (partner) exists
    customer_name = qb_invoice_data.get("customer_name")
    if not customer_name:
        logger.error("Customer name missing from QB invoice data.")
        return None
    
    odoo_partner_id = ensure_partner_exists(name=customer_name, is_customer=True, is_supplier=False)
    if not odoo_partner_id:
        logger.error(f"Failed to ensure Odoo partner for customer: {customer_name}. Invoice will be skipped. Please check Odoo partner creation logic and logs for details.")
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
            args_list=[[('type', '=', 'sale')]],
            kwargs_dict={"fields": ["id", "name"], "limit": 1} # Added name to log which journal is used
        )
        if journals:
            sales_journal_id = journals[0]["id"]
            logger.info(f"Found sales journal '{journals[0].get('name', 'ID: '+str(sales_journal_id))}' to use.") # Log the name
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
                "product.product", "read", args_list=[product_id], kwargs_dict={"fields": ["property_account_income_id", "product_tmpl_id"]}
            )
            if product_template_info and product_template_info[0].get("property_account_income_id"):
                odoo_line_account_id = product_template_info[0]["property_account_income_id"][0] # It's a tuple (id, name)
            elif product_template_info and product_template_info[0].get("product_tmpl_id"): # Check template
                 template_id = product_template_info[0]["product_tmpl_id"][0]
                 template_info_full = _odoo_rpc_call(
                    "product.template", "read", args_list=[template_id], kwargs_dict={"fields": ["property_account_income_id"]}
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
                # Add a pass statement here if no other action is needed in the try block after strptime
                # or if the intention was just to validate. If strptime fails, the except block handles it.
                pass 
            
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
            args_list=[["x_qb_txn_id", "=", qb_invoice_data.get("qb_txn_id")], ["move_type", "=", "out_invoice"]],
            kwargs_dict={"fields": ["id"], "limit": 1}
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
            args_list=[[existing_invoice_id], update_payload]
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
            args_list=[odoo_invoice_payload]
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

def create_or_update_odoo_payment(qb_payment_data: Dict[str, Any]) -> Optional[int]:
    """
    Placeholder for creating or updating an Odoo payment from QuickBooks payment data.
    This function needs to be fully implemented.
    """
    logger.info(f"Placeholder: Processing QB Payment: {qb_payment_data}")
    # TODO: Implement full logic for payment creation/update
    # 1. Load payment mapping from field_mapping.json
    # 2. Find related partner (customer)
    # 3. Find related invoice(s) if applicable
    # 4. Determine payment method/journal
    # 5. Prepare Odoo payment payload
    # 6. Check if payment exists (e.g., using a custom QB TxnID field on account.payment)
    # 7. Create or update Odoo payment
    # 8. Potentially reconcile with invoice(s)
    return None

def create_or_update_odoo_sales_order(qb_sales_order_data: Dict[str, Any]) -> Optional[int]:
    """
    Placeholder for creating or updating an Odoo sales order from QuickBooks sales order data.
    This function needs to be fully implemented.
    """
    logger.info(f"Placeholder: Processing QB Sales Order: {qb_sales_order_data}")
    # TODO: Implement full logic for sales order creation/update
    # 1. Load sales order mapping from field_mapping.json
    # 2. Find related partner (customer)
    # 3. Prepare Odoo sales order payload (header and lines)
    #    - Map products, quantities, prices
    #    - Handle taxes, shipping, etc.
    # 4. Check if sales order exists (e.g., using a custom QB TxnID field on sale.order)
    # 5. Create or update Odoo sales order
    return None

def create_or_update_odoo_bill(qb_bill_data: Dict[str, Any]) -> Optional[int]:
    """
    Placeholder for creating or updating an Odoo bill (vendor bill) from QuickBooks bill data.
    This function needs to be fully implemented.
    """
    logger.info(f"Placeholder: Processing QB Bill: {qb_bill_data}")
    # TODO: Implement full logic for bill creation/update
    # 1. Load bill mapping from field_mapping.json
    # 2. Find related partner (vendor)
    # 3. Prepare Odoo bill payload (header and lines)
    #    - Map products/expense accounts, quantities, prices
    #    - Handle taxes, payment terms
    # 4. Check if bill exists (e.g., using a custom QB TxnID field on account.move)
    # 5. Create or update Odoo bill (move_type='in_invoice')
    return None

def create_or_update_odoo_purchase_order(qb_purchase_order_data: Dict[str, Any]) -> Optional[int]:
    """
    Placeholder for creating or updating an Odoo purchase order from QuickBooks purchase order data.
    This function needs to be fully implemented.
    """
    logger.info(f"Placeholder: Processing QB Purchase Order: {qb_purchase_order_data}")
    # TODO: Implement full logic for purchase order creation/update
    # 1. Load purchase order mapping from field_mapping.json
    # 2. Find related partner (vendor)
    # 3. Prepare Odoo purchase order payload (header and lines)
    #    - Map products, quantities, prices
    #    - Handle taxes, shipping terms
    # 4. Check if purchase order exists (e.g., using a custom QB TxnID field on purchase.order)
    # 5. Create or update Odoo purchase order
    return None

def create_or_update_odoo_journal_entry(qb_journal_entry_data):
    logger.info("Placeholder: create_or_update_odoo_journal_entry called")
    # TODO: Implement actual logic
    return None

def create_or_update_odoo_credit_memo(qb_credit_memo_data: Dict[str, Any]) -> Optional[int]:
    """
    Creates or updates a credit memo in Odoo from QuickBooks data using field_mapping.json.
    Credit Memos are 'out_refund' in Odoo.
    """
    logger.info(f"Processing QB Credit Memo: Ref {qb_credit_memo_data.get('ref_number')}, Customer: {qb_credit_memo_data.get('customer_name')}, TxnID: {qb_credit_memo_data.get('qb_txn_id')}")
    logger.debug(f"Full QB Credit Memo data: {qb_credit_memo_data}")

    credit_memo_mapping = FIELD_MAPPING.get("entities", {}).get("CreditMemos")
    if not credit_memo_mapping:
        logger.error("Credit Memo mapping not found in field_mapping.json. Cannot process credit memo.")
        return None

    # Ensure customer (partner) exists
    customer_name = qb_credit_memo_data.get("customer_name")
    if not customer_name:
        logger.error("Customer name missing from QB credit memo data.")
        return None
    
    odoo_partner_id = ensure_partner_exists(name=customer_name, is_customer=True, is_supplier=False)
    if not odoo_partner_id:
        logger.error(f"Failed to ensure Odoo partner for customer: {customer_name}. Credit memo will be skipped. Please check Odoo partner creation logic and logs for details.")
        return None

    # Determine Odoo journal (typically the same sales journal as invoices)
    default_journal_name = credit_memo_mapping.get("default_values", {}).get("journal_name", "Customer Invoices") # Or a specific credit note journal
    sales_journal_id = ensure_journal_exists(default_journal_name, journal_type_list=['sale'])
    if not sales_journal_id:
        logger.warning(f"Default sales/credit journal '{default_journal_name}' not found. Trying to find any sales journal.")
        journals = _odoo_rpc_call(
            "account.journal",
            "search_read",
            args_list=[[('type', '=', 'sale')]], # Corrected line
            kwargs_dict={"fields": ["id", "name"], "limit": 1}
        )
        if journals:
            sales_journal_id = journals[0]["id"]
            logger.info(f"Found sales journal '{journals[0].get('name', 'ID: '+str(sales_journal_id))}' to use for credit memo.")
        else:
            logger.error(f"Sales journal for credit memos not found in Odoo. Cannot create credit memo.")
            return None
    # Prepare credit memo lines
    credit_memo_lines_for_odoo = []
    for qb_line in qb_credit_memo_data.get("lines", []):
        product_id = None
        item_name = qb_line.get("item_name") # QBD Item Name (might be FullName)
        
        if item_name:
            # Attempt to find product by name (or default_code if mapping implies that)
            product_id = ensure_product_exists(model_code=item_name, description=qb_line.get("description", item_name))
            if not product_id:
                logger.warning(f"Could not ensure Odoo product for QB item '{item_name}'. Line description: '{qb_line.get('description')}'. Credit memo line may be incomplete or use a generic product.")
                # TODO: Fallback to a generic "Sales" product or similar if configured

        # Determine account for the line. This is crucial.
        # Priority: 1. QB Line Account, 2. Item's Income Account (from QB, mapped), 3. Default Sales/Income Account
        line_account_name_qb = qb_line.get("account_name") # If QB provides account at line level (e.g. for non-item lines)
        odoo_line_account_id = None

        if line_account_name_qb:
            odoo_line_account_id = ensure_account_exists(line_account_name_qb, account_type_hint="income")
        elif product_id: # If product exists, try to get its income account from Odoo product.template
            product_template_info = _odoo_rpc_call(
                "product.product", "read", args_list=[product_id], kwargs_dict={"fields": ["property_account_income_id", "product_tmpl_id"]}
            )
            if product_template_info and product_template_info[0].get("property_account_income_id"):
                odoo_line_account_id = product_template_info[0]["property_account_income_id"][0] # It's a tuple (id, name)
            elif product_template_info and product_template_info[0].get("product_tmpl_id"): # Check template
                 template_id = product_template_info[0]["product_tmpl_id"][0]
                 template_info_full = _odoo_rpc_call(
                    "product.template", "read", args_list=[template_id], kwargs_dict={"fields": ["property_account_income_id"]}
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
            logger.error(f"Failed to determine or create income account for credit memo line: '{qb_line.get('description', item_name)}'. Skipping line.")
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

        credit_memo_lines_for_odoo.append((0, 0, line_data))

    if not credit_memo_lines_for_odoo and qb_credit_memo_data.get("lines"): # Only warn if there were lines to process
        logger.warning(f"No lines could be processed for QB Credit Memo Ref {qb_credit_memo_data.get('ref_number')}. Credit Memo will not be created/updated if it has no lines.")
        # Depending on Odoo rules, a credit memo with no lines might not be allowed.
        # For now, we'll let it try, Odoo will reject if invalid.

    # Prepare Odoo credit memo payload using field_mapping.json
    odoo_credit_memo_payload = {
        "move_type": credit_memo_mapping.get("default_values", {}).get("move_type", "out_refund"),
        "partner_id": odoo_partner_id,
        "journal_id": sales_journal_id,
        "invoice_line_ids": credit_memo_lines_for_odoo,
        "x_qb_txn_id": qb_credit_memo_data.get("qb_txn_id") 
    }

    # Map fields from qb_credit_memo_data to odoo_credit_memo_payload based on field_mapping
    for mapping_item in credit_memo_mapping.get("fields", []):
        qbd_field_name = mapping_item["qbd_field"]
        odoo_field_name = mapping_item["odoo_field"]

        if qbd_field_name in qb_credit_memo_data:
            value = qb_credit_memo_data[qbd_field_name]
            # Basic transformations can be added here if needed (e.g., date formatting)
            if "date" in odoo_field_name and isinstance(value, str): # Ensure date format if necessary
                try:
                    # Assuming QB dates are YYYY-MM-DD. If not, parse and reformat.
                    datetime.strptime(value, "%Y-%m-%d") 
                except ValueError:
                    logger.warning(f"Date field {qbd_field_name} ('{value}') is not in YYYY-MM-DD format. Odoo might reject.")
               
            elif odoo_field_name not in ["partner_id", "journal_id", "invoice_line_ids", "move_type", "x_qb_txn_id"]:
                odoo_credit_memo_payload[odoo_field_name] = value

    # Search for existing credit memo in Odoo using QB TxnID
    existing_credit_memo_id = None

    if qb_credit_memo_data.get("qb_txn_id"):
        logger.info(f"Searching for existing Odoo credit memo with x_qb_txn_id: {qb_credit_memo_data.get('qb_txn_id')}")
        existing_credit_memos = _odoo_rpc_call(
            model="account.move",
            method="search_read",
            args_list=[[('x_qb_txn_id', '=', qb_credit_memo_data.get('qb_txn_id')), ('move_type', '=', 'out_refund')]],
            kwargs_dict={"fields": ["id"], "limit": 1}

        )

        if existing_credit_memos:
            existing_credit_memo_id = existing_credit_memos[0]["id"]
            logger.info(f"Found existing Odoo credit memo ID: {existing_credit_memo_id} for QB TxnID: {qb_credit_memo_data.get('qb_txn_id')}")

    if existing_credit_memo_id:
        update_payload = {k: v for k, v in odoo_credit_memo_payload.items() if k != "move_type"} # move_type cannot be changed

        # For lines, to replace all:
        if "invoice_line_ids" in update_payload:
            update_payload["invoice_line_ids"] = [(5, 0, 0)] + credit_memo_lines_for_odoo

        logger.info(f"Attempting to update Odoo credit memo ID: {existing_credit_memo_id}")
        logger.debug(f"Odoo Credit Memo Update Payload: {update_payload}")
        success = _odoo_rpc_call(
            model="account.move",
            method="write",
            args_list=[[existing_credit_memo_id], update_payload]
        )
        if success:
            logger.info(f"Successfully updated Odoo credit memo ID: {existing_credit_memo_id}")
            return existing_credit_memo_id
        else:
            logger.error(f"Failed to update Odoo credit memo ID: {existing_credit_memo_id}")
            return None
    else:
        # Create new credit memo
        logger.info("Attempting to create new Odoo credit memo.")
        logger.debug(f"Odoo Credit Memo Create Payload: {odoo_credit_memo_payload}")

        # Check if there are any lines, as Odoo might require lines for a credit memo
        if not credit_memo_lines_for_odoo and qb_credit_memo_data.get("lines"): # If QB had lines but we processed none
            logger.error(f"No processable lines for new QB Credit Memo Ref {qb_credit_memo_data.get('ref_number')}. Creation aborted.")
            return None
        if not odoo_credit_memo_payload.get("invoice_line_ids"): # If payload has no lines at all
            logger.warning(f"Creating credit memo {qb_credit_memo_data.get('ref_number')} with no lines. Odoo may reject this.")

        new_credit_memo_id = _odoo_rpc_call(
            model="account.move",
            method="create",
            args_list=[odoo_credit_memo_payload]
        )
        if new_credit_memo_id:
            logger.info(f"Successfully created Odoo credit memo with ID: {new_credit_memo_id} for QB TxnID: {qb_credit_memo_data.get('qb_txn_id')}")
            # Post the newly created credit memo
            _odoo_rpc_call(model="account.move", method="action_post", args=[[new_credit_memo_id]])
            logger.info(f"Posted newly created credit memo {new_credit_memo_id}")
            return new_credit_memo_id
        else:
            logger.error(f"Failed to create Odoo credit memo for QB Ref: {qb_credit_memo_data.get('ref_number')}")
            return None
