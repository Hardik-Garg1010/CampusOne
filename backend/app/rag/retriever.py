from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = BASE_DIR / "knowledge_real"

CACHE_DIR = BASE_DIR / ".campusone_cache"
CACHE_EMBEDDINGS = CACHE_DIR / "knowledge_embeddings.npy"
CACHE_SIGNATURE = CACHE_DIR / "knowledge_signature.txt"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

MIN_TEXT_LENGTH = 80

# Retrieve a wider candidate pool before applying intent,
# relevance, diversity, and duplicate filtering.
CANDIDATE_MULTIPLIER = 8

# Maximum number of final chunks from the same section.
MAX_CHUNKS_PER_SECTION = 1

# Final number returned to the API.
DEFAULT_TOP_K = 3


# ============================================================
# DATA STRUCTURE
# ============================================================

@dataclass
class KnowledgeChunk:
    domain: str
    title: str
    section: str
    text: str
    source_url: str
    source: str
    chunk_id: str
    verified_at: str
    academic_year: str


# ============================================================
# RETRIEVER
# ============================================================

class KnowledgeRetriever:

    def __init__(self):
        print("[RAG] Initializing knowledge retriever...")
        print(f"[RAG] Knowledge directory: {KNOWLEDGE_DIR}")

        self.model = SentenceTransformer(
            EMBEDDING_MODEL
        )

        self.chunks: List[KnowledgeChunk] = []
        self.embeddings: np.ndarray | None = None

        self._load_knowledge()
        self._build_index()

    # ========================================================
    # LOAD KNOWLEDGE
    # ========================================================

    def _load_knowledge(self) -> None:

        if not KNOWLEDGE_DIR.exists():
            print(
                "[RAG] WARNING: Knowledge directory does not exist."
            )
            return

        self._load_markdown_files()
        self._load_jsonl_files()

        print(
            f"[RAG] Loaded {len(self.chunks)} useful knowledge chunks."
        )

        domain_counts: Dict[str, int] = {}

        for chunk in self.chunks:
            domain_counts[chunk.domain] = (
                domain_counts.get(chunk.domain, 0) + 1
            )

        for domain in sorted(domain_counts):
            print(
                f"[RAG] {domain}: "
                f"{domain_counts[domain]}"
            )

    # ========================================================
    # MARKDOWN / TEXT
    # ========================================================

    def _load_markdown_files(self) -> None:

        for path in KNOWLEDGE_DIR.rglob("*"):

            if not path.is_file():
                continue

            if path.suffix.lower() not in {
                ".md",
                ".txt",
            }:
                continue

            domain = path.parent.name

            try:
                text = path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                ).strip()
            except Exception as exc:
                print(
                    f"[RAG] WARNING: Could not read "
                    f"{path}: {exc}"
                )
                continue

            if len(text) < MIN_TEXT_LENGTH:
                continue

            title = path.stem.replace("_", " ").title()

            self.chunks.append(
                KnowledgeChunk(
                    domain=domain,
                    title=title,
                    section=title,
                    text=text,
                    source_url="",
                    source="local_knowledge",
                    chunk_id=f"{domain}_{path.stem}",
                    verified_at="",
                    academic_year="",
                )
            )

    @staticmethod
    def _is_blocked_record(record: Dict[str, Any]) -> bool:
        """Reject development placeholders before they enter the RAG index."""
        blob = " ".join(
            str(record.get(key) or "")
            for key in ("title", "section", "content", "text", "source")
        ).lower()
        return any(
            marker in blob
            for marker in (
                "synthetic prototype data",
                "prototype note",
                "in deployment, it must be replaced",
                "prototype data for campusone",
            )
        )

    # ========================================================
    # JSONL
    # ========================================================

    def _load_jsonl_files(self) -> None:

        for path in KNOWLEDGE_DIR.rglob("*.jsonl"):

            try:
                with path.open(
                    "r",
                    encoding="utf-8",
                    errors="ignore",
                ) as file:

                    for line_number, line in enumerate(
                        file,
                        start=1,
                    ):

                        line = line.strip()

                        if not line:
                            continue

                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if self._is_blocked_record(record):
                            continue

                        text = str(
                            record.get("content")
                            or record.get("text")
                            or ""
                        ).strip()

                        if len(text) < MIN_TEXT_LENGTH:
                            continue

                        domain = str(
                            record.get("domain")
                            or path.parent.name
                        ).strip()

                        title = str(
                            record.get("title")
                            or path.stem
                        ).strip()

                        section = str(
                            record.get("section")
                            or title
                        ).strip()

                        source_url = str(
                            record.get("source_url")
                            or record.get("url")
                            or ""
                        ).strip()

                        source = str(
                            record.get("source_type")
                            or record.get("source")
                            or "knowledge_base"
                        ).strip()

                        chunk_id = str(
                            record.get("id")
                            or record.get("chunk_id")
                            or f"{path.stem}_{line_number}"
                        ).strip()

                        verified_at = str(
                            record.get("verified_at")
                            or ""
                        ).strip()

                        academic_year = str(
                            record.get("academic_year")
                            or ""
                        ).strip()

                        self.chunks.append(
                            KnowledgeChunk(
                                domain=domain,
                                title=title,
                                section=section,
                                text=text,
                                source_url=source_url,
                                source=source,
                                chunk_id=chunk_id,
                                verified_at=verified_at,
                                academic_year=academic_year,
                            )
                        )

            except Exception as exc:
                print(
                    f"[RAG] WARNING: Could not process "
                    f"{path}: {exc}"
                )

    # ========================================================
    # BUILD SEMANTIC INDEX
    # ========================================================

    @staticmethod
    def _knowledge_signature(texts: List[str]) -> str:
        """Return a stable fingerprint for the current embedding inputs."""
        h = hashlib.sha256()
        h.update(EMBEDDING_MODEL.encode("utf-8"))
        for text in texts:
            h.update(b"\0")
            h.update(text.encode("utf-8", errors="ignore"))
        return h.hexdigest()

    def _build_index(self) -> None:
        if not self.chunks:
            print("[RAG] WARNING: No knowledge chunks found.")
            return

        texts = [self._embedding_text(chunk) for chunk in self.chunks]
        signature = self._knowledge_signature(texts)

        try:
            if CACHE_EMBEDDINGS.exists() and CACHE_SIGNATURE.exists():
                cached_signature = CACHE_SIGNATURE.read_text(encoding="utf-8").strip()
                if cached_signature == signature:
                    cached = np.load(CACHE_EMBEDDINGS)
                    if cached.shape[0] == len(self.chunks):
                        self.embeddings = np.asarray(cached, dtype=np.float32)
                        print(f"[RAG] Loaded cached semantic index: {len(self.chunks)} chunks.")
                        return
        except Exception as exc:
            print(f"[RAG] WARNING: Could not load cached semantic index: {exc}")

        print("[RAG] Building semantic index...")
        self.embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=True,
            batch_size=32,
        )
        self.embeddings = np.asarray(self.embeddings, dtype=np.float32)

        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            np.save(CACHE_EMBEDDINGS, self.embeddings)
            CACHE_SIGNATURE.write_text(signature, encoding="utf-8")
            print("[RAG] Semantic index cache saved.")
        except Exception as exc:
            print(f"[RAG] WARNING: Could not save semantic index cache: {exc}")

        print(f"[RAG] Semantic index built: {len(self.chunks)} chunks.")

    @staticmethod
    def _embedding_text(
        chunk: KnowledgeChunk,
    ) -> str:

        # Metadata is included so a query such as
        # "eligibility criteria" can semantically align with
        # an "Eligibility Criteria" section.
        return (
            f"Domain: {chunk.domain}\n"
            f"Title: {chunk.title}\n"
            f"Section: {chunk.section}\n"
            f"Content: {chunk.text}"
        )

    # ========================================================
    # QUERY INTENT
    # ========================================================

    @staticmethod
    def _detect_intents(
        query: str,
    ) -> Dict[str, List[str]]:

        q = query.lower()

        intents: Dict[str, List[str]] = {
            "eligibility": [
                "eligibility",
                "eligible",
                "eligibility criteria",
                "criteria",
                "qualification",
                "qualifications",
                "who can apply",
                "can i apply",
                "requirements",
                "required qualification",
            ],
            "application": [
                "apply",
                "application",
                "how to apply",
                "application process",
                "admission process",
                "admission procedure",
                "steps",
                "procedure",
            ],
            "fees": [
                "fee",
                "fees",
                "tuition",
                "cost",
                "charges",
                "payment",
                "pay",
            ],
            "scholarship": [
                "scholarship",
                "scholarships",
                "financial aid",
                "merit scholarship",
                "fee waiver",
            ],
            "refund": [
                "refund",
                "refund policy",
                "cancellation",
                "withdraw",
                "withdrawal",
            ],
            "hostel": [
                "hostel",
                "accommodation",
                "residence",
                "room",
                "hostel fee",
            ],
            "transport": [
                "transport",
                "bus",
                "shuttle",
                "transportation",
            ],
            "contact": [
                "contact",
                "phone",
                "email",
                "counsellor",
                "counselor",
                "admissions office",
            ],
            "selection": [
                "selection",
                "selected",
                "entrance exam",
                "entrance examination",
                "interview",
                "selection criteria",
            ],
        }

        active: Dict[str, List[str]] = {}

        for intent, terms in intents.items():

            matched = [
                term
                for term in terms
                if term in q
            ]

            if matched:
                active[intent] = matched

        return active

    # ========================================================
    # INTENT -> SECTION / TITLE TERMS
    # ========================================================

    INTENT_SECTION_TERMS = {
        "eligibility": [
            "eligibility",
            "eligibility criteria",
            "eligibility and selection",
            "criteria",
            "qualification",
            "requirements",
        ],
        "application": [
            "application process",
            "admission process",
            "how to apply",
            "application",
            "steps",
            "procedure",
        ],
        "fees": [
            "fee",
            "fee structure",
            "tuition",
            "fees",
            "charges",
            "payment",
        ],
        "scholarship": [
            "scholarship",
            "scholarships",
            "financial support",
            "merit",
        ],
        "refund": [
            "refund",
            "refund policy",
            "withdrawal",
            "cancellation",
        ],
        "hostel": [
            "hostel",
            "accommodation",
            "residence",
        ],
        "transport": [
            "transport",
            "bus",
            "shuttle",
        ],
        "contact": [
            "contact",
            "counsellor",
            "counselor",
            "admissions office",
        ],
        "selection": [
            "selection",
            "selection criteria",
            "entrance",
            "interview",
        ],
    }

    # ========================================================
    # INTENT SCORE
    # ========================================================

    def _intent_score(
        self,
        query: str,
        chunk: KnowledgeChunk,
        intents: Dict[str, List[str]],
    ) -> float:

        if not intents:
            return 0.0

        title = chunk.title.lower()
        section = chunk.section.lower()
        text = chunk.text.lower()

        score = 0.0

        for intent in intents:

            terms = self.INTENT_SECTION_TERMS.get(
                intent,
                [],
            )

            for term in terms:

                if term in section:
                    # Strongest signal:
                    # query intent matches section heading.
                    score = max(score, 1.0)

                elif term in title:
                    score = max(score, 0.80)

                elif term in text:
                    score = max(score, 0.30)

        return min(score, 1.0)

    # ========================================================
    # EXACT PHRASE SCORE
    # ========================================================

    @staticmethod
    def _phrase_score(
        query: str,
        chunk: KnowledgeChunk,
    ) -> float:

        q_tokens = set(
            re.findall(
                r"\b[a-z0-9]+\b",
                query.lower(),
            )
        )

        if not q_tokens:
            return 0.0

        section_title = (
            f"{chunk.title} {chunk.section}"
        ).lower()

        matched = sum(
            1
            for token in q_tokens
            if len(token) >= 3
            and token in section_title
        )

        return min(
            matched / max(len(q_tokens), 1),
            1.0,
        )

    # ========================================================
    # DOMAIN FILTER
    # ========================================================

    @staticmethod
    def _normalize_domain(
        domain: str,
    ) -> str:

        return re.sub(r"\\s+", " ", str(domain).strip().lower().replace("_", " ")).strip()

    # ========================================================
    # SEARCH
    # ========================================================

    def search(
        self,
        query: str,
        domain: str = "",
        top_k: int = DEFAULT_TOP_K,
    ) -> List[Dict[str, Any]]:

        query = str(query).strip()

        if not query:
            return []

        if self.embeddings is None:
            return []

        # ----------------------------------------------------
        # Candidate domain filtering
        # ----------------------------------------------------

        normalized_requested_domain = (
            self._normalize_domain(domain)
            if domain
            else ""
        )

        candidate_indices = []

        for index, chunk in enumerate(self.chunks):

            if normalized_requested_domain:

                if (
                    self._normalize_domain(chunk.domain)
                    != normalized_requested_domain
                ):
                    continue

            candidate_indices.append(index)

        if not candidate_indices:
            return []

        # ----------------------------------------------------
        # Query embedding
        # ----------------------------------------------------

        query_embedding = self.model.encode(
            query,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        query_embedding = np.asarray(
            query_embedding,
            dtype=np.float32,
        )

        candidate_embeddings = self.embeddings[
            candidate_indices
        ]

        semantic_scores = (
            candidate_embeddings @ query_embedding
        )

        # ----------------------------------------------------
        # Query intent
        # ----------------------------------------------------

        intents = self._detect_intents(query)

        # ----------------------------------------------------
        # Score candidates
        # ----------------------------------------------------

        scored: List[Tuple[float, int, Dict[str, float]]] = []

        for local_index, global_index in enumerate(
            candidate_indices
        ):

            chunk = self.chunks[global_index]

            semantic = float(
                semantic_scores[local_index]
            )

            phrase = self._phrase_score(
                query,
                chunk,
            )

            intent = self._intent_score(
                query,
                chunk,
                intents,
            )

            # Metadata/section relevance is deliberately strong
            # for intent-specific queries.
            #
            # This means:
            # "What are the eligibility criteria?"
            #
            # will prefer a section titled
            # "Eligibility Criteria"
            # over a generally related admission-process chunk.

            metadata = 0.0

            section_lower = chunk.section.lower()
            title_lower = chunk.title.lower()

            if intents:

                for intent_name in intents:

                    terms = self.INTENT_SECTION_TERMS.get(
                        intent_name,
                        [],
                    )

                    for term in terms:

                        if term in section_lower:
                            metadata = max(
                                metadata,
                                1.0,
                            )

                        elif term in title_lower:
                            metadata = max(
                                metadata,
                                0.80,
                            )

            # Program-specific relevance prevents a generic fee query for
            # B.Tech from being hijacked by a hostel-fee chunk.
            q_lower = query.lower()
            program_bonus = 0.0
            if any(term in q_lower for term in ("b.tech", "btech", "b tech")):
                chunk_blob = f"{chunk.title} {chunk.section} {chunk.text}".lower()
                if any(term in chunk_blob for term in ("b.tech", "btech", "b tech")):
                    program_bonus = 0.10

            # Base semantic score remains the largest component.
            # Intent-aware metadata and program relevance are controlled
            # boosts, not replacements for semantic similarity.
            final_score = (
                0.58 * semantic
                + 0.17 * metadata
                + 0.10 * phrase
                + 0.15 * intent
                + program_bonus
            )

            # Prefer records explicitly marked as final/verified over noisy
            # legacy extraction chunks when both answer the same request.
            chunk_id_lower = chunk.chunk_id.lower()
            if chunk_id_lower.startswith("final-"):
                final_score += 0.12

            scored.append(
                (
                    final_score,
                    global_index,
                    {
                        "semantic": semantic,
                        "metadata": metadata,
                        "phrase": phrase,
                        "intent": intent,
                    },
                )
            )

        # ----------------------------------------------------
        # Sort
        # ----------------------------------------------------

        scored.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        candidate_limit = max(
            top_k * CANDIDATE_MULTIPLIER,
            top_k,
        )

        scored = scored[:candidate_limit]

        # ----------------------------------------------------
        # Diversity + near-duplicate suppression
        # ----------------------------------------------------

        selected = []

        section_counts: Dict[str, int] = {}

        selected_texts: List[str] = []

        for final_score, global_index, components in scored:

            chunk = self.chunks[global_index]

            section_key = (
                f"{self._normalize_domain(chunk.domain)}:"
                f"{chunk.section.strip().lower()}"
            )

            current_count = section_counts.get(
                section_key,
                0,
            )

            if current_count >= MAX_CHUNKS_PER_SECTION:
                continue

            normalized_text = self._normalize_for_duplicate(
                chunk.text
            )

            if self._is_near_duplicate(
                normalized_text,
                selected_texts,
            ):
                continue

            selected.append(
                (
                    final_score,
                    global_index,
                    components,
                )
            )

            selected_texts.append(
                normalized_text
            )

            section_counts[section_key] = (
                current_count + 1
            )

            if len(selected) >= top_k:
                break

        # ----------------------------------------------------
        # Convert to API format
        # ----------------------------------------------------

        results: List[Dict[str, Any]] = []

        for final_score, global_index, components in selected:

            chunk = self.chunks[global_index]

            results.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "domain": chunk.domain,
                    "title": chunk.title,
                    "source": chunk.source,
                    "source_url": chunk.source_url,
                    "section": chunk.section,
                    "text": chunk.text,
                    "verified_at": chunk.verified_at,
                    "academic_year": chunk.academic_year,
                    "score": round(
                        float(final_score),
                        4,
                    ),
                }
            )

        return results

    # ========================================================
    # DUPLICATE HELPERS
    # ========================================================

    @staticmethod
    def _normalize_for_duplicate(
        text: str,
    ) -> str:

        return " ".join(
            re.sub(
                r"[^a-z0-9\s]",
                " ",
                text.lower(),
            ).split()
        )

    @staticmethod
    def _is_near_duplicate(
        text: str,
        selected_texts: List[str],
    ) -> bool:

        if not text:
            return True

        text_tokens = set(text.split())

        if not text_tokens:
            return True

        for existing in selected_texts:

            existing_tokens = set(
                existing.split()
            )

            if not existing_tokens:
                continue

            intersection = (
                len(
                    text_tokens
                    & existing_tokens
                )
            )

            union = (
                len(
                    text_tokens
                    | existing_tokens
                )
            )

            if union == 0:
                continue

            jaccard = intersection / union

            if jaccard >= 0.82:
                return True

        return False


# ============================================================
# GLOBAL RETRIEVER
# ============================================================

retriever = KnowledgeRetriever()
