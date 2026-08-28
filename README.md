# 无职转生 (Mushoku Tensei) — Autonomous Agent Backend

Security / data-analysis agent. Scans EVM smart contracts, runs web research,
and scouts marketplace jobs (Dealwork, Superteam, Toku).

## Layout
- `capabilities/contract_scan.py` — heuristic EVM vulnerability scanner
- `capabilities/web_research.py` — search + extractive summarizer
- `daemons/dealwork_worker.py` — Dealwork.ai scout/bid daemon
- `daemons/superteam_worker.py` — Superteam Earn scout/submit daemon
- `controlplane/app.py` — web control plane (dashboard + scan/research API + webhooks)

## Local run
```
python3 controlplane/app.py
# open http://localhost:8080
```

## Deploy
- Vercel: `vercel --prod` (uses vercel.json)
- Render: connect repo, uses render.yaml
- DNS: commetautomations.site (Cloudflare)

## Credentials (not in repo)
- Dealwork: ~/.openwork/credentials.json
- Superteam: ~/.openwork/st_superteam.key
- GitHub PAT: ~/.openwork/gh_pat.txt
