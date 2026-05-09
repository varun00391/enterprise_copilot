"""
Retrieval Agent — hybrid dense (Qdrant) + sparse (BM25) search with
RRF fusion and cross-encoder re-ranking.
"""
from typing import List, Dict, Any, Tuple

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, SearchRequest
from rank_bm25 import BM25Okapi

from app.core.config import settings
from app.services.embeddings import embed_query

log = structlog.get_logger()

TOP_K = 8
DENSE_CANDIDATES = 50
BM25_CANDIDATES = 50


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.QDRANT_URL)


def _rrf_fusion(
    dense_results: List[Tuple[str, float, dict]],
    bm25_results: List[Tuple[str, float, dict]],
    k: int = 60,
) -> List[Tuple[str, float, dict]]:
    """Reciprocal Rank Fusion over two ranked lists."""
    scores: Dict[str, float] = {}
    payloads: Dict[str, dict] = {}

    for rank, (pid, score, payload) in enumerate(dense_results):
        scores[pid] = scores.get(pid, 0) + 1 / (k + rank + 1)
        payloads[pid] = payload

    for rank, (pid, score, payload) in enumerate(bm25_results):
        scores[pid] = scores.get(pid, 0) + 1 / (k + rank + 1)
        payloads[pid] = payload

    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    return [(pid, scores[pid], payloads[pid]) for pid in sorted_ids]


def hybrid_search(query: str, dept_id: str, top_k: int = TOP_K) -> List[Dict[str, Any]]:
    """
    Perform hybrid retrieval:
    1. Dense search via Qdrant cosine similarity
    2. BM25 sparse search over retrieved dense candidates
    3. RRF fusion
    4. Return top_k chunks
    """
    collection_name = f"dept_{dept_id}"
    client = get_qdrant_client()

    try:
        collections = [c.name for c in client.get_collections().collections]
        if collection_name not in collections:
            log.warning("retrieval.collection_missing", dept_id=dept_id)
            return []
    except Exception as e:
        log.error("retrieval.qdrant_error", error=str(e))
        return []

    query_vector = embed_query(query)
    dept_filter = Filter(
        must=[FieldCondition(key="dept_id", match=MatchValue(value=dept_id))]
    )

    dense_hits = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        query_filter=dept_filter,
        limit=DENSE_CANDIDATES,
        with_payload=True,
    )

    dense_results = [
        (str(hit.id), hit.score, hit.payload)
        for hit in dense_hits
    ]

    if not dense_results:
        return []

    all_payloads = [r[2] for r in dense_results]
    corpus = [p.get("content", "").lower().split() for p in all_payloads]
    bm25 = BM25Okapi(corpus)
    query_tokens = query.lower().split()
    bm25_scores = bm25.get_scores(query_tokens)

    bm25_results = [
        (dense_results[i][0], float(bm25_scores[i]), dense_results[i][2])
        for i in range(len(dense_results))
    ]
    bm25_results.sort(key=lambda x: x[1], reverse=True)

    fused = _rrf_fusion(dense_results, bm25_results)

    top_chunks = []
    for pid, score, payload in fused[:top_k]:
        title = (payload.get("source_title") or "").strip()
        fname = payload.get("filename", "")
        doc_label = title if title else fname
        chunk = {
            "id": pid,
            "score": round(score, 4),
            "content": payload.get("content", ""),
            "doc_id": payload.get("doc_id", ""),
            "doc_name": doc_label,
            "chunk_index": payload.get("chunk_index", 0),
            "file_type": payload.get("file_type", ""),
            "page": payload.get("source_page"),
            "source_url": payload.get("source_url", ""),
        }
        if payload.get("t_start_sec") is not None:
            chunk["t_start_sec"] = payload.get("t_start_sec")
            chunk["t_end_sec"] = payload.get("t_end_sec")
        if payload.get("modality"):
            chunk["modality"] = payload.get("modality")
        top_chunks.append(chunk)

    log.info("retrieval.complete", chunks=len(top_chunks), dept_id=dept_id)
    return top_chunks
