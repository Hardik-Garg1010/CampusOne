# CampusOne

**One front door for every campus service.**

CampusOne is a prototype AI campus assistant that understands a student's request, routes it to the appropriate service domain, retrieves grounded information, and asks for clarification when routing is ambiguous.

## Initial domains

- IT
- Fees
- Facilities
- Library

## Current vertical slice

Student question → semantic domain routing → confidence/margin gate → domain-specific retrieval → grounded prototype answer + source.

## Backend

```powershell
cd backend
python -m venv .venv
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH="."
uvicorn app.main:app --reload
```

API docs: `http://127.0.0.1:8000/docs`

## Notes

- `sentence-transformers/all-MiniLM-L6-v2` is the intended local semantic router/retriever.
- A TF-IDF fallback keeps local development possible if the transformer model is unavailable.
- Current knowledge files include clearly labelled synthetic prototype content where official institutional data is not available.
- LLM generation is currently a provider-neutral mock. The next implementation step is to add the selected LLM provider without changing the routing/RAG interfaces.
