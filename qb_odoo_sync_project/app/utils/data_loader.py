"""
Data loading utilities for QB Odoo Sync application.

Handles loading and managing account crosswalk data and other configuration files.
"""
import json
from pathlib import Path
from ..logging_config import logger

# Define the base directory for qb_odoo_sync_project and the data directory
# __file__ is the path to the current file (data_loader.py)
# .resolve() makes it an absolute path
# .parent gives the directory of the current file (app/utils)
# .parent.parent gives the directory of the 'app' folder (app)
# .parent.parent.parent gives the root of the 'qb_odoo_sync_project'
BASE_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_PROJECT_DIR / "data"
SYNC_CACHE_FILE = DATA_DIR / "sync_cache.json" # Path for the sync cache file

# Global variables to cache data
_account_crosswalk_data = None
_field_mapping_data = None
_sync_cache_data = None # Cache for sync timestamps

def load_account_crosswalk():
    """Load account crosswalk data from JSON file. Returns cached data if available."""
    global _account_crosswalk_data
    # Return cached data if already loaded
    if _account_crosswalk_data is not None:
        return _account_crosswalk_data
    
    crosswalk_path = DATA_DIR / "account_crosswalk.json"
    logger.debug(f"Attempting to load account crosswalk from: {crosswalk_path}")
    
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        if not crosswalk_path.exists():
            logger.warning(f"Account crosswalk file not found at {crosswalk_path}. Creating an empty one.")
            with crosswalk_path.open('w', encoding='utf-8') as f:
                json.dump({}, f, indent=2)
            _account_crosswalk_data = {}
            return _account_crosswalk_data

        with crosswalk_path.open('r', encoding='utf-8') as f:
            loaded_data = json.load(f)
        
        _account_crosswalk_data = loaded_data
        logger.info(f"Successfully loaded {len(_account_crosswalk_data)} account mappings from {crosswalk_path}")
        return _account_crosswalk_data
        
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {crosswalk_path}: {e}")
        _account_crosswalk_data = {}
        return _account_crosswalk_data
    except Exception as e:
        logger.error(f"Unexpected error loading account crosswalk from {crosswalk_path}: {e}", exc_info=True)
        _account_crosswalk_data = {}
        return _account_crosswalk_data

def load_field_mapping():
    """Load field mapping data from JSON file. Returns cached data if available."""
    global _field_mapping_data
    # Return cached data if already loaded
    if _field_mapping_data is not None:
        return _field_mapping_data
    
    mapping_path = DATA_DIR / "field_mapping.json"
    logger.debug(f"Attempting to load field mapping from: {mapping_path}")

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        if not mapping_path.exists():
            logger.warning(f"Field mapping file not found at {mapping_path}. Creating an empty one.")
            with mapping_path.open('w', encoding='utf-8') as f:
                json.dump({}, f, indent=2)
            _field_mapping_data = {}
            return _field_mapping_data

        with mapping_path.open('r', encoding='utf-8') as f:
            loaded_data = json.load(f)
        
        _field_mapping_data = loaded_data
        logger.info(f"Successfully loaded field mapping from {mapping_path}")
        return _field_mapping_data
        
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {mapping_path}: {e}")
        _field_mapping_data = {}
        return _field_mapping_data
    except Exception as e:
        logger.error(f"Unexpected error loading field mapping from {mapping_path}: {e}", exc_info=True)
        _field_mapping_data = {}
        return _field_mapping_data

# --- Sync Cache Functions ---

def load_sync_cache():
    """Load sync cache data from JSON file. Returns cached data if available."""
    global _sync_cache_data
    if _sync_cache_data is not None:
        return _sync_cache_data

    logger.debug(f"Attempting to load sync cache from: {SYNC_CACHE_FILE}")
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not SYNC_CACHE_FILE.exists():
            logger.warning(f"Sync cache file not found at {SYNC_CACHE_FILE}. Initializing an empty cache.")
            _sync_cache_data = {}
            with SYNC_CACHE_FILE.open('w', encoding='utf-8') as f:
                json.dump({}, f, indent=2)
            return _sync_cache_data

        with SYNC_CACHE_FILE.open('r', encoding='utf-8') as f:
            loaded_data = json.load(f)
        
        _sync_cache_data = loaded_data
        logger.info(f"Successfully loaded sync cache from {SYNC_CACHE_FILE}")
        return _sync_cache_data
        
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {SYNC_CACHE_FILE}: {e}")
        _sync_cache_data = {} # Initialize with empty cache on error
        return _sync_cache_data
    except Exception as e:
        logger.error(f"Unexpected error loading sync cache from {SYNC_CACHE_FILE}: {e}", exc_info=True)
        _sync_cache_data = {} # Initialize with empty cache on error
        return _sync_cache_data

