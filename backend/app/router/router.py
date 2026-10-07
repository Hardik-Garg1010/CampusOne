from __future__ import annotations







from dataclasses import dataclass



from pathlib import Path



from typing import Dict, List, Optional, Tuple

from collections import Counter

import re







import numpy as np



from sentence_transformers import SentenceTransformer











# ============================================================



# CONFIGURATION



# ============================================================







BASE_DIR = Path(__file__).resolve().parents[2]



KNOWLEDGE_DIR = BASE_DIR / "knowledge_real"







EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"







# These are routing gates, not probabilities.



CONFIDENCE_THRESHOLD = 0.70



# The balanced, curated routing profiles have a tighter score spread than the

# old uneven scraped corpora. Calibrate the ambiguity gate to that score scale.

MARGIN_THRESHOLD = 0.20







TOP_K_DOMAIN_CHUNKS = 5











# ============================================================



# CANONICAL DOMAIN NAMES



# ============================================================







# Domain names are normalized so that:



#



# Admission



# admission



# ADMISSION



#  admission



#



# all become:



#



# Admission



#



# This prevents the router from treating different casing as



# separate domains.







CANONICAL_DOMAINS = {



    "admission": "Admission",



    "facilities": "Facilities",



    "fees": "Fees",



    "it": "IT",



    "library": "Library",



    "academics": "Academics",



    "campus_services": "Campus Services",



    "career": "Career",



    "examinations": "Examinations",



    "health": "Health",



    "hostel": "Hostel",



    "policies": "Policies",



    "security": "Security",



    "sports": "Sports",



    "student_affairs": "Student Affairs",



    "transport": "Transport",



}











# ============================================================



# ROUTE RESULT



# ============================================================







@dataclass



class RouteResult:



    domain: Optional[str]



    top_score: float



    second_domain: Optional[str]



    second_score: float



    margin: float



    decision: str



    reason: str



    scores: Dict[str, float]







    def as_dict(self) -> dict:



        return {



            "domain": self.domain,



            "top_score": round(self.top_score, 4),



            "second_domain": self.second_domain,



            "second_score": round(self.second_score, 4),



            "margin": round(self.margin, 4),



            "decision": self.decision,



            "reason": self.reason,



            "scores": {



                domain: round(score, 4)



                for domain, score in self.scores.items()



            },



        }











# ============================================================



# DOMAIN ROUTER



# ============================================================







