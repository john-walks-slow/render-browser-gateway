#!/usr/bin/env python3
"""Public gateway for the Render free-tier browser service.

Single public PORT, three capabilities:
  GET  /health          -> {"ok": true}            (open, for Render checks)
  POST /fetch           -> {url, format} => page content (token required)
  ALL  /mcp...          -> proxied to `lightpanda mcp` (token required)

Auth: ?token= query, Authorization: Bearer, or X-Token header.
Only stdlib is used; lightpanda itself comes from pip.
"""
import http.client
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

TOKEN = os.environ.get("BROWSER_TOKEN", "")
MCP_HOST = "127.0.0.1"
MCP_PORT = int(os.environ.get("MCP_PORT", "8899"))
CDP_HOST = "127.0.0.1"
CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
FETCH_TIMEOUT = int(os.environ.get("FETCH_TIMEOUT", "120"))
MAX_BYTES = int(os.environ.get("DUMP_MAX_BYTES", "400000"))
FETCH_FORMATS = ("markdown", "text", "html", "semantic_tree_text")

fetch_lock = threading.Lock()


def authorized(h):
    if not TOKEN:
        return True
    q = parse_qs(urlparse(h.path).query)
    if q.get("token", [""])[0] == TOKEN:
        return True
    hdrs = h.headers
    if hdrs.get("Authorization", "") == "Bearer " + TOKEN:
        return True
    return hdrs.get("X-Token", "") == TOKEN


