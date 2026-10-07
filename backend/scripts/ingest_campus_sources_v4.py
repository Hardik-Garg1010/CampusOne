"""
CampusOne — Bennett University KB Ingestion v4
----------------------------------------------
Goals:
1. Fetch only official Bennett sources from the existing campus_sources.json manifest.
2. Extract meaningful page/document content while suppressing navigation/footer boilerplate.
3. Follow linked PDFs, but classify each document using its title/URL/content instead of
   blindly assigning it to the domain that discovered it.
4. Deduplicate globally BEFORE writing domain files.
5. Keep a single primary domain for each canonical content chunk.
6. Preserve source URL, source_id, title, section, document URL, and academic-year hints.
7. Write to a staging directory first. Existing backend/knowledge is never overwritten
   unless --apply is explicitly supplied.

Usage from backend:
    python scripts\ingest_campus_sources_v4.py
    python scripts\ingest_campus_sources_v4.py --apply

Dependencies:
    pip install requests beautifulsoup4 lxml pypdf
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "campus_sources.json"
KNOWLEDGE = ROOT / "knowledge"
STAGING = ROOT / "knowledge_v4_staging"
REPORT_DIR = ROOT / "data" / "ingestion_reports"

TIMEOUT = 25
MAX_PDF_BYTES = 15_000_000
MAX_LINKED_DOCS_PER_SOURCE = 80

CANONICAL_DOMAINS = [
    "admission", "it", "library", "fees", "hostel", "transport",
    "academics", "examinations", "student_affairs", "health", "sports",
    "campus_services", "security", "career", "policies", "facilities",
]

DOMAIN_ALIASES = {
    "admissions": "admission",
    "student_affairs": "student_affairs",
    "student-affairs": "student_affairs",
    "exam": "examinations",
    "exams": "examinations",
    "campus": "campus_services",
    "placement": "career",
    "placements": "career",
}

# Strong domain indicators. These are not question examples; they are document
# classification vocabulary used to keep linked documents in the correct domain.
DOMAIN_TERMS = {
    "admission": [
        "admission", "applicant", "application", "eligibility", "selection",
        "entrance", "bule t", "bule t", "cuet", "clat", "scholarship",
        "international admission", "prospectus", "application form",
    ],
    "it": [
        "wifi", "wi-fi", "helpdesk", "it helpdesk", "password reset",
        "lms support", "office 365", "student login", "erp portal",
        "email", "microsoft 365", "turnitin", "technical support",
    ],
    "library": [
        "library", "lrc", "learning resource centre", "circulation",
        "borrowing", "return", "renewal", "inter-library", "e-journal",
        "ebook", "e-book", "database", "research support", "turnitin",
    ],
    "fees": [
        "fee", "fees", "tuition", "semester fee", "refund", "payment",
        "hostel fee", "transport fee", "financial", "installment",
    ],
    "hostel": [
        "hostel", "residence", "residential", "room", "mess", "warden",
        "accommodation", "hostel fee", "resident",
    ],
    "transport": [
        "transport", "bus", "route", "shuttle", "day scholar", "pick-up",
        "drop", "vehicle", "transportation",
    ],
    "academics": [
        "academic", "curriculum", "course", "credit", "semester",
        "registration", "programme", "program", "attendance", "grading",
        "faculty", "department",
    ],
    "examinations": [
        "examination", "exam", "result", "re-evaluation", "revaluation",
        "seating plan", "scribe", "exam form", "grade", "end semester",
    ],
    "student_affairs": [
        "student affairs", "student welfare", "grievance", "nss",
        "student activity", "club", "counselling", "counseling",
        "anti-ragging", "student support",
    ],
    "health": [
        "health", "medical", "wellness centre", "wellness center",
        "doctor", "ambulance", "clinic", "medical facility", "counsellor",
        "counselor",
    ],
    "sports": [
        "sport", "sports", "stadium", "gym", "fitness", "cricket",
        "football", "basketball", "badminton", "swimming", "athletic",
    ],
    "campus_services": [
        "campus services", "dining", "cafeteria", "shopping", "atm",
        "food court", "convenience", "campus facility",
    ],
    "security": [
        "security", "safety", "emergency", "security office", "guard",
        "lost and found", "access control", "incident",
    ],
    "career": [
        "career", "placement", "recruiter", "internship", "corporate",
        "employer", "training and placement", "t&p", "job",
    ],
    "policies": [
        "policy", "policies", "code of conduct", "regulation", "rules",
        "ordinance", "anti-ragging", "sexual harassment", "privacy policy",
    ],
    "facilities": [
        "facility", "facilities", "classroom", "air conditioning", "maintenance",
        "infrastructure", "laboratory", "lab", "building", "repair",
    ],
}

BOILERPLATE_PATTERNS = [
    r"\bclick here\b",
    r"\bread more\b",
    r"\bsearch\b",
    r"\bmenu\b",
    r"\bhome\s*\|\s*about\b",
    r"\bprivacy policy\b",
    r"\bterms and conditions\b",
    r"\bcopyright\b",
    r"\ball rights reserved\b",
    r"\bsubscribe\b",
]

NOISE_LINE_PATTERNS = [
    re.compile(r"^\s*(home|menu|search)\s*$", re.I),
    re.compile(r"^\s*(read more|click here)\s*$", re.I),
    re.compile(r"^\s*(privacy policy|terms and conditions)\s*$", re.I),
    re.compile(r"^\s*(facebook|instagram|linkedin|youtube|twitter|x)\s*$", re.I),
]

YEAR_RE = re.compile(r"\b(?:AY|Academic Year|Session|Semester)\s*[:\-]?\s*(20\d{2})\s*[-/]\s*(20\d{2})\b", re.I)
YEAR_RE2 = re.compile(r"\b(20\d{2})\s*[-/]\s*(20\d{2})\b")


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if any(p.search(line) for p in NOISE_LINE_PATTERNS):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def canonical_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9%₹$.,:/\- ]+", "", text)
    return text.strip()


def sha(text: str) -> str:
    return hashlib.sha256(canonical_text(text).encode("utf-8")).hexdigest()


def boilerplate_score(text: str) -> int:
    low = text.lower()
    return sum(bool(re.search(p, low)) for p in BOILERPLATE_PATTERNS)


def fetch(url: str, session: requests.Session):
    try:
        r = session.get(url, timeout=TIMEOUT, headers={
            "User-Agent": "CampusOne-KB-Ingestion/4.0"
        })
        r.raise_for_status()
        return r
    except Exception as e:
        return None


def extract_html(url: str, html: bytes):
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()

    # Remove obvious site chrome.
    for tag in soup.select("nav, footer, header, .menu, .navbar, .footer, .header"):
        tag.decompose()

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", class_=re.compile(r"(content|page-content|entry-content|post-content)", re.I))
        or soup.body
    )

    if not main:
        return title, "", []

    links = []
    for a in main.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if urlparse(href).netloc.endswith("bennett.edu.in"):
            links.append((a.get_text(" ", strip=True), href))

    # Preserve headings as section boundaries.
    blocks = []
    for node in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"]):
        txt = node.get_text(" ", strip=True)
        if not txt:
            continue
        if node.name == "table":
            rows = []
            for tr in node.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if cells:
                    rows.append(" | ".join(cells))
            txt = "\n".join(rows)
        blocks.append((node.name, txt))

    return title, blocks, links


def extract_pdf(url: str, content: bytes):
    if PdfReader is None:
        return "", "pypdf not installed"
    if len(content) > MAX_PDF_BYTES:
        return "", "pdf too large"
    try:
        import io
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pages.append("")
        return clean_text("\n\n".join(pages)), ""
    except Exception as e:
        return "", str(e)


def section_chunks(title: str, blocks, chunk_chars=1800, overlap=250):
    chunks = []
    current_section = title or "General"
    current = []

    def flush():
        nonlocal current
        if not current:
            return
        text = clean_text("\n".join(current))
        if len(text) >= 120:
            if len(text) <= chunk_chars:
                chunks.append((current_section, text))
            else:
                start = 0
                while start < len(text):
                    end = min(len(text), start + chunk_chars)
                    piece = text[start:end].strip()
                    if len(piece) >= 120:
                        chunks.append((current_section, piece))
                    if end >= len(text):
                        break
                    start = max(start + 1, end - overlap)
        current = []

    for kind, txt in blocks:
        if kind in ("h1", "h2", "h3", "h4"):
            flush()
            current_section = txt[:220]
        else:
            current.append(txt)
            if sum(len(x) for x in current) >= chunk_chars:
                flush()

    flush()
    return chunks


def score_domain(domain: str, text: str, url: str, title: str):
    blob = f"{title} {url} {text}".lower()
    score = 0
    for term in DOMAIN_TERMS.get(domain, []):
        if term in blob:
            score += 1 + (1 if term in title.lower() else 0)
    return score


def classify_document(seed_domain: str, source_title: str, doc_url: str, doc_title: str, text: str):
    scores = {
        d: score_domain(d, text, doc_url, doc_title or source_title)
        for d in CANONICAL_DOMAINS
    }

    # The manifest's seed domain is a tie-breaker, not an unconditional assignment.
    scores[seed_domain] += 1

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_domain, top_score = ranked[0]
    second_score = ranked[1][1]

    # Generic Bennett pages/documents should remain in the seed domain when no
    # meaningful domain evidence exists.
    if top_score <= 1:
        return seed_domain, scores

    # Avoid arbitrary reassignment when evidence is weak.
    if top_score == second_score:
        return seed_domain, scores

    return top_domain, scores


def source_items(manifest):
    # Supports both the current list format and a dict containing "sources".
    if isinstance(manifest, list):
        return manifest
    if isinstance(manifest, dict):
        return manifest.get("sources", [])
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="replace backend/knowledge with the cleaned v4 KB after a successful build")
    ap.add_argument("--max-linked-docs", type=int, default=MAX_LINKED_DOCS_PER_SOURCE)
    args = ap.parse_args()

    if not MANIFEST.exists():
        raise SystemExit(f"Manifest not found: {MANIFEST}")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = source_items(manifest)

    STAGING.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Always start with a clean staging area.
    for p in STAGING.glob("*"):
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()

    session = requests.Session()

    records = []
    seen_hashes = {}
    stats = Counter()
    failures = []
    linked_seen = set()

    for src in sources:
        seed_domain = DOMAIN_ALIASES.get(
            str(src.get("domain", "")).strip().lower(),
            str(src.get("domain", "")).strip().lower()
        )
        if seed_domain not in CANONICAL_DOMAINS:
            continue

        source_id = str(src.get("source_id") or src.get("id") or "")
        source_url = str(src.get("url") or src.get("source_url") or "")
        source_title = str(src.get("title") or source_id)

        if not source_url:
            continue

        # Authenticated integrations are intentionally not public-RAG sources.
        if src.get("access") == "authenticated" or src.get("authenticated") is True:
            stats["authenticated_skipped"] += 1
            continue

        stats["sources_attempted"] += 1
        r = fetch(source_url, session)
        if not r:
            failures.append({"source_id": source_id, "url": source_url, "reason": "fetch failed"})
            continue

        ctype = r.headers.get("content-type", "").lower()
        is_pdf = source_url.lower().split("?")[0].endswith(".pdf") or "application/pdf" in ctype

        documents = [(source_url, source_title, "", [])]
        discovered_links = []

        if is_pdf:
            pdf_text, err = extract_pdf(source_url, r.content)
            if err:
                failures.append({"source_id": source_id, "url": source_url, "reason": err})
            else:
                documents = [(source_url, source_title, pdf_text, None)]
        else:
            title, blocks, links = extract_html(source_url, r.content)
            documents = [(source_url, title or source_title, blocks, blocks)]
            discovered_links = links[:args.max_linked_docs]

        for doc_url, doc_title, payload, _ in documents:
            if isinstance(payload, list):
                chunks = section_chunks(doc_title, payload)
                full_text = "\n".join(x[1] for x in chunks)
            else:
                full_text = payload
                chunks = [("Document", payload)] if len(payload) >= 120 else []

            if not chunks:
                stats["documents_without_content"] += 1
            else:
                stats["documents_with_content"] += 1

            domain, scores = classify_document(
                seed_domain, source_title, doc_url, doc_title, full_text
            )

            for section, chunk in chunks:
                content = clean_text(chunk)
                if len(content) < 120:
                    continue

                h = sha(content)
                if h in seen_hashes:
                    stats["duplicates_removed"] += 1
                    continue

                seen_hashes[h] = (domain, source_id, doc_url)

                years = YEAR_RE.findall(f"{doc_title}\n{content}")
                if not years:
                    years = YEAR_RE2.findall(f"{doc_title}\n{content}")

                records.append({
                    "text": content,
                    "domain": domain,
                    "source_id": source_id,
                    "source_url": source_url,
                    "document_url": doc_url,
                    "title": doc_title,
                    "section": section,
                    "academic_year": years[0] if years else None,
                    "content_hash": h,
                    "discovered_from_domain": seed_domain,
                    "domain_scores": scores,
                })
                stats[f"records_{domain}"] += 1

        # Follow only official Bennett linked PDFs/pages, with strong limits.
        for link_text, link_url in discovered_links:
            clean_url = link_url.split("#")[0]
            if clean_url in linked_seen or clean_url == source_url:
                continue
            parsed = urlparse(clean_url)
            if not parsed.netloc.endswith("bennett.edu.in"):
                continue

            # Only follow document-like resources or clearly content pages.
            path = parsed.path.lower()
            looks_like_doc = (
                path.endswith(".pdf")
                or any(k in path for k in [
                    "/notice", "/notices", "/circular", "/document", "/download",
                    "/policy", "/academic", "/exam", "/hostel", "/library",
                    "/placement", "/career", "/admission", "/fee"
                ])
            )
            if not looks_like_doc:
                continue

            linked_seen.add(clean_url)
            rr = fetch(clean_url, session)
            if not rr:
                continue

            ct = rr.headers.get("content-type", "").lower()
            linked_pdf = clean_url.lower().endswith(".pdf") or "application/pdf" in ct

            if linked_pdf:
                txt, err = extract_pdf(clean_url, rr.content)
                if err or len(txt) < 120:
                    continue
                linked_chunks = [("Document", txt)]
                linked_title = link_text.strip() or Path(parsed.path).stem
            else:
                linked_title, linked_blocks, _ = extract_html(clean_url, rr.content)
                linked_chunks = section_chunks(linked_title, linked_blocks)

            full_linked_text = "\n".join(x[1] for x in linked_chunks)
            domain, scores = classify_document(
                seed_domain, source_title, clean_url, linked_title, full_linked_text
            )

            for section, chunk in linked_chunks:
                content = clean_text(chunk)
                if len(content) < 120:
                    continue
                h = sha(content)
                if h in seen_hashes:
                    stats["duplicates_removed"] += 1
                    continue
                seen_hashes[h] = (domain, source_id, clean_url)

                years = YEAR_RE.findall(f"{linked_title}\n{content}") or YEAR_RE2.findall(
                    f"{linked_title}\n{content}"
                )

                records.append({
                    "text": content,
                    "domain": domain,
                    "source_id": source_id,
                    "source_url": source_url,
                    "document_url": clean_url,
                    "title": linked_title,
                    "section": section,
                    "academic_year": years[0] if years else None,
                    "content_hash": h,
                    "discovered_from_domain": seed_domain,
                    "domain_scores": scores,
                })
                stats[f"records_{domain}"] += 1

        time.sleep(0.05)

    # Remove chunks with obvious boilerplate signals.
    before = len(records)
    records = [r for r in records if boilerplate_score(r["text"]) <= 1]
    stats["boilerplate_removed"] = before - len(records)

    # Sort for reproducibility.
    records.sort(key=lambda r: (r["domain"], r["source_id"], r["document_url"], r["section"], r["content_hash"]))

    # Write staging KB.
    by_domain = defaultdict(list)
    for r in records:
        by_domain[r["domain"]].append(r)

    for domain in CANONICAL_DOMAINS:
        items = by_domain.get(domain, [])
        if not items:
            continue
        d = STAGING / domain
        d.mkdir(parents=True, exist_ok=True)
        out = d / f"bennett_{domain}_kb.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    report = {
        "total_records": len(records),
        "sources_attempted": stats["sources_attempted"],
        "authenticated_skipped": stats["authenticated_skipped"],
        "documents_with_content": stats["documents_with_content"],
        "documents_without_content": stats["documents_without_content"],
        "duplicates_removed": stats["duplicates_removed"],
        "boilerplate_removed": stats["boilerplate_removed"],
        "records_by_domain": {d: len(by_domain.get(d, [])) for d in CANONICAL_DOMAINS},
        "unique_sources_by_domain": {
            d: len({x["source_id"] for x in by_domain.get(d, [])})
            for d in CANONICAL_DOMAINS
        },
        "failures": failures,
        "linked_documents_seen": len(linked_seen),
        "staging_path": str(STAGING),
    }

    (REPORT_DIR / "ingestion_v4_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    lines = [
        "# CampusOne KB Ingestion v4 Report",
        "",
        f"- Total records: **{len(records)}**",
        f"- Sources attempted: **{stats['sources_attempted']}**",
        f"- Authenticated sources skipped: **{stats['authenticated_skipped']}**",
        f"- Documents with content: **{stats['documents_with_content']}**",
        f"- Documents without usable content: **{stats['documents_without_content']}**",
        f"- Exact duplicates removed: **{stats['duplicates_removed']}**",
        f"- Boilerplate chunks removed: **{stats['boilerplate_removed']}**",
        f"- Linked documents inspected: **{len(linked_seen)}**",
        "",
        "## Domain distribution",
        "",
    ]
    for d in CANONICAL_DOMAINS:
        lines.append(
            f"- {d}: {len(by_domain.get(d, []))} records / "
            f"{len({x['source_id'] for x in by_domain.get(d, [])})} source IDs"
        )
    lines += [
        "",
        "## Failures",
        "",
    ]
    if failures:
        for x in failures[:100]:
            lines.append(f"- `{x['source_id']}` — {x['url']} — {x['reason']}")
    else:
        lines.append("- None")

    (REPORT_DIR / "ingestion_v4_report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )

    print("=" * 70)
    print("CAMPUSONE KB INGESTION V4")
    print("=" * 70)
    print(f"Total records:             {len(records)}")
    print(f"Exact duplicates removed:  {stats['duplicates_removed']}")
    print(f"Boilerplate removed:       {stats['boilerplate_removed']}")
    print(f"Linked docs inspected:     {len(linked_seen)}")
    print()
    for d in CANONICAL_DOMAINS:
        print(f"{d:20} {len(by_domain.get(d, [])):6} records | {len({x['source_id'] for x in by_domain.get(d, [])}):3} sources")
    print()
    print(f"STAGING: {STAGING}")
    print(f"REPORT:  {REPORT_DIR / 'ingestion_v4_report.md'}")

    if args.apply:
        if KNOWLEDGE.exists():
            backup = ROOT / "data" / "backups" / f"knowledge_backup_before_v4_{int(time.time())}"
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(KNOWLEDGE, backup)
            print(f"Backup created: {backup}")

        if KNOWLEDGE.exists():
            shutil.rmtree(KNOWLEDGE)
        shutil.copytree(STAGING, KNOWLEDGE)
        print(f"APPLIED: {KNOWLEDGE}")
    else:
        print()
        print("DRY RUN ONLY — existing backend/knowledge was NOT modified.")
        print("Run with --apply only after reviewing ingestion_v4_report.md")


if __name__ == "__main__":
    main()
