#!/usr/bin/env python3
"""
无职转生 — Superteam Earn worker (capability module)
====================================================
Polls live Superteam Earn bounties, scores them against 无职转生's
capability tags, and (in LIVE mode) submits a structured entry.

Auth: Bearer <apiKey> from ~/.openwork/st_superteam.key
API docs: ~/.openwork/superteam_skill.md

Verified against live API 2026-08-28 (auth 200, live listings returned).

Run:
  python3 superteam_worker.py --mode scout          # read-only
  python3 superteam_worker.py --mode live           # submit (commits!)
  python3 superteam_worker.py --once                # one cycle then exit
  python3 superteam_worker.py --loop --interval 600 # daemon poll
"""
import json, os, sys, time, argparse, urllib.request, urllib.error

KEY_PATH = os.path.expanduser("~/.openwork/st_superteam.key")
BASE = "https://superteam.fun"

MY_TAGS = ["security", "smart-contract-audit", "blockchain", "data-analysis",
           "web-research", "content-generation"]
# keyword heuristics for title/desc matching
MY_KEYWORDS = ["security", "audit", "vulnerab", "smart contract", "solana", "evm",
               "on-chain", "onchain", "research", "data analysis", "data-analysis",
               "report", "writing", "content", "web research", "blockchain"]

MIN_REWARD = 100  # USDG — skip peanuts


def load_key():
    with open(KEY_PATH) as f:
        return f.read().strip()


def api(method, path, body=None, key=None):
    key = key or load_key()
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode() or "{}"
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = raw
            return r.status, parsed
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode() or "")[:400]
    except Exception as e:
        return "ERR", str(e)[:200]


def score_listing(item):
    title = (item.get("title") or "").lower()
    text = title
    matched = [k for k in MY_KEYWORDS if k in text]
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
    print(f"\n=== SCOUT: {len(items)} live listings, {len(scored)} match 无职转生 ===")
    for sc, it, matched, reward, slug, lid in scored:
        print(f"\n[{sc:.2f}] {it.get('title')}")
        print(f"       id={lid}  reward={reward}{it.get('token','')}  agentAccess={it.get('agentAccess')}  slug={slug}")
        print(f"       matched={matched}")
    return scored


def submit(listing_id, slug, link="", tweet="", other_info="", telegram=""):
    body = {
        "listingId": listing_id,
        "link": link,
        "tweet": tweet,
        "otherInfo": other_info or "无职转生 autonomous agent — security/data submission.",
        "eligibilityAnswers": [],
        "ask": None,
        "telegram": telegram,
    }
    return api("POST", "/api/agents/submissions/create", body)


def main():
    ap = argparse.ArgumentParser(description="无职转生 Superteam worker")
    ap.add_argument("--mode", choices=["scout", "live"], default="scout")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=600)
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    if args.mode == "live":
        print("[WARN] LIVE mode submits real bounty entries.")
        if input("Type 'CONFIRM LIVE' to proceed: ").strip() != "CONFIRM LIVE":
            args.mode = "scout"

    while True:
        matches = scout(limit=args.limit)
        if args.mode == "live" and matches:
            top = matches[0]
            sc, it, matched, reward, slug, lid = top
            st, resp = submit(lid, slug,
                other_info=f"无职转生 here — autonomous {', '.join(matched)} agent. Ready to deliver.")
            print(f"[live] submit {lid}: {st} {resp}")
        if args.once or not args.loop:
            break
        print(f"\n[sleep {args.interval}s]\n")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
