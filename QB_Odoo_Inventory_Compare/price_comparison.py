import pandas as pd
from thefuzz import process
import datetime
import os

def load_and_clean_data():
    # Get the directory where this script is located
    base_dir = os.path.dirname(os.path.abspath(__file__))
    odoo_path = os.path.join(base_dir, 'Product (product.template).csv')
    qb_path = os.path.join(base_dir, 'QB_Products_Export_2025-07-08 - Copy2.csv')
    
    # Read the CSV files
    odoo_df = pd.read_csv(odoo_path)
    qb_df = pd.read_csv(qb_path)
    
    # Clean the data
    odoo_df['Internal Reference'] = odoo_df['Internal Reference'].fillna('').str.strip()
    qb_df['Item'] = qb_df['Item'].fillna('').str.strip()
    qb_df['Price'] = pd.to_numeric(qb_df['Price'], errors='coerce')
    
    return odoo_df, qb_df

def find_price_differences():
    odoo_df, qb_df = load_and_clean_data()
    differences = []
    total = len(odoo_df)
    print(f"Comparing {total} Odoo products against QB products...")

    # Prepare QB reference sets
    qb_df['MPN_clean'] = qb_df['MPN'].fillna('').astype(str).str.strip()
    qb_df['Item_after_colon'] = qb_df['Item'].apply(lambda x: x.split(':', 1)[1].strip() if isinstance(x, str) and ':' in x else '')

    for idx, odoo_row in odoo_df.iterrows():
        odoo_ref = str(odoo_row['Internal Reference']).strip()
        if not odoo_ref:
            continue
        if idx % 100 == 0 and idx > 0:
            print(f"Processed {idx} of {total} Odoo products...")
        match_found = False
        # 1. Exact match with MPN
        qb_mpn_matches = qb_df[qb_df['MPN_clean'] == odoo_ref]
        if not qb_mpn_matches.empty:
            qb_row = qb_mpn_matches.iloc[0]
            match_found = True
            match_type = 'MPN'
            match_quality = 100
        else:
            # 2. Exact match with text after ':' in Item
            qb_item_matches = qb_df[qb_df['Item_after_colon'] == odoo_ref]
            if not qb_item_matches.empty:
                qb_row = qb_item_matches.iloc[0]
                match_found = True
                match_type = 'ItemAfterColon'
                match_quality = 100
        if match_found:
            qb_price = qb_row['Price']
            odoo_price = pd.to_numeric(odoo_row['Sales Price'], errors='coerce')
            if pd.notna(qb_price) and pd.notna(odoo_price) and qb_price != odoo_price:
                print(f"Match ({match_type}): {odoo_ref} <-> {qb_row['Item']} | Odoo: {odoo_price} | QB: {qb_price}")
                differences.append({
                    'Internal Reference': odoo_ref,
                    'Product Name': odoo_row['Name'],
                    'Odoo Price': odoo_price,
                    'QB Price': qb_price,
                    'Match Quality': f"{match_quality}% ({match_type})"
                })
    print(f"Finished comparing all products.")
    return pd.DataFrame(differences)

def generate_report():
    differences_df = find_price_differences()
    # Sort by Internal Reference for easier review
    differences_df = differences_df.sort_values('Internal Reference')
    # Generate the report
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    output_file = f'price_comparison_{today}.csv'
    differences_df.to_csv(output_file, index=False)
    # Print summary
    print(f"\nPrice comparison report generated: {output_file}")
    print(f"Found {len(differences_df)} matched products.")
    if len(differences_df) > 0:
        print(f"Sample match: {differences_df.iloc[0].to_dict()}")

if __name__ == "__main__":
    print("Starting price comparison analysis...")
    generate_report()
    print("\nAnalysis complete!")
