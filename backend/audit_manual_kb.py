import json
from pathlib import Path
from collections import Counter, defaultdict

KB = Path(__file__).resolve().parent / "knowledge"

records = []
errors = []
files = list(KB.rglob("*.jsonl"))

for path in files:
    try:
        with path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                    if not isinstance(r, dict):
                        raise ValueError("not a JSON object")
                    records.append(r)
                except Exception as e:
                    errors.append(f"{path}:{line_no} -> {e}")
    except Exception as e:
        errors.append(f"{path} -> {e}")

print("=" * 70)
print("CAMPUSONE KNOWLEDGE BASE AUDIT")
print("=" * 70)

print(f"JSONL files: {len(files)}")
print(f"Total records: {len(records)}")
print(f"Parse errors: {len(errors)}")

domains = Counter(
    str(r.get("domain", "")).strip().lower()
    for r in records
)

print("\nDOMAIN COVERAGE")
for domain, count in sorted(domains.items()):
    print(f"{domain:25} {count}")

groups = defaultdict(list)

for r in records:
    content = " ".join(
        str(r.get("content", "")).split()
    ).lower()

    if content:
        groups[content].append(r)

duplicates = [
    g for g in groups.values()
    if len(g) > 1
]

cross_domain = [
    g for g in duplicates
    if len({str(x.get("domain", "")).lower() for x in g}) > 1
]

short = [
    r for r in records
    if len(str(r.get("content", "")).strip()) < 80
]

missing_url = [
    r for r in records
    if not r.get("source_url")
]

missing_domain = [
    r for r in records
    if not r.get("domain")
]

missing_content = [
    r for r in records
    if not str(r.get("content", "")).strip()
]

print(f"\nExact duplicate groups: {len(duplicates)}")
print(f"Cross-domain duplicate groups: {len(cross_domain)}")
print(f"Short records (<80 chars): {len(short)}")
print(f"Missing source URLs: {len(missing_url)}")
print(f"Missing domains: {len(missing_domain)}")
print(f"Missing content: {len(missing_content)}")

print("\nSERVICE DOMAINS")

for domain in [
    "campus_services",
    "career",
    "health",
    "hostel",
    "sports",
    "student_affairs",
    "transport"
]:
    print(f"{domain:25} {domains.get(domain, 0)}")

print("\nTOP SOURCES")

sources = Counter(
    str(r.get("source_id", "unknown"))
    for r in records
)

for source, count in sources.most_common(15):
    print(f"{source:40} {count}")

if errors:
    print("\nPARSE ERRORS")
    for e in errors[:20]:
        print(e)

print("\n" + "=" * 70)
print("AUDIT COMPLETE")
print("=" * 70)
