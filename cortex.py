#!/usr/bin/env python3
"""
mojo-cortex entrypoint
Run any Cortex CLI command or start the Model Context Protocol (MCP) server:
  python cortex.py mcp
  python cortex.py status
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from cortex.cli import run_cli

if __name__ == "__main__":
    run_cli()
