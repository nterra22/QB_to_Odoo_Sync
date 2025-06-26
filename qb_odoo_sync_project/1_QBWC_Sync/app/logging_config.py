"""
Logging configuration for QB Odoo Sync application.

Provides comprehensive logging with detailed debugging for SOAP interactions,
XML processing, and Odoo API calls.
"""
import logging
import os
from pathlib import Path

# Hardcoded log directory and file path
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_FILE_PATH = LOG_DIR / "qbwc_debug.log"

def setup_logging():
    """
    Set up comprehensive logging for the application.
    
    Creates both console and file handlers with detailed formatting
    to match the debugging capabilities of the original script.
    """
    # Create main logger
    logger = logging.getLogger('qb_odoo_sync')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Clear any existing handlers to prevent duplicates
    logger.handlers.clear()

    # Create log directory if it doesn't exist
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Console Handler with detailed formatting
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - CONSOLE - %(name)s - %(module)s - %(funcName)s - %(lineno)d - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File Handler with even more detailed formatting
    try:
        file_handler = logging.FileHandler(LOG_FILE_PATH, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - FILE - %(name)s - %(module)s - %(funcName)s - %(lineno)d - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        
        logger.info(f"File logging initialized. Debug messages will be written to {LOG_FILE_PATH}")
    except Exception as e:
        logger.error(f"Failed to initialize file logging to {LOG_FILE_PATH}: {e}", exc_info=True)
    
    # Set up child loggers for specific modules with more detailed debugging
    
    # SOAP patches logger - for XML processing debugging
    soap_logger = logging.getLogger('qb_odoo_sync.soap_patches')
    soap_logger.setLevel(logging.DEBUG)
    
    # QBWC service logger - for QB Web Connector interactions
    qbwc_logger = logging.getLogger('qb_odoo_sync.services.qbwc_service')
    qbwc_logger.setLevel(logging.DEBUG)
    
    # Odoo service logger - for Odoo API calls
    odoo_logger = logging.getLogger('qb_odoo_sync.services.odoo_service')
    odoo_logger.setLevel(logging.DEBUG)
    
    # Data loader logger - for crosswalk and configuration
    data_logger = logging.getLogger('qb_odoo_sync.utils.data_loader')
    data_logger.setLevel(logging.DEBUG)
    
    # Add request/response logging for debugging SOAP interactions
    spyne_logger = logging.getLogger('spyne.protocol.xml')
    spyne_logger.setLevel(logging.DEBUG)
    spyne_logger.addHandler(console_handler)
    spyne_logger.addHandler(file_handler if 'file_handler' in locals() else console_handler)
    
    return logger

# Initialize and get the logger instance for other modules to import
logger = setup_logging()
