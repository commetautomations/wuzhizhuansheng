#!/usr/bin/env python3
"""
无职转生 — Web Research & Data Analysis (capability module)
===========================================================
Self-contained research engine (stdlib only).

Pipeline:
  1. Collect sources via DuckDuckGo HTML (no API key) — web_search()
  2. Extract readable text from each result URL — fetch_readable()
  3. Score relevance, dedupe, and summarize via a simple extractive
     algorithm (frequency-based sentence ranking) — summarize()
  4. Emit a structured research brief (markdown + JSON)

This is the module the agent calls when a Dealwork/Toku/Superteam job asks for
"web research", "data analysis", "technical writing", or "structured report".

Run:
  python3 web_research.py "EVM reentrancy patterns 2026" --take 8
  python3 web_research.py "layer2 sequencer risks" --json
"""
import os, re, sys, json, html, argparse, urllib.parse, urllib.request, urllib.error
from collections import Counter
from html.parser import HTMLParser

UA = {"User-Agent": "Mozilla/5.0 (compatible; MushokuTensei-Research/1.0)"}


# ---------------------------------------------------------------------------
# 1. Search (DuckDuckGo HTML endpoint, no key)
# ---------------------------------------------------------------------------
def web_search(query: str, take: int = 8) -> list:
    """Return list of {title, url, snippet}."""
    q = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={q}"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            page = r.read().decode("utf-8", "ignore")
    except Exception as e:
        return [{"error": str(e)[:200]}]

    results = []
    # results are in <a class="result__a" href=...>title</a> ... <a class="result__snippet">...
    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', page, re.S):
        href = m.group(1)
        title = _strip_tags(m.group(2))
        snippet = _strip_tags(m.group(3))
        # DDG wraps real url in uddg= param
        real = re.search(r"uddg=([^&]+)", href)
        if real:
            href = urllib.parse.unquote(real.group(1))
        results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= take:
            break
    return results


# ---------------------------------------------------------------------------
# 2. Readable extraction
# ---------------------------------------------------------------------------
class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.buf = []
        self.skip_tags = {"script", "style", "noscript", "svg", "head", "iframe"}

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in self.skip_tags and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)

    def text(self):
        return " ".join(self.buf)


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def fetch_readable(url: str, max_chars: int = 6000) -> str:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read(2_000_000).decode("utf-8", "ignore")
    except Exception as e:
        return f"[fetch error: {str(e)[:120]}]"
    p = _TextExtractor()
    try:
        p.feed(raw)
    except Exception:
        pass
    text = p.text()
    # collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


# ---------------------------------------------------------------------------
# 3. Extractive summarizer
# ---------------------------------------------------------------------------
STOP = set("the a an and or of to in for on at by with from as is are was were be "
           "this that these those it its their our your his her they we you i he she "
           "will would can could should may might has have had do does did not no yes "
           "but if then than so such into out up down over under again more most other "
           "about which who whom whose what when where why how all any both each few "
           "other some more most own same ten via per amp https http www com org net".split())


def summarize(text: str, sentences_take: int = 8) -> dict:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 30]
    if not sentences:
        return {"summary": "", "keywords": [], "sentenceCount": 0}
    # word freq
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.]{2,}", " ".join(sentences).lower())
    freq = Counter(w for w in words if w not in STOP)
    # score sentences
    scored = []
    for s in sentences:
        sw = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.]{2,}", s.lower())
        score = sum(freq.get(w, 0) for w in sw) / max(1, len(sw))
        scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    top = [s for _, s in scored[:sentences_take]]
    keywords = [w for w, _ in freq.most_common(12)]
    return {"summary": " ".join(top), "keywords": keywords, "sentenceCount": len(sentences)}


# ---------------------------------------------------------------------------
# 4. Orchestration
# ---------------------------------------------------------------------------
def research(query: str, take: int = 8, read: bool = True, max_read: int = 4) -> dict:
    results = web_search(query, take)
    if results and "error" in results[0]:
        return {"query": query, "error": results[0]["error"], "sources": []}
    sources = []
    for i, res in enumerate(results):
        entry = dict(res)
        if read and i < max_read:
            entry["extracted"] = fetch_readable(res["url"])
            if entry["extracted"] and not entry["extracted"].startswith("[fetch error"):
                entry["analysis"] = summarize(entry["extracted"])
        sources.append(entry)
    # aggregate keywords
    kw = Counter()
    for s in sources:
        if "analysis" in s:
            kw.update(s["analysis"]["keywords"])
    brief = {
        "query": query,
        "sourceCount": len(sources),
        "topKeywords": [w for w, _ in kw.most_common(15)],
        "sources": sources,
    }
    return brief


def render_markdown(brief: dict) -> str:
    if "error" in brief:
        return f"# Research failed\n\n{brief['error']}"
    md = [f"# 无职转生 Research Brief — “{brief['query']}”", ""]
    md.append(f"**Sources scanned:** {brief['sourceCount']}")
    if brief.get("topKeywords"):
        md.append(f"**Key themes:** {', '.join(brief['topKeywords'][:12])}")
    md.append("")
    md.append("## Sources")
    for i, s in enumerate(brief["sources"], 1):
        md.append(f"\n{i}. **{s['title']}**")
        md.append(f"   <{s['url']}>")
        if s.get("snippet"):
            md.append(f"   _{s['snippet'][:240]}_")
        if "analysis" in s:
            a = s["analysis"]
            if a.get("summary"):
                md.append(f"   **TL;DR:** {a['summary'][:600]}")
    md.append("")
    md.append("---")
    md.append("_Compiled by 无职转生 autonomous research engine (extractive summarization). Verify critical claims against primary sources._")
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser(description="无职转生 web research")
    ap.add_argument("query")
    ap.add_argument("--take", type=int, default=8)
    ap.add_argument("--no-read", action="store_true", help="skip fetching full pages")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    brief = research(args.query, args.take, read=not args.no_read)
    if args.json:
        print(json.dumps(brief, indent=2))
    else:
        print(render_markdown(brief))


if __name__ == "__main__":
    main()
