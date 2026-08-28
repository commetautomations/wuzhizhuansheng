#!/usr/bin/env python3
"""
无职转生 — Smart Contract Security Scanner (capability module)
=============================================================
Self-contained, dependency-free EVM/Solidity vulnerability scanner.

It works in two modes:
  1. SOURCE mode  : scan a .sol source blob with a rule-based static analysis
                    (reentrancy, selfdestruct, tx.origin, unchecked low-level
                    calls, missing access control, delegatecall, integer
                    pitfalls, pausable/upgradeable hazards, etc.)
  2. ADDRESS mode : if an Etherscan-style API key is supplied via
                    ETHERSCAN_API_KEY env, fetch verified source for an address
                    and scan it.

Output is a structured report (risk score + findings + remediation), the same
shape the agent delivers to a Dealwork/Toku/Superteam client.

Run directly:
  python3 contract_scan.py --source contract.sol
  python3 contract_scan.py --address 0x... --chain ethereum
"""
import os, re, sys, json, argparse, urllib.request, urllib.error

# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------
# Each rule: (id, severity, title, regex/matcher, remediation)
SEVERITY_WEIGHT = {"CRITICAL": 10, "HIGH": 6, "MEDIUM": 3, "LOW": 1, "INFO": 0}

RULES = [
    ("REENTRANCY", "HIGH", "Potential reentrancy (external value call + balance/state mutation in same function)",
     lambda s: re.search(r"\.(call|send|transfer|delegatecall)\s*\(|\.call\{[^}]*\}\s*\(", s)
               and re.search(r"(balances|allowed|owed|staked|rewards)\[[^\]]+\]\s*[-+]=", s),
     "Apply checks-effects-interactions: update all state BEFORE any external call, or use OpenZeppelin ReentrancyGuard. The classic bug is the balance decrement appearing after the .call."),

    ("SELFDESTRUCT", "HIGH", "selfdestruct / suicide present",
     lambda s: re.search(r"\b(selfdestruct|suicide)\s*\(", s),
     "Remove selfdestruct unless absolutely required; it can permanently brick the contract and is deprecated in recent EVM forks."),

    ("TX_ORIGIN", "MEDIUM", "Authorization via tx.origin",
     lambda s: re.search(r"tx\.origin\s*==", s),
     "Use msg.sender for authorization; tx.origin is vulnerable to phishing via malicious intermediary contracts."),

    ("UNCHECKED_CALL", "MEDIUM", "Unchecked low-level call return value",
     lambda s: re.search(r"[^.]\.call\{[^}]*\}\s*\([^;]*\)\s*;", s) and
               not re.search(r"if\s*\([^)]*\.call", s),
     "Check the boolean return of low-level .call/.delegatecall; ignore failure can hide fund-loss bugs."),

    ("DELEGATECALL_UNTRUSTED", "HIGH", "delegatecall to untrusted/immutable-address storage",
     lambda s: re.search(r"delegatecall", s) and re.search(r"delegatecall\([^)]*(address|msg\.sender|user)", s),
     "Never delegatecall into attacker-controllable code; the callee can hijack this contract's storage."),

    ("MISSING_ACCESS_CONTROL", "HIGH", "Privileged function without access control",
     lambda s: (re.search(r"function\s+(withdraw|mint|burn|setOwner|owner|pause|unpause|upgrade|setFee|setAdmin)\b", s)
                and not re.search(r"onlyOwner|modifier\s+(onlyOwner|onlyAdmin|onlyRole|auth)", s)),
     "Add an access-control modifier (onlyOwner / onlyRole) to every privileged function, and emit events on state changes."),

    ("UNPROTECTED_INIT", "CRITICAL", "Initializable contract without initializer guard",
     lambda s: re.search(r"function\s+initialize\s*\(", s) and
               not re.search(r"initializer|alreadyInitialized|initializing", s),
     "Protect initialize() with an 'initializer' modifier (OpenZeppelin Initializable) to prevent re-initialization takeovers."),

    ("ARBITRARY_JUMP", "CRITICAL", "assembly { delegatecall / jump } to computed target",
     lambda s: re.search(r"assembly\s*\{[^}]*(delegatecall|jump|jumpi)\s*\(", s),
     "Avoid raw assembly control-flow to computed destinations; it enables arbitrary-jump exploits."),

    ("WEAK_RNG", "MEDIUM", "Block values used as randomness",
     lambda s: re.search(r"(block\.timestamp|block\.difficulty|blockhash|block\.number)\b", s)
                and re.search(r"(random|rand|lottery|draw|roll|reward)\b", s, re.I),
     "Block attributes are manipulable by miners/validators; use a VRF (Chainlink VRF) for on-chain randomness."),

    ("INTEGER_UNSADED", "MEDIUM", "Arithmetic without SafeMath / unchecked block",
     lambda s: re.search(r"\b(uint\d+)\s+\w+\s*=", s) and
               re.search(r"(\+\+|--|\+|\-|\*|\/)\s*=", s) and
               not re.search(r"SafeMath|using\s+SafeCast|unchecked\s*\{", s),
     "Use Solidity 0.8+ (safe by default) or SafeMath; wrap intentional wrapping in 'unchecked' with a comment."),

    ("UNPROTECTED_ETHER", "LOW", "Contract receives Ether without withdrawal path",
     lambda s: re.search(r"(payable|receive\(\)|fallback\(\))", s) and
               not re.search(r"function\s+(withdraw|retrieve|rescue)\s*\(", s),
     "Ensure a withdraw() path exists; Ether sent to a contract with no withdrawal can be permanently locked."),

    ("PRAGMA_FLOAT", "LOW", "Floating pragma",
     lambda s: re.search(r"pragma\s+solidity\s+\^", s),
     "Lock the pragma to a specific version (e.g. pragma solidity 0.8.24;) to avoid compiling with a different/buggy compiler."),

    ("NO_EVENTS", "INFO", "State-changing functions without events",
     lambda s: re.search(r"function\s+(set|update|transfer|mint|burn|approve)\w*\(", s)
                and not re.search(r"emit\s+\w+", s),
     "Emit events on every state change for off-chain observability and easier incident response."),
]


