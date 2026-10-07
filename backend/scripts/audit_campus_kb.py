from __future__ import annotations
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB_ROOT = ROOT / "knowledge"
REPORT_ROOT = ROOT / "data" / "ingestion_reports"
REPORT_ROOT.mkdir(parents=True, exist_ok=True)

MIN_GOOD_CHARS = 120
BOILERPLATE = [
    r"\bmenu\b", r"\bsearch\b", r"\bread more\b",
    r"\bclick here\b", r"\bprivacy policy\b",
    r"\bterms and conditions\b", r"\ball rights reserved\b",
    r"\bskip to\b", r"\bsubscribe\b",
]

IMPORTANT = {
    "fees": ["fee","tuition","refund","scholarship","payment","charge"],
    "it": ["wifi","wi-fi","lms","erp","password","helpdesk","office 365","onedrive","turnitin"],
    "library": ["library","borrow","renew","return","fine","database","e-journal","ebook","remote access"],
    "hostel": ["hostel","room","mess","laundry","warden","residence"],
    "transport": ["transport","bus","route","shuttle","day scholar"],
    "academics": ["academic","calendar","attendance","course","semester","registration","credit"],
    "examinations": ["exam","examination","result","re-evaluation","scribe","seating plan"],
    "student_affairs": ["student affairs","grievance","club","student council","nss","discipline"],
    "health": ["wellness","medical","doctor","counselling","counseling","ambulance","health"],
    "sports": ["sport","sports","gym","basketball","football","cricket","badminton"],
    "campus_services": ["dining","cafeteria","canteen","atm","shop","campus"],
    "security": ["security","emergency","anti-ragging","ragging","safety","posh","fire"],
    "career": ["placement","career","internship","recruiter","employability"],
    "policies": ["policy","guideline","ordinance","regulation","conduct","notice","form"],
}

def norm(s):
    return re.sub(r"\W+", " ", str(s).lower()).strip()

def h(s):
    return hashlib.sha256(norm(s).encode()).hexdigest()

