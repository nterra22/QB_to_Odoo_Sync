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
        in_protocol=Soap11(validator='lxml'),
        out_protocol=Soap11()
    )

    # Create a WSGI application for Spyne
    spyne_wsgi_app = WsgiApplication(soap_app)    # Define the main SOAP endpoint at /quickbooks
    @flask_app.route("/quickbooks", methods=['POST', 'GET'])
    def qbwc_soap_endpoint():
        """Handle SOAP requests and WSDL generation for QBWC."""
        def start_response(status, headers, exc_info=None):
            pass

        response_iterable = spyne_wsgi_app(request.environ, start_response)
        response_data = b"".join(response_iterable)
        return Response(response_data, mimetype='text/xml')

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
    print("[INFO] Flask app created. /quickbooks POST and GET endpoint registered for Spyne.")
    print(f"[INFO] Flask URL Map: {flask_app.url_map}")
    return flask_app
