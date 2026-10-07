
from pathlib import Path
import re

router = Path(__file__).resolve().parent / "app" / "router" / "router.py"

if not router.exists():
    raise SystemExit(f"Router not found: {router}")

text = router.read_text(encoding="utf-8")

m = re.search(r"CANONICAL_DOMAINS\s*=\s*\{.*?\n\}", text, flags=re.S)
if not m:
    raise SystemExit("Could not find CANONICAL_DOMAINS block. No changes made.")

new_domains = (
    'CANONICAL_DOMAINS = {\n'
    '    "admission": "Admission",\n'
    '    "facilities": "Facilities",\n'
    '    "fees": "Fees",\n'
    '    "it": "IT",\n'
    '    "library": "Library",\n'
    '    "academics": "Academics",\n'
    '    "campus_services": "Campus Services",\n'
    '    "career": "Career",\n'
    '    "examinations": "Examinations",\n'
    '    "health": "Health",\n'
    '    "hostel": "Hostel",\n'
    '    "policies": "Policies",\n'
    '    "security": "Security",\n'
    '    "sports": "Sports",\n'
    '    "student_affairs": "Student Affairs",\n'
    '    "transport": "Transport",\n'
    '}'
)
text = text[:m.start()] + new_domains + text[m.end():]

if "self.routing_chunks" not in text:
    needle = "        self.domain_embeddings: Dict[str, np.ndarray] = {}"
    if needle not in text:
        raise SystemExit("Could not find domain_embeddings state. No changes made.")

    replacement = needle + (
        "\n\n"
        "        # Clean corpus used only for domain classification.\n"
        "        self.routing_chunks: Dict[str, List[str]] = {}\n"
        "        self.routing_embeddings: Dict[str, np.ndarray] = {}"
    )
    text = text.replace(needle, replacement, 1)

    init_old = (
        "        self._load_knowledge()\n"
        "        self._build_indexes()"
    )
    init_new = (
        "        self._load_knowledge()\n"
        "        self._build_routing_corpus()\n"
        "        self._build_indexes()"
    )

    if init_old not in text:
        raise SystemExit("Could not find router initialization calls. No changes made.")

    text = text.replace(init_old, init_new, 1)

if "def _build_routing_corpus" not in text:
    marker = re.search(
        r"\n    # ={40,}\n    # BUILD EMBEDDINGS\n    # ={40,}\n\n    def _build_indexes",
        text,
    )
    if not marker:
        raise SystemExit("Could not find BUILD EMBEDDINGS section. No changes made.")

    method = r'''
    # ========================================================
    # ROUTING CORPUS
    # ========================================================

    def _build_routing_corpus(self):
        curated = {
            "Campus Services": "campus_services",
            "Career": "career",
            "Health": "health",
            "Hostel": "hostel",
            "Sports": "sports",
            "Student Affairs": "student_affairs",
            "Transport": "transport",
        }

        self.routing_chunks = {}

        for domain, folder_name in curated.items():
            folder = KNOWLEDGE_DIR / folder_name
            chunks = []

            if folder.exists():
                files = [
                    p for p in folder.glob("bennett_*.jsonl")
                    if not p.name.endswith("_kb.jsonl")
                ]

                for path in files:
                    try:
                        import json
                        with path.open(
                            "r",
                            encoding="utf-8",
                            errors="ignore",
                        ) as f:
                            for line in f:
                                if not line.strip():
                                    continue

                                try:
                                    record = json.loads(line)
                                except json.JSONDecodeError:
                                    continue

                                content = str(
                                    record.get("content", "")
                                ).strip()

                                if len(content) >= 50:
                                    chunks.append(content)

                    except Exception as exc:
                        print(
                            f"[ROUTER] WARNING: Could not read "
                            f"curated file {path}: {exc}"
                        )

            seen = set()
            unique = []

            for chunk in chunks:
                key = " ".join(chunk.lower().split())

                if key in seen:
                    continue

                seen.add(key)
                unique.append(chunk)

            self.routing_chunks[domain] = unique

            print(
                f"[ROUTER] Routing corpus {domain}: "
                f"{len(unique)} curated chunks"
            )

        for domain, chunks in self.domain_chunks.items():
            if domain in curated:
                continue

            self.routing_chunks[domain] = list(chunks)

            print(
                f"[ROUTER] Routing corpus {domain}: "
                f"{len(chunks)} existing chunks"
            )

        print(
            f"[ROUTER] Routing corpus domains: "
            f"{len(self.routing_chunks)}"
        )

'''
    text = text[:marker.start()] + "\n" + method + text[marker.start():]

build_match = re.search(
    r"    def _build_indexes\(self\):.*?(?=\n    # ={40,}\n    # SCORE ONE DOMAIN)",
    text,
    flags=re.S,
)
if not build_match:
    raise SystemExit("Could not find _build_indexes body. No changes made.")

new_build = r'''
    def _build_indexes(self):
        print("\n[ROUTER] Building semantic routing indexes...")

        for domain in sorted(self.routing_chunks.keys()):
            chunks = self.routing_chunks[domain]

            if not chunks:
                continue

            embeddings = self.model.encode(
                chunks,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

            self.routing_embeddings[domain] = np.asarray(
                embeddings,
                dtype=np.float32,
            )

            print(
                f"[ROUTER] Routing indexed {domain}: "
                f"{len(chunks)} chunks"
            )

        print("[ROUTER] Semantic domain router ready.\n")

'''
text = text[:build_match.start()] + new_build + text[build_match.end():]

text = text.replace(
    "        if not self.domain_embeddings:\n",
    "        if not self.routing_embeddings:\n",
    1,
)

score_match = re.search(
    r"        # ----------------------------------------------------\n"
    r"        # Score every canonical domain\n"
    r"        # ----------------------------------------------------\n"
    r"\n"
    r"        scores: Dict\[str, float\] = \{\}\n"
    r"\n"
    r"        for domain in self\.domain_embeddings\.keys\(\):.*?"
    r"        if not scores:",
    text,
    flags=re.S,
)

if not score_match:
    raise SystemExit("Could not find scoring block. No changes made.")

new_score = r'''
        # ----------------------------------------------------
        # Score every domain using the clean routing corpus.
        # ----------------------------------------------------

        scores: Dict[str, float] = {}

        for domain, embeddings in self.routing_embeddings.items():

            if embeddings is None or len(embeddings) == 0:
                scores[domain] = 0.0
                continue

            similarities = embeddings @ query_embedding

            top_n = min(TOP_K_DOMAIN_CHUNKS, len(similarities))
            top_scores = np.sort(similarities)[-top_n:]

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

            scores[domain] = float(score)

        if not scores:'''

text = text[:score_match.start()] + new_score + text[score_match.end():]

compile(text, str(router), "exec")

backup = router.with_name(router.stem + "_before_routing_patch.py")
if not backup.exists():
    backup.write_text(router.read_text(encoding="utf-8"), encoding="utf-8")

router.write_text(text, encoding="utf-8")

print(f"Patched successfully: {router}")
print(f"Backup created: {backup}")
print("Knowledge files were not modified.")
