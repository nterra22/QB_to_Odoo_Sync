#!/usr/bin/env python3
"""
Test script to verify SOAP methods are working correctly.
"""
import requests
import xml.etree.ElementTree as ET

# SOAP endpoint URL
SOAP_URL = "http://localhost:5000/quickbooks"

def test_server_version():
    """Test the serverVersion SOAP method."""
    soap_body = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" 
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
               xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <serverVersion xmlns="http://developer.intuit.com/"/>
  </soap:Body>
</soap:Envelope>"""
    
    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'SOAPAction': 'http://developer.intuit.com/serverVersion'
    }
    
    try:
        response = requests.post(SOAP_URL, data=soap_body, headers=headers)
        print("=" * 60)
        print("SERVER VERSION TEST")
        print("=" * 60)
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print("Response Body:")
        print(response.text)
        
        # Check if it's a fault
        if "soap11env:Fault" in response.text:
            print("❌ ERROR: Still getting SOAP fault for serverVersion")
            return False
        else:
            print("✅ SUCCESS: No SOAP fault for serverVersion")
            return True
            
    except Exception as e:
        print(f"❌ ERROR: Exception occurred: {e}")
        return False

def test_client_version():
    """Test the clientVersion SOAP method."""
    soap_body = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" 
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
               xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <clientVersion xmlns="http://developer.intuit.com/">
      <strVersion>33.0.10015.91</strVersion>
    </clientVersion>
  </soap:Body>
</soap:Envelope>"""
    
    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'SOAPAction': 'http://developer.intuit.com/clientVersion'
    }
    
    try:
        response = requests.post(SOAP_URL, data=soap_body, headers=headers)
        print("\n" + "=" * 60)
        print("CLIENT VERSION TEST")
        print("=" * 60)
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print("Response Body:")
        print(response.text)
        
        # Check if it's a fault
        if "soap11env:Fault" in response.text:
            print("❌ ERROR: Still getting SOAP fault for clientVersion")
            return False
        else:
            print("✅ SUCCESS: No SOAP fault for clientVersion")
            return True
            
    except Exception as e:
        print(f"❌ ERROR: Exception occurred: {e}")
        return False

if __name__ == "__main__":
    print("Testing SOAP service methods...")
    
    server_ok = test_server_version()
    client_ok = test_client_version()
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    if server_ok and client_ok:
        print("✅ ALL TESTS PASSED: SOAP service is working correctly!")
        print("QuickBooks Web Connector should now be able to proceed past version checks.")
    else:
        print("❌ SOME TESTS FAILED: SOAP service still has issues.")
        if not server_ok:
            print("  - serverVersion method failed")
        if not client_ok:
            print("  - clientVersion method failed")
