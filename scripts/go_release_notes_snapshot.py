#!/usr/bin/env python3
"""Export the latest stable Go release notes as a filesystem tenant."""

from docs_mcp_server.snapshots.go_release_notes import main


if __name__ == "__main__":
    main()