class DomainRouter:







    def __init__(self):



        print("[ROUTER] Initializing semantic domain router...")



        print(f"[ROUTER] Knowledge directory: {KNOWLEDGE_DIR}")







        self.model = SentenceTransformer(EMBEDDING_MODEL)







        # domain -> list of knowledge chunks



        self.domain_chunks: Dict[str, List[str]] = {}







        # domain -> embedding matrix



        self.domain_embeddings: Dict[str, np.ndarray] = {}







        # Clean corpus used only for domain classification.



        self.routing_chunks: Dict[str, List[str]] = {}



        self.routing_embeddings: Dict[str, np.ndarray] = {}



        # Automatically derived domain profiles and centroids.

        self.domain_profiles: Dict[str, Dict[str, float]] = {}

        self.domain_centroids: Dict[str, np.ndarray] = {}







        self._load_knowledge()



        self._build_routing_corpus()



        self._build_indexes()







    # ========================================================



    # DOMAIN NORMALIZATION



    # ========================================================







    def _canonical_domain(self, domain: str) -> Optional[str]:



        """



        Convert any domain spelling/casing into one canonical name.







        Example:



            admission -> Admission



            Admission -> Admission



            ADMISSION -> Admission



        """







        if not domain:



            return None







        key = str(domain).strip().lower()







        return CANONICAL_DOMAINS.get(key)







    # ========================================================



    # LOAD KNOWLEDGE



    # ========================================================







    def _load_knowledge(self):



        """



        Discover domains from backend/knowledge.







        Supports:



            .md



            .txt



            .jsonl







        Domain names are normalized and merged so duplicate



        casing cannot create duplicate router domains.



        """







        if not KNOWLEDGE_DIR.exists():



            print("[ROUTER] WARNING: Knowledge directory does not exist.")



            return







        raw_domains: Dict[str, List[str]] = {}







        # ----------------------------------------------------



        # Scan domain directories



        # ----------------------------------------------------







        for domain_dir in KNOWLEDGE_DIR.iterdir():







            if not domain_dir.is_dir():



                continue







            raw_domain = domain_dir.name



            canonical_domain = self._canonical_domain(raw_domain)







            if canonical_domain is None:



                print(



                    f"[ROUTER] WARNING: Ignoring unknown domain "



                    f"directory: {raw_domain}"



                )



                continue







            raw_domains.setdefault(canonical_domain, [])







            # ------------------------------------------------



            # Markdown / text files



            # ------------------------------------------------







            for file_path in domain_dir.rglob("*"):







                if not file_path.is_file():



                    continue







                suffix = file_path.suffix.lower()







                # --------------------------------------------



                # Markdown / TXT



                # --------------------------------------------







                if suffix in {".md", ".txt"}:







                    try:



                        text = file_path.read_text(



                            encoding="utf-8",



                            errors="ignore",



                        ).strip()







                        if len(text) >= 50:



                            raw_domains[canonical_domain].append(text)







                    except Exception as exc:



                        print(



                            f"[ROUTER] WARNING: Could not read "



                            f"{file_path}: {exc}"



                        )







                # --------------------------------------------



                # JSONL



                # --------------------------------------------







                elif suffix == ".jsonl":







                    try:



                        import json







                        with file_path.open(



                            "r",



                            encoding="utf-8",



                            errors="ignore",



                        ) as f:







                            for line in f:







                                line = line.strip()







                                if not line:



                                    continue







                                try:



                                    record = json.loads(line)



                                except json.JSONDecodeError:



                                    continue







                                record_domain = record.get("domain")







                                # If JSONL contains a domain,



                                # normalize it too.



                                if record_domain:



                                    json_domain = self._canonical_domain(



                                        record_domain



                                    )







                                    if json_domain is None:



                                        continue







                                    # If the JSONL domain disagrees



                                    # with the folder, use canonical



                                    # domain from the record.



                                    target_domain = json_domain



                                else:



                                    target_domain = canonical_domain







                                content = record.get("content", "")







                                if not content:



                                    # Some datasets may use text



                                    # instead of content.



                                    content = record.get("text", "")







                                if not content:



                                    continue







                                content = str(content).strip()







                                if len(content) >= 50:



                                    raw_domains.setdefault(



                                        target_domain,



                                        [],



                                    )







                                    raw_domains[target_domain].append(



                                        content



                                    )







                    except Exception as exc:



                        print(



                            f"[ROUTER] WARNING: Could not process "



                            f"{file_path}: {exc}"



                        )







        # ----------------------------------------------------



        # Deduplicate chunks



        # ----------------------------------------------------







        for domain, chunks in raw_domains.items():







            unique_chunks = []



            seen = set()







            for chunk in chunks:







                # Normalize only for duplicate detection.



                normalized = " ".join(chunk.lower().split())







                if normalized in seen:



                    continue







                seen.add(normalized)



                unique_chunks.append(chunk)







            self.domain_chunks[domain] = unique_chunks







        # ----------------------------------------------------



        # Print final domains



        # ----------------------------------------------------







        print("\n[ROUTER] Domains discovered:")







        for domain in sorted(self.domain_chunks.keys()):



            print(



                f"  - {domain}: "



                f"{len(self.domain_chunks[domain])} chunks"



            )







        print(



            f"[ROUTER] Total domains: "



            f"{len(self.domain_chunks)}"



        )











    # ========================================================



    # ROUTING CORPUS



    # ========================================================







    def _build_routing_corpus(self):
        """Build a balanced routing corpus directly from the active KB."""
        self.routing_chunks = {}
        max_chunks = 80

        for domain, chunks in self.domain_chunks.items():
            if not chunks:
                continue

            unique = []
            seen = set()
            for chunk in chunks:
                key = " ".join(str(chunk).lower().split())
                if key in seen:
                    continue
                seen.add(key)
                unique.append(chunk)

            if len(unique) > max_chunks:
                step = len(unique) / max_chunks
                unique = [unique[min(int(i * step), len(unique) - 1)] for i in range(max_chunks)]

            self.routing_chunks[domain] = unique
            print(f"[ROUTER] Routing corpus {domain}: {len(unique)} KB chunks")

        print(f"[ROUTER] Active routing domains: {len(self.routing_chunks)}")


    def _build_domain_profiles(self):
        """Build lexical profiles from the active KB; no hard-coded examples."""
        if not self.routing_chunks:
            self.domain_profiles = {}
            print("[ROUTER] WARNING: No routing chunks available.")
            return

        stop_words = {
            "the", "and", "for", "with", "from", "that", "this", "are", "is",
            "was", "were", "what", "where", "when", "how", "who", "which",
            "about", "into", "their", "there", "have", "has", "had", "will",
            "can", "may", "students", "student", "university", "bennett", "campus",
            "available", "provide", "provides", "facility", "facilities", "service",
            "services", "information", "also", "more", "through", "than", "using",
            "used", "use", "within", "across", "under", "over", "per", "each", "all",
            "its", "our", "you", "your",
        }

        domain_terms = {}
        document_frequency = Counter()

        for domain, chunks in self.routing_chunks.items():
            terms = []
            for chunk in chunks:
                tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{2,}", chunk.lower())
                unique_tokens = set()
                for token in tokens:
                    token = token.strip("-'")
                    if token and token not in stop_words:
                        terms.append(token)
                        unique_tokens.add(token)
                for token in unique_tokens:
                    document_frequency[token] += 1
            domain_terms[domain] = terms

        n_domains = max(len(domain_terms), 1)
        self.domain_profiles = {}

        for domain, terms in domain_terms.items():
            counts = Counter(terms)
            total = sum(counts.values()) or 1
            weights = {}
            for token, count in counts.items():
                tf = count / total
                df = document_frequency[token]
                idf = np.log((1 + n_domains) / (1 + df)) + 1.0
                weights[token] = float(tf * idf)

            self.domain_profiles[domain] = dict(
                sorted(weights.items(), key=lambda x: x[1], reverse=True)[:300]
            )
            print(
                f"[ROUTER] Derived routing profile {domain}: "
                f"{len(self.routing_chunks[domain])} KB chunks"
            )

        # High-signal vocabulary is derived only from the actual routing KB.
        # No user questions or hand-written examples are stored here.
        self.domain_signal_terms = {}
        for domain, profile in self.domain_profiles.items():
            self.domain_signal_terms[domain] = {
                token: weight
                for token, weight in list(profile.items())[:80]
            }
            print(
                f"[ROUTER] Signal vocabulary {domain}: "
                f"{len(self.domain_signal_terms[domain])} terms"
            )

        print(f"[ROUTER] Domain profiles derived from {len(self.domain_profiles)} active KB domains.")


    # High-signal service vocabulary. These are domain/service terms, not
    # hard-coded user questions. They complement KB-derived profiles when a
    # domain has sparse or noisy source text.
    DOMAIN_CUES = {
        "Fees": {"fee", "fees", "tuition", "charges", "payment", "refund", "dues", "semester"},
        "IT": {"it", "wifi", "wi-fi", "internet", "password", "login", "lms", "helpdesk", "help", "technical", "support", "reset", "email"},
        "Hostel": {"hostel", "dorm", "residence", "accommodation", "room", "mess", "laundry"},
        "Library": {"library", "book", "books", "journal", "journals", "database", "borrow", "borrowing", "lrc"},
        "Transport": {"transport", "bus", "route", "pickup", "drop", "shuttle"},
        "Health": {"health", "medical", "doctor", "ambulance", "wellness", "counselling", "hospital"},
        "Sports": {"sport", "sports", "gym", "badminton", "basketball", "football", "swimming", "tennis", "squash"},
        "Career": {"career", "placement", "placements", "internship", "internships", "recruitment", "job", "jobs"},
        "Examinations": {"exam", "exams", "examination", "result", "results", "revaluation", "re-evaluation", "seating", "scribe"},
        "Admission": {"admission", "apply", "application", "eligibility", "selection", "scholarship", "counsellor", "counselor"},
        "Academics": {"academic", "academics", "course", "courses", "curriculum", "subject", "subjects", "faculty", "attendance"},
        "Security": {"security", "cctv", "guard", "guards", "emergency", "safety"},
        "Student Affairs": {"student", "students", "club", "clubs", "council", "grievance", "discipline", "nss"},
        "Policies": {"policy", "policies", "ordinance", "rules", "regulations", "guidelines"},
        "Campus Services": {"campus", "dining", "food", "atm", "facility", "facilities", "shopping", "wifi"},
    }

    def _cue_score(self, query: str, domain: str) -> float:
        """Score explicit service vocabulary without using question examples."""
        cues = self.DOMAIN_CUES.get(domain, set())
        if not cues:
            return 0.0

        q = query.lower()
        tokens = set(re.findall(r"[a-zA-Z][a-zA-Z0-9-]{1,}", q))
        matched = {
            c for c in cues
            if c.lower() in tokens or c.lower() in q
        }

        if not matched:
            return 0.0

        # Multiple explicit service terms are stronger evidence than a
        # single generic word. Keep the score bounded so semantic evidence
        # still matters for normal queries.
        return float(
            np.clip(
                0.62 + 0.16 * (len(matched) - 1),
                0.0,
                1.0,
            )
        )


    # Terms that are unusually specific to one campus service. These are
    # service vocabulary, not hard-coded user questions. They are useful
    # when the semantic KB contains overlapping concepts such as hostel
    # accommodation versus hostel fees, or IT versus physical security.
    EXCLUSIVE_CUES = {
        "Fees": {
            "fee", "fees", "tuition", "charges", "payment",
            "dues", "semester fee", "fee payment",
        },
        "IT": {
            "helpdesk", "help-desk", "it-helpdesk", "wifi",
            "wi-fi", "internet", "password", "lms", "login",
            "technical support", "technical", "reset",
        },
        "Library": {
            "library", "lrc", "borrowing", "borrow", "journal",
            "database",
        },
        "Transport": {
            "transport", "shuttle", "pickup", "drop", "route",
        },
        "Health": {
            "ambulance", "wellness", "medical", "doctor", "hospital",
            "counselling",
        },
        "Sports": {
            "badminton", "basketball", "football", "swimming",
            "tennis", "squash", "gym",
        },
        "Career": {
            "placement", "placements", "internship", "internships",
            "recruitment",
        },
        "Examinations": {
            "examination", "exam", "revaluation", "re-evaluation",
            "result", "results", "scribe", "seating plan",
        },
        "Admission": {
            "admission", "eligibility", "application", "scholarship",
            "counsellor", "counselor",
        },
        "Security": {
            "security", "cctv", "guard", "emergency", "safety",
        },
        "Hostel": {
            "hostel", "accommodation", "residence", "dorm", "hostel facilities",
        },
        "Student Affairs": {
            "grievance", "student grievance", "student council", "clubs",
        },
        "Policies": {
            "policy", "policies", "regulations", "ordinance", "rules",
        },
        "Academics": {
            "attendance", "curriculum", "course registration", "timetable",
        },
        "Campus Services": {
            "dining", "food", "cafeteria", "atm", "campus services",
        },
    }

    def _exclusive_cue_score(self, query: str, domain: str) -> float:
        cues = self.EXCLUSIVE_CUES.get(domain, set())
        if not cues:
            return 0.0

        q = query.lower()
        tokens = set(re.findall(r"[a-zA-Z][a-zA-Z0-9-]{1,}", q))
        matched = {
            cue for cue in cues
            if cue.lower() in tokens or cue.lower() in q
        }

        if not matched:
            return 0.0

        # One highly specific term is enough to establish strong routing
        # evidence; two or more make the signal even stronger.
        return float(
            np.clip(
                0.82 + 0.08 * (len(matched) - 1),
                0.0,
                1.0,
            )
        )


    def _priority_intent_domain(self, query: str):
        """High-signal service taxonomy gate. This is not a question-answer list."""
        q = query.lower()
        families = {
            "IT": ("wifi", "wi-fi", "internet", "helpdesk", "it support", "password reset", "lms"),
            "Fees": ("fee", "fees", "tuition", "fee structure", "charges", "payment", "dues"),
            "Hostel": ("hostel", "hostel facilities", "accommodation", "residence", "dorm"),
            "Career": ("career services", "career services centre", "placement", "internship", "recruitment"),
            "Student Affairs": ("grievance", "student grievance", "student council", "student affairs"),
            "Policies": ("policy", "policies", "regulations", "ordinance", "rules"),
            "Academics": ("attendance", "curriculum", "course registration", "timetable"),
            "Library": ("library", "lrc", "borrowing", "journal", "database"),
            "Campus Services": ("dining", "food facilities", "cafeteria", "atm"),
            "Transport": ("transport", "shuttle", "pickup", "drop", "route"),
            "Sports": ("badminton", "basketball", "football", "swimming", "tennis", "squash", "gym", "sports facilities"),
            "Security": ("security", "cctv", "guard", "emergency", "safety"),
            "Health": ("ambulance", "wellness", "medical", "doctor", "hospital", "counselling", "counseling"),
            "Examinations": ("examination", "exam", "revaluation", "re-evaluation", "result", "results", "scribe", "seating plan"),
        }
        active = []
        for domain, cues in families.items():
            if any(cue in q for cue in cues):
                active.append(domain)

        # Financial language wins over hostel/accommodation wording when both occur.
        if any(x in q for x in ("fee", "fees", "tuition", "fee structure", "payment", "dues", "charges")) and "IT" not in active and "Career" not in active:
            return "Fees"

        # If exactly one strong service family is present, route directly.
        if len(active) == 1:
            return active[0]
        return None

    def _lexical_domain_score(self, query: str, domain: str) -> float:
        profile = self.domain_profiles.get(domain, {})
        if not profile:
            return 0.0

        tokens = {
            t.strip("-'")
            for t in re.findall(
                r"[a-zA-Z][a-zA-Z0-9'-]{2,}",
                query.lower(),
            )
        }

        matched = [profile[t] for t in tokens if t in profile]
        if not matched:
            return 0.0

        total = max(sum(profile.values()), 1e-12)
        max_weight = max(profile.values()) or 1e-12

        coverage = max(0.0, min(1.0, sum(matched) / total))
        strongest = max(0.0, min(1.0, max(matched) / max_weight))

        # Stable lexical evidence; no square-root numerical instability.
        return float(
            np.clip(
                0.45 * np.sqrt(coverage) + 0.55 * strongest,
                0.0,
                1.0,
            )
        )


    def _domain_signal_score(self, query: str, domain: str) -> float:
        """Score strong vocabulary derived from the routing KB."""
        profile = self.domain_signal_terms.get(domain, {})
        if not profile:
            return 0.0

        tokens = {
            t.strip("-'")
            for t in re.findall(
                r"[a-zA-Z][a-zA-Z0-9'-]{2,}",
                query.lower(),
            )
        }

        matched = [profile[t] for t in tokens if t in profile]
        if not matched:
            return 0.0

        max_weight = max(profile.values()) or 1e-12
        strongest = max(matched) / max_weight
        count_bonus = min(len(set(
            t for t in tokens if t in profile
        )) / 3.0, 1.0)

        return float(
            np.clip(
                0.75 * strongest + 0.25 * count_bonus,
                0.0,
                1.0,
            )
        )

    # BUILD EMBEDDINGS



    # ========================================================











    def _build_indexes(self):

        self._build_domain_profiles()



        print("\n[ROUTER] Building semantic routing indexes...")



        self.domain_centroids = {}



        for domain in sorted(self.routing_chunks.keys()):

            chunks = self.routing_chunks[domain]



            if not chunks:

                continue



            embeddings = self.model.encode(

                chunks,

                normalize_embeddings=True,

                show_progress_bar=False,

            )



            embeddings = np.asarray(

                embeddings,

                dtype=np.float32,

            )



            self.routing_embeddings[domain] = embeddings



            centroid = np.mean(embeddings, axis=0)

            norm = np.linalg.norm(centroid)



            if norm > 0:

                centroid = centroid / norm



            self.domain_centroids[domain] = centroid.astype(

                np.float32

            )



            print(

                f"[ROUTER] Routing indexed {domain}: "

                f"{len(chunks)} chunks"

            )



        print("[ROUTER] Semantic domain router ready.\n")



    # SCORE ONE DOMAIN



    # ========================================================







    def _score_domain(



        self,



        query_embedding: np.ndarray,



        domain: str,



    ) -> float:







        embeddings = self.routing_embeddings.get(domain)







        if embeddings is None or len(embeddings) == 0:



            return 0.0







        # Since both query and chunk embeddings are normalized,



        # dot product = cosine similarity.



        similarities = embeddings @ query_embedding







        # Strongest few pieces of evidence.



        top_n = min(



            TOP_K_DOMAIN_CHUNKS,



            len(similarities),



        )







        top_scores = np.sort(similarities)[-top_n:]







        # Weight the strongest evidence more heavily.



        if top_n == 1:



            score = float(top_scores[-1])







        elif top_n == 2:



            score = (



                0.70 * float(top_scores[-1])



                + 0.30 * float(top_scores[-2])



            )







        else:



            score = (



                0.55 * float(top_scores[-1])



                + 0.25 * float(top_scores[-2])



                + 0.12 * float(top_scores[-3])



                + 0.08 * float(np.mean(top_scores[:-3]))



            )







        return float(score)







    # ========================================================



    # ROUTE



    # ========================================================







    def route(self, query: str) -> RouteResult:







        query = str(query).strip()







        if not query:



            return RouteResult(



                domain=None,



                top_score=0.0,



                second_domain=None,



                second_score=0.0,



                margin=0.0,



                decision="CLARIFY",



                reason="The query is empty.",



                scores={},



            )







        if not self.routing_embeddings:







            return RouteResult(



                domain=None,



                top_score=0.0,



                second_domain=None,



                second_score=0.0,



                margin=0.0,



                decision="CLARIFY",



                reason="No domain knowledge is available.",



                scores={},



            )







        # ----------------------------------------------------



        # Encode query



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











        # ----------------------------------------------------

        # Hybrid scoring: semantic evidence + KB-derived lexical

        # evidence + domain centroid consistency.

        # ----------------------------------------------------



        scores: Dict[str, float] = {}



        for domain, embeddings in self.routing_embeddings.items():

            if embeddings is None or len(embeddings) == 0:

                scores[domain] = 0.0

                continue



            similarities = embeddings @ query_embedding

            top_n = min(TOP_K_DOMAIN_CHUNKS, len(similarities))

            top_scores = np.sort(similarities)[-top_n:]



            max_sim = float(top_scores[-1])

            mean_top = float(np.mean(top_scores))



            centroid = self.domain_centroids.get(domain)

            centroid_sim = (

                float(centroid @ query_embedding)

                if centroid is not None

                else 0.0

            )



            lexical = self._lexical_domain_score(query, domain)



            semantic = float(np.clip((max_sim + 1.0) / 2.0, 0.0, 1.0))

            consistency = float(

                np.clip((mean_top + 1.0) / 2.0, 0.0, 1.0)

            )

            centroid_score = float(

                np.clip((centroid_sim + 1.0) / 2.0, 0.0, 1.0)

            )



            signal = self._domain_signal_score(query, domain)
            cue = self._cue_score(query, domain)
            exclusive_cue = self._exclusive_cue_score(query, domain)

            # Semantic evidence remains important, while explicit service
            # vocabulary can resolve otherwise overlapping domains.
            base_score = (
                0.34 * semantic
                + 0.14 * consistency
                + 0.10 * centroid_score
                + 0.12 * lexical
                + 0.10 * signal
                + 0.20 * cue
            )

            # A highly specific service term is strong routing evidence.
            # Add only a bounded bonus rather than replacing semantic
            # similarity, so genuinely ambiguous queries still clarify.
            scores[domain] = float(
                np.clip(
                    base_score + 0.16 * exclusive_cue,
                    0.0,
                    1.0,
                )
            )



        if not scores:







            return RouteResult(



                domain=None,



                top_score=0.0,



                second_domain=None,



                second_score=0.0,



                margin=0.0,



                decision="CLARIFY",



                reason="No valid domains were found.",



                scores={},



            )







        # ----------------------------------------------------



        # Sort domains by score



        # ----------------------------------------------------







        ranked = sorted(



            scores.items(),



            key=lambda item: item[1],



            reverse=True,



        )







        top_domain, top_score = ranked[0]







        if len(ranked) >= 2:



            second_domain, second_score = ranked[1]



        else:



            second_domain = None



            second_score = 0.0







        margin = top_score - second_score

        # High-signal service intent override.
        priority_domain = self._priority_intent_domain(query)
        if priority_domain in scores:
            priority_score = scores.get(priority_domain, 0.0)
            if priority_score >= 0.45:
                top_domain = priority_domain
                top_score = priority_score
                ranked_without_top = [(d, sc) for d, sc in ranked if d != priority_domain]
                if ranked_without_top:
                    second_domain, second_score = ranked_without_top[0]
                else:
                    second_domain, second_score = None, 0.0
                margin = top_score - second_score
                return RouteResult(
                    domain=top_domain,
                    top_score=top_score,
                    second_domain=second_domain,
                    second_score=second_score,
                    margin=margin,
                    decision="ROUTE",
                    reason="A high-signal campus service intent identified the destination domain.",
                    scores=scores,
                )







        # ----------------------------------------------------



        # Confidence + margin gate



        # ----------------------------------------------------







        if (



            top_score >= CONFIDENCE_THRESHOLD



            and margin >= MARGIN_THRESHOLD



        ):







            decision = "ROUTE"







            reason = (



                "The top domain has sufficient semantic confidence "



                "and a sufficient margin over the second-best domain."



            )







        else:







            decision = "CLARIFY"







            if top_score < CONFIDENCE_THRESHOLD:







                reason = (



                    "The top domain score is below the confidence "



                    "threshold; clarification is required."



                )







            else:







                reason = (



                    "The top two domains are too close; "



                    "clarification is required."



                )







        # ----------------------------------------------------



        # Return result



        # ----------------------------------------------------







        return RouteResult(



            domain=top_domain if decision == "ROUTE" else top_domain,



            top_score=float(top_score),



            second_domain=second_domain,



            second_score=float(second_score),



            margin=float(margin),



            decision=decision,



            reason=reason,



            scores=scores,



        )











# ============================================================



# GLOBAL ROUTER INSTANCE



# ============================================================







router = DomainRouter()
