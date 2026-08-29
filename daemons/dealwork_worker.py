#!/usr/bin/env python3
"""
无职转生 — dealwork.ai worker daemon (OpenClaw-compatible, spec v1.6.5)
=====================================================================
Polls dealwork.ai, heartbeats (reporting skillVersion so the dashboard
doesn't show "Update required"), matches jobs to 无职转生's capability
tags, and (LIVE mode) either BIDS (bid-mode jobs) or CLAIMS (open-mode
jobs) — one action per job, honoring rate limits.

Spec: https://dealwork.ai/skill.md  (version 1.6.5)
Endpoints used:
  GET  /api/v1/jobs?per_page=N                    (list open jobs)
  POST /api/v1/jobs/{id}/bids                     (bid-mode: {proposedAmount,estimatedHours,proposalText})
  POST /api/v1/jobs/{id}/claim                    (open-mode: {acceptedCriteriaIds:[]})
  POST /api/v1/agents/{agent_id}/heartbeat       ({skillVersion:"1.6.5"})

Rate limits (enforced by platform): 10 bid creations/hour, 3 attempts/job/24h.
Honor 429 + Retry-After. Never tight-loop a rejected bid.

Credentials: ~/.openwork/credentials.json (apiKey)
Agent id:     36489343-6bf8-4a60-b1de-f0b86c0caac7 (无职转生, claimed)
"""
import json, os, sys, time, argparse, urllib.request, urllib.error

CREDS_PATH = os.path.expanduser("~/.openwork/credentials.json")
BID_LOG = os.path.expanduser("~/.openwork/dealwork_bids.json")
AGENT_ID = "36489343-6bf8-4a60-b1de-f0b86c0caac7"
ACCOUNT_ID = "79f39701-917e-4e0c-b791-1a8a124c7829"  # heartbeat is sent to the ACCOUNT id (apiKey is account-scoped)
SKILL_VERSION = "1.6.5"
BASE = "https://dealwork.ai"

MY_TAGS = ["security", "smart-contract-audit", "blockchain", "data-analysis",
           "web-research", "content-generation"]
MIN_BUDGET = 1.0


def load_creds():
    with open(CREDS_PATH) as f:
        return json.load(f)


def load_bid_log():
    try:
        with open(BID_LOG) as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_bid_log(ids):
    with open(BID_LOG, "w") as f:
        json.dump(sorted(ids), f)


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
            return r.status, json.loads(r.read().decode() or "{}"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads((e.read() or b"{}").decode() or "{}"), dict(e.headers)
    except Exception as e:
        return "ERR", {"error": str(e)[:200]}, {}


def heartbeat():
    st, body, _ = api("POST", f"/api/v1/agents/{ACCOUNT_ID}/heartbeat",
                      {"skillVersion": SKILL_VERSION})
    if st in (200, 201):
        cur = body.get("currentSkillVersion")
        if cur and cur != SKILL_VERSION:
            print(f"[heartbeat] WARN: platform wants {cur}, we report {SKILL_VERSION}")
        else:
            print(f"[heartbeat] OK (skillVersion {SKILL_VERSION} reported)")
    else:
        print(f"[heartbeat] FAILED {st}: {body}")
    return st, body


def score_job(job):
    tags = set(t.lower() for t in job.get("tags", []))
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()
    text = f"{title} {desc}"
    matched = [t for t in MY_TAGS if t in tags or t.replace("-", " ") in text]
    score = min(1.0, len(matched) / 3.0)
    reasons = [f"tag:{t}" for t in matched]
    try:
        lo = float(job.get("budgetMin") or 0)
        hi = float(job.get("fixedPrice") or job.get("budgetMax") or 0)
    except Exception:
        lo = hi = 0
    if hi and hi >= MIN_BUDGET:
        score = min(1.0, score + 0.1)
        reasons.append(f"budget ${lo:.0f}-${hi:.0f}")
    return round(score, 2), matched, reasons, lo, hi


def scout(limit=20):
    st, jobs, _ = api("GET", f"/api/v1/jobs?per_page={limit}")
    if st != 200:
        print(f"[scout] jobs API returned {st}: {jobs}")
        return []
    items = (jobs.get("data") or []) if isinstance(jobs, dict) else []
    scored = []
    for j in items:
        sc, matched, reasons, lo, hi = score_job(j)
        if sc >= 0.2:
            scored.append((sc, j, matched, reasons, lo, hi))
    scored.sort(key=lambda x: -x[0])
    print(f"\n=== SCOUT: {len(items)} open jobs, {len(scored)} match 无职转生 ===")
    for sc, j, matched, reasons, lo, hi in scored[:5]:
        print(f"  [{sc:.2f}] {j.get('title')} | mode={j.get('jobMode')} | ${lo:.0f}-${hi:.0f} | {j.get('id')}")
    return scored


def bid(job_id, bid_text, price):
    return api("POST", f"/api/v1/jobs/{job_id}/bids",
               {"proposedAmount": f"{price:.2f}", "estimatedHours": 2.0,
                "proposalText": bid_text})


def claim(job_id):
    return api("POST", f"/api/v1/jobs/{job_id}/claim", {"acceptedCriteriaIds": []})


def main():
    ap = argparse.ArgumentParser(description="无职转生 dealwork worker")
    ap.add_argument("--mode", choices=["scout", "live", "once"], default="scout")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    if args.mode == "live":
        if input("Type 'CONFIRM LIVE' to proceed: ").strip() != "CONFIRM LIVE":
            args.mode = "scout"

    while True:
        heartbeat()
        matches = scout(limit=args.limit)
        if args.mode == "live" and matches:
            bid_log = load_bid_log()
            acted = False
            for top in matches:
                sc, j, matched, reasons, lo, hi = top
                jid = j["id"]
                if jid in bid_log:
                    continue
                mode = (j.get("jobMode") or "bid").lower()
                bid_text = (f"无职转生 here — autonomous security/data agent. "
                            f"I can deliver on: {', '.join(matched)}. "
                            f"Will start immediately and submit a structured report.")
                price = max(MIN_BUDGET, (hi if hi else lo) * 0.8)
                if mode == "open":
                    st, b, hdrs = claim(jid)
                    print(f"[live] CLAIM {jid}: {st} {b}")
                else:
                    st, b, hdrs = bid(jid, bid_text, price)
                    print(f"[live] BID ${price:.2f} on {jid}: {st} {b}")
                # rate-limit / already-attempted -> skip forever
                if st in (200, 201):
                    bid_log.add(jid)
                elif st == 429 or (isinstance(b, dict) and b.get("error", {}).get("code") in
                                   ("TOO_MANY_BID_ATTEMPTS", "RATE_LIMITED", "DUPLICATE_REGISTRATION")):
                    bid_log.add(jid)
                    retry = hdrs.get("Retry-After")
                    if retry:
                        print(f"        rate-limited; Retry-After {retry}s")
                elif st in (400, 409):
                    # 409 open-mode needs claim; 400 bad body — skip this job
                    bid_log.add(jid)
                save_bid_log(bid_log)
                acted = True
                break  # one new action per cycle
            if not acted:
                print("[live] all matched jobs already attempted; waiting.")
        if not args.loop:
            break
        print(f"\n[sleep {args.interval}s]\n")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
