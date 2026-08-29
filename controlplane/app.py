#!/usr/bin/env python3
"""
无职转生 — Agent Control Plane (lightweight, stdlib-only)
=========================================================
Serves each agent at /agents/<agent_name> under the fixed subdomain
agents.commetautomations.site. The root lists all registered agents.

Routes (per agent at /agents/<name>):
  GET  /                          -> list all agents
  GET  /agents/<name>             -> agent dashboard (HTML)
  GET  /agents/<name>/api/status  -> JSON status
  POST /agents/<name>/api/scan    -> contract scan on pasted .sol
  POST /agents/<name>/api/research-> web research on a query
  GET  /agents/<name>/webhook/<src> -> marketplace ping endpoint

Adding a new agent = append to AGENTS below. Scales to "a lot of agents"
with zero DNS/infra changes (they all share agents.commetautomations.site).

Deploy: vercel --prod (vercel.json routes /(.*) -> app.py)
"""
import os, sys, json, html, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "capabilities"))
import contract_scan, web_research

AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "dev-token-change-me")
PORT = int(os.environ.get("PORT", "8080"))

# ---- Agent registry: add new agents here ----
AGENTS = {
    "无职转生": {
        "display": "无职转生 (Mushoku Tensei / Rudeus Greyrat)",
        "description": "Security & data-analysis agent. EVM contract scans, web research, marketplace scouting (Dealwork/Superteam/Toku).",
        "capabilities": ["contract_scan", "web_research", "dealwork_scout", "superteam_scout"],
    },
    "洛琪希": {
        "display": "洛琪希 (Mushoku Tensei / Roxy Migurdia)",
        "description": "Magic-circle & on-chain analysis specialist. Deep EVM contract audits, vulnerability research, and structured data-analysis reporting.",
        "capabilities": ["contract_scan", "web_research", "dex_scout", "onchain_analytics"],
    },
}

EVENTS = []  # in-memory webhook log (swap for DB later)


def _auth_ok(h): return h.get("X-Agent-Token") == AGENT_TOKEN


def _json(h, obj, code=200):
    b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    h.send_response(code); h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(b))); h.end_headers(); h.wfile.write(b)


def _html(h, body_html, code=200):
    page = f"""<!doctype html><html><head><meta charset=utf-8>
<title>Agents | commetautomations</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem}}
h1{{font-size:1.6rem}} code{{background:#f4f4f4;padding:1px 4px;border-radius:3px}}
.card{{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}}
ul{{padding-left:1.2rem}}</style></head><body>{body_html}</body></html>"""
    b = page.encode("utf-8")
    h.send_response(code); h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(b))); h.end_headers(); h.wfile.write(b)


def agent_card(name, meta):
    return f"""<div class=card><h3><a href=/agents/{name}>{meta['display']}</a></h3>
    <p>{meta['description']}</p>
    <p><b>Caps:</b> {', '.join(meta['capabilities'])}</p>
    <p><a href=/agents/{name}/api/status>status json</a></p></div>"""


class Handler(BaseHTTPRequestHandler):
    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        p = urlparse(self.path)
        seg = [unquote(s) for s in p.path.split("/") if s]
        # root -> list agents
        if not seg:
            cards = "".join(agent_card(n, m) for n, m in AGENTS.items())
            return _html(self, f"<h1>Agent Registry</h1><p>{len(AGENTS)} agent(s) hosted on this subdomain.</p>{cards}")
        if seg[0] == "agents" and len(seg) >= 2:
            name = seg[1]
            meta = AGENTS.get(name)
            if not meta:
                return _html(self, f"<h1>404</h1><p>No agent '{html.escape(name)}'.</p>", 404)
            if len(seg) == 2:
                ev = "".join(f"<li>{html.escape(str(e))}</li>" for e in EVENTS[-10:]) or "<li>(none yet)</li>"
                return _html(self, f"""<h1>{meta['display']}</h1>
                <div class=card>{meta['description']}<br><b>Caps:</b> {', '.join(meta['capabilities'])}</div>
                <div class=card><h3>Try a contract scan</h3>
                  <form action=/agents/{name}/api/scan method=post>
                  <textarea name=source rows=6 style="width:100%">pragma solidity ^0.8.0; contract V {{ mapping(address=>uint) b; function w(uint a) public {{ b[msg.sender]-=a; (bool o,)=msg.sender.call{{value:a}}(\"\"); }} }}</textarea><br>
                  <button type=submit>Scan</button></form></div>
                <div class=card><h3>Webhook events</h3><ul>{ev}</ul></div>""")
            if seg[2] == "api" and seg[3] == "status":
                return _json(self, {"agent": name, "status": "online",
                                    "capabilities": meta["capabilities"], "recentWebhooks": EVENTS[-10:]})
        return _json(self, {"error": "not found"}, 404)

    def do_POST(self):
        p = urlparse(self.path)
        seg = [unquote(s) for s in p.path.split("/") if s]
        if seg[0] == "agents" and len(seg) >= 4 and seg[2] == "api":
            name, action = seg[1], seg[3]
            meta = AGENTS.get(name)
            if not meta:
                return _json(self, {"error": "no agent"}, 404)
            body = self._body()
            if action == "scan":
                try:
                    src = parse_qs(body.decode()).get("source", [""])[0] or json.loads(body).get("source", "")
                except Exception:
                    src = body.decode()
                if not src:
                    return _json(self, {"error": "no source"}, 400)
                return _json(self, contract_scan.scan_source(src))
            if action == "research":
                try:
                    q = parse_qs(body.decode()).get("query", [""])[0] or json.loads(body).get("query", "")
                except Exception:
                    q = body.decode()
                if not q:
                    return _json(self, {"error": "no query"}, 400)
                return _json(self, web_research.research(q, take=5, read=False))
            if seg[2] == "webhook":
                EVENTS.append({"agent": name, "src": seg[3], "payload": body.decode()[:500]})
                return _json(self, {"received": True})
        return _json(self, {"error": "not found"}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Agent control plane on :{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
