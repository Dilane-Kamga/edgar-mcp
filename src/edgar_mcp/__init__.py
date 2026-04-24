from __future__ import annotations

import os
import sys


def main() -> None:
    if not os.environ.get("EDGAR_MCP_CONTACT"):
        print(
            "Error: EDGAR_MCP_CONTACT env var is required.\n"
            "Set it to an email the SEC can reach you at.",
            file=sys.stderr,
        )
        sys.exit(1)
    from .server import mcp

    mcp.run()
