# Getting Started with MCP Tools

The Model Context Protocol (MCP) provides a standardized way for AI assistants to access external data sources and tools.

## What is MCP?

MCP is an open protocol that enables secure, controlled interactions between AI systems and external resources like databases, APIs, and file systems.

## Key Features

- **Standardized Interface**: Consistent API across different data sources
- **Security**: Built-in authentication and authorization
- **Extensibility**: Easy to add new tools and data sources
- **Performance**: Optimized for real-time AI interactions

## Installation

```bash
pip install mcp-tools
```

## Basic Usage

```python
from mcp_tools import Client

client = Client()
results = client.search("documentation")
```

This will search across all configured MCP data sources and return relevant results.
