from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parents[1]

DATA_DIR = BASE_DIR / "data"
KNOWLEDGE_DIR = BASE_DIR / "knowledge" / "admission"

SOURCES_FILE = DATA_DIR / "bennett_admission_sources.json"
OUTPUT_FILE = KNOWLEDGE_DIR / "bennett_admission_kb.jsonl"

USER_AGENT = (
    "CampusOne/0.1 "
    "(Bennett University admission knowledge ingestion)"
)

REQUEST_TIMEOUT = 30

TARGET_CHARS = 2400
MAX_CHARS = 3200
MIN_CHARS = 180
OVERLAP_CHARS = 300


def clean_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def normalize_heading(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"\s+", " ", value)
    return value[:300]


def make_id(
    domain: str,
    source_id: str,
    index: int,
    text: str,
) -> str:
    digest = hashlib.sha1(
        text.encode("utf-8")
    ).hexdigest()[:16]

    safe_source = re.sub(
        r"[^a-z0-9]+",
        "_",
        source_id.lower(),
    ).strip("_")

    return (
        f"{domain.lower()}_"
        f"{safe_source}_"
        f"{index:04d}_"
        f"{digest}"
    )


def extract_sections(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(
        html,
        "lxml",
    )

    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "iframe",
            "form",
            "nav",
            "footer",
        ]
    ):
        tag.decompose()

    root = soup.find("main") or soup.body or soup

    sections: list[dict[str, str]] = []

    current_heading = "Page overview"
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_parts

        text = clean_text(
            "\n".join(current_parts)
        )

        if len(text) >= MIN_CHARS:
            sections.append(
                {
                    "section": current_heading,
                    "text": text,
                }
            )

        current_parts = []

    for element in root.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "p",
            "li",
            "tr",
            "blockquote",
        ]
    ):

        name = element.name.lower()

        if name.startswith("h"):

            heading = normalize_heading(
                element.get_text(
                    " ",
                    strip=True,
                )
            )

            if heading:
                flush()
                current_heading = heading

            continue

        if name == "tr":

            cells = [
                clean_text(
                    cell.get_text(
                        " ",
                        strip=True,
                    )
                )
                for cell in element.find_all(
                    ["th", "td"]
                )
            ]

            cells = [
                cell
                for cell in cells
                if cell
            ]

            if cells:
                current_parts.append(
                    " | ".join(cells)
                )

            continue

        text = clean_text(
            element.get_text(
                " ",
                strip=True,
            )
        )

        if text:
            current_parts.append(text)

    flush()

    return sections


def split_large_section(
    section_text: str,
) -> list[str]:

    paragraphs = [
        clean_text(part)
        for part in re.split(
            r"\n{2,}",
            section_text,
        )
        if clean_text(part)
    ]

    if not paragraphs:
        paragraphs = [section_text]

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:

        if not current:
            current = paragraph
            continue

        proposed = (
            current
            + "\n\n"
            + paragraph
        )

        if len(proposed) <= TARGET_CHARS:
            current = proposed
            continue

        if len(current) >= MIN_CHARS:
            chunks.append(current)

        overlap = current[-OVERLAP_CHARS:]

        current = (
            overlap
            + "\n\n"
            + paragraph
        )

        if len(current) > MAX_CHARS:

            sentences = re.split(
                r"(?<=[.!?])\s+",
                current,
            )

            current = ""

            for sentence in sentences:

                if not current:
                    current = sentence
                    continue

                proposed = (
                    current
                    + " "
                    + sentence
                )

                if len(proposed) <= TARGET_CHARS:
                    current = proposed

                else:
                    if len(current) >= MIN_CHARS:
                        chunks.append(current)

                    current = sentence

    if current and len(current) >= MIN_CHARS:
        chunks.append(current)

    return chunks


def fetch(
    session: requests.Session,
    url: str,
) -> str | None:

    try:

        response = session.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT
            },
        )

        response.raise_for_status()

        return response.text

    except requests.RequestException as exc:

        print(
            f"[FETCH ERROR] {url}: {exc}"
        )

        return None


