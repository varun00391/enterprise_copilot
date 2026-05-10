"""
Evaluation Agent — RAGAS metrics on assistant answers (faithfulness, answer relevancy).

Runs asynchronously after chat persistence when online sampling is enabled.
Scores are stored on `AnswerEvaluation` and optionally mirrored to Langfuse.
"""
from __future__ import annotations

import random
import threading
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger()


def _context_texts_from_sources(source_chunks: Optional[List[Dict[str, Any]]]) -> List[str]:
    if not source_chunks:
        return []
    texts: List[str] = []
    for item in source_chunks:
        if not isinstance(item, dict):
            continue
        t = (item.get("content") or "").strip()
        if t:
            texts.append(t)
    return texts


def run_ragas_evaluation(
    question: str,
    answer: str,
    contexts: List[str],
) -> Dict[str, Any]:
    """
    Returns dict with float scores and optional error/skip flags.
    Keys: faithfulness, answer_relevancy, skipped, error
    """
    out: Dict[str, Any] = {"skipped": False, "error": None}
    q = (question or "").strip()
    a = (answer or "").strip()
    if not q or not a or not contexts:
        out["skipped"] = True
        return out

    try:
        from datasets import Dataset
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from ragas import evaluate
        from ragas.metrics import faithfulness, answer_relevancy

        from app.core.config import settings

        _openai_kw: Dict[str, Any] = {}
        bu = (settings.OPENAI_BASE_URL or "").strip()
        if bu:
            _openai_kw["base_url"] = bu
        llm = ChatOpenAI(
            model=settings.OPENAI_CHAT_MODEL,
            openai_api_key=settings.OPENAI_API_KEY or "",
            temperature=0.0,
            **_openai_kw,
        )
        try:
            embeddings = OpenAIEmbeddings(
                model=settings.OPENAI_EMBEDDING_MODEL,
                openai_api_key=settings.OPENAI_API_KEY or "",
                **_openai_kw,
            )
        except TypeError:
            legacy: Dict[str, Any] = {
                "model": settings.OPENAI_EMBEDDING_MODEL,
                "openai_api_key": settings.OPENAI_API_KEY or "",
            }
            if bu:
                legacy["openai_api_base"] = bu
            embeddings = OpenAIEmbeddings(**legacy)

        ds = Dataset.from_dict(
            {
                "question": [q],
                "answer": [a],
                "contexts": [contexts],
            }
        )
        try:
            scores = evaluate(
                ds,
                metrics=[faithfulness, answer_relevancy],
                llm=llm,
                embeddings=embeddings,
            )
        except TypeError:
            scores = evaluate(ds, metrics=[faithfulness, answer_relevancy])
        row = scores.to_pandas().iloc[0].to_dict()

        def _num(key: str) -> Optional[float]:
            v = row.get(key)
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        out["faithfulness"] = _num("faithfulness")
        out["answer_relevancy"] = _num("answer_relevancy")
        serial_row: Dict[str, Any] = {}
        for k, v in row.items():
            try:
                serial_row[str(k)] = float(v)
            except (TypeError, ValueError):
                serial_row[str(k)] = str(v)
        out["raw_row"] = serial_row
        return out
    except Exception as e:
        log.warning("evaluation.ragas_failed", error=str(e))
        out["error"] = str(e)
        return out


def should_flag_scores(faithfulness: Optional[float], answer_relevancy: Optional[float]) -> bool:
    from app.core.config import settings

    bad = False
    if faithfulness is not None and faithfulness < settings.RAGAS_FLAG_FAITHFULNESS_LT:
        bad = True
    if answer_relevancy is not None and answer_relevancy < settings.RAGAS_FLAG_ANSWER_RELEVANCY_LT:
        bad = True
    return bad


def persist_evaluation_row(
    *,
    database_url: str,
    message_id: str,
    dept_id: Optional[str],
    question: str,
    answer: str,
    source_chunks: Optional[List[Dict[str, Any]]],
    langfuse_trace_id: Optional[str],
) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.exc import IntegrityError
    import uuid

    from app.models.models import AnswerEvaluation
    from app.core.config import settings

    contexts = _context_texts_from_sources(source_chunks)
    if not contexts:
        return

    scores = run_ragas_evaluation(question, answer, contexts)

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        try:
            mid = uuid.UUID(str(message_id))
        except ValueError:
            return

        ev = AnswerEvaluation(
            message_id=mid,
            dept_id=uuid.UUID(dept_id) if dept_id else None,
            faithfulness=scores.get("faithfulness"),
            answer_relevancy=scores.get("answer_relevancy"),
            flagged=False,
            error_message=scores.get("error"),
            raw_metrics=scores.get("raw_row"),
            langfuse_trace_id=(langfuse_trace_id or "")[:120] or None,
        )
        if scores.get("skipped"):
            ev.flagged = False
            ev.error_message = ev.error_message or "skipped_no_context"
        elif scores.get("error"):
            ev.flagged = False
        else:
            ev.flagged = should_flag_scores(ev.faithfulness, ev.answer_relevancy)

        db.add(ev)
        db.commit()

        if langfuse_trace_id and settings.langfuse_configured and not scores.get("skipped"):
            from app.services.langfuse_tracing import get_langfuse_client, lf_flush, lf_score_trace

            lf = get_langfuse_client()
            if lf:
                if ev.faithfulness is not None:
                    lf_score_trace(lf, trace_id=langfuse_trace_id, name="faithfulness", value=float(ev.faithfulness))
                if ev.answer_relevancy is not None:
                    lf_score_trace(lf, trace_id=langfuse_trace_id, name="answer_relevancy", value=float(ev.answer_relevancy))
                lf_flush(lf)
    except IntegrityError:
        db.rollback()
    except Exception as e:
        log.warning("evaluation.persist_failed", error=str(e))
        db.rollback()
    finally:
        db.close()
        engine.dispose()


def schedule_online_evaluation(
    *,
    database_url: str,
    dept_id: str,
    user_question: str,
    assistant_message_id: str,
    answer_text: str,
    source_chunks: Optional[List[Dict[str, Any]]],
    langfuse_trace_id: Optional[str],
) -> None:
    """Fire-and-forget thread when sampling triggers."""

    def _worker():
        persist_evaluation_row(
            database_url=database_url,
            message_id=assistant_message_id,
            dept_id=dept_id,
            question=user_question,
            answer=answer_text,
            source_chunks=source_chunks,
            langfuse_trace_id=langfuse_trace_id,
        )

    threading.Thread(target=_worker, daemon=True).start()


def maybe_schedule_chat_evaluation(
    *,
    database_url: str,
    dept_id: str,
    user_question: str,
    assistant_message_id: str,
    answer_text: str,
    source_chunks: Optional[List[Dict[str, Any]]],
    langfuse_trace_id: Optional[str],
) -> None:
    from app.core.config import settings

    if not settings.RAGAS_EVAL_ENABLED:
        return
    if not answer_text or not answer_text.strip():
        return
    if random.random() >= settings.RAGAS_EVAL_SAMPLE_RATE:
        return
    schedule_online_evaluation(
        database_url=database_url,
        dept_id=dept_id,
        user_question=user_question,
        assistant_message_id=assistant_message_id,
        answer_text=answer_text,
        source_chunks=source_chunks,
        langfuse_trace_id=langfuse_trace_id,
    )
