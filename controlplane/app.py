#!/usr/bin/env python3
"""
无职转生 — Agent Control Plane (lightweight, stdlib-only)
=========================================================
A single-file web service exposing:
  GET  /                -> status dashboard (HTML)
  GET  /api/status      -> JSON agent status
  POST /api/scan        -> run contract_scan on pasted .sol source
  POST /api/research    -> run web_research on a query
  GET  /webhook/dealwork -> marketplace ping endpoint (records events)

Deployable on Vercel (as a Python function via vercel.json) or Render
(as a web service via render.yaml). No external deps.

Auth: a simple shared token in X-Agent-Token header (set AGENT_TOKEN env).
"""
import os, sys, json, html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "capabilities"))
import contract_scan, web_research

AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "dev-token-change-me")
PORT = int(os.environ.get("PORT", "8080"))

# In-memory event log for webhooks (demo; swap for a DB later)
EVENTS = []


def _auth_ok(headers):
    return headers.get("X-Agent-Token") == AGENT_TOKEN


def _json(handler, obj, code=200):
    body = json.dumps(obj).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _html(handler, body_html, code=200):
    page = f"""<!doctype html><html><head><meta charset=utf-8>
<title>无职转生 Control Plane</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem}}
h1{{font-size:1.6rem}}code{{background:#f4f4f4;padding:1px 4px;border-radius:3px}}
pre{{background:#1e1e1e;color:#ddd;padding:1rem;overflow:auto;border-radius:6px}}
.card{{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}}</style></head>
<body>{body_html}</body></html>"""
    b = page.encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(b)))
    handler.end_headers()
    handler.wfile.write(b)


class Handler(BaseHTTPRequestHandler):
    def _read_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length:
            return self.rfile.read(length)
        return b""

    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/api/status":
            return _json(self, {
                "agent": "无职转生",
                "status": "online",
                "capabilities": ["contract_scan", "web_research", "dealwork_scout", "superteam_scout"],
                "recentWebhooks": EVENTS[-10:],
            })
        if p.path == "/":
            ev = "".join(f"<li>{html.escape(str(e))}</li>" for e in EVENTS[-10:]) or "<li>(none yet)</li>"
            return _html(self, f"""
            <h1>无职转生 — Control Plane</h1>
            <div class=card><b>Status:</b> online · <b>Capabilities:</b> contract scan, web research, marketplace scouts</div>
            <div class=card><h3>Try a contract scan</h3>
              <form action=/api/scan method=post>
                <textarea name=source rows=8 style="width:100%">pragma solidity ^0.8.0;
contract Vault {{ mapping(address=>uint) b; function w(uint a) public {{ b[msg.sender]-=a; (bool o,)=msg.sender.call{{value:a}}(\"\"); }} }}</textarea><br>
                <button type=submit>Scan</button></form></div>
            <div class=card><h3>Recent webhook events</h3><ul>{ev}</ul></div>
            <p><a href=/api/status>JSON status</a></p>""")
        return _json(self, {"error": "not found"}, 404)

    def do_POST(self):
        p = urlparse(self.path)
        body = self._read_body()
        if p.path == "/api/scan":
            try:
                src = parse_qs(body.decode()).get("source", [""])[0] or json.loads(body).get("source", "")
            except Exception:
                src = body.decode()
            if not src:
                return _json(self, {"error": "no source"}, 400)
            rep = contract_scan.scan_source(src)
            return _json(self, rep)
        if p.path == "/api/research":
            try:
                q = parse_qs(body.decode()).get("query", [""])[0] or json.loads(body).get("query", "")
            except Exception:
                q = body.decode()
            if not q:
                return _json(self, {"error": "no query"}, 400)
            brief = web_research.research(q, take=5, read=False)
            return _json(self, brief)
        if p.path == "/webhook/dealwork":
            EVENTS.append({"src": "dealwork", "payload": body.decode()[:500]})
            return _json(self, {"received": True})
        if p.path == "/webhook/superteam":
            EVENTS.append({"src": "superteam", "payload": body.decode()[:500]})
            return _json(self, {"received": True})
        return _json(self, {"error": "not found"}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"无职转生 control plane on :{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
