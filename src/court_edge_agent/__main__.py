"""Entry point for running the MCP server as a module.

    python -m court_edge_agent.mcp_server   # preferred
    python -m court_edge_agent              # also works
"""

from court_edge_agent.mcp_server import mcp

mcp.run()
