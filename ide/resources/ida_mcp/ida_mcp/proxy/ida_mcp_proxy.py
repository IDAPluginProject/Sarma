"""IDA MCP Proxy (coordinator client) - stdio transport entrypoint

MCP server using stdio transport, accessing multiple IDA instances through the coordinator.

Architecture
====================
proxy/
├── __init__.py           # module exports
├── _server.py            # shared FastMCP server (reused by stdio/HTTP)
├── lifecycle.py          # proxy-side lifecycle operations
├── register_tools.py     # centralized registration of all forwarded tools
├── ida_mcp_proxy.py      # stdio transport entrypoint (this file)
├── _http.py              # HTTP helpers
└── _state.py             # state management and instance selection

Usage
====================
Run directly: python ida_mcp_proxy.py
Or as module: python -m ida_mcp.proxy.ida_mcp_proxy
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any

if __package__ in {None, ""}:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from ida_mcp.proxy._server import server
else:
    from ._server import server


# ============================================================================
# Entrypoint - stdio transport
# ============================================================================

if __name__ == "__main__":
    import signal
    
    def _signal_handler(sig: int, frame: Any) -> None:
        """Graceful exit."""
        sys.exit(0)
    
    # register signal handler (Windows only supports SIGINT)
    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, _signal_handler)
    
    try:
        server.run(show_banner=False)
    except KeyboardInterrupt:
        pass  # silent exit
