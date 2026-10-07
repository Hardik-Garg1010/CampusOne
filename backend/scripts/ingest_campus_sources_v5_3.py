"""
CampusOne KB Ingestion V5.3
===========================
V5.3 fixes the concrete problems found in V5:

1. PDF parsing:
   pypdf.PdfReader needs a seekable stream. V5 passed raw bytes, producing
   hundreds of "'bytes' object has no attribute 'seek'" failures.
   V5.3 wraps downloaded PDF bytes with io.BytesIO.

2. Integration entries:
   ERP/LMS/library-account/helpdesk entries are authenticated integrations,
   not public RAG sources. They are reported separately and are not crawled.

3. Linked-document fan-out:
   Registrar/index pages can expose hundreds of unrelated documents.
   V5.3 only follows links whose visible label or filename is relevant to
   the seed source domain, while preserving the seed domain as ownership.

4. Deduplication:
   Exact duplicate chunks are removed within each domain, but identical source
   documents are tracked separately in the report so we can see coverage.

5. Conservative extraction:
   Navigation filtering is kept small. We do not discard whole pages merely
   because individual fragments are short.

6. Safe staging:
   Existing backend/knowledge is untouched unless --apply is supplied.

Usage:
  python scripts\ingest_campus_sources_v5_2.py
  python scripts\ingest_campus_sources_v5_2.py --apply
"""

from __future__ import annotations

import argparse
import hashlib
import io
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
STAGING = ROOT / "backend" / "knowledge_v5_3_staging"
REPORT_DIR = ROOT / "backend" / "data" / "ingestion_reports"

TIMEOUT = 25
MIN_CHARS = 60
MAX_CHARS = 2200
OVERLAP = 180

INTEGRATION_DOMAINS = {"integrations", "integration"}
INTEGRATION_IDS = {"erp", "lms", "library_account", "helpdesk"}

BOILERPLATE_EXACT = {
    "skip to content", "skip to main content", "menu", "search",
    "close", "loading", "read more", "learn more", "click here",
}

SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".mp4", ".mp3", ".zip", ".rar", ".7z",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}

FOLLOW_EXTENSIONS = {".pdf", ".html", ".htm"}

DOMAIN_KEYWORDS = {
    "admission": [
        "admission", "eligibility", "selection", "application", "scholarship",
        "bule t", "bule t", "entrance", "prospectus", "applicant",
    ],
    "it": [
        "it", "information technology", "lms", "password", "email",
        "wifi", "wi-fi", "helpdesk", "help desk", "intranet",
        "university management", "ums", "telephone directory",
    ],
    "library": [
        "library", "lrc", "circulation", "borrowing", "e-resource",
        "database", "mobile app", "user guide",
    ],
    "fees": [
        "fee", "fees", "refund", "payment", "education loan",
        "tuition", "withdrawal", "no dues",
    ],
    "hostel": [
        "hostel", "residence", "residential", "accommodation",
        "mess", "off-campus",
    ],
    "transport": [
        "transport", "bus", "shuttle", "route", "vehicle",
    ],
    "academics": [
        "academic", "academics", "calendar", "ordinance", "regulation",
        "curriculum", "credit", "semester", "program",
    ],
    "examinations": [
        "exam", "examination", "date sheet", "seating plan", "re-evaluation",
        "revaluation", "scribe", "result", "end term",
    ],
    "student_affairs": [
        "student affairs", "student life", "grievance", "nss",
        "social extension", "clubs", "counselling",
    ],
    "health": [
        "health", "wellness", "medical", "clinic", "ambulance",
    ],
    "sports": [
        "sport", "sports", "fitness", "stadium", "complex",
    ],
    "campus_services": [
        "student services", "infrastructure", "campus services",
        "dining", "shopping", "atm",
    ],
    "security": [
        "security", "anti-ragging", "ragging", "safety", "emergency",
    ],
    "career": [
        "career", "placement", "internship", "recruitment",
        "career counselling", "employer",
    ],
    "policies": [
        "policy", "policies", "iqac", "code of conduct", "guideline",
        "ordinance", "regulation",
    ],
}

