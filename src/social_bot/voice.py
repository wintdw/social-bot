"""The operator's own voice, retrieved from their messages — style for the rewriter.

The rewriter writes captions in a **brand** voice (the DNA + the voice menu). This
module adds the operator's **real** voice: it searches a corpus of the operator's
own messages (normalized JSONL, the same shape the twin project ingests) for the
lines closest to the post being written, and the rewriter is handed those lines —
plus the learned ``profile.md`` — as ``=== MY VOICE ===``.

Two rules this module exists to hold, both inherited from the twin project:

* **Retrieval feeds voice, not answers.** The hits show how the operator writes —
  diction, rhythm, teencode level, address terms — never what to say. The facts
  come from the draft; the structure comes from the DNA. Nothing here is ever
  presented as a source of truth.
* **It is an enhancement, never a gate.** A missing corpus, a missing optional
  dependency or a failed embedding call must never fail a rewrite: the caller
  gets ``""`` and the prompt is simply shorter.

The retrieval mechanism is ported from the twin project (``keyword``, ``fusion``,
``store``, ``embed*``, ``pipeline.retrieve``): pure-Python BM25, an embedded
LanceDB vector index, and reciprocal-rank fusion of the two when the corpus is
dominated by short fragments, where neither ranker is reliable alone.

**``lancedb`` and ``fastembed`` are imported inside functions, never at module
scope**, so importing this module (and therefore the rewriter worker, and the
test suite) needs only PyYAML. The vector backends simply report "not installed"
until the ``[voice]`` extra is present.
"""

from __future__ import annotations

import json
import math
import os
import pathlib
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .config import ROOT

TABLE_NAME = "chunks"  # matches the twin's index, so one can be copied in place


# -- records -------------------------------------------------------------


@dataclass
class Record:
    """One normalized message (or one chunk of a long message).

    Field-for-field the same shape the twin's ingest writes, so a corpus (and an
    index) produced by the twin can be used here unchanged.
    """

    id: str
    chat: str = ""
    source: str = ""
    author: str = ""
    is_me: bool = False
    timestamp: str = ""
    text: str = ""
    reply_to: str | None = None
    chunk_index: int = 0
    chunk_total: int = 1

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["reply_to"] = self.reply_to or ""
        return row

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> Record:
        return cls(
            id=str(row.get("id", "")),
            chat=str(row.get("chat", "")),
            source=str(row.get("source", "")),
            author=str(row.get("author", "")),
            is_me=bool(row.get("is_me", False)),
            timestamp=str(row.get("timestamp", "")),
            text=str(row.get("text", "")),
            reply_to=(str(row["reply_to"]) if row.get("reply_to") else None),
            chunk_index=int(row.get("chunk_index", 0)),
            chunk_total=int(row.get("chunk_total", 1)),
        )


