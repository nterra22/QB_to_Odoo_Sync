"""
Main entry point for the QB PostgreSQL Sync application.

This script initializes the Flask application with the QBWC service
for extracting QuickBooks inventory to a master PostgreSQL database.
"""
import logging
import sys
import os

# Add the current directory and SD Master Database to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '2_SD_Master_Database'))

from app import create_app

# Configuration values
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5000  # Port to match .qwc file configuration
FLASK_DEBUG = True

def main():
    """Main application entry point."""
    try:
        # Create the output directory if it doesn't exist
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '2_SD_Master_Database')
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Create the Flask app instance using the factory
        flask_app = create_app()
          # Get logger after app creation (logging is set up in create_app)
        logger = logging.getLogger("qb_postgres_sync")
        
        logger.info("=" * 60)
        logger.info("QuickBooks → PostgreSQL Sync Service Starting")
        logger.info("=" * 60)
        logger.info(f"QBWC Service URL: http://{SERVER_HOST}:{SERVER_PORT}/quickbooks")
        logger.info(f"Flask DEBUG mode: {FLASK_DEBUG}")
        logger.info("This service extracts QB inventory to PostgreSQL database")
        logger.info("=" * 60)

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