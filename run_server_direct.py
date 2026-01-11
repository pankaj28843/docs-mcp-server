#!/usr/bin/env python3
"""
Direct server runner for performance benchmarking.
Runs the MCP server directly without Docker for easier testing.
"""

from src.docs_mcp_server.app import main

if __name__ == "__main__":
    main()
