from pathlib import Path
import json
import re
import hashlib
import shutil

BASE = Path(".")
V6 = BASE / "knowledge_v6_staging"
SRC = BASE / "knowledge"
OUT = BASE / "knowledge_real"

# Never overwrite an existing real KB accidentally.
if OUT.exists():
    backup = BASE / "knowledge_real_backup"
    if backup.exists():
        shutil.rmtree(backup)
    OUT.rename(backup)
    print(f"[BACKUP] Existing knowledge_real moved to {backup}")

OUT.mkdir(parents=True, exist_ok=True)

DOMAINS = [
    "academics",
    "admission",
    "campus_services",
    "career",
    "examinations",
    "fees",
    "health",
    "hostel",
    "it",
    "library",
    "policies",
    "security",
    "sports",
    "student_affairs",
    "transport",
]

# Weak V6 domains have better manually-curated Bennett files.
CURATED_OVERRIDE = {
    "campus_services",
    "career",
    "health",
    "hostel",
    "sports",
    "student_affairs",
    "transport",
    "library",
    "facilities",
}

# V6 domains with enough useful records.
V6_PRIMARY = {
    "academics",
    "admission",
    "examinations",
    "fees",
    "it",
    "policies",
    "security",
}

# Files which contain intentionally curated Bennett material.
CURATED_JSONL = {
    "campus_services": ["bennett_campus_services.jsonl"],
    "career": ["bennett_career.jsonl"],
    "health": ["bennett_health.jsonl"],
    "hostel": ["bennett_hostel.jsonl"],
    "sports": ["bennett_sports.jsonl"],
    "student_affairs": ["bennett_student_affairs.jsonl"],
    "transport": ["bennett_transport.jsonl"],
}

MARKDOWN_FILES = {
    "facilities": [
        "classroom_ac.md",
        "maintenance.md",
    ],
    "fees": [
        "refunds.md",
        "semester_fee.md",
    ],
    "it": [
        "email.md",
        "password_reset.md",
        "wifi.md",
    ],
    "library": [
        "borrowing.md",
        "library_hours.md",
    ],
}

