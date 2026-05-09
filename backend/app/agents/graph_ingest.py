"""Build Neo4j graph incrementally from document chunks after vector indexing."""
from __future__ import annotations

from typing import List

import structlog

from app.core.config import settings
from app.agents.graph_extraction import extract_graph_from_text
from app.services.graph_store import get_graph_driver, upsert_chunk_graph

log = structlog.get_logger()


def _sample_chunk_indices(total: int, max_chunks: int) -> List[int]:
    if total <= 0:
        return []
    cap = min(max_chunks, total)
    if cap >= total:
        return list(range(total))
    step = total / cap
    return [min(total - 1, int(i * step)) for i in range(cap)]


def ingest_graph_for_document(
    dept_id: str,
    doc_id: str,
    filename: str,
    chunks: List[str],
) -> None:
    """Extract and upsert graph triples for a subset of chunks (cost-controlled)."""
    if not settings.neo4j_configured or not settings.GRAPH_BUILD_ON_INGEST:
        return
    if not get_graph_driver():
        return
    if not chunks:
        return

    indices = _sample_chunk_indices(len(chunks), int(settings.GRAPH_MAX_CHUNKS_PER_DOC))
    done = 0
    for idx in indices:
        text = chunks[idx]
        entities, relations = extract_graph_from_text(text)
        if not entities and not relations:
            continue
        upsert_chunk_graph(dept_id, doc_id, idx, filename, entities, relations)
        done += 1
    if done:
        log.info("graph_ingest.doc_complete", doc_id=doc_id, dept_id=dept_id, chunks_indexed=done)
