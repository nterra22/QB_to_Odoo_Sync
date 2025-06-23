@echo off
REM QB-Odoo Sync MCP Server Startup Script for Windows

echo Starting QB-Odoo Sync MCP Server...
echo.

REM Change to the script directory
cd /d "%~dp0"

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python and try again
    pause
    exit /b 1
)

REM Check if required files exist
if not exist "server.py" (
    echo Error: server.py not found in current directory
    pause
    exit /b 1
)

if not exist "..\qb_odoo_sync_project" (
    echo Error: QB Odoo Sync project not found
    echo Make sure the main application is properly installed
    pause
    exit /b 1
)

REM Start the server
echo Server starting... Press Ctrl+C to stop
echo.
python start_server.py

pause
