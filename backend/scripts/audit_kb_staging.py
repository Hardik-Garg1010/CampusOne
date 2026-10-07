import argparse
import json
from pathlib import Path
from collections import Counter, defaultdict


def load_records(kb_dir: Path):
    records = []
    parse_errors = []

    for path in sorted(kb_dir.rglob("*.jsonl")):
        domain_from_file = path.parent.name

        try:
            with path.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()

                    if not line:
                        continue

                    try:
                        record = json.loads(line)
                        record["_file_domain"] = domain_from_file
                        record["_file"] = str(path)
                        record["_line"] = line_no
                        records.append(record)
                    except Exception as e:
                        parse_errors.append(
                            f"{path}:{line_no} -> {e}"
                        )

        except Exception as e:
            parse_errors.append(f"{path} -> {e}")

    return records, parse_errors


def normalize_text(text):
    if not isinstance(text, str):
        return ""

    return " ".join(text.lower().split())


def main():
    parser = argparse.ArgumentParser(
        description="Audit a CampusOne KB directory."
    )

    parser.add_argument(
        "--kb-dir",
        required=True,
        help="Path to the KB directory to audit."
    )

    args = parser.parse_args()

    kb_dir = Path(args.kb_dir)

    if not kb_dir.exists():
        print(f"ERROR: KB directory does not exist:")
        print(kb_dir)
        return

    print("=" * 72)
    print("CAMPUSONE KB STAGING AUDIT")
    print("=" * 72)
    print(f"KB directory: {kb_dir}")
    print()

    records, parse_errors = load_records(kb_dir)

    print(f"Total records:     {len(records)}")
    print(f"JSONL files:       {len(list(kb_dir.rglob('*.jsonl')))}")
    print(f"Parse errors:      {len(parse_errors)}")
    print()

    # ------------------------------------------------------------
    # Domain statistics
    # ------------------------------------------------------------

    domain_counts = Counter()
    domain_sources = defaultdict(set)
    domain_urls = defaultdict(set)

    for r in records:
        domain = r.get("domain") or r.get("_file_domain")

        domain_counts[domain] += 1

        source_id = r.get("source_id")
        if source_id:
            domain_sources[domain].add(source_id)

        url = (
            r.get("source_url")
            or r.get("url")
            or r.get("document_url")
        )

        if url:
            domain_urls[domain].add(url)

    print("DOMAIN COVERAGE")
    print("-" * 72)

    for domain in sorted(domain_counts):
        print(
            f"{domain:20}"
            f"{domain_counts[domain]:7} records | "
            f"{len(domain_sources[domain]):3} sources | "
            f"{len(domain_urls[domain]):3} URLs"
        )

    print()

    # ------------------------------------------------------------
    # Exact duplicate analysis
    # ------------------------------------------------------------

    text_groups = defaultdict(list)

    for r in records:
        text = (
            r.get("text")
            or r.get("content")
            or r.get("chunk")
            or ""
        )

        key = normalize_text(text)

        if key:
            text_groups[key].append(r)

    duplicate_groups = {
        k: v
        for k, v in text_groups.items()
        if len(v) > 1
    }

    print("DUPLICATE ANALYSIS")
    print("-" * 72)
    print(f"Exact duplicate groups: {len(duplicate_groups)}")

    cross_domain = []

    for text, group in duplicate_groups.items():
        domains = set()

        for r in group:
            domains.add(
                r.get("domain") or r.get("_file_domain")
            )

        if len(domains) > 1:
            cross_domain.append(group)

    print(f"Cross-domain duplicate groups: {len(cross_domain)}")
    print()

    # ------------------------------------------------------------
    # Cross-domain duplicate examples
    # ------------------------------------------------------------

    print("CROSS-DOMAIN DUPLICATE EXAMPLES")
    print("-" * 72)

    shown = 0

    for group in cross_domain:
        if shown >= 15:
            break

        domains = sorted({
            r.get("domain") or r.get("_file_domain")
            for r in group
        })

        urls = sorted({
            r.get("source_url")
            or r.get("url")
            or r.get("document_url")
            or "NO_URL"
            for r in group
        })

        sample = (
            group[0].get("text")
            or group[0].get("content")
            or group[0].get("chunk")
            or ""
        )

        print(f"Domains: {domains}")
        print(f"URLs: {urls[:3]}")
        print(f"Text: {sample[:250].replace(chr(10), ' ')}")
        print()

        shown += 1

    # ------------------------------------------------------------
    # URL/domain relationships
    # ------------------------------------------------------------

    url_domains = defaultdict(set)

    for r in records:
        url = (
            r.get("source_url")
            or r.get("url")
            or r.get("document_url")
        )

        domain = r.get("domain") or r.get("_file_domain")

        if url and domain:
            url_domains[url].add(domain)

    shared_urls = {
        url: domains
        for url, domains in url_domains.items()
        if len(domains) > 1
    }

    print("SHARED OFFICIAL URL ANALYSIS")
    print("-" * 72)
    print(f"URLs assigned to multiple domains: {len(shared_urls)}")

    shown = 0

    for url, domains in sorted(shared_urls.items()):
        if shown >= 20:
            break

        print(f"{sorted(domains)}")
        print(f"  {url}")
        shown += 1

    print()

    # ------------------------------------------------------------
    # Record quality
    # ------------------------------------------------------------

    short_records = []
    missing_urls = []
    missing_domains = []

    for r in records:
        text = (
            r.get("text")
            or r.get("content")
            or r.get("chunk")
            or ""
        )

        if len(text.strip()) < 120:
            short_records.append(r)

        url = (
            r.get("source_url")
            or r.get("url")
            or r.get("document_url")
        )

        if not url:
            missing_urls.append(r)

        if not r.get("domain") and not r.get("_file_domain"):
            missing_domains.append(r)

    print("QUALITY CHECKS")
    print("-" * 72)
    print(f"Short records (<120 chars): {len(short_records)}")
    print(f"Missing source URLs:        {len(missing_urls)}")
    print(f"Missing domains:            {len(missing_domains)}")
    print()

    # ------------------------------------------------------------
    # Source volume
    # ------------------------------------------------------------

    source_counts = Counter()

    for r in records:
        source_id = r.get("source_id") or "UNKNOWN"
        source_counts[source_id] += 1

    print("TOP SOURCE VOLUMES")
    print("-" * 72)

    for source_id, count in source_counts.most_common(20):
        print(f"{count:6}  {source_id}")

    print()

    # ------------------------------------------------------------
    # Important domains
    # ------------------------------------------------------------

    print("LOW-COVERAGE DOMAINS")
    print("-" * 72)

    for domain in sorted(domain_counts):
        if domain_counts[domain] < 20:
            print(
                f"{domain:20} {domain_counts[domain]:5} records"
            )

    print()

    # ------------------------------------------------------------
    # Parse errors
    # ------------------------------------------------------------

    if parse_errors:
        print("PARSE ERRORS")
        print("-" * 72)

        for error in parse_errors[:20]:
            print(error)

        if len(parse_errors) > 20:
            print(
                f"... and {len(parse_errors) - 20} more"
            )

        print()

    print("=" * 72)
    print("AUDIT COMPLETE")
    print("=" * 72)


if __name__ == "__main__":
    main()