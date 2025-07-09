# 1. QBWC Sync Application

This folder contains the QuickBooks Web Connector (QBWC) service that extracts inventory data from QuickBooks and stores it in the SD Master Database.

## Purpose
- Connects to QuickBooks via QuickBooks Web Connector
- Extracts all inventory items with full details
- Stores data in SD Master Database with unique sync keys
- Provides comprehensive logging and error handling

## How to Run

1. **Prerequisites**
   - Ensure SD Master Database is set up (see `../2_SD_Master_Database/`)
   - Install dependencies: `pip install -r requirements.txt`

2. **Start the Service**
   ```bash
   python run.py
   ```

3. **Configure QuickBooks Web Connector**
   - Service URL: `http://localhost:8000/qbwc`
   - Username: `admin`
   - Password: `odoo123`

## Files
- `run.py` - Main application entry point
- `app/` - Flask application and QBWC service
- `logs/` - Application logs
- `test_qbwc.py` - Service testing utility
- `SoundDecisionSync.qwc` - QuickBooks Web Connector configuration

## Service Endpoints
- **SOAP Service**: `http://localhost:8000/qbwc`
- **WSDL**: `http://localhost:8000/qbwc?wsdl`
- **Health Check**: `http://localhost:8000/health`

## Process Flow
1. QBWC authenticates with service
2. Service requests inventory data from QuickBooks in batches
3. Each inventory item is processed and stored in SD Master Database
4. Unique `sync_key` is generated for each record
5. Sync operations are logged for tracking

## Configuration
Edit `app/services/qbwc_service.py` to modify:
- QBWC credentials
- Batch sizes
- Processing logic
