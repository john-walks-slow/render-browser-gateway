# browser-gateway

Free-tier browser capability for AI Agents, running Lightpanda on Render
(`free` plan, Singapore). Single public port serves three things:

| Endpoint | Auth | Use |
|---|---|---|
| `GET /health` | none | Render health check |
| `POST /fetch` | token | `{url, format}` → page content (`markdown`/`text`/`html`/`semantic_tree_text`) |
| `ALL /mcp` | token | Streamable-HTTP MCP → full browser tools (navigate/click/type/extract) |

Auth: `?token=`, `Authorization: Bearer`, or `X-Token` header.

## REST example

```bash
curl -s -X POST https://<svc>.onrender.com/fetch?token=$BROWSER_TOKEN \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","format":"markdown"}'
```

## MCP example (any MCP client)

```json
{
  "mcpServers": {
    "browser": {
      "type": "streamable-http",
      "url": "https://<svc>.onrender.com/mcp?token=$BROWSER_TOKEN"
    }
  }
}
```

## Limits (free tier)

- 512MB RAM / 0.1 CPU: requests are serialized, one at a time.
- Free services sleep after 15 min idle (~1 min cold start).
- No screenshots / persistent login (Lightpanda text engine).
- Datacenter IP: weak against reCAPTCHA / bot walls.
