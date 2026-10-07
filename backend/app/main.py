from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field, model_validator

from app.llm.client import llm
from app.rag.retriever import retriever
from app.router.router import router


app = FastAPI(
    title="CampusOne API",
    version="0.1.0",
)


class RouteRequest(BaseModel):
    question: str = Field(min_length=2)


class AskRequest(BaseModel):
    question: str | None = Field(default=None, min_length=2)
    message: str | None = Field(default=None, min_length=2)

    @model_validator(mode="after")
    def validate_input(self) -> "AskRequest":
        if not self.question and not self.message:
            raise ValueError(
                "Either 'question' or 'message' is required."
            )
        return self

    def get_text(self) -> str:
        return self.question or self.message  # type: ignore[return-value]


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "CampusOne",
    }


@app.post("/route")
def route(request: RouteRequest) -> dict:
    return router.route(request.question).as_dict()


@app.post("/ask")
def ask(request: AskRequest) -> dict:
    question = request.get_text()

    # ---------------------------------------------------------
    # 1. Route the question to the correct campus domain
    # ---------------------------------------------------------
    route_result = router.route(question)
    routing = route_result.as_dict()

    # ---------------------------------------------------------
    # 2. If routing is uncertain, ask for clarification
    # ---------------------------------------------------------
    if route_result.decision == "CLARIFY":
        top_domain = (
            route_result.domain
            or max(
                route_result.scores,
                key=route_result.scores.get,
            )
        )

        return {
            "message": (
                "I want to make sure I send this to the right "
                "campus service. Is this about "
                f"{top_domain} or {route_result.second_domain}?"
            ),
            "decision": "CLARIFY",
            "domain": None,
            "routing": routing,
            "sources": [],
        }

    # ---------------------------------------------------------
    # 3. Retrieve grounded knowledge from the selected domain
    # ---------------------------------------------------------
    contexts = retriever.search(
        question,
        route_result.domain or "",
        top_k=3,
    )

    # ---------------------------------------------------------
    # 4. Generate an answer using the retrieved context
    # ---------------------------------------------------------
    if not contexts:
        return {
            "message": (
                "I couldn't find a reliable answer in the "
                "available campus knowledge base. "
                "Please contact the relevant campus service "
                "for assistance."
            ),
            "decision": "ROUTE",
            "domain": route_result.domain,
            "routing": routing,
            "sources": [],
        }

    answer = llm.generate(
        question,
        contexts,
    )

    # ---------------------------------------------------------
    # 5. Return answer + routing information + sources
    # ---------------------------------------------------------
    return {
        "message": answer,
        "decision": "ROUTE",
        "domain": route_result.domain,
        "routing": routing,
        "sources": contexts,
    }
