"""
Graph RAG Agent (Phase 3) — LangGraph workflow:
query interpretation → Neo4j subgraph traversal → hybrid vector/BM25 retrieval → context fusion for reasoning.
"""
from __future__ import annotations

from typing import Any, Dict, List, TypedDict

import structlog
from langgraph.graph import END, StateGraph

from app.core.config import settings
from app.agents.retrieval import TOP_K, hybrid_search
from app.agents.graph_extraction import extract_query_graph_terms
from app.services.graph_store import get_graph_driver, resolve_seed_entities, subgraph_to_text

log = structlog.get_logger()


class GraphRAGState(TypedDict, total=False):
    query: str
    dept_id: str
    seed_terms: List[str]
    seed_eids: List[str]
    subgraph_text: str
    vector_chunks: List[Dict[str, Any]]
    fused_chunks: List[Dict[str, Any]]


def _fuse_graph_vector_chunks(
    subgraph_text: str,
    vector_chunks: List[Dict[str, Any]],
    top_k: int = TOP_K,
) -> List[Dict[str, Any]]:
    st = (subgraph_text or "").strip()
    if not st:
        return vector_chunks
    graph_chunk: Dict[str, Any] = {
        "id": "graph-rag-context",
        "score": 1.0,
        "content": "**[Knowledge graph]** — relations extracted from department documents:\n" + st,
        "doc_id": "knowledge_graph",
        "doc_name": "Knowledge graph context",
        "chunk_index": 0,
        "file_type": "graph",
        "source_url": "",
    }
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for c in [graph_chunk] + (vector_chunks or []):
        body = (c.get("content") or "")[:240]
        key = (c.get("doc_id"), c.get("chunk_index"), body)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= top_k + 2:
            break
    return out[: top_k + 2]


def _node_interpret(state: GraphRAGState) -> GraphRAGState:
    terms = extract_query_graph_terms(state.get("query") or "")
    return {"seed_terms": terms}


def _node_traverse(state: GraphRAGState) -> GraphRAGState:
    dept_id = state.get("dept_id") or ""
    if not get_graph_driver():
        return {"seed_eids": [], "subgraph_text": ""}
    terms = state.get("seed_terms") or []
    eids = resolve_seed_entities(dept_id, terms, limit=14)
    text = subgraph_to_text(dept_id, eids) if eids else ""
    return {"seed_eids": eids, "subgraph_text": text}


def _node_vector(state: GraphRAGState) -> GraphRAGState:
    chunks = hybrid_search(state.get("query") or "", state.get("dept_id") or "", top_k=TOP_K)
    return {"vector_chunks": chunks}


def _node_fuse(state: GraphRAGState) -> GraphRAGState:
    fused = _fuse_graph_vector_chunks(
        state.get("subgraph_text") or "",
        state.get("vector_chunks") or [],
        top_k=TOP_K,
    )
    return {"fused_chunks": fused}


def _build_graph_rag_workflow() -> StateGraph:
    g = StateGraph(GraphRAGState)
    g.add_node("interpret", _node_interpret)
    g.add_node("traverse", _node_traverse)
    g.add_node("retrieve", _node_vector)
    g.add_node("fuse", _node_fuse)
    g.set_entry_point("interpret")
    g.add_edge("interpret", "traverse")
    g.add_edge("traverse", "retrieve")
    g.add_edge("retrieve", "fuse")
    g.add_edge("fuse", END)
    return g


_compiled_graph_rag = None


def graph_rag_retrieve(query: str, dept_id: str) -> List[Dict[str, Any]]:
    """
    Run Graph RAG pipeline when enabled and Neo4j is configured; otherwise hybrid search only.
    Falls back to vector-only retrieval on any failure.
    """
    if not settings.graph_rag_active:
        return hybrid_search(query, dept_id, top_k=TOP_K)
    if not get_graph_driver():
        log.info("graph_rag.fallback_no_driver", dept_id=dept_id)
        return hybrid_search(query, dept_id, top_k=TOP_K)

    global _compiled_graph_rag
    if _compiled_graph_rag is None:
        _compiled_graph_rag = _build_graph_rag_workflow().compile()

    try:
        out: GraphRAGState = _compiled_graph_rag.invoke(
            {"query": query, "dept_id": dept_id},
        )
        fused = out.get("fused_chunks")
        if fused:
            log.info(
                "graph_rag.complete",
                dept_id=dept_id,
                seeds=len(out.get("seed_eids") or []),
                chunks=len(fused),
            )
            return fused
    except Exception as e:
        log.warning("graph_rag.invoke_failed", error=str(e))
    return hybrid_search(query, dept_id, top_k=TOP_K)
