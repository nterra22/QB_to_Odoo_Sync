#!/usr/bin/env python3
"""
Test script for the QB-Odoo Sync MCP Server

This script tests the core functionality of the MCP server
to ensure it's working properly.
"""

import sys
import os
import json
from datetime import datetime

# Add the current directory to path
sys.path.insert(0, os.path.dirname(__file__))

def test_imports():
    """Test that all required modules can be imported"""
    print("Testing imports...")
    
    try:
        from sync_wrapper import (
            get_odoo_invoices,
            get_odoo_partners,
            get_odoo_products,
            get_sync_status
        )
        print("✓ Sync wrapper functions imported successfully")
        return True
    except ImportError as e:
        print(f"✗ Failed to import sync wrapper: {e}")
        return False

def test_odoo_connection():
    """Test connection to Odoo"""
    print("\nTesting Odoo connection...")
    
    try:
        from sync_wrapper import get_sync_status
        status = get_sync_status()
        
        if status.get("odoo_connected"):
            print("✓ Odoo connection successful")
            return True
        else:
            print("✗ Odoo connection failed")
            print(f"Status: {status}")
            return False
    except Exception as e:
        print(f"✗ Error testing Odoo connection: {e}")
        return False

def test_qbxml_generation():
    """Test QBXML generation"""
    print("\nTesting QBXML generation...")
    
    try:
        # Add the main project to path
        project_dir = os.path.join(os.path.dirname(__file__), '..', 'qb_odoo_sync_project')
        sys.path.insert(0, project_dir)
        
        from app.utils.qbxml_builder import build_customer_add_qbxml
        
        # Test data
        test_customer = {
            'name': 'Test Customer',
            'is_company': True,
            'street': '123 Test St',
            'city': 'Test City',
            'zip': '12345'
        }
        
        qbxml = build_customer_add_qbxml(test_customer)
        
        if qbxml and '<CustomerAdd>' in qbxml:
            print("✓ QBXML generation successful")
            return True
        else:
            print("✗ QBXML generation failed")
            return False
    except Exception as e:
        print(f"✗ Error testing QBXML generation: {e}")
        return False

def test_data_retrieval():
    """Test data retrieval from Odoo"""
    print("\nTesting data retrieval...")
    
    try:
        from sync_wrapper import get_odoo_partners
        
        partners = get_odoo_partners(limit=1)
        
        if isinstance(partners, list):
            print(f"✓ Data retrieval successful - got {len(partners)} partners")
            return True
        else:
            print("✗ Data retrieval failed - invalid response")
            return False
    except Exception as e:
        print(f"✗ Error testing data retrieval: {e}")
        return False

def main():
    """Run all tests"""
    print("QB-Odoo Sync MCP Server Test Suite")
    print("=" * 40)
    
    tests = [
        test_imports,
        test_odoo_connection,
        test_qbxml_generation,
        test_data_retrieval
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    print("\n" + "=" * 40)
    print("Test Results:")
    print(f"✓ Passed: {sum(results)}")
    print(f"✗ Failed: {len(results) - sum(results)}")
    
    if all(results):
        print("\n🎉 All tests passed! MCP server should work correctly.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
