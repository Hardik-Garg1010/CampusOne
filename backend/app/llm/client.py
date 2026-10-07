from __future__ import annotations

import re
from typing import Any, Dict, List

import os
import requests


# ============================================================
# CONFIGURATION
# ============================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

OPENAI_BASE_URL = os.getenv(
    "OPENAI_BASE_URL",
    "https://api.openai.com/v1",
).rstrip("/")

LLM_MODEL = os.getenv(
    "LLM_MODEL",
    "gpt-4o-mini",
).strip()

LLM_TIMEOUT = int(
    os.getenv("LLM_TIMEOUT", "45")
)


# ============================================================
# LLM CLIENT
# ============================================================

class LLMClient:

    def __init__(self):
        self.api_key = OPENAI_API_KEY
        self.base_url = OPENAI_BASE_URL
        self.model = LLM_MODEL
        self.timeout = LLM_TIMEOUT

        if self.api_key:
            print(
                f"[LLM] Provider: OpenAI-compatible API | "
                f"Model: {self.model}"
            )
        else:
            print(
                "[LLM] No OPENAI_API_KEY found. "
                "Using deterministic grounded fallback."
            )

    # ========================================================
    # PUBLIC GENERATION METHOD
    # ========================================================

    def generate(
        self,
        question: str,
        contexts: List[Dict[str, Any]],
    ) -> str:

        question = str(question).strip()

        if not question:
            return "Please provide your campus-related question."

        if not contexts:
            return (
                "I couldn't find sufficiently relevant information "
                "in the CampusOne knowledge base to answer that "
                "question. Please rephrase your question or contact "
                "the relevant campus service."
            )

        # Optional external LLM.
        #
        # CampusOne does NOT require an API key. If one is not
        # configured, the local grounded formatter below is used.
        if self.api_key:
            try:
                answer = self._generate_with_llm(
                    question,
                    contexts,
                )

                if answer:
                    return answer

            except Exception as exc:
                print(f"[LLM] Generation failed: {exc}")
                print(
                    "[LLM] Falling back to local grounded response."
                )

        return self._fallback_answer(
            question,
            contexts,
        )

    # ========================================================
    # BUILD SOURCE CONTEXT FOR OPTIONAL LLM
    # ========================================================

    def _build_context(
        self,
        contexts: List[Dict[str, Any]],
    ) -> str:

        source_blocks = []

        for index, context in enumerate(contexts, start=1):

            title = str(
                context.get("title")
                or "CampusOne Knowledge Base"
            ).strip()

            section = str(
                context.get("section")
                or ""
            ).strip()

            source_url = str(
                context.get("source_url")
                or ""
            ).strip()

            text = str(
                context.get("text")
                or context.get("content")
                or ""
            ).strip()

            if not text:
                continue

            block = [
                f"[Source {index}]",
                f"Title: {title}",
            ]

            if section:
                block.append(f"Section: {section}")

            if source_url:
                block.append(f"URL: {source_url}")

            block.append(f"Content:\n{text}")

            source_blocks.append(
                "\n".join(block)
            )

        return "\n\n".join(source_blocks)

    # ========================================================
    # OPTIONAL LLM GENERATION
    # ========================================================

    def _generate_with_llm(
        self,
        question: str,
        contexts: List[Dict[str, Any]],
    ) -> str:

        source_context = self._build_context(contexts)

        system_prompt = """
You are CampusOne, an enterprise-style university campus assistant.

Answer the user's question using ONLY the supplied CampusOne
knowledge sources.

Rules:
1. Do not invent facts.
2. Do not use outside knowledge.
3. If the sources are insufficient, say so.
4. Preserve qualifications such as "as applicable to the program"
   and "as per program requirements".
5. Synthesize complementary sources instead of repeating them.
6. Cite factual claims using [Source N].
7. Keep the response concise and useful.
8. Do not mention routing, embeddings, similarity scores, or
   internal implementation details.

Use numbered steps for processes and bullets for lists.
"""

        user_prompt = f"""
User question:
{question}

CampusOne knowledge sources:
{source_context}

Write the final answer.
"""

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt.strip(),
                },
                {
                    "role": "user",
                    "content": user_prompt.strip(),
                },
            ],
            "temperature": 0.1,
        }

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )

        response.raise_for_status()

        data = response.json()
        choices = data.get("choices", [])

        if not choices:
            raise RuntimeError(
                "LLM provider returned no choices."
            )

        answer = choices[0].get(
            "message",
            {},
        ).get("content", "")

        if isinstance(answer, list):
            answer = "\n".join(
                str(item.get("text", ""))
                for item in answer
                if isinstance(item, dict)
                and item.get("text")
            )

        answer = str(answer).strip()

        if not answer:
            raise RuntimeError(
                "LLM provider returned an empty answer."
            )

        return answer

    # ========================================================
    # LOCAL GROUNDED FALLBACK
    # ========================================================

    def _fallback_answer(
        self,
        question: str,
        contexts: List[Dict[str, Any]],
    ) -> str:
        """
        Produce a concise, grounded answer without an external LLM.

        The fallback is intentionally deterministic. It:
        - removes duplicate / near-duplicate retrieved chunks;
        - extracts individual factual sentences instead of dumping chunks;
        - ranks sentences against the user's question and retrieval score;
        - limits the final answer to a small number of useful facts; and
        - cites only the sources that contributed selected facts.

        No facts are generated that are not present in the retrieved
        CampusOne knowledge base.
        """

        # Never surface synthetic/prototype placeholder records in a
        # user-facing answer. These are development artifacts, not
        # authoritative campus knowledge.
        contexts = [
            context for context in contexts
            if not self._is_synthetic_context(context)
        ]

        cleaned_contexts = self._deduplicate_contexts(contexts)

        if not cleaned_contexts:
            return (
                "I couldn't find sufficiently relevant information "
                "in the CampusOne knowledge base."
            )

        candidates = []
        question_tokens = self._content_tokens(question)

        for context_index, context in enumerate(cleaned_contexts):
            text = self._clean_retrieved_text(
                str(
                    context.get("text")
                    or context.get("content")
                    or ""
                )
            )

            if not text:
                continue

            context_score = self._safe_float(
                context.get("score"),
                default=0.0,
            )

            title = str(
                context.get("title")
                or "CampusOne Knowledge Base"
            ).strip()

            section = str(
                context.get("section")
                or ""
            ).strip()

            url = str(
                context.get("source_url")
                or ""
            ).strip()

            sentences = self._split_sentences(text)

            for sentence_index, sentence in enumerate(sentences):
                sentence = self._clean_sentence(sentence)

                if self._is_synthetic_context({"text": sentence}):
                    continue

                if not self._is_useful_sentence(sentence):
                    continue

                sentence_tokens = self._content_tokens(sentence)
                overlap = self._token_overlap(
                    question_tokens,
                    sentence_tokens,
                )

                # Retrieval relevance is the strongest signal. Question
                # overlap helps select the exact fact from a noisy chunk.
                score = (
                    0.55 * context_score
                    + 0.35 * overlap
                    + 0.10 * self._metadata_overlap(
                        question_tokens,
                        title,
                        section,
                    )
                )

                # Prefer earlier sentences only very slightly; this keeps
                # the fallback deterministic without favoring boilerplate.
                score += max(
                    0.0,
                    0.02 - (sentence_index * 0.001),
                )

                candidates.append(
                    {
                        "score": score,
                        "sentence": sentence,
                        "title": title,
                        "section": section,
                        "url": url,
                        "context_index": context_index,
                    }
                )

        if not candidates:
            return (
                "I found relevant campus sources, but they do not "
                "contain enough readable information to give a reliable "
                "answer."
            )

        candidates.sort(
            key=lambda item: (
                item["score"],
                -item["context_index"],
            ),
            reverse=True,
        )

        selected = self._select_diverse_sentences(
            candidates,
            max_sentences=6,
        )

        if not selected:
            return (
                "I found relevant campus sources, but I could not "
                "extract a concise answer from them."
            )

        # Assign stable source numbers before rendering inline citations.
        source_numbers = {}
        for item in selected:
            key = (
                item["title"].lower(),
                item["url"].lower(),
            )
            if key not in source_numbers:
                source_numbers[key] = len(source_numbers) + 1
            item["source_number"] = source_numbers[key]

        # ----------------------------------------------------
        # User-facing answer
        # ----------------------------------------------------

        lines = [
            "Here’s what I found:",
            "",
        ]

        for item in selected:
            source_number = item.get("source_number")
            citation = (
                f" [Source {source_number}]"
                if source_number
                else ""
            )
            lines.append(
                f"• {item['sentence']}{citation}"
            )

        # ----------------------------------------------------
        # Source list — only sources actually used in the answer
        # ----------------------------------------------------

        source_lines = []
        seen_sources = set()
        source_numbers = {}

        for item in selected:
            title = item["title"]
            url = item["url"]

            key = (
                title.lower(),
                url.lower(),
            )

            if key not in source_numbers:
                source_numbers[key] = len(source_numbers) + 1

            source_number = source_numbers[key]
            item["source_number"] = source_number

            if key in seen_sources:
                continue

            seen_sources.add(key)

            if url:
                source_lines.append(
                    f"- [Source {source_number}] {title} — {url}"
                )
            else:
                source_lines.append(
                    f"- [Source {source_number}] {title}"
                )

        if source_lines:
            lines.extend(
                [
                    "",
                    "Sources:",
                    *source_lines,
                ]
            )

        return "\n".join(lines)

    # ========================================================
    # RETRIEVAL CLEANUP
    # ========================================================

    @staticmethod
    def _is_synthetic_context(context: Dict[str, Any]) -> bool:
        blob = " ".join(
            str(context.get(key) or "")
            for key in ("title", "section", "text", "content", "source")
        ).lower()
        markers = (
            "synthetic prototype data",
            "prototype note",
            "in deployment, it must be replaced",
            "prototype data for campusone",
        )
        return any(marker in blob for marker in markers)


    @classmethod
    def _deduplicate_contexts(
        cls,
        contexts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Remove exact and near-duplicate retrieved chunks."""

        unique = []
        signatures = []

        for context in contexts:
            text = cls._clean_retrieved_text(
                str(
                    context.get("text")
                    or context.get("content")
                    or ""
                )
            )

            if not text:
                continue

            signature = cls._content_tokens(text)

            if not signature:
                continue

            duplicate = False

            for existing in signatures:
                similarity = cls._set_similarity(
                    signature,
                    existing,
                )

                if similarity >= 0.86:
                    duplicate = True
                    break

            if duplicate:
                continue

            cleaned = dict(context)
            cleaned["text"] = text
            unique.append(cleaned)
            signatures.append(signature)

        return unique

    @staticmethod
    def _clean_retrieved_text(text: str) -> str:
        """Normalize scraped/chunked text while preserving sentences."""

        text = text.replace("\\r", " ").replace("\\n", " ")
        text = re.sub(r"\\s+", " ", text).strip()

        # Remove markdown/list markers that are formatting noise in the
        # scraped source. The factual sentence itself is retained.
        text = re.sub(r"(?:^|\\s)[#]{1,6}\\s*", " ", text)
        text = re.sub(r"(?:^|\\s)[•▪●◦]+\\s*", " ", text)

        return re.sub(r"\\s+", " ", text).strip()

    @staticmethod
    def _clean_sentence(sentence: str) -> str:
        sentence = re.sub(r"\\s+", " ", sentence).strip()
        sentence = re.sub(r"^[-•▪●◦]+\\s*", "", sentence)
        return sentence.strip()

    @staticmethod
    def _is_useful_sentence(sentence: str) -> bool:
        """Reject obvious scraping/navigation noise and tiny fragments."""

        if len(sentence) < 35:
            return False

        lower = sentence.lower().strip()

        # Generic navigation / webpage boilerplate should not become an
        # answer bullet. This is intentionally pattern-based rather than
        # tied to any particular user question.
        noise_patterns = (
            "skip to main content",
            "click here",
            "read more",
            "learn more",
            "menu",
            "home |",
            "privacy policy",
            "terms and conditions",
            "javascript",
        )

        return not any(
            pattern in lower
            for pattern in noise_patterns
        )

    @staticmethod
    def _content_tokens(text: str) -> set[str]:
        return {
            token
            for token in re.findall(
                r"[a-z0-9]+",
                text.lower(),
            )
            if len(token) > 2
        }

    @staticmethod
    def _token_overlap(
        question_tokens: set[str],
        sentence_tokens: set[str],
    ) -> float:
        if not question_tokens or not sentence_tokens:
            return 0.0

        return len(
            question_tokens.intersection(sentence_tokens)
        ) / len(question_tokens)

    @staticmethod
    def _metadata_overlap(
        question_tokens: set[str],
        title: str,
        section: str,
    ) -> float:
        metadata_tokens = LLMClient._content_tokens(
            f"{title} {section}"
        )

        if not question_tokens or not metadata_tokens:
            return 0.0

        return len(
            question_tokens.intersection(metadata_tokens)
        ) / len(question_tokens)

    @staticmethod
    def _set_similarity(
        first: set[str],
        second: set[str],
    ) -> float:
        union = first | second

        if not union:
            return 1.0

        return len(first & second) / len(union)

    @staticmethod
    def _safe_float(
        value: Any,
        default: float = 0.0,
    ) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _select_diverse_sentences(
        cls,
        candidates: List[Dict[str, Any]],
        max_sentences: int = 6,
    ) -> List[Dict[str, Any]]:
        """Select high-value facts while suppressing repetition."""

        selected = []
        used_source_keys = set()

        for candidate in candidates:
            sentence_tokens = cls._content_tokens(
                candidate["sentence"]
            )

            if not sentence_tokens:
                continue

            duplicate = False

            for existing in selected:
                existing_tokens = cls._content_tokens(
                    existing["sentence"]
                )

                if cls._set_similarity(
                    sentence_tokens,
                    existing_tokens,
                ) >= 0.72:
                    duplicate = True
                    break

            if duplicate:
                continue

            source_key = (
                candidate["title"].lower(),
                candidate["url"].lower(),
            )

            # Prefer source diversity for the first two selected facts.
            if (
                selected
                and len(used_source_keys) < 2
                and source_key in used_source_keys
            ):
                continue

            selected.append(candidate)
            used_source_keys.add(source_key)

            if len(selected) >= max_sentences:
                break

        # If only one source was retrieved, fill the remaining slots from
        # that source rather than returning an unnecessarily short answer.
        if len(selected) < max_sentences:
            selected_keys = {
                (
                    item["sentence"].lower(),
                    item["title"].lower(),
                    item["url"].lower(),
                )
                for item in selected
            }

            for candidate in candidates:
                key = (
                    candidate["sentence"].lower(),
                    candidate["title"].lower(),
                    candidate["url"].lower(),
                )

                if key in selected_keys:
                    continue

                sentence_tokens = cls._content_tokens(
                    candidate["sentence"]
                )

                if any(
                    cls._set_similarity(
                        sentence_tokens,
                        cls._content_tokens(item["sentence"]),
                    ) >= 0.72
                    for item in selected
                ):
                    continue

                selected.append(candidate)
                selected_keys.add(key)

                if len(selected) >= max_sentences:
                    break

        return selected

    # ========================================================
    # ANSWER INTENT
    # ========================================================

    @staticmethod
    def _answer_intent(
        question: str,
    ) -> str:

        if any(
            term in question
            for term in (
                "eligibility",
                "eligible",
                "qualification",
                "qualifications",
                "requirements",
                "who can apply",
            )
        ):
            return "eligibility"

        if any(
            term in question
            for term in (
                "fee",
                "fees",
                "tuition",
                "cost",
                "charges",
                "payment",
            )
        ):
            return "fees"

        if any(
            term in question
            for term in (
                "scholarship",
                "scholarships",
                "financial aid",
            )
        ):
            return "scholarship"

        if any(
            term in question
            for term in (
                "hostel",
                "accommodation",
                "residence",
            )
        ):
            return "hostel"

        if any(
            term in question
            for term in (
                "refund",
                "refund policy",
                "withdrawal",
                "cancellation",
            )
        ):
            return "refund"

        if any(
            term in question
            for term in (
                "apply",
                "application",
                "admission process",
                "how to apply",
                "steps",
            )
        ):
            return "application"

        return "general"

    # ========================================================
    # SECTION LABEL
    # ========================================================

    @staticmethod
    def _clean_section_label(
        section: str,
    ) -> str:

        section = str(section).strip()

        if not section:
            return ""

        # Remove a trailing colon because Markdown heading syntax
        # already provides the visual separation.
        section = section.rstrip(":")

        return section

    # ========================================================
    # SECTION BODY FORMATTER
    # ========================================================

    def _format_section_body(
        self,
        text: str,
        intent: str,
    ) -> List[str]:

        raw_lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        if not raw_lines:
            return []

        output: List[str] = []

        # ----------------------------------------------------
        # Remove repeated section-heading lines that are already
        # represented by the Markdown heading.
        # ----------------------------------------------------

        for line in raw_lines:

            normalized = line.rstrip(":").strip().lower()

            if intent == "eligibility" and normalized in {
                "eligibility criteria",
                "eligibility",
            }:
                continue

            if normalized in {
                "selection criteria",
                "application process",
                "admission process",
                "scholarships & financial support",
                "merit-based & transparent",
            }:
                # Keep meaningful heading text as a heading only
                # when it is not the outer section heading.
                continue

            # ------------------------------------------------
            # Known criteria/list lines are presented as bullets.
            # ------------------------------------------------

            if self._is_bullet_candidate(line, intent):
                output.append(f"• {line}")
            else:
                output.append(line)

        # ----------------------------------------------------
        # If there are many lines, preserve readability by
        # separating the first explanatory paragraph from lists.
        # ----------------------------------------------------

        if len(output) > 1:
            formatted: List[str] = []

            for index, line in enumerate(output):

                if (
                    index > 0
                    and line.startswith("• ")
                    and formatted
                    and not formatted[-1].endswith("\n")
                ):
                    if (
                        formatted
                        and not formatted[-1].startswith("• ")
                    ):
                        formatted.append("")

                formatted.append(line)

            return formatted

        return output

    # ========================================================
    # BULLET DETECTION
    # ========================================================

    @staticmethod
    def _is_bullet_candidate(
        line: str,
        intent: str,
    ) -> bool:

        lower = line.lower()

        if intent == "eligibility":

            return any(
                phrase in lower
                for phrase in (
                    "class xii",
                    "class 12",
                    "national-level entrance",
                    "graduation results",
                    "bennett university entrance",
                    "personal interview",
                    "minimum ",
                    "overall cgpa",
                    "qualifying examination",
                    "prerequisite subjects",
                    "pre-requisite subjects",
                    "credit hours",
                )
            )

        if intent == "fees":
            return any(
                phrase in lower
                for phrase in (
                    "tuition",
                    "fee",
                    "fees",
                    "charge",
                    "payment",
                )
            )

        if intent == "scholarship":
            return "scholarship" in lower

        if intent == "hostel":
            return any(
                phrase in lower
                for phrase in (
                    "hostel",
                    "accommodation",
                    "residence",
                    "room",
                )
            )

        if intent == "refund":
            return any(
                phrase in lower
                for phrase in (
                    "refund",
                    "withdraw",
                    "cancellation",
                )
            )

        return False

    # ========================================================
    # TEXT HELPERS
    # ========================================================

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """
        Simple sentence splitter.

        It intentionally avoids external NLP dependencies.
        """

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        if not text:
            return []

        return [
            part.strip()
            for part in re.split(
                r"(?<=[.!?])\s+",
                text,
            )
            if part.strip()
        ]

    @classmethod
    def _first_useful_sentence(
        cls,
        text: str,
    ) -> str:

        sentences = cls._split_sentences(text)

        for sentence in sentences:

            if len(sentence) >= 45:
                return sentence

        return sentences[0] if sentences else ""

    @staticmethod
    def _looks_like_list_item(
        text: str,
    ) -> bool:

        lower = text.lower().strip()

        # Common heading/list patterns found in scraped webpages.
        patterns = (
            "class xii",
            "national-level entrance",
            "graduation results",
            "bennett university entrance",
            "personal interview",
        )

        return any(
            pattern in lower
            for pattern in patterns
        )

    @staticmethod
    def _extract_list_items(
        text: str,
    ) -> List[str]:

        items = []

        # Preserve line structure from the retrieved source.
        raw_lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        for line in raw_lines:

            # Ignore obvious headings.
            if len(line) < 15:
                continue

            lower = line.lower()

            # These are useful admission criteria in the current
            # Bennett admission source.
            useful_patterns = (
                "class xii",
                "national-level entrance",
                "graduation results",
                "bennett university entrance",
                "personal interview",
            )

            if any(
                pattern in lower
                for pattern in useful_patterns
            ):
                items.append(line)

        return items

    @staticmethod
    def _already_present(
        candidate: str,
        existing: List[str],
    ) -> bool:

        candidate_normalized = " ".join(
            candidate.lower().split()
        )

        for item in existing:

            item_normalized = " ".join(
                item.lower().split()
            )

            if candidate_normalized == item_normalized:
                return True

            # Avoid repeating almost identical sentences.
            if (
                candidate_normalized in item_normalized
                or item_normalized in candidate_normalized
            ):
                return True

        return False


# ============================================================
# GLOBAL CLIENT INSTANCE
# ============================================================

llm = LLMClient()