def save_sync_cache():
    """Save the current sync cache data to JSON file."""
    global _sync_cache_data
    if _sync_cache_data is None:
        logger.warning("Sync cache is not loaded. Cannot save.")
        return

    logger.debug(f"Attempting to save sync cache to: {SYNC_CACHE_FILE}")
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True) # Ensure data directory exists
        with SYNC_CACHE_FILE.open('w', encoding='utf-8') as f:
            json.dump(_sync_cache_data, f, indent=2, sort_keys=True)
        logger.info(f"Successfully saved sync cache to {SYNC_CACHE_FILE}")
    except Exception as e:
        logger.error(f"Unexpected error saving sync cache to {SYNC_CACHE_FILE}: {e}", exc_info=True)

def get_sync_cache():
    """Returns the loaded sync cache data, loading it if necessary."""
    if _sync_cache_data is None:
        load_sync_cache()
    return _sync_cache_data

def update_sync_cache(record_type: str, record_id: str, timestamp: str):
    """
    Update the sync cache for a given record.

    Args:
        record_type (str): Type of the record (e.g., 'partner', 'invoice').
        record_id (str): Unique identifier for the record.
        timestamp (str): The modification timestamp (e.g., TimeModified).
    """
    cache = get_sync_cache() # Ensures cache is loaded
    if record_type not in cache:
        cache[record_type] = {}
    cache[record_type][record_id] = timestamp
    save_sync_cache()
    logger.debug(f"Updated sync cache for {record_type} ID {record_id} with timestamp {timestamp}")

def is_record_changed(record_type: str, record_id: str, current_timestamp: str) -> bool:
    """
    Check if the record's current timestamp is different from the cached one.

    Args:
        record_type (str): Type of the record.
        record_id (str): Unique identifier for the record.
        current_timestamp (str): The current modification timestamp of the record.

    Returns:
        bool: True if the record is new or changed, False otherwise.
    """
    cache = get_sync_cache()
    if record_type not in cache or record_id not in cache[record_type]:
        logger.debug(f"Record {record_type} ID {record_id} not found in cache. Considered new/changed.")
        return True # Record not in cache, so it's new or needs processing
    
    cached_timestamp = cache[record_type][record_id]
    changed = current_timestamp != cached_timestamp
    if changed:
        logger.debug(f"Record {record_type} ID {record_id} changed. Current: {current_timestamp}, Cached: {cached_timestamp}")
    else:
        logger.debug(f"Record {record_type} ID {record_id} unchanged. Timestamp: {current_timestamp}")
    return changed

# --- End Sync Cache Functions ---

def get_account_crosswalk_data():
    """Returns the loaded account crosswalk data, loading it if necessary."""
    if _account_crosswalk_data is None:
        load_account_crosswalk() # Ensures data is loaded and cached
    return _account_crosswalk_data

def get_account_map(qb_account_full_name):
    """
    Get account mapping for a QuickBooks account.
    
    Args:
        qb_account_full_name (str): Full name of the QuickBooks account
        
    Returns:
        dict or None: Account mapping data or None if not found
    """
    crosswalk_data = get_account_crosswalk_data()
    return crosswalk_data.get(qb_account_full_name) if isinstance(crosswalk_data, dict) else None

def reload_account_crosswalk():
    """Force reload of account crosswalk data."""
    global _account_crosswalk_data
    _account_crosswalk_data = None
    load_account_crosswalk() # This will reload and re-cache

def get_field_mapping():
    """Returns the loaded field mapping data, loading it if necessary."""
    if _field_mapping_data is None:
        load_field_mapping() # Ensures data is loaded and cached
    return _field_mapping_data

# Initialize data on import by calling the getters
# This ensures that any import-time access to the data is valid.
# get_account_crosswalk_data()
# get_field_mapping()
# Commenting out direct calls on import; loading will be triggered by first actual use.
# This can prevent issues if logger or other dependencies aren't fully set up at exact import time.
