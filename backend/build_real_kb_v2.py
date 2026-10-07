from pathlib import Path
import json
import re
import hashlib
import shutil

BASE = Path(".")
V6 = BASE / "knowledge_v6_staging"
SRC = BASE / "knowledge"
OUT = BASE / "knowledge_real_v2"

if OUT.exists():
    backup = BASE / "knowledge_real_v2_backup"
    if backup.exists():
        shutil.rmtree(backup)
    OUT.rename(backup)

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

# These domains have intentionally curated Bennett records.
CURATED_JSONL = {
    "campus_services": "bennett_campus_services.jsonl",
    "career": "bennett_career.jsonl",
    "health": "bennett_health.jsonl",
    "hostel": "bennett_hostel.jsonl",
    "sports": "bennett_sports.jsonl",
    "student_affairs": "bennett_student_affairs.jsonl",
    "transport": "bennett_transport.jsonl",
}

MARKDOWN_FILES = {
    "fees": ["refunds.md", "semester_fee.md"],
    "it": ["email.md", "password_reset.md", "wifi.md"],
    "library": ["borrowing.md", "library_hours.md"],
}

# Stronger V6 domains.
V6_DOMAINS = {
    "academics",
    "admission",
    "examinations",
    "policies",
    "security",
}

# Minimum useful content length.
MIN_LENGTH = 100


def clean_text(value):
    if value is None:
        return ""

    value = str(value)
    value = value.replace("\x00", " ")
    value = re.sub(r"\s+", " ", value).strip()

    return value


def normalize(text):
    text = clean_text(text).lower()
    text = re.sub(r"https?://\S+", " URL ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def looks_like_noise(text):
    t = normalize(text)

    if len(t) < MIN_LENGTH:
        return True

    # Website navigation / footer contamination.
    noise_terms = [
        "skip to content",
        "all rights reserved",
        "cookie policy",
        "privacy policy",
        "terms and conditions",
        "student login",
        "staff faculty login",
        "quick links",
        "follow us",
        "subscribe",
        "facebook instagram linkedin youtube",
    ]

    hits = sum(term in t for term in noise_terms)

    if hits >= 2:
        return True

    # Unrelated article/blog content accidentally captured in IT.
    if "it" in t or "helpdesk" in t or "wifi" in t:
        unrelated = [
            "fashion design",
            "mba graduates",
            "mass communication",
            "business studies",
            "digital fashion",
            "film tv web series",
            "career skills",
            "placement cells",
            "growth hacking",
        ]

        if sum(x in t for x in unrelated) >= 2:
            return True

    return False


def record(
    domain,
    content,
    title="",
    section="",
    source_url="",
    source_id="",
    source="Bennett University",
    verified_at="",
    academic_year="",
):
    content = clean_text(content)
    title = clean_text(title)
    section = clean_text(section)

    if not content or looks_like_noise(content):
        return None

    digest = hashlib.sha256(
        f"{domain}|{title}|{section}|{content}".encode("utf-8")
    ).hexdigest()[:16]

    return {
        "id": f"real2-{domain}-{digest}",
        "domain": domain,
        "title": title or domain.title(),
        "section": section,
        "content": content,
        "source_url": source_url,
        "source": source,
        "source_id": source_id,
        "authority": "official_bennett",
        "access": "public",
        "status": "current",
        "academic_year": academic_year,
        "verified_at": verified_at,
    }


def read_jsonl(path, domain):
    output = []

    with path.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            try:
                obj = json.loads(line)
            except Exception:
                continue

            if not isinstance(obj, dict):
                continue

            content = (
                obj.get("content")
                or obj.get("text")
                or obj.get("body")
                or obj.get("chunk")
                or ""
            )

            item = record(
                domain=domain,
                content=content,
                title=obj.get("title") or obj.get("heading") or "",
                section=obj.get("section") or obj.get("category") or "",
                source_url=obj.get("source_url") or obj.get("url") or "",
                source_id=obj.get("source_id") or path.stem,
                source=obj.get("source") or "Bennett University",
                verified_at=obj.get("verified_at") or "",
                academic_year=obj.get("academic_year") or "",
            )

            if item:
                output.append(item)

    return output


def read_markdown(path, domain):
    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).strip()

    if not text:
        return []

    headings = re.findall(
        r"(?m)^#{1,6}\s+(.+)$",
        text,
    )

    title = (
        headings[0].strip()
        if headings
        else path.stem.replace("_", " ").title()
    )

    item = record(
        domain=domain,
        content=text,
        title=title,
        section="Reference",
        source_id=path.name,
    )

    return [item] if item else []


