"""
Lightweight local RAG for doctrine files.

- Source: data/doctrine/*.(pdf|md|txt)
- Retrieval: BM25 lexical ranking (no external vector DB dependency)
- Output: top-k snippets with source/page citations for prompt augmentation
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from pypdf import PdfReader
    HAS_PDF_READER = True
except Exception:
    HAS_PDF_READER = False


TOKEN_RE = re.compile(r"[A-Za-z0-9_\u3131-\u318E\uAC00-\uD7A3]+")


@dataclass
class DoctrineChunk:
    source: str
    page: int
    text: str
    tokens: List[str]
    term_freq: Dict[str, int]
    length: int


class DoctrineRAG:
    def __init__(
        self,
        doctrine_dir: str = "data/doctrine",
        fallback_doc: str = "doctrine_basis.md",
        max_pdf_pages: Optional[int] = None,
        chunk_chars: int = 900,
        chunk_overlap: int = 180,
    ) -> None:
        self.doctrine_dir = Path(doctrine_dir)
        self.fallback_doc = Path(fallback_doc)
        self.max_pdf_pages = max_pdf_pages
        self.chunk_chars = chunk_chars
        self.chunk_overlap = chunk_overlap

        self._chunks: List[DoctrineChunk] = []
        self._idf: Dict[str, float] = {}
        self._avg_len: float = 1.0
        self._built = False

    def _tokenize(self, text: str) -> List[str]:
        return [m.group(0).lower() for m in TOKEN_RE.finditer(text)]

    def _chunk_text(self, text: str) -> List[str]:
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return []

        chunks = []
        i = 0
        n = len(text)
        step = max(1, self.chunk_chars - self.chunk_overlap)
        while i < n:
            j = min(n, i + self.chunk_chars)
            # Try to cut at sentence-ish boundary for readability.
            if j < n:
                cut = max(text.rfind(". ", i, j), text.rfind("। ", i, j), text.rfind(" ", i, j))
                if cut > i + int(self.chunk_chars * 0.65):
                    j = cut + 1
            chunk = text[i:j].strip()
            if len(chunk) >= 80:
                chunks.append(chunk)
            i += step
        return chunks

    def _read_text_file(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def _read_pdf_pages(self, path: Path) -> List[Tuple[int, str]]:
        if not HAS_PDF_READER:
            return []
        try:
            reader = PdfReader(str(path))
            out: List[Tuple[int, str]] = []
            pages = reader.pages if self.max_pdf_pages is None else reader.pages[: self.max_pdf_pages]
            for idx, page in enumerate(pages, start=1):
                txt = (page.extract_text() or "").strip()
                if txt:
                    out.append((idx, txt))
            return out
        except Exception:
            return []

    def _iter_documents(self) -> List[Tuple[str, int, str]]:
        docs: List[Tuple[str, int, str]] = []

        if self.doctrine_dir.exists():
            for ext in ("*.md", "*.txt", "*.pdf"):
                for path in sorted(self.doctrine_dir.glob(ext)):
                    if path.suffix.lower() == ".pdf":
                        for page, text in self._read_pdf_pages(path):
                            docs.append((path.name, page, text))
                    else:
                        text = self._read_text_file(path)
                        if text:
                            docs.append((path.name, 1, text))

        if self.fallback_doc.exists():
            text = self._read_text_file(self.fallback_doc)
            if text:
                docs.append((self.fallback_doc.name, 1, text))

        return docs

    def build_index(self, force: bool = False) -> None:
        if self._built and not force:
            return

        chunks: List[DoctrineChunk] = []
        for source, page, text in self._iter_documents():
            for c in self._chunk_text(text):
                tokens = self._tokenize(c)
                if not tokens:
                    continue
                tf: Dict[str, int] = {}
                for t in tokens:
                    tf[t] = tf.get(t, 0) + 1
                chunks.append(
                    DoctrineChunk(
                        source=source,
                        page=page,
                        text=c,
                        tokens=tokens,
                        term_freq=tf,
                        length=len(tokens),
                    )
                )

        self._chunks = chunks
        self._idf = {}
        self._avg_len = 1.0

        if not chunks:
            self._built = True
            return

        n_docs = len(chunks)
        self._avg_len = sum(c.length for c in chunks) / n_docs

        df: Dict[str, int] = {}
        for c in chunks:
            for t in set(c.tokens):
                df[t] = df.get(t, 0) + 1

        for term, freq in df.items():
            self._idf[term] = math.log(1.0 + (n_docs - freq + 0.5) / (freq + 0.5))

        self._built = True

    def _score_bm25(self, query_tokens: List[str], chunk: DoctrineChunk, k1: float = 1.2, b: float = 0.75) -> float:
        if not query_tokens:
            return 0.0
        score = 0.0
        dl = max(1, chunk.length)
        norm = k1 * (1.0 - b + b * dl / max(1e-9, self._avg_len))
        for t in set(query_tokens):
            f = chunk.term_freq.get(t, 0)
            if f <= 0:
                continue
            idf = self._idf.get(t, 0.0)
            score += idf * (f * (k1 + 1.0)) / (f + norm)
        return score

    def search(self, query: str, top_k: int = 5, min_score: float = 0.05) -> List[Dict[str, object]]:
        self.build_index()
        if not self._chunks:
            return []

        q_tokens = self._tokenize(query)
        ranked: List[Tuple[float, DoctrineChunk]] = []
        for c in self._chunks:
            s = self._score_bm25(q_tokens, c)
            if s >= min_score:
                ranked.append((s, c))

        ranked.sort(key=lambda x: x[0], reverse=True)
        out: List[Dict[str, object]] = []
        for score, chunk in ranked[:top_k]:
            out.append(
                {
                    "source": chunk.source,
                    "page": chunk.page,
                    "score": round(float(score), 4),
                    "text": chunk.text,
                }
            )
        return out

    def format_context(self, query: str, top_k: int = 5, max_chars: int = 4200) -> str:
        hits = self.search(query=query, top_k=top_k)
        if not hits:
            return "No retrieved doctrine chunks."

        parts: List[str] = []
        remain = max_chars
        for h in hits:
            head = f"[{h['source']} | p.{h['page']} | score={h['score']}] "
            body = str(h["text"])
            piece = head + body
            if len(piece) > remain:
                piece = piece[: max(0, remain - 3)].rstrip() + "..."
            if piece:
                parts.append(piece)
                remain -= len(piece) + 2
            if remain <= 120:
                break
        return "\n\n".join(parts)
