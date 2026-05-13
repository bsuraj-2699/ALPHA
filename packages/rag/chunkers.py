"""Document → Chunk converters for the three supported source types.

The output Chunk shape is fixed by `packages.rag.store.Chunk`:
    id        — stable identifier; survives re-ingestion (idempotent upsert)
    text      — what gets embedded and BM25-indexed
    metadata  — filterable payload (doc_type, ticker, etc.)
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from packages.rag.store import Chunk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Rules
# ---------------------------------------------------------------------------

def chunk_rules(rules_path: Path) -> list[Chunk]:
    """One chunk per rule. Body packs name, description, rationale, conditions
    so both BM25 and dense retrieval surface the rule when its terms appear."""
    spec = json.loads(rules_path.read_text(encoding="utf-8"))
    chunks: list[Chunk] = []
    for rule in spec["rules"]:
        rid = rule["id"]
        text = _format_rule(rule)
        chunks.append(
            Chunk(
                id=f"rule:{rid}",
                text=text,
                metadata={
                    "doc_type": "rule",
                    "rule_id": rid,
                    "category": rule.get("category"),
                    "subcategory": rule.get("subcategory"),
                    "markets": list(rule.get("markets", [])),
                    "name": rule.get("name"),
                },
            )
        )
    # Override rules: same shape, different doc_type so a query for fraud finds them.
    for ovr in spec.get("override_rules", []):
        oid = ovr["id"]
        text = _format_override(ovr)
        chunks.append(
            Chunk(
                id=f"override:{oid}",
                text=text,
                metadata={
                    "doc_type": "rule",
                    "rule_id": oid,
                    "category": "override",
                    "name": ovr.get("name"),
                    "action": ovr.get("action"),
                },
            )
        )
    return chunks


def _format_rule(rule: dict[str, Any]) -> str:
    rid = rule["id"]
    lines = [
        f"[{rid}] {rule.get('name', '')}",
        rule.get("description", ""),
        "",
        f"Category: {rule.get('category')} / {rule.get('subcategory')}",
        f"Markets: {', '.join(rule.get('markets', []))}",
        "",
        "Conditions:",
    ]
    for tier, cond in (rule.get("conditions") or {}).items():
        lines.append(f"  {tier}: {cond}")
    rationale = rule.get("rationale")
    if rationale:
        lines.extend(["", "Rationale:", rationale])
    return "\n".join(lines)


def _format_override(ovr: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"[{ovr['id']}] {ovr.get('name', '')}",
            f"Action: {ovr.get('action')}",
            f"Trigger: {ovr.get('trigger')}",
            "",
            ovr.get("rationale", ""),
        ]
    )


# ---------------------------------------------------------------------------
# 2. Annual reports / filings (PDF) — token-based 512/50 chunking
# ---------------------------------------------------------------------------

# rough proxy: ~4 chars per token for English finance prose. We try tiktoken
# when present, fall back to char-count to avoid a hard dep at import time.

def _token_len(text: str) -> int:
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def _split_tokens(text: str, target: int, overlap: int) -> list[str]:
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        ids = enc.encode(text)
        out: list[str] = []
        step = max(1, target - overlap)
        for start in range(0, len(ids), step):
            window = ids[start : start + target]
            if not window:
                break
            out.append(enc.decode(window))
            if start + target >= len(ids):
                break
        return out
    except Exception:
        # Char-based fallback (~4 chars/token)
        target_chars = target * 4
        overlap_chars = overlap * 4
        out2: list[str] = []
        step = max(1, target_chars - overlap_chars)
        for start in range(0, len(text), step):
            piece = text[start : start + target_chars]
            if not piece:
                break
            out2.append(piece)
            if start + target_chars >= len(text):
                break
        return out2


def chunk_filing(
    pdf_path: Path,
    ticker: str,
    fiscal_year: int | str,
    target_tokens: int = 512,
    overlap_tokens: int = 50,
) -> list[Chunk]:
    """Semantic-ish chunking via unstructured.io's `partition_pdf`.

    Sections are inferred from the unstructured element types
    (Title/NarrativeText/Table). Each section is then split into 512-token
    windows with 50-token overlap.
    """
    sections = _partition_pdf_sections(pdf_path)

    chunks: list[Chunk] = []
    for section_title, body in sections:
        if not body.strip():
            continue
        for idx, piece in enumerate(_split_tokens(body, target_tokens, overlap_tokens)):
            cid = f"filing:{ticker}:{fiscal_year}:{_slug(section_title)}:{idx}"
            chunks.append(
                Chunk(
                    id=cid,
                    text=piece,
                    metadata={
                        "doc_type": "filing",
                        "ticker": ticker,
                        "fiscal_year": str(fiscal_year),
                        "section": section_title,
                    },
                )
            )
    return chunks


def _partition_pdf_sections(pdf_path: Path) -> list[tuple[str, str]]:
    """Group unstructured elements into (section_title, body_text) pairs."""
    from unstructured.partition.pdf import partition_pdf

    elements = partition_pdf(filename=str(pdf_path), strategy="fast")
    sections: list[tuple[str, list[str]]] = [("preamble", [])]
    for el in elements:
        category = getattr(el, "category", "") or el.__class__.__name__
        text = str(el).strip()
        if not text:
            continue
        if category in ("Title", "Header"):
            sections.append((text[:120], []))
        else:
            sections[-1][1].append(text)
    return [(title, "\n\n".join(body)) for title, body in sections if body]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "section"


# ---------------------------------------------------------------------------
# 3. Earnings call transcripts — chunk by speaker turn
# ---------------------------------------------------------------------------

# Accepts either a leading "Speaker Name:" or a speaker line followed by body.
_SPEAKER_LINE = re.compile(
    r"^(?P<name>[A-Z][A-Za-z\.\- ]{1,60}?(?:\s*[—-]\s*[A-Za-z, ]+)?):\s*(?P<rest>.*)$"
)


def chunk_transcript(
    transcript_path: Path | str,
    ticker: str,
    quarter: str,
    text: str | None = None,
) -> list[Chunk]:
    """Split on speaker turns. Each turn becomes one chunk."""
    if text is None:
        text = Path(transcript_path).read_text(encoding="utf-8", errors="replace")

    turns = _split_speaker_turns(text)
    chunks: list[Chunk] = []
    for idx, (speaker, body) in enumerate(turns):
        if not body.strip():
            continue
        cid = f"transcript:{ticker}:{quarter}:{idx}"
        chunks.append(
            Chunk(
                id=cid,
                text=f"{speaker}: {body.strip()}",
                metadata={
                    "doc_type": "transcript",
                    "ticker": ticker,
                    "quarter": quarter,
                    "speaker": speaker,
                    "turn_index": idx,
                },
            )
        )
    return chunks


def _split_speaker_turns(text: str) -> Iterable[tuple[str, str]]:
    current_speaker = "Unknown"
    current_body: list[str] = []
    for line in text.splitlines():
        m = _SPEAKER_LINE.match(line.strip())
        if m and len(m.group("name")) <= 60:
            if current_body:
                yield current_speaker, "\n".join(current_body).strip()
            current_speaker = m.group("name").strip()
            rest = m.group("rest").strip()
            current_body = [rest] if rest else []
        else:
            current_body.append(line)
    if current_body:
        yield current_speaker, "\n".join(current_body).strip()
