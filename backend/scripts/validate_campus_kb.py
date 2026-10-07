"""
CampusOne KB validator.

Validates the new campus JSONL schema and accepts the existing
legacy Admission schema separately so the Admission pipeline is not
forced to change just to validate the new domains.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"

NEW_REQUIRED = {
    "id", "domain", "title", "section", "content",
    "source_url", "source_type", "source_id", "authority", "verified_at"
}

OFFICIAL_PREFIXES = (
    "https://www.bennett.edu.in",
    "https://bennett.edu.in",
    "https://library.bennett.edu.in",
    "https://helpdesk.bennett.edu.in",
    "https://lms.bennett.edu.in",
    "https://d2xwywryb7yxbo.cloudfront.net",
)

def validate_file(path: Path) -> tuple[int, list[str]]:
    errors = []
    count = 0

    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{path}:{line_no}: invalid JSON: {exc}")
                continue

            domain = str(row.get("domain", "")).strip().lower()

            # Existing Admission KB has a different but valid legacy schema.
            if domain == "admission":
                legacy_required = {"id", "domain", "title", "section", "content", "source_url"}
                missing = legacy_required - set(row)
                if missing:
                    errors.append(f"{path}:{line_no}: admission missing {sorted(missing)}")
                if not str(row.get("source_url", "")).startswith(OFFICIAL_PREFIXES):
                    errors.append(f"{path}:{line_no}: admission non-official URL")
                count += 1
                continue

            missing = NEW_REQUIRED - set(row)
            if missing:
                errors.append(f"{path}:{line_no}: missing fields {sorted(missing)}")

            if not str(row.get("content", "")).strip():
                errors.append(f"{path}:{line_no}: empty content")

            if row.get("source_type") not in {"html", "pdf"}:
                errors.append(f"{path}:{line_no}: unexpected source_type={row.get('source_type')!r}")

            if not str(row.get("source_url", "")).startswith(OFFICIAL_PREFIXES):
                errors.append(f"{path}:{line_no}: non-official URL: {row.get('source_url')}")

            count += 1

    return count, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain")
    args = parser.parse_args()

    if args.domain:
        paths = sorted((KNOWLEDGE / args.domain).glob("*.jsonl"))
        domains = [args.domain]
    else:
        paths = []
        domains = sorted(p.name for p in KNOWLEDGE.iterdir() if p.is_dir())

    total = 0
    all_errors = []

    for domain in domains:
        domain_paths = sorted((KNOWLEDGE / domain).glob("*.jsonl"))
        if not domain_paths:
            print(f"{domain}: NO JSONL FILE")
            continue

        domain_count = 0
        for path in domain_paths:
            count, errors = validate_file(path)
            domain_count += count
            all_errors.extend(errors)

        print(f"{domain}: {domain_count} records")
        total += domain_count

    print(f"\nTOTAL: {total} records")

    if all_errors:
        print("\nVALIDATION ERRORS:")
        for error in all_errors[:100]:
            print(" -", error)
        if len(all_errors) > 100:
            print(f"... {len(all_errors)-100} more")
        return 1

    print("VALID")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