def load_records(directory: pathlib.Path) -> list[Record]:
    """Read every ``*.jsonl`` in ``directory`` (sorted) into one record list."""
    records: list[Record] = []
    for path in sorted(pathlib.Path(directory).glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        records.append(Record.from_dict(json.loads(line)))
                    except (ValueError, TypeError):
                        continue  # a malformed line is skipped, never fatal
    return records


# -- BM25 (diacritic-folded, so unaccented chat still matches) ------------


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
# `đ` is a base letter with a stroke, not a diacritic, so NFD does not split it.
# Case is preserved, so `fold` is usable on its own, not just before `.lower()`.
_STROKE = {"đ": "d", "Đ": "D", "ð": "d"}


def fold(text: str) -> str:
    """Strip Vietnamese diacritics to ASCII base letters (``đ`` -> ``d``)."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    stripped = unicodedata.normalize("NFC", stripped)
    for source, target in _STROKE.items():
        stripped = stripped.replace(source, target)
    return stripped


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(fold(text).lower())


class BM25:
    """Okapi BM25 over plain strings. Pure Python: no model, no index file."""

    def __init__(self, docs: Sequence[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.term_freqs = [Counter(tokenize(doc)) for doc in docs]
        self.lengths = [sum(tf.values()) for tf in self.term_freqs]
        self.avg_length = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0

        doc_freq: Counter[str] = Counter()
        for tf in self.term_freqs:
            doc_freq.update(tf.keys())
        total = len(docs)
        self.idf = {
            term: math.log(1 + (total - freq + 0.5) / (freq + 0.5))
            for term, freq in doc_freq.items()
        }

    def score(self, query: str, index: int) -> float:
        tf = self.term_freqs[index]
        length = self.lengths[index] or 1
        norm = 1 - self.b + self.b * length / (self.avg_length or 1)
        total = 0.0
        for term in set(tokenize(query)):
            freq = tf.get(term)
            if not freq:
                continue
            total += self.idf.get(term, 0.0) * (freq * (self.k1 + 1)) / (freq + self.k1 * norm)
        return total

    def top(self, query: str, k: int) -> list[tuple[int, float]]:
        scored = [(index, self.score(query, index)) for index in range(len(self.term_freqs))]
        scored = [(index, score) for index, score in scored if score > 0]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]


def _keyword_search(records: Sequence[Record], query: str, k: int) -> list[dict[str, Any]]:
    """The ``k`` best-matching records as row dicts (shape matches the vector store)."""
    if not records or not query.strip():
        return []
    ranked = BM25([record.text for record in records]).top(query, k)
    hits: list[dict[str, Any]] = []
    for index, score in ranked:
        row = records[index].to_dict()
        row["_score"] = score
        hits.append(row)
    return hits


def reciprocal_rank_fusion(
    result_lists: Sequence[Sequence[dict[str, Any]]],
    k: int,
    key: str = "id",
    k_const: int = 60,
) -> list[dict[str, Any]]:
    """Fuse ranked lists by rank alone (no score calibration between rankers).

    A row found by both rankers keeps the fields of whichever list saw it first,
    *plus* any extra keys the other one adds — so a hit that came back from the
    vector ranker still carries its ``_similarity`` for the relevance gate even
    when the lexical ranker happened to list it first.
    """
    scores: dict[str, float] = {}
    rows: dict[str, dict[str, Any]] = {}

    for results in result_lists:
        for rank, row in enumerate(results):
            ident = str(row.get(key) or row.get("text") or "")
            if not ident:
                continue
            scores[ident] = scores.get(ident, 0.0) + 1.0 / (k_const + rank + 1)
            if ident in rows:
                for name, value in row.items():
                    rows[ident].setdefault(name, value)
            else:
                rows[ident] = dict(row)

    ordered = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    fused: list[dict[str, Any]] = []
    for ident, score in ordered[:k]:
        row = dict(rows[ident])
        row["_score"] = score
        fused.append(row)
    return fused


# -- embeddings ----------------------------------------------------------


class LocalEmbeddings:
    """``embedding.provider: local`` — fastembed (ONNX), CPU, no key, no server."""

    def __init__(self, model: str, cache_dir: str = "", batch_size: int = 64):
        from fastembed import TextEmbedding  # noqa: PLC0415 (the [voice] extra)

        if not model:
            raise ValueError("voice.embedding.model is not set")
        self.batch_size = max(1, int(batch_size))
        kwargs = {"cache_dir": cache_dir} if cache_dir else {}
        self._model = TextEmbedding(model_name=model, **kwargs)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.embed(list(texts), batch_size=self.batch_size)
        return [[float(value) for value in vector] for vector in vectors]


class HttpEmbeddings:
    """``embedding.provider: openai`` — an OpenAI-compatible ``/embeddings`` endpoint.

    Stdlib ``urllib``, like every other outbound call in this project. The model
    must match the one that built the index.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        batch_size: int = 64,
        timeout_seconds: float = 120.0,
    ):
        if not base_url:
            raise ValueError("voice.embedding.base_url is not set")
        if not model:
            raise ValueError("voice.embedding.model is not set")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.batch_size = max(1, int(batch_size))
        self.timeout = float(timeout_seconds)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_batch(list(texts[start : start + self.batch_size])))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        body = json.dumps({"model": self.model, "input": batch}).encode("utf-8")
        request = urllib.request.Request(f"{self.base_url}/embeddings", data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace").strip()
            raise RuntimeError(f"embeddings HTTP {exc.code}: {detail[:200]}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise RuntimeError(f"embeddings request failed: {exc}") from exc
        rows = payload.get("data") or []
        if len(rows) != len(batch):
            raise RuntimeError(f"embedded {len(rows)} of {len(batch)} texts")
        return [[float(value) for value in row["embedding"]] for row in rows]


# -- vector store --------------------------------------------------------


class VectorStore:
    """Embedded LanceDB table (no server, plain files on disk)."""

    def __init__(self, path: pathlib.Path | str):
        import lancedb  # noqa: PLC0415 (the [voice] extra)

        self.path = str(path)
        pathlib.Path(self.path).mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(self.path)

    def rebuild(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            raise ValueError("refusing to build an index with no rows")
        self.db.create_table(TABLE_NAME, data=rows, mode="overwrite")
        return len(rows)

    def count(self) -> int:
        try:
            return self.db.open_table(TABLE_NAME).count_rows()
        except Exception:  # a missing table is simply an empty index
            return 0

    def search(self, vector: list[float], limit: int = 8, only_me: bool = False):
        query = self.db.open_table(TABLE_NAME).search(vector)
        try:  # sentence embeddings are directional: cosine beats the L2 default
            query = query.metric("cosine")
        except (AttributeError, TypeError):
            pass
        query = query.limit(limit)
        if only_me:
            query = query.where("is_me = true")
        return query.to_list()


# -- config plumbing -----------------------------------------------------


def _config(cfg: dict) -> dict:
    return dict(cfg.get("voice", {}) or {})


def _resolve(raw: Any) -> pathlib.Path:
    """A configured path, resolved against the project root when relative."""
    path = pathlib.Path(str(raw or "")).expanduser()
    return path if path.is_absolute() else ROOT / path


def corpus_dir(cfg: dict) -> pathlib.Path:
    return _resolve(_config(cfg).get("corpus_dir"))


def index_dir(cfg: dict) -> pathlib.Path:
    return _resolve(_config(cfg).get("index_dir"))


def profile_file(cfg: dict) -> pathlib.Path:
    return _resolve(_config(cfg).get("profile_file"))


def backend(cfg: dict) -> str:
    return str(_config(cfg).get("backend", "vector")).strip().lower()


def top_k(cfg: dict) -> int:
    return int(_config(cfg).get("top_k", 8) or 8)


def only_me(cfg: dict) -> bool:
    return bool(_config(cfg).get("only_me", True))


def min_similarity(cfg: dict) -> float:
    """The cosine-similarity floor an example must clear (0 = no floor)."""
    return float(_config(cfg).get("min_similarity", 0.0) or 0.0)


def min_example_words(cfg: dict) -> int:
    """How many words an example needs to be worth quoting (0 = no minimum)."""
    return int(_config(cfg).get("min_example_words", 0) or 0)


def enabled(cfg: dict) -> bool:
    """True when the voice block is on and there is a corpus to search."""
    if not _config(cfg).get("enabled"):
        return False
    directory = corpus_dir(cfg)
    return directory.is_dir() and any(directory.glob("*.jsonl"))


def embedder(cfg: dict):
    """The configured embedding backend (lazy: imports fastembed only when used)."""
    emb = dict(_config(cfg).get("embedding") or {})
    provider = str(emb.get("provider", "local")).strip().lower()
    if provider == "local":
        return LocalEmbeddings(
            model=str(emb.get("model", "")),
            cache_dir=str(emb.get("cache_dir", "") or ""),
            batch_size=int(emb.get("batch_size", 64)),
        )
    api_key = str(emb.get("api_key") or os.environ.get("SOCIAL_BOT_VOICE_EMBEDDING_API_KEY", ""))
    return HttpEmbeddings(
        base_url=str(emb.get("base_url", "")),
        model=str(emb.get("model", "")),
        api_key=api_key,
        batch_size=int(emb.get("batch_size", 64)),
        timeout_seconds=float(emb.get("timeout_seconds", 120.0)),
    )


_RECORDS_CACHE: dict[str, tuple[int, list[Record]]] = {}


def _records(cfg: dict) -> list[Record]:
    """The corpus, memoized on the directory's own mtime (a scan rewrites files)."""
    directory = corpus_dir(cfg)
    try:
        stamp = int(directory.stat().st_mtime_ns)
    except OSError:
        return []
    key = str(directory)
    cached = _RECORDS_CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    records = load_records(directory)
    _RECORDS_CACHE[key] = (stamp, records)
    return records


# -- retrieval -----------------------------------------------------------


def query_for_draft(draft: dict) -> str:
    """The retrieval query for one draft: what the post is about.

    The source's own title and excerpt — that is what exists before a caption
    does. A draft with neither (a bare photo post) falls back to whatever caption
    it already carries.
    """
    parts = [str(draft.get("title") or "").strip(), str(draft.get("excerpt") or "").strip()]
    query = "\n".join(part for part in parts if part)
    return query or str(draft.get("caption") or "").strip()


_OVERFETCH = 4  # candidates fetched per requested example, before link-only rows drop
_URL_RE = re.compile(r"https?://\S+|\bwww\.\S+", re.IGNORECASE)


def has_voice(text: str) -> bool:
    """True when a message says something, rather than only carrying a link.

    A chat export is full of bare links — shares, course URLs, "check this" — and
    as a style example a link teaches nothing. Short messages are deliberately
    *not* filtered here: terse fragments are this voice's signature, and the
    length gate is a separate, configurable knob (`min_example_words`). Only text
    left with no word at all once its links are removed is dropped.
    """
    return bool(re.search(r"\w", _URL_RE.sub(" ", text or ""), re.UNICODE))


def _meaningful_words(text: str) -> int:
    """Word count of a message with its links removed (0 for a link-only row)."""
    return len(re.findall(r"\w+", _URL_RE.sub(" ", text or ""), re.UNICODE))


def _is_example(hit: dict, floor: float, min_words: int, *, require_similarity: bool) -> bool:
    """Whether a retrieved row is worth putting in front of the model.

    Two things make a row useless as a *style* example, both seen on real drafts:
    a bare link (`has_voice`), and a fragment that merely shares a common word
    with the query — ``in CZ we trust`` for an article titled *How LLMs Can Find
    a Needle in a Haystack*, matched on "in"/"we". The similarity floor is what
    catches the second. Measured on this corpus, unrelated chat sits at 0.46–0.50
    while a genuine topical match reaches 0.55+, so the floor separates them
    cleanly. BM25 cannot: its scores for junk (8.8–10.6) overlap a good match's
    (8.9–16.8), which is why under `hybrid` only rows the semantic ranker vetted
    may pass — a row with no `_similarity` was never vetted.
    """
    text = str(hit.get("text", ""))
    if not has_voice(text):
        return False
    if min_words and _meaningful_words(text) < min_words:
        return False
    if not require_similarity:
        return True
    similarity = hit.get("_similarity")
    return isinstance(similarity, (int, float)) and float(similarity) >= floor


def search(cfg: dict, query: str, k: int | None = None) -> list[dict[str, Any]]:
    """Retrieve ``k`` style examples: by vector, keyword (BM25), or both fused.

    Every candidate has to clear the gate in :func:`_is_example` — which is what
    keeps junk out of the prompt, at the cost of returning fewer (or no) examples:
    an empty list is the honest answer for a topic this corpus has nothing to say
    about, and the caller then writes from the profile and the voice menu alone.

    Raises on a genuine failure (no index, no embedding backend); callers that
    must not fail — the rewriter worker — go through :func:`examples_block`.
    """
    limit = int(k if k is not None else top_k(cfg))
    # Fetch more than asked for: candidates get dropped by the gate, and the
    # block is better filled with rows that survive it.
    pool = max(limit * _OVERFETCH, 24)
    backend_name = backend(cfg)
    floor = min_similarity(cfg)
    min_words = min_example_words(cfg)
    # Only the semantic ranker can judge relevance; keyword mode has no vetting
    # to rely on, so it gets the length filter alone.
    require_similarity = backend_name != "keyword"

    if backend_name == "keyword":
        hits = _keyword_search(_corpus_records(cfg), query, pool)
    elif backend_name == "hybrid":
        candidates = max(pool, int(_config(cfg).get("hybrid_candidates", 60) or 60))
        lexical = _keyword_search(_corpus_records(cfg), query, candidates)
        semantic = _vector_search(cfg, query, candidates)
        hits = reciprocal_rank_fusion([lexical, semantic], pool)
    else:
        hits = _vector_search(cfg, query, pool)

    kept = [
        hit
        for hit in hits
        if _is_example(hit, floor, min_words, require_similarity=require_similarity)
    ]
    return kept[:limit]


def _corpus_records(cfg: dict) -> list[Record]:
    """Corpus records, narrowed to the operator's own when ``only_me``."""
    records = _records(cfg)
    return [record for record in records if record.is_me] if only_me(cfg) else records


def _vector_search(cfg: dict, query: str, k: int) -> list[dict[str, Any]]:
    """Nearest corpus rows, each annotated with ``_similarity`` (cosine, higher is better).

    The gate in :func:`search` needs a number with an absolute meaning, and
    LanceDB only returns a distance — so it is converted here, at the one place
    that knows the metric was cosine.
    """
    vector = embedder(cfg).embed([query])[0]
    rows = VectorStore(index_dir(cfg)).search(vector, limit=k, only_me=only_me(cfg))
    for row in rows:
        distance = row.get("_distance")
        if isinstance(distance, (int, float)):
            row["_similarity"] = 1.0 - float(distance)
    return rows


def profile_text(cfg: dict) -> str:
    """The learned ``profile.md`` ('' when there is none, or it is switched off)."""
    if not _config(cfg).get("include_profile", True):
        return ""
    path = profile_file(cfg)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def render_examples(hits: Sequence[dict[str, Any]], max_chars: int = 0) -> str:
    """Render hits as numbered style examples, optionally capped in length."""
    blocks: list[str] = []
    used = 0
    for index, hit in enumerate(hits, start=1):
        who = "me" if hit.get("is_me") else (hit.get("author") or "other")
        meta = f"({hit.get('chat', '?')} · {who} · {hit.get('timestamp', '')})"
        block = f"[{index}] {meta}\n{hit.get('text', '')}".strip()
        if max_chars > 0 and blocks and used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def examples_block(cfg: dict, draft: dict, *, k: int | None = None) -> str:
    """The ``=== MY VOICE ===`` body for one draft: profile + topic-matched lines.

    Returns ``""`` — never raises — when the block is off, there is nothing to say,
    or retrieval fails. The voice is an enhancement on top of the DNA and the voice
    menu, so it must never be the reason a rewrite fails.

    The two halves fail independently: a broken index costs the examples but still
    lets the learned ``profile.md`` ride along, since it needs no retrieval at all.
    """
    if not enabled(cfg):
        return ""

    hits: list[dict[str, Any]] = []
    query = query_for_draft(draft)
    if query:
        try:
            hits = search(cfg, query, k)
        except Exception as exc:  # enhancement only: warn and write without them
            print(
                f"[voice] retrieval failed ({exc}); writing without voice examples",
                file=sys.stderr,
            )

    profile = profile_text(cfg)
    examples = render_examples(hits, int(_config(cfg).get("max_examples_chars", 0) or 0))
    if not profile and not examples:
        return ""

    parts: list[str] = []
    if profile:
        parts.append(profile)
    if examples:
        parts.append(
            f"--- real messages I wrote, closest to this topic (style only) ---\n{examples}"
        )
    return "\n\n".join(parts)


# -- corpus + index maintenance ------------------------------------------


def build_index(cfg: dict) -> int:
    """Embed the corpus into the LanceDB index; returns the row count.

    A no-op for the ``keyword`` backend, which reads the JSONL directly.
    """
    records = _records(cfg) if corpus_dir(cfg).is_dir() else []
    if not records:
        raise ValueError(
            f"no corpus records in {corpus_dir(cfg)}; put the messages there as *.jsonl"
        )
    if backend(cfg) == "keyword":
        return len(records)

    vectors = embedder(cfg).embed([record.text for record in records])
    if len(vectors) != len(records):
        raise RuntimeError(f"embedded {len(vectors)} of {len(records)} records")
    rows = [
        {**record.to_dict(), "vector": vector}
        for record, vector in zip(records, vectors, strict=True)
    ]
    count = VectorStore(index_dir(cfg)).rebuild(rows)
    _RECORDS_CACHE.pop(str(corpus_dir(cfg)), None)
    return count


def status(cfg: dict) -> dict:
    """A snapshot of the voice configuration for `voice status` / debugging."""
    records = _records(cfg)
    return {
        "enabled": enabled(cfg),
        "backend": backend(cfg),
        "corpus_dir": str(corpus_dir(cfg)),
        "index_dir": str(index_dir(cfg)),
        "profile_file": str(profile_file(cfg)),
        "records": len(records),
        "mine": sum(1 for record in records if record.is_me),
        "profile": bool(profile_text(cfg)),
        "top_k": top_k(cfg),
        "only_me": only_me(cfg),
        "min_similarity": min_similarity(cfg),
        "min_example_words": min_example_words(cfg),
    }


__all__ = [
    "BM25",
    "Record",
    "backend",
    "build_index",
    "corpus_dir",
    "embedder",
    "enabled",
    "examples_block",
    "fold",
    "has_voice",
    "index_dir",
    "load_records",
    "min_example_words",
    "min_similarity",
    "only_me",
    "profile_text",
    "query_for_draft",
    "reciprocal_rank_fusion",
    "render_examples",
    "search",
    "status",
    "tokenize",
    "top_k",
]