def scan_source(source: str) -> dict:
    findings = []
    # strip line comments + block comments for cleaner matches, but keep line numbers via mapping
    lines = source.splitlines()
    cleaned = [re.sub(r"//.*", "", ln) for ln in lines]
    cleaned = [re.sub(r"/\*.*?\*/", "", ln, flags=re.S) for ln in cleaned]
    text = "\n".join(cleaned)

    for rid, sev, title, matcher, fix in RULES:
        try:
            if matcher(text):
                # locate first occurrence line
                line_no = None
                for i, ln in enumerate(cleaned, 1):
                    if matcher(ln):
                        line_no = i
                        break
                findings.append({
                    "id": rid, "severity": sev, "title": title,
                    "line": line_no, "remediation": fix,
                })
        except Exception:
            continue

    # risk score
    score = sum(SEVERITY_WEIGHT[f["severity"]] for f in findings)
    score = min(100, score)
    band = "CRITICAL" if score >= 40 else "HIGH" if score >= 20 else "MEDIUM" if score >= 8 else "LOW" if score else "CLEAN"
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    findings.sort(key=lambda f: sev_order[f["severity"]])
    return {
        "tool": "无职转生 contract_scan",
        "riskScore": score,
        "riskBand": band,
        "findingCount": len(findings),
        "severityBreakdown": _count_by_sev(findings),
        "findings": findings,
    }


def _count_by_sev(findings):
    out = {}
    for f in findings:
        out[f["severity"]] = out.get(f["severity"], 0) + 1
    return out


# ---------------------------------------------------------------------------
# Address mode (optional)
# ---------------------------------------------------------------------------
CHAINS = {
    "ethereum": "https://api.etherscan.io/api",
    "bsc": "https://api.bscscan.com/api",
    "polygon": "https://api.polygonscan.com/api",
    "arbitrum": "https://api.arbiscan.io/api",
    "optimism": "https://api.optimistic.etherscan.io/api",
    "base": "https://api.basescan.org/api",
}


def fetch_source(address: str, chain: str = "ethereum") -> str:
    key = os.environ.get("ETHERSCAN_API_KEY")
    if not key:
        raise RuntimeError("ETHERSCAN_API_KEY env not set; cannot fetch on-chain source.")
    base = CHAINS.get(chain, CHAINS["ethereum"])
    url = f"{base}?module=contract&action=getsourcecode&address={address}&apikey={key}"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=25) as r:
        data = json.loads(r.read().decode())
    res = (data.get("result") or [{}])[0]
    if res.get("SourceCode") in (None, ""):
        raise RuntimeError(f"No verified source for {address} on {chain}.")
    return res["SourceCode"]


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------
def render_markdown(report: dict, target: str = "contract") -> str:
    md = []
    md.append(f"# 无职转生 Security Scan — {target}")
    md.append("")
    md.append(f"**Risk score:** {report['riskScore']}/100  **Band:** {report['riskBand']}")
    md.append(f"**Findings:** {report['findingCount']}  {report['severityBreakdown']}")
    md.append("")
    if not report["findings"]:
        md.append("_No issues matched the rule set. Note: this is a heuristic scan, not a substitute for a full audit._")
        return "\n".join(md)
    md.append("## Findings")
    for f in report["findings"]:
        loc = f" (line {f['line']})" if f.get("line") else ""
        md.append(f"\n### [{f['severity']}] {f['id']} — {f['title']}{loc}")
        md.append(f"- **Fix:** {f['remediation']}")
    md.append("")
    md.append("---")
    md.append("_Heuristic static analysis by 无职转生. For production funds, commission a human audited review._")
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser(description="无职转生 contract scanner")
    ap.add_argument("--source", help="path to .sol file")
    ap.add_argument("--address", help="contract address (needs ETHERSCAN_API_KEY)")
    ap.add_argument("--chain", default="ethereum")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    args = ap.parse_args()

    if args.address:
        src = fetch_source(args.address, args.chain)
        target = args.address
    elif args.source:
        with open(args.source) as f:
            src = f.read()
        target = args.source
    else:
        # demo contract if nothing given
        src = SAMPLE_VULN
        target = "SAMPLE_VULNERABLE.sol"

    report = scan_source(src)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_markdown(report, target))


SAMPLE_VULN = r"""
pragma solidity ^0.8.0;

contract Vault {
    mapping(address => uint) public balances;
    address public owner;

    function deposit() public payable {
        balances[msg.sender] += msg.value;
    }

    function withdraw(uint amount) public {
        require(balances[msg.sender] >= amount);
        (bool ok, ) = msg.sender.call{value: amount}("");
        balances[msg.sender] -= amount;
    }

    function kill() public {
        selfdestruct(payable(owner));
    }

    function setOwner(address o) public {
        owner = o;
    }

    function getReward() public view returns (uint) {
        return uint(keccak256(abi.encodePacked(block.timestamp, msg.sender))) % 100;
    }
}
"""


if __name__ == "__main__":
    main()