# For index pages, only follow links that have an obvious relationship to
# the seed's domain. This avoids dumping every Registrar notice into every
# domain that references the Registrar index.
FOLLOW_ALWAYS_IDS = {
    "admission_home", "application_process", "eligibility_selection",
    "fee_structure", "scholarships", "faqs",
    "examination_department", "library_home", "library_mobile_app",
    "placements", "placement_contact", "student_affairs",
    "grievance_portal", "nss", "sports_complex", "student_life_sports",
    "campus_security", "anti_ragging",
}

# Broad index sources are useful, but should not automatically ingest every
# linked PDF.
INDEX_IDS = {
    "registrar_notices", "refund_policy", "refund_policies",
    "it_policy", "hostel_policies", "ordinances_policies",
    "sports_policy", "placement_policy", "internship_policies",
    "academic_documents", "student_conduct", "iqac_policies",
    "safety_policies",
}


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def canonical_url(url: str) -> str:
    url, _ = urldefrag(url)
    p = urlparse(url)
    return p._replace(
        scheme=p.scheme.lower(),
        netloc=p.netloc.lower(),
        path=(p.path.rstrip("/") or "/"),
        fragment="",
    ).geturl()


def same_site(a: str, b: str) -> bool:
    x = urlparse(a).netloc.lower().replace("www.", "")
    y = urlparse(b).netloc.lower().replace("www.", "")
    return x == y and bool(x)


