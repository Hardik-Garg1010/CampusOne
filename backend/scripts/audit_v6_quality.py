
import argparse
import json
from collections import defaultdict, Counter
from pathlib import Path

def main():
    ap = argparse.ArgumentParser(description="CampusOne V6 staging quality review")
    ap.add_argument("--kb-dir", default="knowledge_v6_staging")
    ap.add_argument("--report", default="data/ingestion_reports/ingestion_v6_report.json")
    ap.add_argument("--out", default="data/ingestion_reports/v6_quality_review.md")
    args = ap.parse_args()

    kb = Path(args.kb_dir)
    report_path = Path(args.report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    records = []
    parse_errors = []
    for fp in sorted(kb.glob("*.jsonl")):
        for n, line in enumerate(fp.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                obj["_file"] = fp.name
                obj["_line"] = n
                records.append(obj)
            except Exception as e:
                parse_errors.append((fp.name, n, str(e)))

    by_text = defaultdict(list)
    by_domain_text = defaultdict(list)
    short = []
    missing = []

    for r in records:
        text = " ".join(str(r.get("text", "")).split())
        domain = r.get("domain", "")
        if len(text) < 120:
            short.append(r)
        if not r.get("source_url") or not domain:
            missing.append(r)
        by_text[text].append(r)
        by_domain_text[(domain, text)].append(r)

    duplicate_groups = {k:v for k,v in by_text.items() if len(v) > 1}
    cross_domain = {
        k:v for k,v in duplicate_groups.items()
        if len({x.get("domain") for x in v}) > 1
    }

    domain_counts = Counter(r.get("domain", "") for r in records)
    source_counts = Counter(r.get("source_id", "") for r in records)

    failures = []
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            failures = report.get("failures", [])
        except Exception:
            report = {}
    else:
        report = {}

    lines = [
        "# CampusOne V6 Quality Review",
        "",
        f"- Total records: **{len(records)}**",
        f"- Parse errors in JSONL: **{len(parse_errors)}**",
        f"- Exact duplicate groups: **{len(duplicate_groups)}**",
        f"- Cross-domain duplicate groups: **{len(cross_domain)}**",
        f"- Short records (<120 chars): **{len(short)}**",
        f"- Missing source URL/domain: **{len(missing)}**",
        f"- Ingestion failures: **{len(failures)}**",
        "",
        "## Domain coverage",
        "",
        "| Domain | Records |",
        "|---|---:|",
    ]
    for d, c in sorted(domain_counts.items()):
        lines.append(f"| {d} | {c} |")

    lines += ["", "## Ingestion failures", ""]
    if failures:
        for f in failures:
            lines.append(
                f"- `{f.get('source_id','?')}` — `{f.get('url','?')}` — "
                f"{f.get('error', f.get('message','unknown error'))}"
            )
    else:
        lines.append("- None")

    lines += ["", "## Duplicate groups", ""]
    if duplicate_groups:
        for i, (text, group) in enumerate(sorted(duplicate_groups.items(),
                                                 key=lambda x: -len(x[1]))):
            domains = sorted({x.get("domain","") for x in group})
            urls = sorted({x.get("source_url","") for x in group})
            preview = text[:350].replace("\n", " ")
            lines += [
                f"### Duplicate group {i+1} ({len(group)} records)",
                f"- Domains: `{', '.join(domains)}`",
                f"- URLs: `{len(urls)}`",
                f"- Text: {preview}",
                "",
            ]
    else:
        lines.append("- None")

    lines += ["## Short records", ""]
    for r in short[:50]:
        t = " ".join(str(r.get("text","")).split())
        lines.append(
            f"- `{r.get('domain')}` / `{r.get('source_id')}` — {t[:250]}"
        )
    if not short:
        lines.append("- None")

    lines += ["", "## Top sources", ""]
    for sid, c in source_counts.most_common(25):
        lines.append(f"- `{sid}`: {c}")

    out.write_text("\n".join(lines), encoding="utf-8")

    print("=" * 72)
    print("CAMPUSONE V6 QUALITY REVIEW")
    print("=" * 72)
    print(f"Records:                 {len(records)}")
    print(f"JSONL parse errors:      {len(parse_errors)}")
    print(f"Exact duplicate groups:  {len(duplicate_groups)}")
    print(f"Cross-domain duplicates: {len(cross_domain)}")
    print(f"Short records:           {len(short)}")
    print(f"Missing metadata:        {len(missing)}")
    print(f"Ingestion failures:      {len(failures)}")
    print("")
    print("DOMAIN COVERAGE")
    for d, c in sorted(domain_counts.items()):
        print(f"{d:24} {c:6}")
    print("")
    print(f"Review written to: {out}")
    print("No KB files were modified.")

if __name__ == "__main__":
    main()
