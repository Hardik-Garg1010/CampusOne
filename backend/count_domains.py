from pathlib import Path

p = Path("knowledge_v6_staging")

print("DOMAIN COUNTS")

for f in sorted(p.glob("*.jsonl")):
    with f.open(encoding="utf-8") as file:
        count = sum(1 for _ in file)
    print(f"{f.stem}: {count}")
