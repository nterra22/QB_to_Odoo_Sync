'''
Minimal Odoo Connection Test Script
'''
import xmlrpc.client
import ssl

# --- CONFIGURATION - REPLACE WITH YOUR ACTUAL ODOO DETAILS ---
ODOO_URL = "https://nterra22-sounddecision-odoo-develop-20178686.dev.odoo.com"  # e.g., "https://your-staging-1234567.dev.odoo.com"
ODOO_DB = "nterra22-sounddecision-odoo-develop-20178686"          # e.g., "your-staging-1234567-master" or your specific DB name
ODOO_USERNAME = "it@wadic.net" # Often your email or a dedicated API user
ODOO_API_KEY = "e8188dcec4b36dbc1e89e4da17b989c7aae8e568" # This is the API key or password for the Odoo user
# --- END CONFIGURATION ---

def test_odoo_connection():
    """
    Tests the connection to Odoo and fetches a few partner names.
    """
    print(f"Attempting to connect to Odoo at {ODOO_URL}, DB: {ODOO_DB}")

    try:
        # For Odoo.sh or other HTTPS URLs, SSL context might be needed if default verification fails.
        # Python 3.6+ usually handles this well, but older versions or specific setups might need unverified context.
        # Use with caution: ssl._create_unverified_context() bypasses SSL certificate verification.
        # context = ssl._create_unverified_context()
        # common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common', context=context)
        common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
        
        version_info = common.version()
        print(f"Successfully connected to Odoo Common RPC. Server version: {version_info}")

        # Authenticate and get UID
        # uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_API_KEY, {})
        # For Odoo.sh with API keys, sometimes the username is the db name or a specific format,
        # and the password is the API key. Refer to your Odoo.sh or Odoo admin panel for API key usage.
        uid = common.login(ODOO_DB, ODOO_USERNAME, ODOO_API_KEY)

        if uid:
            print(f"Authentication successful. UID: {uid}")
        else:
            print("Authentication failed. No UID returned. Check DB, Username, and API Key.")
            # Try legacy authenticate method if login fails, though login is preferred for Odoo 9+
            print("Trying legacy authenticate method...")
            uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_API_KEY, {})
            if uid:
                print(f"Legacy authentication successful. UID: {uid}")
            else:
                print("Legacy authentication also failed.")
                return

        # Connect to the object endpoint
        # models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object', context=context)
        models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object')

        # Perform a simple read operation (e.g., list first 5 partners)
        print("Attempting to read partner data...")
        partner_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'res.partner', 'search',
            [[]],  # Domain (empty for all)
            {'limit': 5} # Options
        )

        if partner_ids:
            print(f"Found partner IDs: {partner_ids}")
            partners = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'res.partner', 'read',
                [partner_ids], 
                {'fields': ['name', 'email']}
            )
            print("\nSuccessfully fetched partners:")
            for partner in partners:
                print(f"- ID: {partner.get('id')}, Name: {partner.get('name')}, Email: {partner.get('email')}")
        else:
            print("No partners found or unable to read partner data.")

    except xmlrpc.client.ProtocolError as pe:
        print(f"XML-RPC Protocol Error: {pe}")
        print("This might indicate an issue with the URL (e.g., HTTP vs HTTPS, wrong path) or server-side problems.")
        print(f"URL attempted: {pe.url}, HTTP status code: {pe.errcode}, Error message: {pe.errmsg}")
    except xmlrpc.client.Fault as f:
        print(f"XML-RPC Fault: {f.faultCode} - {f.faultString}")
        print("This is an error reported by the Odoo server (e.g., authentication failure, access rights).")
    except ConnectionRefusedError:
        print(f"Connection Refused: Could not connect to {ODOO_URL}. Check if the Odoo server is running and accessible.")
    except ssl.SSLCertVerificationError as sve:
        print(f"SSL Certificate Verification Error: {sve}")
        print("The SSL certificate of the Odoo server could not be verified.")
        print("If you are using a self-signed certificate or Odoo.sh with a custom domain that's not fully set up,")
        print("you might need to adjust SSL settings or ensure your system trusts the certificate.")
        print("For testing with Odoo.sh, ensure the URL is exactly as provided by Odoo.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        print(f"Error type: {type(e)}")

if __name__ == "__main__":
    test_odoo_connection()

print("\nScript finished. If you see partner names above, the connection was successful.")
print("If you see errors, please check your ODOO_URL, ODOO_DB, ODOO_USERNAME, and ODOO_API_KEY values in this script.")
