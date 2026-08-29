#!/usr/bin/env python3
"""
Client-ready report wrapper for 无职转生 contract scans.
Takes raw contract_scan output and renders a clean, payable deliverable.
Used for direct-sale fulfillment (Reddit/X/DM clients paying USDT/USDC).
"""
import json, sys, datetime


def render(raw):
    out = []
    out.append("=" * 60)
    out.append("  无职转生 — SMART CONTRACT SECURITY REPORT")
    out.append("=" * 60)
    out.append(f"Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    out.append(f"Risk score: {raw.get('riskScore')} / 10   Band: {raw.get('riskBand')}")
    out.append(f"Findings: {raw.get('findingCount')}")
    sb = raw.get("severityBreakdown", {})
    if sb:
        out.append("Severity: " + ", ".join(f"{k}={v}" for k, v in sb.items()))
    out.append("")
    out.append("--- FINDINGS ---")
    for i, f in enumerate(raw.get("findings", []), 1):
        sev = f.get("severity", "?")
        title = f.get("title") or f.get("name") or "issue"
        desc = f.get("description") or ""
        out.append(f"{i}. [{sev}] {title}")
        if desc:
            out.append(f"   {desc}")
        loc = f.get("location") or f.get("line")
        if loc:
            out.append(f"   location: {loc}")
    out.append("")
    out.append("--- REMEDIATION ---")
    for r in raw.get("remediation", []):
        out.append(f" - {r}")
    out.append("")
    out.append("Payment: USDT/USDC (ERC20, Ethereum) to 0x208de531560fdeafd2188e5cd20970791edfda19")
    out.append("=" * 60)
    return "\n".join(out)


if __name__ == "__main__":
    raw = json.load(sys.stdin)
    print(render(raw))