def hash_text(text: str) -> str:
    normalized = re.sub(r"\W+", " ", text.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_boilerplate(text: str) -> bool:
    t = clean_text(text)
    if len(t) < MIN_CHARS:
        return True
    low = t.lower()
    if low in BOILERPLATE_EXACT:
        return True
    # Do not remove normal paragraphs just because they are short/repetitive.
    return False


def chunk_text(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []

    if len(text) <= MAX_CHARS:
        return [text] if len(text) >= MIN_CHARS else []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + MAX_CHARS, len(text))
        if end < len(text):
            candidates = [
                text.rfind(". ", start, end),
                text.rfind("; ", start, end),
                text.rfind(" ", start, end),
            ]
            boundary = max(candidates)
            if boundary > start + int(MAX_CHARS * 0.55):
                end = boundary + 1

        piece = clean_text(text[start:end])
        if len(piece) >= MIN_CHARS:
            chunks.append(piece)

        if end >= len(text):
            break
        start = max(start + 1, end - OVERLAP)

    return chunks


def extract_html(html: str, page_url: str):
    soup = BeautifulSoup(html, "lxml")

    for tag in soup([
        "script", "style", "noscript", "svg", "iframe",
        "form", "nav", "footer",
    ]):
        tag.decompose()

    title = clean_text(
        soup.title.get_text(" ", strip=True)
    ) if soup.title else ""

    blocks = []
    for node in soup.find_all([
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "li", "td", "th", "blockquote",
    ]):
        txt = clean_text(node.get_text(" ", strip=True))
        if not txt:
            continue
        if is_boilerplate(txt):
            continue
        blocks.append(txt)

    # Preserve page order and combine tiny adjacent fragments.
    merged = []
    for block in blocks:
        if merged and len(merged[-1]) < 180 and len(block) < 320:
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
    # CRITICAL FIX: pypdf needs a seekable file-like object.
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for page_no, page in enumerate(reader.pages, 1):
        try:
            text = clean_text(page.extract_text() or "")
        except Exception:
            text = ""
        if text:
            pages.append((page_no, text))
    return pages


def fetch(session: requests.Session, url: str):
    try:
        r = session.get(
            url,
            timeout=TIMEOUT,
            headers={"User-Agent": "CampusOne-KB-Ingestion/5.1"},
            allow_redirects=True,
        )
        r.raise_for_status()
        return r
    except Exception as exc:
        return None, str(exc)


def response_kind(r) -> str:
    ctype = (r.headers.get("content-type") or "").lower()
    path = urlparse(r.url).path.lower()
    if "application/pdf" in ctype or path.endswith(".pdf"):
        return "pdf"
    return "html"


def normalize_manifest(raw):
    if isinstance(raw, dict):
        for key in ("sources", "data", "items", "entries"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break

    if not isinstance(raw, list):
        raise ValueError("campus_sources.json must contain a list or a list field.")

    sources = []
    for item in raw:
        if not isinstance(item, dict):
            continue

        url = item.get("url") or item.get("source_url") or item.get("link")
        domain = item.get("domain") or item.get("category") or item.get("area")
        source_id = item.get("source_id") or item.get("id") or item.get("key")
        title = item.get("title") or item.get("name") or source_id or url

        if not url or not isinstance(url, str):
            continue
        if not url.startswith(("http://", "https://")):
            continue

        domain = str(domain or "general").strip().lower()
        source_id = str(source_id or hashlib.md5(url.encode()).hexdigest()[:10])

        sources.append({
            "source_id": source_id,
            "domain": domain,
            "title": str(title),
            "url": canonical_url(url),
        })

    unique = {}
    for s in sources:
        unique[(s["source_id"], s["url"])] = s
    return list(unique.values())


def link_is_relevant(source, link_url, label):
    source_id = source["source_id"]
    if source_id in FOLLOW_ALWAYS_IDS:
        return True

    text = f"{label} {Path(urlparse(link_url).path).name}".lower()
    domain = source["domain"]
    keys = DOMAIN_KEYWORDS.get(domain, [])

    # For broad Registrar/IQAC index pages, require an explicit domain signal.
    if source_id in INDEX_IDS:
        return any(k in text for k in keys)

    # Normal pages can follow PDFs/HTML, but still avoid obviously unrelated
    # document titles.
    if not keys:
        return True
    return any(k in text for k in keys)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-links", type=int, default=25)
    parser.add_argument("--sleep", type=float, default=0.15)
    args = parser.parse_args()

    if not MANIFEST.exists():
        print(f"ERROR: manifest not found: {MANIFEST}")
        sys.exit(1)

    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    all_sources = normalize_manifest(raw)

    public_sources = []
    skipped_integrations = []

    for s in all_sources:
        if (
            s["domain"] in INTEGRATION_DOMAINS
            or s["source_id"] in INTEGRATION_IDS
        ):
            skipped_integrations.append(s)
        else:
            public_sources.append(s)

    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    files = {}
    seen_text = {}
    cross_domain_text = defaultdict(set)
    cross_url_text = defaultdict(set)
    domain_counts = Counter()
    source_counts = Counter()
    source_documents = defaultdict(set)
    failures = []
    failure_types = Counter()
    linked_inspected = 0
    links_skipped_irrelevant = 0
    boilerplate_removed = 0

    def domain_file(domain):
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", domain).strip("_") or "general"
        if safe not in files:
            files[safe] = (STAGING / f"{safe}.jsonl").open(
                "w", encoding="utf-8"
            )
        return files[safe]

    def add_record(
        *,
        text, source, document_url, document_title, page=None,
    ):
        nonlocal boilerplate_removed

        for chunk in chunk_text(text):
            if is_boilerplate(chunk):
                boilerplate_removed += 1
                continue

            h = hash_text(chunk)
            source_documents[source["source_id"]].add(document_url)

            # V5.3: track repeated chunks across domains/URLs so obvious
            # website-wide navigation can be filtered without removing
            # legitimate shared official content.
            cross_domain_text[h].add(source["domain"])
            cross_url_text[h].add(document_url)

            low = chunk.lower()
            generic_nav_signals = (
                "toll free no", "admission process", "hostel lateral entry",
                "fee ay 2026-27 overview", "download brochure", "international",
            )
            generic_nav = (
                len(low) > 250
                and sum(1 for sig in generic_nav_signals if sig in low) >= 2
            )
            if generic_nav:
                boilerplate_removed += 1
                continue

            # Deduplicate only within the owning domain. The same official
            # page may legitimately be mapped to multiple domains in the
            # manifest (for example fees + admission), so global dedup would
            # incorrectly delete valid domain coverage.
            seen_key = (source["domain"], h)
            if seen_key in seen_text:
                continue

            rec = {
                "text": chunk,
                "domain": source["domain"],
                "source_id": source["source_id"],
                "source_title": source["title"],
                "source_url": source["url"],
                "document_url": document_url,
                "document_title": document_title,
                "page": page,
                "ingestion_version": "v5.3",
            }
            seen_text[seen_key] = rec

            fp = domain_file(source["domain"])
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            domain_counts[source["domain"]] += 1
            source_counts[source["source_id"]] += 1

    for idx, source in enumerate(public_sources, 1):
        print(
            f"[{idx}/{len(public_sources)}] "
            f"{source['domain']:20} {source['source_id']} -> {source['url']}"
        )

        result = fetch(session, source["url"])
        if isinstance(result, tuple):
            failures.append({
                "source_id": source["source_id"],
                "url": source["url"],
                "error": result[1],
            })
            failure_types["request"] += 1
            continue

        r = result
        final_url = canonical_url(r.url)
        kind = response_kind(r)

        links = []
        try:
            if kind == "pdf":
                # Prevent HTML masquerading as a PDF.
                if not r.content.startswith(b"%PDF"):
                    failures.append({
                        "source_id": source["source_id"],
                        "url": source["url"],
                        "error": "response identified as PDF but bytes did not start with %PDF",
                    })
                    failure_types["invalid_pdf_response"] += 1
                    continue

                for page_no, txt in extract_pdf(r.content):
                    add_record(
                        text=txt,
                        source=source,
                        document_url=final_url,
                        document_title=source["title"],
                        page=page_no,
                    )
            else:
                title, blocks, links = extract_html(r.text, final_url)
                add_record(
                    text="\n".join(blocks),
                    source=source,
                    document_url=final_url,
                    document_title=title or source["title"],
                )
        except Exception as exc:
            failures.append({
                "source_id": source["source_id"],
                "url": source["url"],
                "error": f"parse error: {exc}",
            })
            failure_types["parse"] += 1
            continue

        # Select linked docs conservatively.
        candidates = []
        for link_url, label in links:
            if not same_site(source["url"], link_url):
                continue

            ext = Path(urlparse(link_url).path).suffix.lower()
            if ext in SKIP_EXTENSIONS:
                continue
            if ext and ext not in FOLLOW_EXTENSIONS:
                continue
            if canonical_url(link_url) == final_url:
                continue

            if not link_is_relevant(source, link_url, label):
                links_skipped_irrelevant += 1
                continue

            score = 0
            text = f"{label} {link_url}".lower()
            if ext == ".pdf":
                score += 3
            if any(k in text for k in DOMAIN_KEYWORDS.get(source["domain"], [])):
                score += 3
            if label:
                score += 1
            candidates.append((score, link_url, label))

        candidates.sort(reverse=True)
        candidates = candidates[:args.max_links]

        for _, link_url, label in candidates:
            linked_inspected += 1
            time.sleep(args.sleep)

            lr = fetch(session, link_url)
            if isinstance(lr, tuple):
                failures.append({
                    "source_id": source["source_id"],
                    "url": link_url,
                    "error": lr[1],
                })
                failure_types["linked_request"] += 1
                continue

            lfinal = canonical_url(lr.url)
            lkind = response_kind(lr)

            try:
                if lkind == "pdf":
                    if not lr.content.startswith(b"%PDF"):
                        failures.append({
                            "source_id": source["source_id"],
                            "url": link_url,
                            "error": "linked response identified as PDF but bytes did not start with %PDF",
                        })
                        failure_types["invalid_linked_pdf"] += 1
                        continue

                    for page_no, txt in extract_pdf(lr.content):
                        add_record(
                            text=txt,
                            source=source,
                            document_url=lfinal,
                            document_title=label or Path(
                                urlparse(lfinal).path
                            ).name,
                            page=page_no,
                        )
                else:
                    title, blocks, _ = extract_html(lr.text, lfinal)
                    add_record(
                        text="\n".join(blocks),
                        source=source,
                        document_url=lfinal,
                        document_title=title or label or source["title"],
                    )
            except Exception as exc:
                failures.append({
                    "source_id": source["source_id"],
                    "url": link_url,
                    "error": f"linked parse error: {exc}",
                })
                failure_types["linked_parse"] += 1

    for fp in files.values():
        fp.close()

    for p in STAGING.glob("*.jsonl"):
        if p.stat().st_size == 0:
            p.unlink()

    report = {
        "version": "v5.3",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "manifest": str(MANIFEST),
        "manifest_sources_total": len(all_sources),
        "public_sources": len(public_sources),
        "skipped_authenticated_integrations": len(skipped_integrations),
        "integration_ids_skipped": [
            s["source_id"] for s in skipped_integrations
        ],
        "total_records": len(seen_text),
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
        "source_document_counts": {
            sid: len(urls) for sid, urls in sorted(source_documents.items())
        },
        "linked_documents_inspected": linked_inspected,
        "links_skipped_irrelevant": links_skipped_irrelevant,
        "boilerplate_removed": boilerplate_removed,
        "cross_domain_duplicate_groups": sum(1 for domains in cross_domain_text.values() if len(domains) > 1),
        "cross_url_duplicate_groups": sum(1 for urls in cross_url_text.values() if len(urls) > 1),
        "failure_count": len(failures),
        "failure_types": dict(failure_types),
        "failures": failures,
        "staging": str(STAGING),
        "applied": False,
    }

    report_json = REPORT_DIR / "ingestion_v5_2_report.json"
    report_md = REPORT_DIR / "ingestion_v5_2_report.md"

    report_json.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        "# CampusOne KB Ingestion V5.3 Report",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Manifest sources: **{report['manifest_sources_total']}**",
        f"- Public sources crawled: **{report['public_sources']}**",
        f"- Authenticated integrations skipped: **{report['skipped_authenticated_integrations']}**",
        f"- Final unique records: **{report['total_records']}**",
        f"- Linked documents inspected: **{report['linked_documents_inspected']}**",
        f"- Irrelevant links skipped: **{report['links_skipped_irrelevant']}**",
        f"- Boilerplate fragments removed: **{report['boilerplate_removed']}**",
        f"- Failures: **{report['failure_count']}**",
        "",
        "## Domain coverage",
        "",
        "| Domain | Records | Sources |",
        "|---|---:|---:|",
    ]

    for d, info in report["domains"].items():
        lines.append(f"| {d} | {info['records']} | {info['sources']} |")

    lines += [
        "",
        "## Failure types",
        "",
    ]

    if failure_types:
        for k, v in sorted(failure_types.items()):
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("- None")

    lines += [
        "",
        "## V5.3 rules",
        "",
        "- Manifest domain is authoritative.",
        "- Authenticated integrations are not treated as public RAG content.",
        "- PDF bytes are parsed through `io.BytesIO`.",
        "- Linked documents inherit the seed source domain.",
        "- Broad index pages follow only domain-relevant links.",
        "- Exact text is deduplicated within each domain. The same content may remain in multiple domains when the manifest explicitly maps an authoritative source to those domains.",
        "- Existing `backend/knowledge` is untouched during dry run.",
        "",
        "## First failures",
        "",
    ]

    for f in failures[:100]:
        lines.append(
            f"- `{f['source_id']}` — `{f['url']}` — {f['error']}"
        )

    report_md.write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "=" * 72)
    print("CAMPUSONE KB INGESTION V5.3")
    print("=" * 72)
    print(f"Manifest sources:          {len(all_sources)}")
    print(f"Public sources crawled:    {len(public_sources)}")
    print(f"Integrations skipped:      {len(skipped_integrations)}")
    print(f"Final unique records:      {len(seen_text)}")
    print(f"Linked docs inspected:     {linked_inspected}")
    print(f"Irrelevant links skipped:  {links_skipped_irrelevant}")
    print(f"Boilerplate removed:       {boilerplate_removed}")
    print(f"Failures:                  {len(failures)}")

    print("\nDOMAIN COVERAGE")
    for d in sorted(domain_counts):
        print(f"{d:22} {domain_counts[d]:6}")

    print("\nFAILURE TYPES")
    for k, v in sorted(failure_types.items()):
        print(f"{k:28} {v:6}")

    print(f"\nSTAGING: {STAGING}")
    print(f"REPORT:  {report_md}")
    print("\nDRY RUN: existing backend\\knowledge was NOT modified.")

    if args.apply:
        if not any(STAGING.glob("*.jsonl")):
            print("ERROR: staging contains no JSONL files; refusing to apply.")
            sys.exit(2)

        backup_root = KNOWLEDGE.parent / "knowledge_backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = backup_root / f"knowledge_before_v5_3_{stamp}"

        if KNOWLEDGE.exists():
            shutil.copytree(KNOWLEDGE, backup)

        new_knowledge = KNOWLEDGE.parent / "knowledge_v5_3_applied"
        if new_knowledge.exists():
            shutil.rmtree(new_knowledge)
        shutil.copytree(STAGING, new_knowledge)

        if KNOWLEDGE.exists():
            shutil.rmtree(KNOWLEDGE)
        new_knowledge.rename(KNOWLEDGE)

        report["applied"] = True
        report["backup"] = str(backup)
        report_json.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print("\nV5.3 APPLIED.")
        print(f"Backup: {backup}")


if __name__ == "__main__":
    main()
