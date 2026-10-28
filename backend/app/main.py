from __future__ import annotations

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field, model_validator

from app.llm.client import llm
from app.rag.retriever import retriever
from app.router.router import router


app = FastAPI(
    title="CampusOne API",
    version="0.2.0",
)


class RouteRequest(BaseModel):
    question: str = Field(min_length=2)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class AskRequest(BaseModel):
    question: str | None = Field(default=None, min_length=2, max_length=4000)
    message: str | None = Field(default=None, min_length=2, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_input(self) -> "AskRequest":
        if not self.question and not self.message:
            raise ValueError("Either 'question' or 'message' is required.")
        return self

    def get_text(self) -> str:
        return self.question or self.message  # type: ignore[return-value]


def _is_context_dependent_followup(question: str) -> bool:
    """Recognize common short follow-ups that depend on prior turns."""
    q = " ".join(question.lower().split())
    markers = (
        "what about",
        "and what about",
        "how about",
        "what are its",
        "what is its",
        "when does it",
        "where can i",
        "how do i do that",
        "how can i do that",
        "tell me more",
        "and the timings",
        "what about the fees",
        "and fees",
        "and timings",
        "why is that",
        "can you explain that",
        "what does that mean",
    )
    starts_with_reference = q.startswith((
        "and ", "also ", "it ", "they ", "them ", "that ", "those ",
        "these ", "its ", "their ", "there ", "then ",
    ))
    return len(q.split()) <= 3 or starts_with_reference or any(
        marker in q for marker in markers
    )


def _conversation_context(history: list[ChatMessage]) -> str:
    if not history:
        return ""

    lines = []
    for item in history[-10:]:
        role = "Student" if item.role == "user" else "CampusOne"
        lines.append(f"{role}: {item.content.strip()}")
    return "\n".join(lines)


def _retrieval_query(question: str, history: list[ChatMessage]) -> str:
    """Expand a follow-up with the latest user topic for better retrieval."""
    if not history or not _is_context_dependent_followup(question):
        return question

    previous_user_questions = [
        item.content.strip()
        for item in history
        if item.role == "user" and item.content.strip()
    ]
    if not previous_user_questions:
        return question

    previous = previous_user_questions[-1]
    if previous.lower() == question.lower():
        return question

    return f"Previous context: {previous}\nCurrent follow-up: {question}"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "CampusOne"}


@app.post("/route")
def route(request: RouteRequest) -> dict:
    return router.route(request.question).as_dict()


@app.post("/ask")
def ask(request: AskRequest) -> dict:
    question = request.get_text().strip()
    history = request.history
    context_text = _conversation_context(history)
    search_query = _retrieval_query(question, history)

    # Routing remains useful for diagnostics, but it must not block a
    # legitimate question from being searched across the full knowledge base.
    route_result = router.route(question)
    routing = route_result.as_dict()

    # Search every indexed domain. This avoids losing the answer when the
    # router is uncertain or its top domain is not the best evidence source.
    contexts = retriever.search(
        search_query,
        domain="",
        top_k=6,
    )

    if not contexts:
        return {
            "message": (
                "I couldn't find sufficiently reliable information in the "
                "available Bennett University knowledge base to answer that. "
                "You can try rephrasing the question, or ask me to help find "
                "the relevant university department."
            ),
            "decision": "NOT_FOUND",
            "domain": route_result.domain,
            "routing": routing,
            "sources": [],
        }

    # Include recent conversation only as context for resolving references
    # and follow-ups. Retrieved KB evidence remains the factual source.
    answer_question = question
    if context_text:
        answer_question = (
            "Recent conversation (use only to understand references and "
            "follow-up intent; do not treat it as factual evidence):\n"
            f"{context_text}\n\nCurrent student question:\n{question}"
        )

    answer = llm.generate(answer_question, contexts)
    primary_domain = contexts[0].get("domain") or route_result.domain

    return {
        "message": answer,
        "decision": "ROUTE",
        "domain": primary_domain,
        "routing": routing,
        "sources": contexts,
    }
