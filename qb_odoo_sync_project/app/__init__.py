"""
Flask application factory for QB Odoo Sync.

Creates and configures the Flask application with SOAP service integration.
"""
from flask import Flask, request, Response
from spyne import Application
from spyne.server.wsgi import WsgiApplication
from spyne.protocol.soap import Soap11

from .logging_config import setup_logging
from .services.qbwc_service import QBWCService
from .soap_patches import PatchedSoap11

def create_app():
    """
    Application factory function.
    
    Returns:
        Flask application instance
    """
    # Initialize logging first
    setup_logging()
    
    # Create Flask application
    flask_app = Flask(__name__)
    flask_app.config["DEBUG"] = True  # FLASK_DEBUG was True by default
    
    # Initialize Spyne SOAP application
    soap_app = Application(
        [QBWCService],
        tns='http://developer.intuit.com/',
        name='QBWC',
        in_protocol=PatchedSoap11(validator='lxml'),
        out_protocol=Soap11()
    )
    
    # Create WSGI application wrapper
    wsgi_app = WsgiApplication(soap_app)
    
    # Define the main SOAP endpoint
    @flask_app.route("/quickbooks", methods=['POST'])  # SOAP_PATH was '/quickbooks'
    def soap_endpoint():
        """Handle SOAP requests from QuickBooks Web Connector."""
        def start_response_wrapper(status, headers, exc_info=None):
            """WSGI start_response wrapper - handled by Flask Response."""
            pass
        
        # Get response from Spyne WSGI application
        response_iterable = wsgi_app(request.environ, start_response_wrapper)
        response_data = b"".join(response_iterable)
        
        return Response(response_data, mimetype='text/xml')
    
    # Add a GET endpoint for /quickbooks to confirm route registration
    @flask_app.route("/quickbooks", methods=['GET'])
    def quickbooks_get():
        return "QBWC SOAP endpoint is registered. Use POST for SOAP requests.", 200

    # Health check endpoint
    @flask_app.route('/health', methods=['GET'])
    def health_check():
        """Simple health check endpoint."""
        return {"status": "healthy", "service": "QB Odoo Sync"}, 200
    
    # Root endpoint with service info
    @flask_app.route('/', methods=['GET'])
    def service_info():
        """Provide basic service information."""
        return {
            "service": "QuickBooks Odoo Sync Server",
            "soap_endpoint": "/quickbooks",
            "status": "running"
        }, 200
    
    # Log startup
    print("[INFO] Flask app created. /quickbooks POST and GET endpoints registered.")
    return flask_app
