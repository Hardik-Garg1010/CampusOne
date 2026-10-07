"""CampusOne robust Bennett source ingestion v3."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "campus_sources.json"
KB = ROOT / "knowledge"
REPORT = ROOT / "data" / "ingestion_reports"
REPORT.mkdir(parents=True, exist_ok=True)

TIMEOUT = 30
CHUNK = 1800
OVERLAP = 250
MIN = 120

HEAD = {
    "User-Agent": "CampusOne/0.3 official-source-ingestion",
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def clean(s):
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def chash(s):
    return hashlib.sha256(
        re.sub(r"\W+", " ", s.lower()).strip().encode()
    ).hexdigest()


def ispdf(r):
    content_type = (r.headers.get("Content-Type") or "").lower()
    return (
        "application/pdf" in content_type
        or r.content[:12].lstrip().startswith(b"%PDF")
    )


def chunks(s):
    s = clean(s)

    if len(s) < MIN:
        return []

    if len(s) <= CHUNK:
        return [s]

    out = []
    start = 0

    while start < len(s):
        end = min(start + CHUNK, len(s))

        if end < len(s):
            boundary = max(
                s.rfind("\n", start, end),
                s.rfind(". ", start, end),
                s.rfind("; ", start, end),
            )

            if boundary > start + CHUNK * 0.55:
                end = boundary + 1

        piece = clean(s[start:end])

        if len(piece) >= MIN:
            out.append(piece)

        if end >= len(s):
            break

        start = max(0, end - OVERLAP)

    return out


def html_extract(r):
    soup = BeautifulSoup(r.text, "lxml")

    for element in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        element.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""

    sections = []
    section = "General"
    buffer = []

    def flush():
        nonlocal buffer

        text = clean("\n".join(buffer))

        if len(text) >= MIN:
            sections.append((section, text))

        buffer = []

    for element in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "tr"]):
        text = clean(element.get_text(" ", strip=True))

        if not text:
            continue

        if element.name in ["h1", "h2", "h3", "h4"]:
            flush()
            section = text[:300]

        elif element.name == "tr":
            cells = [
                clean(cell.get_text(" ", strip=True))
                for cell in element.find_all(["th", "td"])
            ]
            cells = [cell for cell in cells if cell]

            if cells:
                buffer.append(" | ".join(cells))

        else:
            buffer.append(text)

    flush()

    pdfs = []

    for anchor in soup.find_all("a", href=True):
        url = urljoin(r.url, anchor["href"].strip())

        if urlparse(url).path.lower().endswith(".pdf") and url not in pdfs:
            pdfs.append(url)

    return title, sections, pdfs[:50]


def pdf_extract(r):
    if not ispdf(r):
        raise ValueError(
            f"Expected PDF, got {r.headers.get('Content-Type')!r}"
        )

    temp = REPORT / "_tmp.pdf"
    temp.write_bytes(r.content)

    try:
        reader = PdfReader(str(temp))
        sections = []

        for page_number, page in enumerate(reader.pages, start=1):
            text = clean(page.extract_text() or "")

            if len(text) >= MIN:
                sections.append((f"Page {page_number}", text))

        title = (
            Path(urlparse(r.url).path)
            .stem
            .replace("-", " ")
            .replace("_", " ")
        )

        return title, sections

    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def records(src, title, sections, url, source_type, discovered=None):
    output = []
    index = 0

    for section, text in sections:
        for piece in chunks(text):
            output.append(
                {
                    "id": (
                        f"{src.get('source_id', 'source')}_"
                        f"{hashlib.sha256(url.encode()).hexdigest()[:16]}_"
                        f"{index:04d}"
                    ),
                    "domain": src["domain"],
                    "title": title[:300],
                    "section": section[:300],
                    "content": piece,
                    "source_url": url,
                    "source_type": source_type,
                    "source_id": src.get("source_id"),
                    "authority": "official_bennett",
                    "access": src.get("access", "public"),
                    "academic_year": src.get("academic_year"),
                    "status": src.get("freshness", "unknown"),
                    "verified_at": now(),
                    "discovered_from": discovered,
                    "chunk_index": index,
                }
            )
            index += 1

    return output


def dedupe(records_list):
    seen = set()
    output = []

    for record in records_list:
        content_hash = chash(record["content"])

        if content_hash not in seen:
            seen.add(content_hash)
            output.append(record)

    return output


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = manifest["sources"]

    records_by_domain = defaultdict(list)

    report = {
        "started_at": now(),
        "source_count": len(sources),
        "results": [],
        "skipped_integrations": [],
    }

    session = requests.Session()
    session.headers.update(HEAD)

    for number, source in enumerate(sources, start=1):
        domain = source["domain"]
        source_id = source["source_id"]
        url = source["url"]

        print(f"\n[{number}/{len(sources)}] {domain}/{source_id}")
        print(f"  {url}")

        if (
            source.get("access") == "authenticated"
            or source.get("source_type") == "integration"
        ):
            print("  SKIP authenticated integration")
            report["skipped_integrations"].append(source)
            continue

        result = {
            "domain": domain,
            "source_id": source_id,
            "url": url,
            "status": None,
            "records": 0,
            "discovered_pdfs": 0,
            "error": None,
        }

        try:
            response = session.get(
                url,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            response.raise_for_status()

            if source.get("source_type") == "pdf" or ispdf(response):
                title, sections = pdf_extract(response)

                extracted = records(
                    source,
                    title,
                    sections,
                    response.url,
                    "pdf",
                )

            else:
                title, sections, pdf_links = html_extract(response)

                result["discovered_pdfs"] = len(pdf_links)

                extracted = records(
                    source,
                    title,
                    sections,
                    response.url,
                    "html",
                )

                for pdf_url in pdf_links:
                    try:
                        pdf_response = session.get(
                            pdf_url,
                            timeout=TIMEOUT,
                            allow_redirects=True,
                        )
                        pdf_response.raise_for_status()

                        pdf_title, pdf_sections = pdf_extract(pdf_response)

                        extracted += records(
                            source,
                            pdf_title,
                            pdf_sections,
                            pdf_response.url,
                            "pdf",
                            response.url,
                        )

                    except Exception as error:
                        print(
                            f"  linked PDF failed: {pdf_url} -> {error}"
                        )

            extracted = dedupe(extracted)

            if extracted:
                records_by_domain[domain].extend(extracted)

                result["status"] = "SUCCESS"
                result["records"] = len(extracted)

                print(f"  SUCCESS {len(extracted)}")

            else:
                result["status"] = "EMPTY"
                print("  EMPTY")

        except Exception as error:
            result["status"] = "FAILED"
            result["error"] = str(error)

            print(f"  FAILED {error}")

        report["results"].append(result)

        time.sleep(0.1)

    for domain, domain_records in records_by_domain.items():
        domain_records = dedupe(domain_records)

        output_directory = KB / domain
        output_directory.mkdir(parents=True, exist_ok=True)

        output_file = output_directory / f"bennett_{domain}_kb.jsonl"

        with output_file.open("w", encoding="utf-8") as file:
            for record in domain_records:
                file.write(
                    json.dumps(record, ensure_ascii=False) + "\n"
                )

        print(f"WRITE {domain}: {len(domain_records)}")

    report["domain_summary"] = {
        domain: len(dedupe(domain_records))
        for domain, domain_records in sorted(records_by_domain.items())
    }

    report["total_records"] = sum(report["domain_summary"].values())
    report["finished_at"] = now()

    report_json = REPORT / "campus_ingestion_report.json"

    report_json.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    counts = defaultdict(int)

    for result in report["results"]:
        counts[result["status"]] += 1

    lines = [
        "# CampusOne Bennett Ingestion Report",
        "",
        "## Summary",
        "",
        f"- Manifest sources: {len(sources)}",
        f"- Public RAG records: {report['total_records']}",
        "",
    ]

    lines += [
        f"- {status}: {count}"
        for status, count in sorted(counts.items())
    ]

    lines += [
        "",
        "## Domain totals",
        "",
    ]

    lines += [
        f"- **{domain}**: {count}"
        for domain, count in report["domain_summary"].items()
    ]

    lines += [
        "",
        "## Failed sources",
        "",
    ]

    failures = [
        result
        for result in report["results"]
        if result["status"] == "FAILED"
    ]

    if not failures:
        lines.append("- None")
    else:
        lines += [
            f"- `{result['domain']}/{result['source_id']}` — "
            f"{result['error']}"
            for result in failures
        ]

    report_markdown = REPORT / "campus_ingestion_report.md"

    report_markdown.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print(f"\nDONE: {report['total_records']} public records")


if __name__ == "__main__":
    main()