def load_manifest() -> tuple[str, bool, list[dict[str, Any]]]:

    if not SOURCES_FILE.exists():
        raise FileNotFoundError(
            f"Source manifest not found: "
            f"{SOURCES_FILE}"
        )

    manifest = json.loads(
        SOURCES_FILE.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(manifest, dict):
        raise ValueError(
            "Expected bennett_admission_sources.json "
            "to contain an object."
        )

    domain = str(
        manifest.get(
            "domain",
            "Admission",
        )
    )

    official_only = bool(
        manifest.get(
            "official_only",
            True,
        )
    )

    urls = manifest.get(
        "urls",
        [],
    )

    if not isinstance(urls, list):
        raise ValueError(
            "Manifest field 'urls' must be a list."
        )

    valid_urls = []

    for item in urls:

        if not isinstance(item, dict):
            continue

        source_id = str(
            item.get("id", "")
        ).strip()

        url = str(
            item.get("url", "")
        ).strip()

        if not source_id or not url:
            continue

        valid_urls.append(
            {
                **item,
                "id": source_id,
                "url": url,
            }
        )

    return (
        domain,
        official_only,
        valid_urls,
    )


def build_records(
    domain: str,
    source: dict[str, Any],
    html: str,
) -> list[dict[str, Any]]:

    source_id = source["id"]
    source_url = source["url"]

    title = str(
        source.get(
            "title",
            source_id.replace(
                "_",
                " ",
            ).title(),
        )
    )

    source_type = str(
        source.get(
            "source_type",
            "official_bennett_webpage",
        )
    )

    academic_year = source.get(
        "academic_year",
        "2026-27",
    )

    sections = extract_sections(
        html
    )

    records: list[dict[str, Any]] = []

    for section in sections:

        section_name = section["section"]
        section_text = section["text"]

        chunks = split_large_section(
            section_text
        )

        for chunk_text in chunks:

            record_index = (
                len(records) + 1
            )

            records.append(
                {
                    "id": make_id(
                        domain,
                        source_id,
                        record_index,
                        (
                            section_name
                            + "\n"
                            + chunk_text
                        ),
                    ),
                    "domain": domain,
                    "title": title,
                    "source": source_id,
                    "source_type": source_type,
                    "source_url": source_url,
                    "section": section_name,
                    "content": chunk_text,
                    "verified_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "academic_year": academic_year,
                    "chunk_index": record_index,
                }
            )

    return records


def main() -> None:

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    KNOWLEDGE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        domain,
        official_only,
        sources,
    ) = load_manifest()

    print("=" * 70)
    print(
        "CampusOne — Bennett Admission KB Ingestion"
    )
    print(
        "Section-aware / context-rich chunking"
    )
    print("=" * 70)

    print(
        f"Domain: {domain}"
    )

    print(
        f"Official-only: {official_only}"
    )

    print(
        f"Sources in manifest: {len(sources)}"
    )

    if not sources:
        raise RuntimeError(
            "The manifest contains no valid URLs. "
            "Refusing to overwrite the existing KB."
        )

    session = requests.Session()

    all_records: list[dict[str, Any]] = []

    for source in sources:

        source_id = source["id"]
        url = source["url"]

        print(
            f"\nFETCH {source_id}"
        )
        print(
            f"       {url}"
        )

        html = fetch(
            session,
            url,
        )

        if not html:

            print(
                f"       SKIP {source_id}"
            )

            continue

        records = build_records(
            domain,
            source,
            html,
        )

        print(
            f"       -> {len(records)} "
            f"context-rich chunks"
        )

        all_records.extend(
            records
        )

    # ---------------------------------------------------------
    # Deduplicate
    # ---------------------------------------------------------

    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for record in all_records:

        key = (
            record["source_url"],
            record["content"],
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(record)

    # ---------------------------------------------------------
    # Re-index
    # ---------------------------------------------------------

    for index, record in enumerate(
        unique,
        start=1,
    ):
        record["chunk_index"] = index

    # ---------------------------------------------------------
    # Safety: never overwrite a working KB with zero records.
    # ---------------------------------------------------------

    if not unique:

        raise RuntimeError(
            "Ingestion produced 0 records. "
            "The existing Admission KB was NOT overwritten."
        )

    # ---------------------------------------------------------
    # Write
    # ---------------------------------------------------------

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:

        for record in unique:

            file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
                + "\n"
            )

    print("\n" + "=" * 70)
    print(
        f"DONE: {len(unique)} records"
    )
    print(
        f"OUTPUT: {OUTPUT_FILE}"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
