#!/usr/bin/env python3
"""
Test script to directly test invoice retrieval from Odoo.
"""
import sys
import os

# Add the current directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'qb_odoo_sync_project'))

from qb_odoo_sync_project.app.services.odoo_service import get_odoo_invoice_for_sync

def test_invoice_retrieval():
    """Test the invoice retrieval directly."""
    print("=" * 60)
    print("TESTING INVOICE RETRIEVAL FROM ODOO")
    print("=" * 60)
    
    try:
        print("Calling get_odoo_invoice_for_sync()...")
        invoice = get_odoo_invoice_for_sync()
        
        if invoice:
            print("✅ SUCCESS: Found invoice!")
            print(f"Invoice ID: {invoice.get('id')}")
            print(f"Invoice Name: {invoice.get('name')}")
            print(f"Invoice State: {invoice.get('state')}")
            print(f"Invoice Type: {invoice.get('move_type')}")
            print(f"Invoice Amount: {invoice.get('amount_total')}")
            print(f"Invoice Date: {invoice.get('invoice_date')}")
            print(f"Partner: {invoice.get('partner_id')}")
            print(f"x_qb_txn_id: {invoice.get('x_qb_txn_id')}")
            
            # Check invoice lines
            lines = invoice.get('invoice_line_details', [])
            print(f"Invoice Lines Count: {len(lines)}")
            for i, line in enumerate(lines):
                print(f"  Line {i+1}: {line.get('name')} - Qty: {line.get('quantity')} - Price: {line.get('price_unit')}")
        else:
            print("❌ ERROR: No invoice found!")
            print("This means the function returned None or empty.")
            
    except Exception as e:
        print(f"❌ ERROR: Exception occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_invoice_retrieval()
