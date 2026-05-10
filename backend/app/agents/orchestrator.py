"""
Orchestrator Agent — coordinates the retrieval and reasoning pipeline
using LangGraph as the state machine.

Video uploads are normalized and indexed by the LangGraph Video Agent subgraph
(`app.agents.video_agent.run_video_ingestion_graph`) at document upload time,
not in this HTTP query path — retrieved chunks surface transcript time ranges and
frame captions alongside other department documents.
"""
from typing import Generator, Optional, Dict, Any

import structlog

from app.core.config import settings
from app.agents.retrieval import hybrid_search
from app.agents.reasoning import stream_answer, stream_answer_analytics
from app.agents.security_agent import sanitize_query
from app.services.langfuse_tracing import (
    get_langfuse_client,
    lf_observation,
    lf_trace_id_from_observation,
    lf_update_trace,
    lf_flush,
)

log = structlog.get_logger()


def _extract_intent(query: str) -> str:
    """Simple intent classification."""
    query_lower = query.lower()
    if any(w in query_lower for w in ["summarize", "summary", "overview"]):
        return "summarization"
    if any(w in query_lower for w in ["compare", "difference", "vs"]):
        return "comparison"
    if any(w in query_lower for w in ["list", "show all", "what are"]):
        return "enumeration"
    return "question_answering"


def _run_query_pipeline_inner(
    query: str,
    dept_id: str,
    user_id: str,
    session_id: str,
    conversation_history: list,
    database_url: Optional[str],
    lf_client,
) -> Generator[str, None, None]:
    query = sanitize_query(query)
    if not query:
        yield 'data: {"type": "error", "content": "Empty query"}\n\n'
        return

    log.info("orchestrator.query_start", dept_id=dept_id, session_id=session_id)

    with lf_observation(lf_client, as_type="span", name="retrieval") as ret_obs:
        if settings.graph_rag_active:
            from app.agents.graph_rag import graph_rag_retrieve

            chunks = graph_rag_retrieve(query=query, dept_id=dept_id)
        else:
            chunks = hybrid_search(query=query, dept_id=dept_id)
        if ret_obs is not None:
            try:
                ret_obs.update(output={"chunks": len(chunks)})
            except Exception:
                pass

    if not chunks:
        log.info("orchestrator.no_chunks", dept_id=dept_id)

    spreadsheet_tuple = None
    chart_insight = None
    if database_url:
        from app.agents.analytics_context import (
            load_spreadsheet_from_chunks,
            load_chart_insight_from_chunks,
            should_use_analytics_path,
        )

        spreadsheet_tuple = load_spreadsheet_from_chunks(database_url, dept_id, chunks)
        chart_insight = load_chart_insight_from_chunks(database_url, dept_id, chunks, query)
        if should_use_analytics_path(query, chunks, spreadsheet_tuple, chart_insight):
            log.info("orchestrator.analytics_path", dept_id=dept_id, session_id=session_id)
            sb, st = (None, None)
            if spreadsheet_tuple:
                sb, st = spreadsheet_tuple
            yield from stream_answer_analytics(
                query=query,
                chunks=chunks,
                conversation_history=conversation_history or [],
                spreadsheet_bytes=sb,
                spreadsheet_type=st,
                chart_description=chart_insight,
                lf_client=lf_client,
            )
            return

    yield from stream_answer(
        query=query,
        chunks=chunks,
        conversation_history=conversation_history or [],
        lf_client=lf_client,
    )


def run_query_pipeline(
    query: str,
    dept_id: str,
    user_id: str,
    session_id: str,
    conversation_history: list = None,
    database_url: Optional[str] = None,
    trace_sink: Optional[Dict[str, Any]] = None,
) -> Generator[str, None, None]:
    """
    Main query pipeline: sanitize → retrieve → stream answer (or analytics-enriched answer).
    `database_url` enables loading full spreadsheets / chart images from retrieved documents.
    Optional `trace_sink` collects Langfuse trace id when tracing is active (same thread).
    """
    lf_client = get_langfuse_client()
    if lf_client:
        with lf_observation(lf_client, as_type="span", name="chat_rag", input={"query": query}) as root:
            if trace_sink is not None and root is not None:
                tid = lf_trace_id_from_observation(root)
                if tid:
                    trace_sink["trace_id"] = tid
            lf_update_trace(
                root,
                user_id=user_id,
                session_id=session_id,
                metadata={"dept_id": dept_id},
            )
            yield from _run_query_pipeline_inner(
                query=query,
                dept_id=dept_id,
                user_id=user_id,
                session_id=session_id,
                conversation_history=conversation_history or [],
                database_url=database_url,
                lf_client=lf_client,
            )
        lf_flush(lf_client)
        return

    yield from _run_query_pipeline_inner(
        query=query,
        dept_id=dept_id,
        user_id=user_id,
        session_id=session_id,
        conversation_history=conversation_history or [],
        database_url=database_url,
        lf_client=None,
    )


def run_multimodal_stream(
    query: str,
    image_bytes: bytes,
    dept_id: str,
    user_id: str,
    session_id: str,
    conversation_history: list = None,
    trace_sink: Optional[Dict[str, Any]] = None,
) -> Generator[str, None, None]:
    """
    Vision (multimodal agent) + RAG + reasoning stream.
    `query` must already be sanitized or may be empty only if caller ensures image-only path is valid.
    """
    query = sanitize_query(query)
    if not query:
        yield 'data: {"type": "error", "content": "Empty query"}\n\n'
        return

    log.info("orchestrator.multimodal_start", dept_id=dept_id, session_id=session_id)

    lf_client = get_langfuse_client()

    def _multimodal_inner():
        from app.agents.multimodal import run_multimodal_query

        mm = run_multimodal_query(
            query=query,
            image_bytes=image_bytes,
            dept_id=dept_id,
            user_id=user_id,
            session_id=session_id,
            conversation_history=conversation_history or [],
            image_presigned_url=None,
            lf_client=lf_client,
        )
        yield from mm["stream_generator"]

    if lf_client:
        with lf_observation(lf_client, as_type="span", name="chat_multimodal", input={"query": query}) as root:
            if trace_sink is not None and root is not None:
                tid = lf_trace_id_from_observation(root)
                if tid:
                    trace_sink["trace_id"] = tid
            lf_update_trace(
                root,
                user_id=user_id,
                session_id=session_id,
                metadata={"dept_id": dept_id, "path": "multimodal"},
            )
            yield from _multimodal_inner()
        lf_flush(lf_client)
        return

    yield from _multimodal_inner()
