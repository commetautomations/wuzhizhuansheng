#!/usr/bin/env python3
"""
无职转生 — dealwork.ai worker daemon (OpenClaw-compatible)
==========================================================
Polls the dealwork.ai marketplace, matches jobs to this agent's capability
tags, and (in LIVE mode) bids + fulfills contracts. SCOUT mode is read-only:
it finds and scores matching jobs without placing any bid or commitment.

Verified against live API 2026-08-28 (agent 36489343-..., healthy, Bearer auth).

Run:
  python3 ~/.openwork/openwork_worker.py --mode scout      # read-only search
  python3 ~/.openwork/openwork_worker.py --mode live       # bid + fulfill (commits!)
  python3 ~/.openwork/openwork_worker.py --mode once       # one scout cycle then exit
  python3 ~/.openwork/openwork_worker.py --loop --interval 300   # daemon poll

Credentials: ~/.openwork/credentials.json  (apiKey)
Docs:         https://dealwork.ai/skill.md
"""
import json, os, sys, time, argparse, urllib.request, urllib.error

CREDS_PATH = os.path.expanduser("~/.openwork/credentials.json")
BASE = "https://dealwork.ai"

# 无职转生 capability tags (from the live agent profile)
MY_TAGS = ["security", "smart-contract-audit", "blockchain", "data-analysis",
           "web-research", "content-generation"]

# Minimum budget (USD) we'll consider. Below this it's not worth the escrow risk.
MIN_BUDGET = 1.0


def load_creds():
    with open(CREDS_PATH) as f:
        return json.load(f)


def api(method, path, body=None, creds=None):
    creds = creds or load_creds()
    key = creds["apiKey"]
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads((e.read() or b"{}").decode() or "{}")
    except Exception as e:
        return "ERR", {"error": str(e)[:200]}


def score_job(job):
    """Return (score 0..1, matched_tags, reasons)."""
    tags = set(t.lower() for t in job.get("tags", []))
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()
    text = f"{title} {desc}"
    matched = [t for t in MY_TAGS if t in tags or t.replace("-", " ") in text]
    score = min(1.0, len(matched) / 3.0)
    reasons = [f"tag:{t}" for t in matched]
    # budget signal
    try:
        lo = float(job.get("budgetMin") or 0)
        hi = float(job.get("fixedPrice") or job.get("budgetMax") or 0)
    except Exception:
        lo = hi = 0
    if hi and hi >= MIN_BUDGET:
        score = min(1.0, score + 0.1)
        reasons.append(f"budget ${lo:.0f}-${hi:.0f}")
    return round(score, 2), matched, reasons, lo, hi


def scout(limit=10):
    status, jobs = api("GET", f"/api/v1/jobs?take={limit}&status=posted")
    if status != 200:
        print(f"[scout] jobs API returned {status}: {jobs}")
        return []
    items = (jobs.get("data") or []) if isinstance(jobs, dict) else []
    scored = []
    for j in items:
        sc, matched, reasons, lo, hi = score_job(j)
        if sc >= 0.2:
            scored.append((sc, j, matched, reasons, lo, hi))
    scored.sort(key=lambda x: -x[0])
    print(f"\n=== SCOUT: {len(items)} open jobs scanned, {len(scored)} match 无职转生 ===")
    for sc, j, matched, reasons, lo, hi in scored:
        print(f"\n[{sc:.2f}] {j.get('title')}")
        print(f"       id={j.get('id')}  mode={j.get('jobMode')}  "
              f"budget=${lo:.0f}-${hi:.0f}  cat={j.get('category')}")
        print(f"       matched={matched}")
        print(f"       why={reasons}")
    return scored


def bid(job_id, bid_text, price):
    """Place a bid. LIVE mode only. Returns (status, body)."""
    return api("POST", f"/api/v1/jobs/{job_id}/bids",
               {"proposal": bid_text, "price": str(price)})


def main():
    ap = argparse.ArgumentParser(description="无职转生 dealwork worker")
    ap.add_argument("--mode", choices=["scout", "live", "once"], default="scout")
    ap.add_argument("--loop", action="store_true", help="poll forever")
    ap.add_argument("--interval", type=int, default=300, help="poll seconds")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    if args.mode == "live":
        print("[WARN] LIVE mode places real bids committing to paid contracts.")
        print("        Flip only after reviewing scout output and confirming scope.")
        confirm = input("Type 'CONFIRM LIVE' to proceed: ")
        if confirm.strip() != "CONFIRM LIVE":
            print("Aborted. Staying in scout.")
            args.mode = "scout"

    while True:
        matches = scout(limit=args.limit)
        if args.mode == "live" and matches:
            # Top match: draft a bid (kept conservative — manual review recommended)
            top = matches[0]
            sc, j, matched, reasons, lo, hi = top
            bid_text = (f"无职转生 here — autonomous security/data agent. "
                        f"I can deliver on: {', '.join(matched)}. "
                        f"Will start immediately and submit a structured report.")
            price = max(MIN_BUDGET, (hi if hi else lo) * 0.8)
            # NOTE: auto-bidding is gated; uncomment after owner sign-off.
            # st, b = bid(j["id"], bid_text, price)
            # print(f"[live] bid on {j['id']}: {st} {b}")
            print(f"[live] would bid ${price:.2f} on {j['id']} (auto-bid disabled pending sign-off)")
        if not args.loop:
            break
        print(f"\n[sleep {args.interval}s]\n")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
