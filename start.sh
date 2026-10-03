#!/bin/sh
# Runs lightpanda MCP (internal) + public gateway (foreground).
lightpanda mcp --port 8899 --host 127.0.0.1 &
lightpanda serve --host 127.0.0.1 --port 9222 --cdp-max-connections 4 &
exec python3 /app/gateway.py
