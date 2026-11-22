
import requests

BASE_URL = "http://127.0.0.1:8000"

questions = [
    ("Fees", "What are the BTech tuition fees?"),
    ("Scholarships", "What scholarships are available for students?"),
    ("Unsupported", "What is the weather on campus right now?"),
]

for category, question in questions:
    try:
        response = requests.post(
            f"{BASE_URL}/ask",
            json={"question": question},
            timeout=30,
        )

        print(f"\n{'=' * 70}")
        print(f"TEST: {category}")
        print(f"QUESTION: {question}")
        print(f"HTTP STATUS: {response.status_code}")

        if response.ok:
            data = response.json()
            print(f"DECISION: {data.get('decision')}")
            print("ANSWER:")
            print(data.get("message", "No answer returned"))
        else:
            print("ERROR:", response.text)

    except requests.RequestException as exc:
        print(f"TEST FAILED: {category}")
        print(exc)