class H(BaseHTTPRequestHandler):
    server_version = "lp-gateway/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, obj):
        try:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = urlparse(self.path).path
        # WS upgrades take precedence: '/' is also the CDP browser endpoint.
        # (Health checks never send Upgrade.)
        if self.headers.get("Upgrade", "").lower() == "websocket":
            if not authorized(self):
                return self._send(401, {"error": "unauthorized"})
            return self._bridge_ws(path)
        if path in ("/health", "/healthz", "/"):
            return self._send(200, {"ok": True})
        if path == "/info":
            return self._send(200, {
                "service": "browser-gateway",
                "engine": "lightpanda",
                "endpoints": ["GET /health", "POST /fetch", "ALL /mcp"],
            })
        if path.startswith("/mcp"):
            if not authorized(self):
                return self._send(401, {"error": "unauthorized"})
            return self._proxy()
        # Anything else goes to the CDP server (incl. WS upgrades).
        if not authorized(self):
            return self._send(401, {"error": "unauthorized"})
        return self._proxy_cdp()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/fetch":
            if not authorized(self):
                return self._send(401, {"error": "unauthorized"})
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return self._send(400, {"error": "bad json body"})
            url = req.get("url", "")
            if not url.startswith(("http://", "https://")):
                return self._send(400, {"error": "url must start with http(s)://"})
            fmt = req.get("format", "markdown")
            if fmt not in FETCH_FORMATS:
                return self._send(400, {"error": "format must be one of %s" % (FETCH_FORMATS,)})
            with fetch_lock:
                try:
                    r = subprocess.run(
                        ["lightpanda", "fetch", url, "--dump", fmt,
                         "--dump-max-bytes", str(MAX_BYTES), "--json"],
                        capture_output=True, timeout=FETCH_TIMEOUT)
                except subprocess.TimeoutExpired:
                    return self._send(504, {"error": "fetch timeout"})
            try:
                data = json.loads(r.stdout or b"{}")
            except Exception:
                return self._send(502, {
                    "error": "browser failed",
                    "detail": (r.stderr or b"")[-500:].decode(errors="replace"),
                })
            if not isinstance(data, dict) or data.get("error"):
                return self._send(502, {"error": "browser failed", "detail": data})
            return self._send(200, {
                "url": url,
                "format": fmt,
                "http_status": data.get("http_status"),
                "content": data.get("content", ""),
            })
        if path.startswith("/mcp"):
            if not authorized(self):
                return self._send(401, {"error": "unauthorized"})
            return self._proxy()
        # Anything else goes to the CDP server (incl. WS upgrades).
        if not authorized(self):
            return self._send(401, {"error": "unauthorized"})
        return self._proxy_cdp()

    def do_PUT(self):
        # PUT /json/new etc. belong to CDP.
        if not authorized(self):
            return self._send(401, {"error": "unauthorized"})
        return self._proxy_cdp()

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/mcp"):
            if not authorized(self):
                return self._send(401, {"error": "unauthorized"})
            return self._proxy()
        # DELETE /json/close/<id> belongs to CDP.
        if not authorized(self):
            return self._send(401, {"error": "unauthorized"})
        return self._proxy_cdp()

    def _proxy(self):
        length = self.headers.get("Content-Length")
        body = self.rfile.read(int(length)) if length else None
        fwd = {k: v for k, v in self.headers.items()
               if k.lower() not in ("host", "content-length", "connection")}
        conn = http.client.HTTPConnection(MCP_HOST, MCP_PORT, timeout=150)
        try:
            conn.request(self.command, self.path, body=body, headers=fwd)
            resp = conn.getresponse()
            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() not in ("connection", "transfer-encoding", "content-length"):
                    self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            shutil.copyfileobj(resp, self.wfile)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._send(502, {"error": "mcp upstream failed: %s" % e})
        finally:
            conn.close()

    def _proxy_cdp(self):
        # Strip ?token= etc: the CDP backend must not see our auth query.
        target = urlparse(self.path).path
        if self.headers.get("Upgrade", "").lower() == "websocket":
            return self._bridge_ws(target)
        length = self.headers.get("Content-Length")
        body = self.rfile.read(int(length)) if length else None
        fwd = {k: v for k, v in self.headers.items()
               if k.lower() not in ("host", "content-length", "connection")}
        conn = http.client.HTTPConnection(CDP_HOST, CDP_PORT, timeout=60)
        try:
            conn.request(self.command, target, body=body, headers=fwd)
            resp = conn.getresponse()
            payload = resp.read()
            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() not in ("connection", "transfer-encoding", "content-length"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._send(502, {"error": "cdp upstream failed: %s" % e})
        finally:
            conn.close()

    def _bridge_ws(self, target):
        import base64
        import hashlib
        import os as _os
        import select
        import socket as _socket
        GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        ckey = self.headers.get("Sec-WebSocket-Key", "")
        if not ckey:
            return self._send(400, {"error": "missing Sec-WebSocket-Key"})
        # 1. Complete the handshake with OUR client first.
        accept = base64.b64encode(
            hashlib.sha1((ckey + GUID).encode()).digest()).decode()
        try:
            self.connection.sendall(
                ("HTTP/1.1 101 Switching Protocols\r\n"
                 "Upgrade: websocket\r\n"
                 "Connection: Upgrade\r\n"
                 "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode("latin-1"))
        except (BrokenPipeError, ConnectionResetError):
            return
        # 2. Open our own handshake to the CDP backend.
        try:
            backend = _socket.create_connection((CDP_HOST, CDP_PORT), timeout=15)
            bkey = base64.b64encode(_os.urandom(16)).decode()
            backend.sendall(
                ("GET %s HTTP/1.1\r\n"
                 "Host: %s:%d\r\n"
                 "Upgrade: websocket\r\n"
                 "Connection: Upgrade\r\n"
                 "Sec-WebSocket-Key: %s\r\n"
                 "Sec-WebSocket-Version: 13\r\n\r\n"
                 % (target, CDP_HOST, CDP_PORT, bkey)).encode("latin-1"))
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = backend.recv(4096)
                if not chunk:
                    raise ConnectionError("backend closed during handshake")
                head += chunk
            if b" 101 " not in head.split(b"\r\n", 1)[0]:
                raise ConnectionError("backend refused: %s" % head[:60])
        except Exception:
            try:
                backend.close()
            except Exception:
                pass
            return  # client already has its 101; just drop
        # 3. Opaque byte relay (WS frames pass through untouched).
        try:
            backend.setblocking(False)
            self.connection.setblocking(False)
            while True:
                r, _, _ = select.select([self.connection, backend], [], [], 300)
                if not r:
                    break
                for src in r:
                    dst = backend if src is self.connection else self.connection
                    try:
                        data = src.recv(65536)
                    except BlockingIOError:
                        continue
                    if not data:
                        raise ConnectionError("closed")
                    dst.sendall(data)
        except Exception:
            pass
        finally:
            try:
                backend.close()
            except Exception:
                pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    print("gateway listening on 0.0.0.0:%d" % port, flush=True)
    srv.serve_forever()
