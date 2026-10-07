import json
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"knowledge"/"admission"/"bennett_admission_kb.jsonl"
required={"id","domain","title","section","content","source_url","source_type","source_id","verified_at","academic_year","chunk_index"}
rows=[]
for i,line in enumerate(p.read_text(encoding="utf-8").splitlines(),1):
    if not line.strip(): continue
    x=json.loads(line)
    missing=required-x.keys()
    if missing: raise SystemExit(f"Line {i} missing {sorted(missing)}")
    rows.append(x)
ids=[x["id"] for x in rows]
if len(ids)!=len(set(ids)): raise SystemExit("Duplicate IDs")
print("VALID",len(rows),"records,",len(set(x["source_id"] for x in rows)),"sources")
