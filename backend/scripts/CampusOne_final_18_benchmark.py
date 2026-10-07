import requests
import json
import time
from collections import Counter

API_URL = "http://127.0.0.1:8000/ask"

TESTS = [
    ("Q01", "My Wi-Fi is not working", "IT"),
    ("Q02", "What are the facilities available in the hostels?", "Hostel"),
    ("Q03", "What are the hostel fees?", "Fees"),
    ("Q04", "What support does the Career Services Centre provide?", "Career"),
    ("Q05", "Where can I find Bennett University's student policies and regulations?", "Policies"),
    ("Q06", "What are the attendance requirements for students?", "Academics"),
    ("Q07", "What dining and food facilities are available on campus?", "Campus Services"),
    ("Q08", "How can I submit a student grievance?", "Student Affairs"),
    ("Q09", "What are the library timings and facilities?", "Library"),
    ("Q10", "What are the B.Tech fee structure and charges?", "Fees"),
    ("Q11", "What are the eligibility requirements for admission?", "Admission"),
    ("Q12", "What transport facilities are available for students?", "Transport"),
    ("Q13", "What sports facilities are available at Bennett University?", "Sports"),
    ("Q14", "What security facilities are available on campus?", "Security"),
    ("Q15", "What medical and health facilities are available for students?", "Health"),
    ("Q16", "How can I apply for re-evaluation of my examination?", "Examinations"),
    ("Q17", "How can I contact the IT Helpdesk?", "IT"),
    ("Q18", "Which service handles facility?", "CLARIFY"),
]

results = []

print("=" * 90)
print("CAMPUSONE — 18 QUERY FINAL BACKEND BENCHMARK")
print("=" * 90)
print(f"API: {API_URL}")
print()

for i, (qid, question, expected) in enumerate(TESTS, 1):
    started = time.perf_counter()

    try:
        r = requests.post(
            API_URL,
            json={"question": question},
            timeout=60,
        )
        latency = (time.perf_counter() - started) * 1000
        r.raise_for_status()
        data = r.json()

        routing = data.get("routing", {}) or {}
        predicted = routing.get("domain", data.get("domain"))
        decision = routing.get("decision", data.get("decision"))
        top_score = float(routing.get("top_score", 0) or 0)
        second_score = float(routing.get("second_score", 0) or 0)
        margin = float(routing.get("margin", 0) or 0)
        sources = data.get("sources", []) or []

        if expected == "CLARIFY":
            correct = decision == "CLARIFY"
        else:
            correct = decision == "ROUTE" and predicted == expected

        results.append({
            "id": qid,
            "question": question,
            "expected": expected,
            "predicted": predicted,
            "decision": decision,
            "correct": correct,
            "top_score": top_score,
            "second_score": second_score,
            "margin": margin,
            "source_count": len(sources),
            "latency_ms": latency,
            "error": None,
        })

        status = "PASS" if correct else "FAIL"
        print(
            f"[{status}] {qid} | expected={expected:<16} "
            f"got={predicted or '-':<16} decision={decision:<8} "
            f"top={top_score:.4f} margin={margin:.4f} "
            f"latency={latency:.0f}ms"
        )

        if not correct:
            print(f"       Question: {question}")

    except Exception as e:
        latency = (time.perf_counter() - started) * 1000
        results.append({
            "id": qid,
            "question": question,
            "expected": expected,
            "predicted": None,
            "decision": "ERROR",
            "correct": False,
            "top_score": 0,
            "second_score": 0,
            "margin": 0,
            "source_count": 0,
            "latency_ms": latency,
            "error": str(e),
        })
        print(f"[ERROR] {qid} | {question}")
        print(f"        {e}")

total = len(results)
correct = sum(x["correct"] for x in results)
errors = sum(x["decision"] == "ERROR" for x in results)
clarifications = sum(x["decision"] == "CLARIFY" for x in results)

# A wrong-confident route means a ROUTE decision to the wrong domain.
wrong_confident = sum(
    x["decision"] == "ROUTE"
    and x["expected"] != "CLARIFY"
    and x["predicted"] != x["expected"]
    for x in results
)

avg_latency = sum(x["latency_ms"] for x in results) / total
route_cases = [
    x for x in results
    if x["expected"] != "CLARIFY"
]
route_correct = sum(
    x["decision"] == "ROUTE" and x["predicted"] == x["expected"]
    for x in route_cases
)

print()
print("=" * 90)
print("FINAL RESULTS")
print("=" * 90)
print(f"Overall correct:       {correct}/{total} ({correct/total*100:.2f}%)")
print(f"Correct domain routes: {route_correct}/{len(route_cases)} ({route_correct/len(route_cases)*100:.2f}%)")
print(f"Clarifications:        {clarifications}/{total} ({clarifications/total*100:.2f}%)")
print(f"Wrong-confident:       {wrong_confident}/{total} ({wrong_confident/total*100:.2f}%)")
print(f"API errors:            {errors}/{total}")
print(f"Average latency:       {avg_latency:.0f} ms")

print()
print("FAILURES")
print("-" * 90)
failures = [x for x in results if not x["correct"]]
if not failures:
    print("None")
else:
    for x in failures:
        print(
            f"{x['id']} | expected={x['expected']} | "
            f"got={x['predicted']} | decision={x['decision']} | "
            f"top={x['top_score']:.4f} | margin={x['margin']:.4f}"
        )
        print(f"  {x['question']}")
        if x["error"]:
            print(f"  ERROR: {x['error']}")

print()
print("DOMAIN BREAKDOWN")
print("-" * 90)
domains = sorted(set(x[2] for x in TESTS if x[2] != "CLARIFY"))
for domain in domains:
    subset = [x for x in results if x["expected"] == domain]
    ok = sum(x["correct"] for x in subset)
    print(f"{domain:<18} {ok}/{len(subset)}")

output = "data/evaluation/final_18_query_results.json"
with open(output, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print()
print(f"Detailed results saved to: {output}")
print("=" * 90)
