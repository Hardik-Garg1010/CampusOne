from app.router.router import router


def test_wifi_routes_to_it():
    result = router.route("How do I connect to campus Wi-Fi?")
    assert result.decision == "ROUTE"
    assert result.domain == "IT"


def test_fee_question_routes_to_fees():
    result = router.route("When is my semester fee deadline?")
    assert result.decision == "ROUTE"
    assert result.domain == "Fees"
