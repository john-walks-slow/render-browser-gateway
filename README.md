# browser-gateway

Free-tier browser capability for AI Agents, running Lightpanda on Render
(`free` plan, Singapore). Single public port serves three things:

| Endpoint | Auth | Use |
|---|---|---|
| `GET /health` | none | Render health check |
| `POST /fetch` | token | `{url, format}` → page content (`markdown`/`text`/`html`/`semantic_tree_text`) |
| `ALL /mcp` | token | Streamable-HTTP MCP → full browser tools (navigate/click/type/extract) |
| `GET /json/*`, `PUT /json/new`, `WS /devtools/*` | token (`?token=`) | Raw CDP passthrough (Playwright `connectOverCDP`, Puppeteer) |

Auth: `?token=`, `Authorization: Bearer`, or `X-Token` header.

## REST example

```bash
curl -s -X POST https://<svc>.onrender.com/fetch?token=$BROWSER_TOKEN \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","format":"markdown"}'
# => {"url":..., "format":"markdown", "http_status":200, "content":"..."}
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

## CDP example (Playwright / Puppeteer)

Browser-level WebSocket lives at `/` (token in query):

```js
import { chromium } from 'playwright-core';
const browser = await chromium.connectOverCDP(
  'wss://<svc>.onrender.com/?token=' + TOKEN);
const page = await (await browser.newContext()).newPage();
await page.goto('https://example.com');
```

`GET /json/version` and `GET /json/list` (same token) work for discovery;
`PUT /json/new` is not implemented by Lightpanda — create targets over WS
(`Target.createTarget`) instead.

## Limits (free tier)

- 512MB RAM / 0.1 CPU: requests are serialized, one at a time.
- Free services sleep after 15 min idle (~1 min cold start).
- No screenshots / persistent login (Lightpanda text engine).
- Datacenter IP: weak against reCAPTCHA / bot walls.
