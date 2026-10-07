import json
import requests
from collections import Counter, defaultdict
from pathlib import Path

EVAL_FILE = Path("data/evaluation/routing_eval.jsonl")
API_URL = "http://127.0.0.1:8000/route"

# ------------------------------------------------------------
# Normalize evaluation labels to router domain names
# ------------------------------------------------------------

DOMAIN_NORMALIZE = {
    "academics": "Academics",
    "admission": "Admission",
    "campus_services": "Campus Services",
    "career": "Career",
    "examinations": "Examinations",
    "fees": "Fees",
    "health": "Health",
    "hostel": "Hostel",
    "it": "IT",
    "library": "Library",
    "policies": "Policies",
    "security": "Security",
    "sports": "Sports",
    "student_affairs": "Student Affairs",
    "transport": "Transport",
}


def normalize_domain(domain):
    return DOMAIN_NORMALIZE.get(
        str(domain).strip().lower(),
        str(domain).strip()
    )


# ------------------------------------------------------------
# Load evaluation dataset
# ------------------------------------------------------------

rows = []

with EVAL_FILE.open("r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            rows.append(json.loads(line))


print("=" * 70)
print("CAMPUSONE V2 ROUTER EVALUATION")
print("=" * 70)
print(f"Evaluation queries: {len(rows)}")


# ------------------------------------------------------------
# Run evaluation
# ------------------------------------------------------------

results = []

for i, row in enumerate(rows, 1):

    question = row["question"]

    # Convert:
    # student_affairs -> Student Affairs
    # campus_services -> Campus Services
    # etc.
    expected = normalize_domain(row["expected_domain"])

    try:

        response = requests.post(
            API_URL,
            json={"question": question},
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        predicted = data.get("domain")
        decision = data.get("decision")

        top_score = float(
            data.get("top_score", 0)
        )

        second_domain = data.get(
            "second_domain"
        )

        second_score = float(
            data.get("second_score", 0)
        )

        margin = float(
            data.get("margin", 0)
        )

        scores = data.get(
            "scores",
            {}
        ) or {}

        ranked = sorted(
            scores.items(),
            key=lambda x: float(x[1]),
            reverse=True
        )

        top2_domains = [
            x[0]
            for x in ranked[:2]
        ]

        results.append({
            "id": row["id"],
            "question": question,
            "expected": expected,
            "predicted": predicted,
            "decision": decision,
            "top_score": top_score,
            "second_domain": second_domain,
            "second_score": second_score,
            "margin": margin,
            "top2": top2_domains,
        })

    except Exception as e:

        results.append({
            "id": row["id"],
            "question": question,
            "expected": expected,
            "predicted": None,
            "decision": "ERROR",
            "top_score": 0,
            "second_domain": None,
            "second_score": 0,
            "margin": 0,
            "top2": [],
            "error": str(e),
        })

    if i % 10 == 0:
        print(
            f"Processed {i}/{len(rows)}"
        )


# ------------------------------------------------------------
# Metrics
# ------------------------------------------------------------

total = len(results)

top1_correct = sum(
    r["predicted"] == r["expected"]
    for r in results
)

top2_correct = sum(
    r["expected"] in r["top2"]
    for r in results
)

clarifications = sum(
    r["decision"] == "CLARIFY"
    for r in results
)

errors = sum(
    r["decision"] == "ERROR"
    for r in results
)

# ROUTE decision but wrong domain
wrong_confident = sum(
    r["decision"] == "ROUTE"
    and r["predicted"] != r["expected"]
    for r in results
)

route_decisions = sum(
    r["decision"] == "ROUTE"
    for r in results
)

correct_routes = sum(
    r["decision"] == "ROUTE"
    and r["predicted"] == r["expected"]
    for r in results
)


# ------------------------------------------------------------
# Overall results
# ------------------------------------------------------------

print()
print("=" * 70)
print("OVERALL RESULTS")
print("=" * 70)

print(
    f"Top-1 accuracy:       {top1_correct}/{total} "
    f"({top1_correct / total * 100:.2f}%)"
)

print(
    f"Top-2 accuracy:       {top2_correct}/{total} "
    f"({top2_correct / total * 100:.2f}%)"
)

print(
    f"ROUTE decisions:      {route_decisions}/{total} "
    f"({route_decisions / total * 100:.2f}%)"
)

print(
    f"Correct ROUTE:        {correct_routes}/{total} "
    f"({correct_routes / total * 100:.2f}%)"
)

print(
    f"Clarifications:       {clarifications}/{total} "
    f"({clarifications / total * 100:.2f}%)"
)

print(
    f"Wrong-confident:      {wrong_confident}/{total} "
    f"({wrong_confident / total * 100:.2f}%)"
)

print(
    f"API errors:           {errors}/{total}"
)


# ------------------------------------------------------------
# Per-domain metrics
# ------------------------------------------------------------

domains = sorted(
    set(r["expected"] for r in results)
)

print()
print("=" * 70)
print("PER-DOMAIN ACCURACY")
print("=" * 70)

for domain in domains:

    domain_rows = [
        r
        for r in results
        if r["expected"] == domain
    ]

    correct = sum(
        r["predicted"] == domain
        for r in domain_rows
    )

    routed_correct = sum(
        r["decision"] == "ROUTE"
        and r["predicted"] == domain
        for r in domain_rows
    )

    clarified = sum(
        r["decision"] == "CLARIFY"
        for r in domain_rows
    )

    print(
        f"{domain:20} "
        f"accuracy={correct / len(domain_rows) * 100:6.2f}% "
        f"route_correct={routed_correct:2d} "
        f"clarify={clarified:2d}"
    )


# ------------------------------------------------------------
# Confusion matrix
# ------------------------------------------------------------

matrix = defaultdict(Counter)

for r in results:

    predicted = (
        r["predicted"]
        or "ERROR"
    )

    matrix[
        r["expected"]
    ][predicted] += 1


print()
print("=" * 70)
print("CONFUSION MATRIX")
print("=" * 70)

for expected in domains:

    print()
    print(
        f"EXPECTED: {expected}"
    )

    for predicted, count in (
        matrix[expected].most_common()
    ):

        print(
            f"  -> {predicted}: {count}"
        )


# ------------------------------------------------------------
# Wrong / failed routes
# ------------------------------------------------------------

failures = [
    r
    for r in results
    if r["predicted"] != r["expected"]
]

failures.sort(
    key=lambda r: r["top_score"],
    reverse=True
)


print()
print("=" * 70)
print("WRONG / FAILED ROUTES")
print("=" * 70)

if not failures:

    print()
    print("No routing failures.")

else:

    for r in failures[:30]:

        print()
        print(
            f"ID:       {r['id']}"
        )

        print(
            f"Question: {r['question']}"
        )

        print(
            f"Expected: {r['expected']}"
        )

        print(
            f"Got:      {r['predicted']}"
        )

        print(
            f"Decision: {r['decision']}"
        )

        print(
            f"Score:    {r['top_score']:.4f}"
        )

        print(
            f"Second:   {r['second_domain']} "
            f"({r['second_score']:.4f})"
        )

        print(
            f"Margin:   {r['margin']:.4f}"
        )


# ------------------------------------------------------------
# Save detailed results
# ------------------------------------------------------------

output = Path(
    "data/evaluation/v2_router_results.json"
)

output.write_text(
    json.dumps(
        results,
        indent=2,
        ensure_ascii=False
    ),
    encoding="utf-8"
)


print()
print("=" * 70)
print(
    f"Detailed results saved to: {output}"
)
print("=" * 70)