def load():
    rows = []
    for p in KB_ROOT.rglob("*.jsonl"):
        if ".backup." in p.name.lower():
            continue
        with p.open(encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    x = json.loads(line)
                    x["_file"] = str(p)
                    x["_line"] = n
                    x["_folder_domain"] = p.parent.name
                    rows.append(x)
                except Exception as e:
                    rows.append({"_parse_error": str(e), "_file": str(p), "_line": n})
    return rows

def main():
    rows = load()
    valid = [x for x in rows if "_parse_error" not in x]
    parse_errors = [x for x in rows if "_parse_error" in x]

    domains = defaultdict(lambda: {
        "records": 0, "sources": set(), "source_counts": Counter(),
        "short": 0, "boilerplate": 0, "missing_url": 0, "term_hits": Counter()
    })
    hashes = defaultdict(list)
    source_counts = Counter()
    short = []
    boiler = []
    missing = []
    mismatch = []

    for x in valid:
        folder = x.get("_folder_domain", "unknown")
        domain = x.get("domain", folder)
        content = str(x.get("content", "") or "")
        sid = x.get("source_id")
        d = domains[folder]
        d["records"] += 1
        if sid:
            d["sources"].add(sid)
            d["source_counts"][sid] += 1
            source_counts[sid] += 1
        if not x.get("source_url"):
            d["missing_url"] += 1
            missing.append({"file":x["_file"],"line":x["_line"],"domain":domain,"source_id":sid})
        if domain != folder:
            mismatch.append({"file":x["_file"],"line":x["_line"],"folder":folder,"record":domain})
        if len(content) < MIN_GOOD_CHARS:
            d["short"] += 1
            short.append({"domain":domain,"source_id":sid,"chars":len(content),"preview":content[:120]})
        hits = [p for p in BOILERPLATE if re.search(p, content.lower())]
        if hits:
            d["boilerplate"] += 1
            boiler.append({"domain":domain,"source_id":sid,"hits":hits,"preview":content[:120]})
        for term in IMPORTANT.get(folder, []):
            if term.lower() in content.lower():
                d["term_hits"][term] += 1
        hashes[h(content)].append({
            "domain":domain,"source_id":sid,"file":x["_file"],"line":x["_line"]
        })

    duplicates = [v for v in hashes.values() if len(v) > 1]
    cross = [v for v in duplicates if len({z["domain"] for z in v}) > 1]

    domain_out = {}
    flags = []

    for domain, d in sorted(domains.items()):
        domain_out[domain] = {
            "records": d["records"],
            "unique_sources": len(d["sources"]),
            "source_counts": dict(d["source_counts"].most_common()),
            "short": d["short"],
            "boilerplate": d["boilerplate"],
            "missing_url": d["missing_url"],
            "important_term_hits": dict(d["term_hits"].most_common()),
        }
        if d["records"] and d["short"] / d["records"] > .15:
            flags.append(f"{domain}: high short-record rate")
        if d["records"] and d["boilerplate"] / d["records"] > .30:
            flags.append(f"{domain}: high boilerplate rate")

    if domain_out.get("library", {}).get("records", 0) < 20:
        flags.append("library: fewer than 20 records; inspect manually")
    if domain_out.get("it", {}).get("records", 0) < 20:
        flags.append("it: fewer than 20 records; inspect manually")

    report = {
        "total_records": len(valid),
        "jsonl_files": len(list(KB_ROOT.rglob("*.jsonl"))),
        "parse_errors": len(parse_errors),
        "exact_duplicate_groups": len(duplicates),
        "cross_domain_duplicate_groups": len(cross),
        "short_records": len(short),
        "boilerplate_records": len(boiler),
        "missing_source_urls": len(missing),
        "domain_mismatches": len(mismatch),
        "domains": domain_out,
        "quality_flags": flags,
        "top_sources": source_counts.most_common(40),
        "duplicate_examples": duplicates[:50],
        "cross_domain_duplicate_examples": cross[:50],
        "short_examples": short[:100],
        "boilerplate_examples": boiler[:100],
        "missing_url_examples": missing[:100],
        "parse_error_examples": parse_errors[:50],
    }

    jp = REPORT_ROOT / "kb_quality_audit.json"
    mp = REPORT_ROOT / "kb_quality_audit.md"
    jp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# CampusOne Knowledge Base Quality Audit", "",
        f"Total records: **{len(valid)}**",
        f"JSONL files: **{report['jsonl_files']}**",
        f"Exact duplicate groups: **{len(duplicates)}**",
        f"Cross-domain duplicate groups: **{len(cross)}**",
        f"Short records: **{len(short)}**",
        f"Boilerplate records: **{len(boiler)}**",
        f"Missing source URLs: **{len(missing)}**",
        f"Domain mismatches: **{len(mismatch)}**",
        f"Parse errors: **{len(parse_errors)}**", "",
        "## Domain coverage", "",
        "| Domain | Records | Sources | Short | Boilerplate |",
        "|---|---:|---:|---:|---:|"
    ]
    for domain, d in domain_out.items():
        lines.append(f"| {domain} | {d['records']} | {d['unique_sources']} | {d['short']} | {d['boilerplate']} |")
    lines += ["", "## Quality flags", ""]
    lines += [f"- WARNING: {x}" for x in flags] if flags else ["- None"]
    lines += ["", "## Highest-volume sources", ""]
    lines += [f"- `{sid}`: {n}" for sid, n in source_counts.most_common(25)]
    mp.write_text("\n".join(lines), encoding="utf-8")

    print("=" * 70)
    print("CAMPUSONE KB QUALITY AUDIT")
    print("=" * 70)
    print(f"Total records:           {len(valid)}")
    print(f"JSONL files:             {report['jsonl_files']}")
    print(f"Exact duplicate groups:  {len(duplicates)}")
    print(f"Cross-domain duplicates: {len(cross)}")
    print(f"Short records:           {len(short)}")
    print(f"Boilerplate signals:     {len(boiler)}")
    print(f"Missing source URLs:     {len(missing)}")
    print(f"Domain mismatches:       {len(mismatch)}")
    print(f"Parse errors:            {len(parse_errors)}")
    print()
    for domain, d in domain_out.items():
        print(f"{domain:20} {d['records']:6} records | {d['unique_sources']:3} sources | {d['short']:5} short | {d['boilerplate']:5} boilerplate")
    print()
    print("QUALITY FLAGS")
    for x in flags or ["None"]:
        print("WARNING:" if x != "None" else "", x)
    print()
    print("Reports:")
    print(jp)
    print(mp)

if __name__ == "__main__":
    main()
