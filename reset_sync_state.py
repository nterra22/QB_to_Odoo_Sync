import os
import shutil
from pathlib import Path

# Define paths relative to this script's location (project root)
PROJECT_ROOT = Path(__file__).resolve().parent
APP_DIR = PROJECT_ROOT / "qb_odoo_sync_project"
DATA_DIR = APP_DIR / "data"
LOG_DIR = APP_DIR / "logs" # Assuming logs are in qb_odoo_sync_project/logs

SYNC_CACHE_FILE = DATA_DIR / "sync_cache.json"
QBWC_DEBUG_LOG_FILE = LOG_DIR / "qbwc_debug.log"
QB_ODOO_SYNC_LOG_FILE = LOG_DIR / "qb_odoo_sync.log" # Main application log

def clear_file(file_path):
    """Safely deletes a file if it exists."""
    if file_path.exists():
        try:
            os.remove(file_path)
            print(f"Successfully deleted: {file_path}")
        except Exception as e:
            print(f"Error deleting {file_path}: {e}")
    else:
        print(f"File not found, skipping: {file_path}")

def main():
    print("--- Starting Fresh: Clearing Sync State for QB Odoo Sync ---")

    # 1. Clear sync cache file
    print("\nStep 1: Clearing application sync cache...")
    clear_file(SYNC_CACHE_FILE)

    # 2. Clear log files
    print("\nStep 2: Clearing log files...")
    clear_file(QBWC_DEBUG_LOG_FILE)
    clear_file(QB_ODOO_SYNC_LOG_FILE) # Clear the main log as well

    print("\n--- Python Application State Cleared ---")
    print("\nIMPORTANT: To ensure QuickBooks Web Connector also starts fresh, please perform the following manual steps:")
    print("1.  Close QuickBooks Desktop completely.")
    print("2.  Close the QuickBooks Web Connector application completely.")
    print("3.  Re-open QuickBooks Desktop and log into your company file.")
    print("4.  Re-open the QuickBooks Web Connector application.")
    print("5.  In QuickBooks Web Connector, select your application (e.g., 'QB Odoo Sync').")
    print("6.  It's recommended to run the sync manually first by clicking 'Update Selected'.")
    print("    Observe the QBWC logs and your application logs closely during this first run.")
    
    print("\nIf QBWC still seems to 'remember' old states (e.g., not sending all expected data):")
    print("  - As a more forceful step, you might need to remove your application from QBWC and then re-add the .qwc file.")
    print("    To do this in QBWC: Right-click your application -> 'Remove'. Then 'Add an application' and select your .qwc file.")
    print("    (Ensure you have a backup or know the location of your .qwc file).")
    print("  - This forces QBWC to treat the application as entirely new and should reset its internal state for your service.")

    print("\n--- Reset Script Finished ---")

if __name__ == "__main__":
    main()