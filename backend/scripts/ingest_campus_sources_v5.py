"""
CampusOne KB Ingestion V5
-------------------------
Goal:
  Build a clean staging knowledge base from the authoritative CampusOne
  source manifest without aggressively reclassifying content.

Design:
  1. Manifest domain is authoritative for each seed source.
  2. Crawl the seed page/document.
  3. Follow useful linked HTML/PDF documents conservatively.
  4. Linked documents inherit the seed source's domain by default.
  5. Global exact-text deduplication removes repeated content.
  6. Boilerplate/navigation fragments are filtered conservatively.
  7. Existing backend/knowledge is NEVER modified unless --apply is used.
  8. --apply backs up the current KB before replacing it.

Usage from backend:
  python scripts/ingest_campus_sources_v5.py
  python scripts/ingest_campus_sources_v5.py --apply
  python scripts/ingest_campus_sources_v5.py --max-links 20

Expected manifest:
  backend/data/campus_sources.json

The script accepts common manifest field names:
  domain, source_id/id, url, title/name
and also ignores integration/authenticated entries that do not have a URL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "backend" / "data" / "campus_sources.json"
KNOWLEDGE = ROOT / "backend" / "knowledge"
STAGING = ROOT / "backend" / "knowledge_v5_staging"
REPORT_DIR = ROOT / "backend" / "data" / "ingestion_reports"

USER_AGENT = (
    "CampusOne-KB-Ingestion/5.0 "
    "(educational project; contact unavailable)"
)

TIMEOUT = 25
MIN_CHARS = 80
MAX_CHARS = 2200
OVERLAP = 180

# Conservative boilerplate patterns. These are intentionally limited.
BOILERPLATE_PATTERNS = [
    r"^\s*skip to (main )?content\s*$",
    r"^\s*menu\s*$",
    r"^\s*search\s*$",
    r"^\s*home\s*$",
    r"^\s*close\s*$",
    r"^\s*read more\s*$",
    r"^\s*learn more\s*$",
    r"^\s*click here\s*$",
    r"^\s*loading\.*\s*$",
]

# File/link types worth following from public seed pages.
FOLLOW_EXTENSIONS = {".pdf", ".html", ".htm"}
SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".mp4", ".mp3", ".zip", ".rar", ".7z",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def canonical_url(url: str) -> str:
    url, _ = urldefrag(url)
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return p._replace(
        scheme=p.scheme.lower(),
        netloc=p.netloc.lower(),
        path=path,
        fragment="",
    ).geturl()


def same_site(url_a: str, url_b: str) -> bool:
    a = urlparse(url_a).netloc.lower().replace("www.", "")
    b = urlparse(url_b).netloc.lower().replace("www.", "")
    return bool(a and b and a == b)


def is_probable_boilerplate(text: str) -> bool:
    t = clean_text(text)
    if len(t) < MIN_CHARS:
        return True
    for pattern in BOILERPLATE_PATTERNS:
        if re.match(pattern, t, flags=re.I):
            return True
    # Very repetitive navigation-like text.
    words = t.lower().split()
    if len(words) >= 10:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.28:
            return True
    return False


def chunk_text(text: str) -> list[str]:
    text = clean_text(text)
    if len(text) <= MAX_CHARS:
        return [text] if len(text) >= MIN_CHARS else []

    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + MAX_CHARS, n)
        if end < n:
            # Prefer sentence/word boundary.
            boundary = max(
                text.rfind(". ", start, end),
                text.rfind("; ", start, end),
                text.rfind(", ", start, end),
                text.rfind(" ", start, end),
            )
            if boundary > start + int(MAX_CHARS * 0.55):
                end = boundary + 1

        piece = clean_text(text[start:end])
        if len(piece) >= MIN_CHARS:
            chunks.append(piece)

        if end >= n:
            break
        start = max(end - OVERLAP, start + 1)

    return chunks


def hash_text(text: str) -> str:
    normalized = re.sub(r"\W+", " ", text.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_html(html: str, page_url: str):
    soup = BeautifulSoup(html, "lxml")

    for tag in soup([
        "script", "style", "noscript", "svg", "iframe",
        "form", "nav", "footer", "header"
    ]):
        tag.decompose()

    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""

    blocks = []
    for node in soup.find_all([
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "li", "td", "th", "blockquote"
    ]):
        txt = clean_text(node.get_text(" ", strip=True))
        if txt and not is_probable_boilerplate(txt):
            blocks.append(txt)

    # Preserve order but merge adjacent tiny fragments.
    merged = []
    for block in blocks:
        if merged and len(merged[-1]) < 160 and len(block) < 300:
            merged[-1] = clean_text(merged[-1] + " " + block)
        else:
            merged.append(block)

    links = []
    for a in soup.find_all("a", href=True):
        href = clean_text(a.get("href", ""))
        if not href:
            continue
        absolute = canonical_url(urljoin(page_url, href))
        label = clean_text(a.get_text(" ", strip=True))
        links.append((absolute, label))

    return title, merged, links


def extract_pdf(content: bytes):
    reader = PdfReader(content)
    pages = []
    for idx, page in enumerate(reader.pages):
        try:
            txt = clean_text(page.extract_text() or "")
        except Exception:
            txt = ""
        if txt:
            pages.append((idx + 1, txt))
    return pages


def fetch(session: requests.Session, url: str):
    try:
        r = session.get(
            url,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        r.raise_for_status()
        return r
    except Exception as exc:
        return None, str(exc)


def response_kind(r, url: str) -> str:
    ctype = (r.headers.get("content-type") or "").lower()
    path = urlparse(url).path.lower()
    if "application/pdf" in ctype or path.endswith(".pdf"):
        return "pdf"
    if "text/html" in ctype or "application/xhtml" in ctype:
        return "html"
    # Some servers send bad/missing content types. Try PDF only for .pdf.
    return "html" if not path.endswith(".pdf") else "pdf"


def normalize_manifest(raw):
    if isinstance(raw, dict):
        for key in ("sources", "data", "items", "entries"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break

    if not isinstance(raw, list):
        raise ValueError("campus_sources.json must contain a list or a dict with a list field.")

    sources = []
    for item in raw:
        if not isinstance(item, dict):
            continue

        url = item.get("url") or item.get("source_url") or item.get("link")
        domain = item.get("domain") or item.get("category") or item.get("area")
        source_id = item.get("source_id") or item.get("id") or item.get("key")
        title = item.get("title") or item.get("name") or source_id or url

        # Authenticated integrations without a public URL belong elsewhere.
        if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue

        sources.append({
            "source_id": str(source_id or hashlib.md5(url.encode()).hexdigest()[:10]),
            "domain": str(domain or "general").strip().lower(),
            "title": str(title),
            "url": canonical_url(url),
        })

    # De-duplicate identical manifest entries while preserving first ownership.
    unique = {}
    for s in sources:
        key = (s["source_id"], s["url"])
        unique.setdefault(key, s)
    return list(unique.values())


def write_record(fp, rec):
    fp.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Replace backend/knowledge after successful staging.")
    parser.add_argument("--max-links", type=int, default=20,
                        help="Maximum useful linked documents per seed source.")
    parser.add_argument("--sleep", type=float, default=0.15,
                        help="Delay between requests.")
    args = parser.parse_args()

    if not MANIFEST.exists():
        print(f"ERROR: manifest not found: {MANIFEST}")
        sys.exit(1)

    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = normalize_manifest(raw)

    if not sources:
        print("ERROR: no public URL sources found in manifest.")
        sys.exit(1)

    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    # Global text hash -> first retained record.
    seen_text = {}
    domain_counts = Counter()
    source_counts = Counter()
    source_urls = defaultdict(set)
    failures = []
    linked_inspected = 0
    boilerplate_removed = 0

    files = {}

    def domain_file(domain):
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", domain).strip("_") or "general"
        if safe not in files:
            path = STAGING / f"{safe}.jsonl"
            files[safe] = path.open("w", encoding="utf-8")
        return files[safe]

    def add_document(
        *,
        text,
        domain,
        source_id,
        source_title,
        source_url,
        document_url,
        document_title,
        section="",
        page=None,
    ):
        nonlocal boilerplate_removed

        for chunk in chunk_text(text):
            if is_probable_boilerplate(chunk):
                boilerplate_removed += 1
                continue

            h = hash_text(chunk)
            if h in seen_text:
                # True global duplicate. Keep the first provenance.
                continue

            rec = {
                "text": chunk,
                "domain": domain,
                "source_id": source_id,
                "source_title": source_title,
                "source_url": source_url,
                "document_url": document_url,
                "document_title": document_title,
                "section": section,
                "page": page,
                "ingestion_version": "v5",
            }
            seen_text[h] = rec
            write_record(domain_file(domain), rec)
            domain_counts[domain] += 1
            source_counts[source_id] += 1
            source_urls[domain].add(source_url)

    # Process each manifest source.
    for i, source in enumerate(sources, 1):
        domain = source["domain"]
        source_id = source["source_id"]
        seed_url = source["url"]

        print(f"[{i}/{len(sources)}] {domain:20} {source_id} -> {seed_url}")

        result = fetch(session, seed_url)
        if isinstance(result, tuple):
            failures.append({
                "source_id": source_id,
                "url": seed_url,
                "error": result[1],
            })
            continue

        r = result
        final_url = canonical_url(r.url)
        kind = response_kind(r, final_url)

        # Keep linked URLs only from the same site and only useful document types.
        links = []

        try:
            if kind == "pdf":
                # This catches servers that claim PDF but actually return HTML.
                content = r.content
                if content[:4] != b"%PDF":
                    # Parse as HTML instead of crashing on "invalid pdf header".
                    kind = "html"
                    title, blocks, links = extract_html(
                        content.decode(r.encoding or "utf-8", errors="ignore"),
                        final_url,
                    )
                else:
                    pages = extract_pdf(content)
                    title = source["title"]
                    blocks = []
                    for page_no, txt in pages:
                        add_document(
                            text=txt,
                            domain=domain,
                            source_id=source_id,
                            source_title=source["title"],
                            source_url=seed_url,
                            document_url=final_url,
                            document_title=title,
                            page=page_no,
                        )
            if kind == "html":
                title, blocks, links = extract_html(
                    r.text,
                    final_url,
                )
                # Group the seed page content into chunks.
                text = "\n".join(blocks)
                add_document(
                    text=text,
                    domain=domain,
                    source_id=source_id,
                    source_title=source["title"],
                    source_url=seed_url,
                    document_url=final_url,
                    document_title=title or source["title"],
                )
        except Exception as exc:
            failures.append({
                "source_id": source_id,
                "url": seed_url,
                "error": f"parse error: {exc}",
            })
            continue

        # Conservative linked-document policy:
        # - inherit the SEED DOMAIN
        # - same host only
        # - PDFs/HTML only
        # - no AI domain reassignment
        candidates = []
        for link_url, label in links:
            if not same_site(seed_url, link_url):
                continue
            ext = Path(urlparse(link_url).path).suffix.lower()
            if ext in SKIP_EXTENSIONS:
                continue
            if ext and ext not in FOLLOW_EXTENSIONS:
                continue

            # Skip obvious self links.
            if canonical_url(link_url) == final_url:
                continue

            candidates.append((link_url, label))

        # Prefer links whose labels look like actual documents.
        def link_score(item):
            url, label = item
            s = 0
            text = f"{label} {url}".lower()
            if url.lower().endswith(".pdf"):
                s += 3
            if any(k in text for k in [
                "notice", "circular", "policy", "manual", "brochure",
                "calendar", "form", "guideline", "regulation",
                "fee", "hostel", "transport", "exam", "admission",
            ]):
                s += 2
            return -s

        candidates = sorted(candidates, key=link_score)[:args.max_links]

        for link_url, label in candidates:
            linked_inspected += 1
            time.sleep(args.sleep)

            lr = fetch(session, link_url)
            if isinstance(lr, tuple):
                failures.append({
                    "source_id": source_id,
                    "url": link_url,
                    "error": lr[1],
                })
                continue

            try:
                lfinal = canonical_url(lr.url)
                lkind = response_kind(lr, lfinal)

                if lkind == "pdf":
                    if lr.content[:4] != b"%PDF":
                        # Bad PDF response; do not let it poison ingestion.
                        failures.append({
                            "source_id": source_id,
                            "url": link_url,
                            "error": "URL advertised/appeared as PDF but response was not a PDF",
                        })
                        continue

                    for page_no, txt in extract_pdf(lr.content):
                        add_document(
                            text=txt,
                            domain=domain,  # IMPORTANT: inherit seed domain
                            source_id=source_id,
                            source_title=source["title"],
                            source_url=seed_url,
                            document_url=lfinal,
                            document_title=label or Path(urlparse(lfinal).path).name,
                            page=page_no,
                        )
                else:
                    ltitle, lblocks, _ = extract_html(lr.text, lfinal)
                    add_document(
                        text="\n".join(lblocks),
                        domain=domain,  # IMPORTANT: inherit seed domain
                        source_id=source_id,
                        source_title=source["title"],
                        source_url=seed_url,
                        document_url=lfinal,
                        document_title=ltitle or label or source["title"],
                    )
            except Exception as exc:
                failures.append({
                    "source_id": source_id,
                    "url": link_url,
                    "error": f"linked parse error: {exc}",
                })

    for fp in files.values():
        fp.close()

    # Remove empty files.
    for p in STAGING.glob("*.jsonl"):
        if p.stat().st_size == 0:
            p.unlink()

    report = {
        "version": "v5",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "manifest": str(MANIFEST),
        "manifest_public_sources": len(sources),
        "total_records": sum(domain_counts.values()),
        "unique_text_chunks": len(seen_text),
        "domains": {
            d: {
                "records": domain_counts[d],
                "sources": len({
                    r["source_id"]
                    for r in seen_text.values()
                    if r["domain"] == d
                }),
            }
            for d in sorted(domain_counts)
        },
        "source_record_counts": dict(sorted(source_counts.items())),
        "linked_documents_inspected": linked_inspected,
        "boilerplate_removed": boilerplate_removed,
        "failures": failures,
        "staging": str(STAGING),
        "applied": False,
    }

    report_path = REPORT_DIR / "ingestion_v5_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    md = [
        "# CampusOne KB Ingestion V5 Report",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Public manifest sources: **{report['manifest_public_sources']}**",
        f"- Final unique records: **{report['total_records']}**",
        f"- Linked documents inspected: **{report['linked_documents_inspected']}**",
        f"- Conservative boilerplate removals: **{report['boilerplate_removed']}**",
        f"- Failures: **{len(report['failures'])}**",
        "",
        "## Domain coverage",
        "",
        "| Domain | Records | Sources |",
        "|---|---:|---:|",
    ]
    for d, info in report["domains"].items():
        md.append(f"| {d} | {info['records']} | {info['sources']} |")

    md += [
        "",
        "## V5 rules",
        "",
        "- Manifest domain is authoritative for each seed source.",
        "- Linked documents inherit the seed domain by default.",
        "- No AI/domain classifier is used during ingestion.",
        "- Global exact-text deduplication is applied.",
        "- Boilerplate filtering is conservative.",
        "- Existing `backend/knowledge` is untouched unless `--apply` is supplied.",
        "",
        "## Failures",
        "",
    ]

    if report["failures"]:
        for f in report["failures"][:200]:
            md.append(f"- `{f['source_id']}` — `{f['url']}` — {f['error']}")
    else:
        md.append("- None")

    (REPORT_DIR / "ingestion_v5_report.md").write_text(
        "\n".join(md),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print("CAMPUSONE KB INGESTION V5")
    print("=" * 72)
    print(f"Public sources:          {len(sources)}")
    print(f"Final unique records:    {sum(domain_counts.values())}")
    print(f"Linked docs inspected:   {linked_inspected}")
    print(f"Boilerplate removed:      {boilerplate_removed}")
    print(f"Failures:                 {len(failures)}")
    print("\nDOMAIN COVERAGE")
    for d in sorted(domain_counts):
        print(f"{d:22} {domain_counts[d]:6}")

    print(f"\nSTAGING: {STAGING}")
    print(f"REPORT:  {REPORT_DIR / 'ingestion_v5_report.md'}")
    print("\nDRY RUN: existing backend/knowledge was NOT modified.")

    if args.apply:
        if not any(STAGING.glob("*.jsonl")):
            print("\nERROR: staging has no JSONL files; refusing to apply.")
            sys.exit(2)

        backup_root = KNOWLEDGE.parent / "knowledge_backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = backup_root / f"knowledge_before_v5_{stamp}"

        if KNOWLEDGE.exists():
            shutil.copytree(KNOWLEDGE, backup)

        new_knowledge = KNOWLEDGE.parent / "knowledge_v5_applied"
        if new_knowledge.exists():
            shutil.rmtree(new_knowledge)
        shutil.copytree(STAGING, new_knowledge)

        if KNOWLEDGE.exists():
            shutil.rmtree(KNOWLEDGE)
        new_knowledge.rename(KNOWLEDGE)

        report["applied"] = True
        report["backup"] = str(backup)
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print(f"\nAPPLIED V5 KB.")
        print(f"Backup: {backup}")
    else:
        print("\nNo changes applied. Review the report before using --apply.")


if __name__ == "__main__":
    main()
