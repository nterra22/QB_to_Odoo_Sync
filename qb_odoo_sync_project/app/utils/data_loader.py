"""
Data loading utilities for QB Odoo Sync application.

Handles loading and managing account crosswalk data and other configuration files.
"""
import json
import os
from pathlib import Path
from ..logging_config import logger

# Hardcoded path for the account crosswalk file
ACCOUNT_CROSSWALK_FILE_PATH = "../data/account_crosswalk.json"
FIELD_MAPPING_FILE_PATH = "../data/field_mapping.json" # Added for field mapping

# Global variable to cache crosswalk data
_account_crosswalk_data = None
_field_mapping_data = None # Added for field mapping

def load_account_crosswalk():
    """Load account crosswalk data from JSON file."""
    global _account_crosswalk_data
    
    try:
        # Convert to Path object for better handling
        crosswalk_path = Path(ACCOUNT_CROSSWALK_FILE_PATH)
        data_dir = crosswalk_path.parent
        
        # Ensure the DATA_DIR exists
        data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Data directory ensured: {data_dir}")

        # If the crosswalk file doesn't exist, create an empty one
        if not crosswalk_path.exists():
            logger.warning(f"Account crosswalk file not found at {crosswalk_path}. Creating an empty one.")
            with crosswalk_path.open('w', encoding='utf-8') as f:
                json.dump({}, f, indent=2)
            _account_crosswalk_data = {}
            return

        with crosswalk_path.open('r', encoding='utf-8') as f:
            _account_crosswalk_data = json.load(f)
        
        logger.info(f"Successfully loaded {len(_account_crosswalk_data)} account mappings from {crosswalk_path}")
        
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {ACCOUNT_CROSSWALK_FILE_PATH}: {e}")
        _account_crosswalk_data = {}
    except Exception as e:
        logger.error(f"Unexpected error loading account crosswalk: {e}", exc_info=True)
        _account_crosswalk_data = {}

def get_account_map(qb_account_full_name):
    """
    Get account mapping for a QuickBooks account.
    
    Args:
        qb_account_full_name (str): Full name of the QuickBooks account
        
    Returns:
        dict or None: Account mapping data or None if not found
    """
    if _account_crosswalk_data is None:
        load_account_crosswalk()
    
    return _account_crosswalk_data.get(qb_account_full_name)

def reload_account_crosswalk():
    """Force reload of account crosswalk data."""
    global _account_crosswalk_data
    _account_crosswalk_data = None
    load_account_crosswalk()

# Added functions for field mapping
def load_field_mapping():
    """Load field mapping data from JSON file."""
    global _field_mapping_data
    
    try:
        mapping_path = Path(FIELD_MAPPING_FILE_PATH)
        data_dir = mapping_path.parent
        
        data_dir.mkdir(parents=True, exist_ok=True) # Ensure data directory exists

        if not mapping_path.exists():
            logger.warning(f"Field mapping file not found at {mapping_path}. Creating an empty one.")
            with mapping_path.open('w', encoding='utf-8') as f:
                json.dump({}, f, indent=2)
            _field_mapping_data = {}
            return

        with mapping_path.open('r', encoding='utf-8') as f:
            _field_mapping_data = json.load(f)
        
        logger.info(f"Successfully loaded field mapping from {mapping_path}")
        
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {FIELD_MAPPING_FILE_PATH}: {e}")
        _field_mapping_data = {}
    except Exception as e:
        logger.error(f"Unexpected error loading field mapping: {e}", exc_info=True)
        _field_mapping_data = {}

def get_field_mapping(entity_name: str):
    """
    Get field mapping for a specific entity.
    
    Args:
        entity_name (str): Name of the entity (e.g., "Customers", "Invoices")
        
    Returns:
        dict or None: Field mapping data for the entity or None if not found
    """
    if _field_mapping_data is None:
        load_field_mapping()
    
    return _field_mapping_data.get("entities", {}).get(entity_name)

def reload_field_mapping():
    """Force reload of field mapping data."""
    global _field_mapping_data
    _field_mapping_data = None
    load_field_mapping()

# Load data on module import
load_account_crosswalk()
load_field_mapping() # Added to load field mappings on import
