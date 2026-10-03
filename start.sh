#!/bin/sh
# Runs lightpanda MCP (internal) + public gateway (foreground).
lightpanda mcp --port 8899 --host 127.0.0.1 &
exec python3 /app/gateway.py
