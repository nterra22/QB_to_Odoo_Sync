"""
Main entry point for the QB Odoo Sync application.

This script initializes the Flask application using the app factory pattern
and runs the development server.
"""
import logging
import sys
import os

# Add the current directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.config import ODOO_URL, ODOO_API_KEY, SERVER_HOST, SERVER_PORT, FLASK_DEBUG

def main():
    """Main application entry point."""
    try:
        # Create the Flask app instance using the factory
        flask_app = create_app()
        
        # Get logger after app creation (logging is set up in create_app)
        logger = logging.getLogger("qb_odoo_sync")
        
        logger.info(f"QuickBooks sync server starting on http://{SERVER_HOST}:{SERVER_PORT}/quickbooks")
        logger.info(f"Using Odoo URL: {ODOO_URL}")
        logger.info(f"Flask DEBUG mode: {FLASK_DEBUG}")
        
        # Security warning for production deployments
        if ODOO_API_KEY and (
            "your_odoo_api_key" in ODOO_API_KEY.lower() or 
            ODOO_API_KEY == "c5f9aa88c5f89b4b8c61d36dda5f7ba106e3b703"
        ):
            logger.warning(
                "WARNING: Using default/placeholder Odoo API Key. "
                "Set ODOO_API_KEY environment variable in production!"
            )
        
        # Run the Flask development server
        flask_app.run(
            host=SERVER_HOST, 
            port=SERVER_PORT, 
            debug=FLASK_DEBUG,
            use_reloader=FLASK_DEBUG  # Only use reloader in debug mode
        )
        
    except KeyboardInterrupt:
        logger.info("Server shutdown requested by user")
    except Exception as e:
        logger.error(f"Failed to start server: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()