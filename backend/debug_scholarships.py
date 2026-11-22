from app.rag.retriever import retriever

queries = [
    "What scholarships are available for students?",
    "What scholarships are available for BTech CSE?",
]

for query in queries:
    print("\n" + "=" * 80)
    print("QUERY:", query)
    print("=" * 80)

    results = retriever.search(query, domain="Admission", top_k=6)

    if not results:
        print("No results returned.")
        continue

    for i, item in enumerate(results, start=1):
        print(f"\n[{i}] Score: {item.get('score')}")
        print("Title:", item.get("title"))
        print("Section:", item.get("section"))
        print("Chunk ID:", item.get("chunk_id"))
        print("Text:", item.get("text"))
