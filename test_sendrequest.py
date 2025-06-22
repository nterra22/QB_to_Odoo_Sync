#!/usr/bin/env python3
"""
Test script to verify sendRequestXML SOAP method is properly defined.
"""
import requests

# SOAP endpoint URL
SOAP_URL = "http://localhost:5000/quickbooks"

def test_send_request_xml():
    """Test the sendRequestXML SOAP method."""
    soap_body = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" 
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
               xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <sendRequestXML xmlns="http://developer.intuit.com/">
      <ticket>test_ticket</ticket>
      <strHCPResponse>test_response</strHCPResponse>
      <strCompanyFileName>test.qbw</strCompanyFileName>
      <qbXMLCountry>US</qbXMLCountry>
      <qbXMLMajorVers>16</qbXMLMajorVers>
      <qbXMLMinorVers>0</qbXMLMinorVers>
    </sendRequestXML>
  </soap:Body>
</soap:Envelope>"""
    
    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'SOAPAction': 'http://developer.intuit.com/sendRequestXML'
    }
    
    try:
        response = requests.post(SOAP_URL, data=soap_body, headers=headers)
        print("=" * 60)
        print("SEND REQUEST XML TEST")
        print("=" * 60)
        print(f"Status Code: {response.status_code}")
        print("Response Body:")
        print(response.text)
        
        # Check if it's a schema validation fault
        if "SchemaValidationError" in response.text:
            print("❌ ERROR: Still getting schema validation error for sendRequestXML")
            return False
        elif "soap11env:Fault" in response.text and "No matching global declaration" in response.text:
            print("❌ ERROR: sendRequestXML method not properly defined in SOAP service")
            return False
        else:
            print("✅ SUCCESS: sendRequestXML method is properly defined!")
            return True
            
    except Exception as e:
        print(f"❌ ERROR: Exception occurred: {e}")
        return False

if __name__ == "__main__":
    print("Testing sendRequestXML SOAP method definition...")
    success = test_send_request_xml()
    
    if success:
        print("\n✅ sendRequestXML is now properly defined in the SOAP service!")
        print("QuickBooks Web Connector should now be able to call this method successfully.")
    else:
        print("\n❌ sendRequestXML still has issues with SOAP definition.")