def add_unique(store, items):
    for item in items:
        key = normalize(item["content"])

        if not key:
            continue

        # Exact normalized duplicate.
        if key in store:
            continue

        store[key] = item


# ------------------------------------------------------------
# Build each domain
# ------------------------------------------------------------

for domain in DOMAINS:

    records = {}

    # Strong V6 domains.
    if domain in V6_DOMAINS:
        path = V6 / f"{domain}.jsonl"

        if path.exists():
            add_unique(
                records,
                read_jsonl(path, domain),
            )

    # Curated Bennett service domains.
    if domain in CURATED_JSONL:
        path = SRC / domain / CURATED_JSONL[domain]

        if path.exists():
            add_unique(
                records,
                read_jsonl(path, domain),
            )

    # Curated markdown.
    if domain in MARKDOWN_FILES:
        for filename in MARKDOWN_FILES[domain]:
            path = SRC / domain / filename

            if path.exists():
                add_unique(
                    records,
                    read_markdown(path, domain),
                )

    # --------------------------------------------------------
    # IT: deliberately DO NOT import noisy V6 IT corpus.
    # --------------------------------------------------------
    if domain == "it":

        # Official Bennett LMS / IT support information.
        add_unique(
            records,
            [
                record(
                    domain="it",
                    title="IT Helpdesk",
                    section="IT Support",
                    content=(
                        "Bennett University IT Helpdesk provides support "
                        "for student IT-related issues. The IT Helpdesk "
                        "contact is it-helpdesk@bennett.edu.in and "
                        "0120-7199700, Extension 9700."
                    ),
                    source_url="https://lms.bennett.edu.in/ilearning-support.php",
                    source_id="ilearning_support",
                )
            ],
        )

        add_unique(
            records,
            [
                record(
                    domain="it",
                    title="LMS Support",
                    section="IT Support",
                    content=(
                        "Bennett University LMS Support can be contacted "
                        "at lms@bennett.edu.in and 0120-7199700, "
                        "Extension 9470."
                    ),
                    source_url="https://lms.bennett.edu.in/ilearning-support.php",
                    source_id="ilearning_support",
                )
            ],
        )

    # --------------------------------------------------------
    # Fees: add a clean current hostel-fee reference.
    # --------------------------------------------------------
    if domain == "fees":

        add_unique(
            records,
            [
                record(
                    domain="fees",
                    title="Hostel Fee",
                    section="Hostel Charges",
                    content=(
                        "For the current Bennett University 2026-27 fee "
                        "structure, hostel accommodation is listed at "
                        "₹1,70,000 per annum for triple sharing/occupancy. "
                        "The hostel fee is subject to an annual increase "
                        "of up to 7%, according to the university fee "
                        "structure."
                    ),
                    source_url="https://www.bennett.edu.in/admission/fee-structure/",
                    source_id="fees_2026_27",
                    academic_year="2026-27",
                )
            ],
        )

    domain_out = OUT / domain
    domain_out.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = domain_out / "bennett_real_v2_kb.jsonl"

    with output.open(
        "w",
        encoding="utf-8",
    ) as f:
        for item in records.values():
            f.write(
                json.dumps(
                    item,
                    ensure_ascii=False,
                )
                + "\n"
            )

    print(
        f"{domain:18} {len(records):4} records"
    )


print()
print("=" * 60)
print("CAMPUSONE REAL BENNETT KB V2 CREATED")
print("=" * 60)

total = 0

for domain in DOMAINS:
    path = (
        OUT
        / domain
        / "bennett_real_v2_kb.jsonl"
    )

    count = (
        sum(
            1
            for _ in path.open(
                "r",
                encoding="utf-8",
            )
        )
        if path.exists()
        else 0
    )

    total += count

print(f"TOTAL RECORDS: {total}")
print(f"OUTPUT: {OUT.resolve()}")
print()
print("UNCHANGED:")
print("  knowledge")
print("  knowledge_v2")
print("  knowledge_v6_staging")
print("  knowledge_real")
