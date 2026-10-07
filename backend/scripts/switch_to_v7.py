from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
RETRIEVER = BACKEND / "app" / "rag" / "retriever.py"
ROUTER = BACKEND / "app" / "router" / "router.py"
V7 = BACKEND / "knowledge_v7"

for path in (RETRIEVER, ROUTER):
    if not path.exists():
        raise FileNotFoundError(f"Missing: {path}")

if not V7.exists():
    raise FileNotFoundError(f"Missing: {V7}")


# ============================================================
# 1. SWITCH RETRIEVER TO V7
# ============================================================

text = RETRIEVER.read_text(encoding="utf-8")

old_path = 'KNOWLEDGE_DIR = BASE_DIR / "knowledge"'
new_path = 'KNOWLEDGE_DIR = BASE_DIR / "knowledge_v7"'

if old_path not in text:
    if new_path not in text:
        raise RuntimeError(
            "Could not find KNOWLEDGE_DIR in retriever.py"
        )
else:
    text = text.replace(old_path, new_path, 1)


# ============================================================
# 2. FIX RETRIEVER DOMAIN NORMALIZATION
# ============================================================

old_normalizer = '''    def _normalize_domain(
        domain: str,
    ) -> str:

        return str(domain).strip().lower()
'''

new_normalizer = '''    def _normalize_domain(
        domain: str,
    ) -> str:

        return (
            str(domain)
            .strip()
            .lower()
            .replace("_", " ")
            .replace("-", " ")
        )
'''

if old_normalizer in text:
    text = text.replace(
        old_normalizer,
        new_normalizer,
        1,
    )
else:
    print(
        "[V7] Retriever normalizer already appears "
        "to be modified or has a different format."
    )

RETRIEVER.write_text(
    text,
    encoding="utf-8",
)


# ============================================================
# 3. SWITCH ROUTER TO V7
# ============================================================

text = ROUTER.read_text(encoding="utf-8")

if old_path not in text:
    if new_path not in text:
        raise RuntimeError(
            "Could not find KNOWLEDGE_DIR in router.py"
        )
else:
    text = text.replace(old_path, new_path, 1)


# ============================================================
# 4. EXPAND ROUTER TO ALL V7 DOMAINS
# ============================================================

old_domains = '''CANONICAL_DOMAINS = {
    "admission": "Admission",
    "facilities": "Facilities",
    "fees": "Fees",
    "it": "IT",
    "library": "Library",
}'''

new_domains = '''CANONICAL_DOMAINS = {
    "academics": "Academics",
    "admission": "Admission",
    "campus_services": "Campus Services",
    "career": "Career",
    "examinations": "Examinations",
    "facilities": "Facilities",
    "fees": "Fees",
    "health": "Health",
    "hostel": "Hostel",
    "it": "IT",
    "library": "Library",
    "policies": "Policies",
    "security": "Security",
    "sports": "Sports",
    "student_affairs": "Student Affairs",
    "transport": "Transport",
}'''

if old_domains in text:
    text = text.replace(
        old_domains,
        new_domains,
        1,
    )
else:
    print(
        "[V7] Router domain list was not in the old 5-domain format."
    )

ROUTER.write_text(
    text,
    encoding="utf-8",
)


print()
print("=" * 60)
print("V7 SWITCH COMPLETE")
print("=" * 60)
print(f"Retriever: {RETRIEVER}")
print(f"Router:    {ROUTER}")
print(f"V7 KB:     {V7}")
print()
print("Old backend\\knowledge was NOT deleted.")
print("=" * 60)