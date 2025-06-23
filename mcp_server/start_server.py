#!/usr/bin/env python3
"""
Startup script for the QB-Odoo Sync MCP Server

This script provides an easy way to start the MCP server with proper
error handling and environment setup.
"""

import sys
import os
import subprocess
from pathlib import Path

def main():
    """Main startup function"""
    
    # Get the directory containing this script
    script_dir = Path(__file__).parent
    server_script = script_dir / "server.py"
    
    # Add the main project to Python path
    project_dir = script_dir.parent / "qb_odoo_sync_project"
    
    if not server_script.exists():
        print(f"Error: Server script not found at {server_script}")
        sys.exit(1)
    
    if not project_dir.exists():
        print(f"Error: Project directory not found at {project_dir}")
        print("Make sure the QB Odoo Sync application is properly installed")
        sys.exit(1)
    
    # Set up environment
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH", "")
    if current_pythonpath:
        env["PYTHONPATH"] = f"{project_dir}{os.pathsep}{current_pythonpath}"
    else:
        env["PYTHONPATH"] = str(project_dir)
    
    print("Starting QB-Odoo Sync MCP Server...")
    print(f"Project directory: {project_dir}")
    print(f"Server script: {server_script}")
    print()
    print("The server will communicate via stdio. Connect your MCP client now.")
    print("Press Ctrl+C to stop the server.")
    print()
    
    try:
        # Run the server script
        result = subprocess.run(
            [sys.executable, str(server_script)],
            env=env,
            cwd=script_dir
        )
        sys.exit(result.returncode)
        
    except KeyboardInterrupt:
        print("\nServer stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nError starting server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
