from __future__ import annotations
import hashlib, json, re, shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
V6 = BACKEND / "knowledge_v6_staging"
OLD = BACKEND / "knowledge"
OUT = BACKEND / "knowledge_v7"
REPORT_DIR = BACKEND / "data" / "ingestion_reports"

CURATED = {"campus_services","career","health","hostel","sports","student_affairs","transport"}
LEGACY = {
    "admission":["bennett_admission_kb.jsonl"],
    "fees":["bennett_fees_kb.jsonl"],
    "it":["bennett_it_kb.jsonl"],
    "library":["bennett_library_kb.jsonl"],
}
MIN_LEN = 80
MAX_LEN = 5000

def clean(x): return re.sub(r"\s+", " ", str(x or "")).strip()
def fp(x): return hashlib.sha256(re.sub(r"[^a-z0-9]+"," ",x.lower()).strip().encode()).hexdigest()

def bad(text):
    t=clean(text)
    if len(t)<MIN_LEN or len(t)>MAX_LEN: return True
    low=t.lower()
    if low in {"skip to content","skip to main content","menu","search","loading","read more","learn more","click here"}: return True
    nav=["admission process","fee ay 2026-27","download brochure","international admissions","hostel lateral entry"]
    return len(t)>250 and sum(x in low for x in nav)>=3

def normalize(raw, domain, origin):
    content=clean(raw.get("content") or raw.get("text"))
    if bad(content): return None
    return {
        "id": raw.get("id") or "v7_"+fp(domain+content)[:20],
        "domain": clean(raw.get("domain") or domain).lower(),
        "title": clean(raw.get("title") or raw.get("source_title") or raw.get("document_title") or domain.title()),
        "section": clean(raw.get("section") or raw.get("heading") or "General"),
        "content": content,
        "source_id": clean(raw.get("source_id") or raw.get("source") or origin),
        "source_url": clean(raw.get("source_url") or raw.get("document_url") or raw.get("url")),
        "authority": raw.get("authority") or "official_bennett",
        "access": raw.get("access") or "public",
        "status": raw.get("status") or "current",
        "academic_year": raw.get("academic_year") or "2026-27",
        "verified_at": raw.get("verified_at") or datetime.now(timezone.utc).isoformat(),
        "ingestion_version": "v7",
    }

def read_file(path, domain):
    rows=[]; errors=[]
    with path.open("r",encoding="utf-8",errors="ignore") as f:
        for n,line in enumerate(f,1):
            if not line.strip(): continue
            try:
                raw=json.loads(line)
                if isinstance(raw,dict):
                    r=normalize(raw,domain,str(path))
                    if r: rows.append(r)
            except Exception as e: errors.append(f"{path}:{n}: {e}")
    return rows,errors

def collect():
    rows=[]; errors=[]; origins=Counter()
    if V6.exists():
        for p in V6.rglob("*.jsonl"):
            r,e=read_file(p,p.parent.name); rows+=r; errors+=e; origins["V6:"+p.parent.name]+=len(r)
    if OLD.exists():
        for d in sorted(CURATED):
            for p in sorted((OLD/d).glob("bennett_*.jsonl")) if (OLD/d).exists() else []:
                if p.name.endswith("_kb.jsonl"): continue
                r,e=read_file(p,d); rows+=r; errors+=e; origins["CURATED:"+d]+=len(r)
        for d,names in LEGACY.items():
            for name in names:
                p=OLD/d/name
                if p.exists():
                    r,e=read_file(p,d); rows+=r; errors+=e; origins["LEGACY:"+d]+=len(r)
    return rows,errors,origins

def main():
    rows,errors,origins=collect()
    if not rows: raise SystemExit("No input records found.")
    seen=set(); unique=[]; cross=defaultdict(set); removed=0
    for r in rows:
        key=fp(r["domain"]+"|"+r["content"]); cross[key].add(r["domain"])
        if key in seen: removed+=1; continue
        seen.add(key); unique.append(r)
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    counts=Counter()
    for r in unique:
        d=OUT/r["domain"]; d.mkdir(parents=True,exist_ok=True)
        with (d/"bennett_v7_kb.jsonl").open("a",encoding="utf-8") as f:
            f.write(json.dumps(r,ensure_ascii=False)+"\n")
        counts[r["domain"]]+=1
    REPORT_DIR.mkdir(parents=True,exist_ok=True)
    report={
        "version":"V7","generated_at":datetime.now(timezone.utc).isoformat(),
        "total_records":len(unique),"duplicates_removed":removed,
        "cross_domain_duplicate_groups":sum(len(v)>1 for v in cross.values()),
        "parse_errors":len(errors),"domain_counts":dict(sorted(counts.items())),
        "origins":dict(origins),"output":str(OUT),
        "existing_backend_knowledge_modified":False,
    }
    (REPORT_DIR/"ingestion_v7_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    lines=["# CampusOne V7 Clean KB Audit","",f"- Total records: **{len(unique)}**",f"- Duplicates removed: **{removed}**",f"- Cross-domain duplicate groups: **{report['cross_domain_duplicate_groups']}**",f"- Parse errors: **{len(errors)}**","","## Domain coverage","","| Domain | Records |","|---|---:|"]
    lines += [f"| {d} | {n} |" for d,n in sorted(counts.items())]
    lines += ["","","Existing `backend/knowledge` was NOT modified.","","V7 uses V6 staging + curated service records + selected legacy Admission/Fees/IT/Library records."]
    (REPORT_DIR/"ingestion_v7_report.md").write_text("\n".join(lines),encoding="utf-8")
    print("V7 CREATED:",OUT)
    print("TOTAL:",len(unique))
    for d,n in sorted(counts.items()): print(f"{d}: {n}")
    print("Existing backend/knowledge was NOT modified.")

if __name__=="__main__": main()
