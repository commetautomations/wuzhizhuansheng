#!/usr/bin/env python3
"""
洛琪希 (Roxy Migurdia) — Superteam Earn worker
==============================================
Second 无职转生-platform agent on Superteam Earn. Polls live bounties,
scores against 洛琪希's capability tags, and (LIVE mode) submits.

Auth: Bearer <apiKey> for 洛琪希 (----silver-95), loaded from
      ~/.openwork/superteam.json -> allAgents.luoqixi.apiKey
      (key is PENDING_HUMAN_PASTE until the owner pastes the full key
       from the dashboard reveal / their own terminal call).

Run:
  python3 luoqixi_superteam_worker.py --mode scout --once
  python3 luoqixi_superteam_worker.py --mode live --loop --interval 600
"""
import json, os, sys, time, argparse, urllib.request, urllib.error

CONF_PATH = os.path.expanduser("~/.openwork/superteam.json")
BASE = "https://superteam.fun"
AGENT_KEY = "luoqixi"  # slot in allAgents

MY_TAGS = ["security", "smart-contract-audit", "blockchain", "data-analysis",
           "web-research", "content-generation", "evm", "solana", "onchain"]
MY_KEYWORDS = ["security", "audit", "vulnerab", "smart contract", "solana", "evm",
               "on-chain", "onchain", "research", "data analysis", "data-analysis",
               "report", "writing", "content", "web research", "blockchain",
               "magic-circle", "contract"]

MIN_REWARD = 100


def load_key():
    with open(CONF_PATH) as f:
        data = json.load(f)
    return data["allAgents"][AGENT_KEY]["apiKey"].strip()


def api(method, path, body=None, key=None):
    key = key or load_key()
    if not key or key == "PENDING_HUMAN_PASTE":
        raise SystemExit("[FATAL] 洛琪希 apiKey not set. Paste the full key from "
                         "the Superteam dashboard reveal into superteam.json "
                         "allAgents.luoqixi.apiKey")
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode() or "{}"
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode() or "")[:400]
    except Exception as e:
        return "ERR", str(e)[:200]


def score_listing(item):
    title = (item.get("title") or "").lower()
    matched = [k for k in MY_KEYWORDS if k in title]
    score = min(1.0, len(matched) / 2.0)
    reward = float(item.get("rewardAmount") or 0)
    if reward >= MIN_REWARD:
        score = min(1.0, score + 0.1)
    agent_ok = item.get("agentAccess") in ("AGENT_ALLOWED", "AGENT_ONLY")
    return round(score, 2), matched, reward, agent_ok, item.get("slug"), item.get("id")


def scout(limit=10):
    st, body = api("GET", f"/api/agents/listings/live?take={limit}")
    if st != 200:
        print(f"[scout] listings API returned {st}: {body}")
        return []
    items = body if isinstance(body, list) else []
    scored = []
    for it in items:
        sc, matched, reward, ok, slug, lid = score_listing(it)
        if sc >= 0.2 and ok:
            scored.append((sc, it, matched, reward, slug, lid))
    scored.sort(key=lambda x: -x[0])
    print(f"\n=== 洛琪希 SCOUT: {len(items)} live, {len(scored)} match ===")
    for sc, it, matched, reward, slug, lid in scored:
        print(f"[{sc:.2f}] {it.get('title')} | {reward}{it.get('token','')} | {slug}")
    return scored


def submit(listing_id, slug, other_info=""):
    body = {
        "listingId": listing_id, "link": "", "tweet": "",
        "otherInfo": other_info or "洛琪希 here — autonomous on-chain analysis & security agent. Payment: USDT/USDC(ERC20) to 0x208de531560fdeafd2188e5cd20970791edfda19.",
        "eligibilityAnswers": [], "ask": None, "telegram": "",
    }
    return api("POST", "/api/agents/submissions/create", body)


def main():
    ap = argparse.ArgumentParser(description="洛琪希 Superteam worker")
    ap.add_argument("--mode", choices=["scout", "live"], default="scout")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=600)
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    if args.mode == "live":
        if input("Type 'CONFIRM LIVE' to submit real entries: ").strip() != "CONFIRM LIVE":
            args.mode = "scout"

    while True:
        matches = scout(limit=args.limit)
        if args.mode == "live" and matches:
            top = matches[0]
            sc, it, matched, reward, slug, lid = top
            st, resp = submit(lid, slug,
                other_info=f"洛琪希 — autonomous {', '.join(matched)} specialist. Ready to deliver.")
            print(f"[live] submit {lid}: {st} {resp}")
        if args.once or not args.loop:
            break
        print(f"\n[sleep {args.interval}s]\n")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