def clean_text(value):
    if value is None:
        return ""
    value = str(value)
    value = value.replace("\x00", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value

def normalize_for_hash(text):
    text = clean_text(text).lower()
    text = re.sub(r"https?://\S+", " URL ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())

def is_boilerplate(text):
    """
    Remove obvious website-wide navigation/footer contamination,
    but keep genuine Bennett content.
    """
    t = clean_text(text).lower()

    if len(t) < 80:
        return True

    boilerplate_terms = [
        "skip to content",
        "all rights reserved",
        "privacy policy",
        "terms and conditions",
        "cookie policy",
        "student login",
        "staff & faculty login",
        "quick links",
        "follow us",
        "subscribe",
        "menu",
        "search",
    ]

    hits = sum(1 for term in boilerplate_terms if term in t)

    # A long chunk containing many generic website-navigation phrases
    # is probably contaminated.
    if hits >= 4:
        return True

    # Obvious repeated navigation-like chunks.
    nav_terms = [
        "home admission academics campus life",
        "about us contact us careers",
        "facebook instagram linkedin youtube",
    ]

    if any(term in t for term in nav_terms):
        return True

    return False

def make_record(record, domain, source_name):
    if not isinstance(record, dict):
        return None

    content = (
        record.get("content")
        or record.get("text")
        or record.get("body")
        or record.get("chunk")
        or ""
    )

    title = (
        record.get("title")
        or record.get("heading")
        or record.get("name")
        or source_name
    )

    section = (
        record.get("section")
        or record.get("category")
        or ""
    )

    content = clean_text(content)
    title = clean_text(title)
    section = clean_text(section)

    if not content or is_boilerplate(content):
        return None

    # Preserve useful metadata where available.
    result = {
        "domain": domain,
        "title": title,
        "section": section,
        "content": content,
        "source_url": record.get("source_url") or record.get("url") or "",
        "source": record.get("source") or "Bennett University",
        "source_id": record.get("source_id") or source_name,
        "authority": record.get("authority") or "official_bennett",
        "access": record.get("access") or "public",
        "status": record.get("status") or "current",
        "academic_year": record.get("academic_year") or "",
        "verified_at": record.get("verified_at") or "",
    }

    # Stable ID based on domain + title + content.
    digest = hashlib.sha256(
        (
            domain
            + "|"
            + title
            + "|"
            + section
            + "|"
            + content
        ).encode("utf-8")
    ).hexdigest()[:16]

    result["id"] = f"real-{domain}-{digest}"

    return result

def read_jsonl(path, domain):
    records = []

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()

            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            rec = make_record(obj, domain, path.name)

            if rec:
                records.append(rec)

    return records

def read_markdown(path, domain):
    text = path.read_text(encoding="utf-8", errors="replace").strip()

    if not text:
        return []

    # Convert markdown headings into useful title metadata.
    headings = re.findall(r"(?m)^#{1,6}\s+(.+)$", text)

    title = headings[0].strip() if headings else path.stem.replace("_", " ").title()

    record = {
        "title": title,
        "section": "Reference",
        "content": text,
        "source": "Bennett University",
        "source_id": path.name,
        "authority": "official_bennett",
        "access": "public",
        "status": "current",
    }

    rec = make_record(record, domain, path.name)

    return [rec] if rec else []

def add_records(store, records):
    for record in records:
        key = normalize_for_hash(record["content"])

        if not key:
            continue

        # Deduplicate identical normalized content.
        if key in store:
            continue

        store[key] = record

all_counts = {}
all_removed = {}

for domain in DOMAINS:
    records = {}

    # ------------------------------------------------------------
    # Primary V6 domains
    # ------------------------------------------------------------
    if domain in V6_PRIMARY:
        path = V6 / f"{domain}.jsonl"

        if path.exists():
            before = 0
            loaded = read_jsonl(path, domain)
            before = len(loaded)
            add_records(records, loaded)

            all_counts[domain] = len(records)
            all_removed[domain] = before - len(records)

    # ------------------------------------------------------------
    # Curated Bennett service domains
    # ------------------------------------------------------------
    if domain in CURATED_JSONL:
        for filename in CURATED_JSONL[domain]:
            path = SRC / domain / filename

            if path.exists():
                loaded = read_jsonl(path, domain)
                add_records(records, loaded)

    # ------------------------------------------------------------
    # Markdown references
    # ------------------------------------------------------------
    if domain in MARKDOWN_FILES:
        for filename in MARKDOWN_FILES[domain]:
            path = SRC / domain / filename

            if path.exists():
                loaded = read_markdown(path, domain)
                add_records(records, loaded)

    # ------------------------------------------------------------
    # Write domain
    # ------------------------------------------------------------
    domain_out = OUT / domain
    domain_out.mkdir(parents=True, exist_ok=True)

    output_file = domain_out / "bennett_real_kb.jsonl"

    with output_file.open("w", encoding="utf-8") as f:
        for record in records.values():
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    count = len(records)

    print(f"{domain:18} {count:4} records")

print()
print("=" * 60)
print("CAMPUSONE REAL BENNETT KB CREATED")
print("=" * 60)

total = 0

for domain in DOMAINS:
    path = OUT / domain / "bennett_real_kb.jsonl"

    if path.exists():
        count = sum(
            1
            for _ in path.open("r", encoding="utf-8")
        )
    else:
        count = 0

    total += count

print(f"TOTAL RECORDS: {total}")
print(f"OUTPUT: {OUT.resolve()}")
print()
print("Router dataset remains untouched:")
print("  knowledge_v2")
print()
print("Original Bennett knowledge remains untouched:")
print("  knowledge")
print()
