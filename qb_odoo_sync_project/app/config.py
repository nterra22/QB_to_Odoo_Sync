"""
Configuration module for QB Odoo Sync application.

Contains all configuration variables, paths, and environment variable mappings.
Follows best practices for secure configuration management.
"""
import os
from pathlib import Path

# Project Root Path - more robust path handling
PROJECT_ROOT = Path(__file__).parent.parent.absolute()

# Odoo Configuration
ODOO_URL = os.environ.get("ODOO_URL", "https://nterra-sounddecision-odoo.odoo.com")
ODOO_API_KEY = os.environ.get("ODOO_API_KEY", "c5f9aa88c5f89b4b8c61d36dda5f7ba106e3b703")
ODOO_DB_NAME = os.environ.get("ODOO_DB_NAME", "")  # Usually not needed for modern Odoo

# QBWC Configuration
QBWC_USERNAME = os.environ.get("QBWC_USERNAME", "admin")
QBWC_PASSWORD = os.environ.get("QBWC_PASSWORD", "odoo123")

# Server Configuration
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "5000"))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "True").lower() in ("true", "1", "yes")

# File Paths - using pathlib for better cross-platform compatibility
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE_NAME = "qbwc_debug.log"
LOG_FILE_PATH = LOG_DIR / LOG_FILE_NAME

DATA_DIR = PROJECT_ROOT / "data"
ACCOUNT_CROSSWALK_FILE_NAME = "account_crosswalk.json"
ACCOUNT_CROSSWALK_FILE_PATH = DATA_DIR / ACCOUNT_CROSSWALK_FILE_NAME

# SOAP Service Configuration
SOAP_PATH = "/quickbooks"  # The path where the SOAP service will be available

# Request Timeouts and Limits
ODOO_REQUEST_TIMEOUT = int(os.environ.get("ODOO_REQUEST_TIMEOUT", "30"))
MAX_JOURNAL_ENTRIES_PER_REQUEST = int(os.environ.get("MAX_JOURNAL_ENTRIES", "10"))
