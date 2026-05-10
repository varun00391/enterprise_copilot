"""
Langfuse OpenTelemetry-style tracing helpers.

Fails closed when Langfuse is disabled or the SDK/API surface differs.
"""
from __future__ import annotations

import contextlib
from typing import Any, Dict, Optional

import structlog

from app.core.config import settings

log = structlog.get_logger()

_langfuse_singleton: Any = None


def get_langfuse_client():
    """Singleton Langfuse client when keys are configured; otherwise None."""
    global _langfuse_singleton
    if not settings.langfuse_configured:
        return None
    if _langfuse_singleton is False:
        return None
    if _langfuse_singleton is not None:
        return _langfuse_singleton
    try:
        from langfuse import Langfuse

        _langfuse_singleton = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY.strip(),
            secret_key=settings.LANGFUSE_SECRET_KEY.strip(),
            base_url=settings.langfuse_base_url,
        )
        return _langfuse_singleton
    except Exception as e:
        log.warning("langfuse.init_failed", error=str(e))
        _langfuse_singleton = False
        return None


@contextlib.contextmanager
def lf_observation(client, *, name: str, as_type: str = "span", **kwargs):
    """
    Context manager wrapping Langfuse observations when client supports them.
    Yields None when tracing is unavailable so callers can branch on obs is None.
    """
    if client is None:
        yield None
        return
    try:
        cm = client.start_as_current_observation(as_type=as_type, name=name, **kwargs)
    except Exception as e:
        log.warning("langfuse.observation_start_failed", name=name, error=str(e))
        yield None
        return
    try:
        with cm as obs:
            yield obs
    except Exception as e:
        log.warning("langfuse.observation_failed", name=name, error=str(e))
        yield None


def lf_trace_id_from_observation(obs) -> Optional[str]:
    if obs is None:
        return None
    for attr in ("trace_id", "traceId"):
        if hasattr(obs, attr):
            val = getattr(obs, attr)
            if val:
                return str(val)
    getter = getattr(obs, "get_trace_id", None)
    if callable(getter):
        try:
            tid = getter()
            if tid:
                return str(tid)
        except Exception:
            pass
    return None


def lf_update_trace(obs, *, user_id: Optional[str] = None, session_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
    if obs is None:
        return
    fn = getattr(obs, "update_trace", None)
    if not callable(fn):
        return
    kw: Dict[str, Any] = {}
    if user_id is not None:
        kw["user_id"] = user_id
    if session_id is not None:
        kw["session_id"] = session_id
    if metadata is not None:
        kw["metadata"] = metadata
    if not kw:
        return
    try:
        fn(**kw)
    except Exception as e:
        log.warning("langfuse.update_trace_failed", error=str(e))


def lf_flush(client) -> None:
    if client is None:
        return
    flush = getattr(client, "flush", None)
    if callable(flush):
        try:
            flush()
        except Exception as e:
            log.warning("langfuse.flush_failed", error=str(e))


def lf_score_trace(client, *, trace_id: str, name: str, value: float, comment: Optional[str] = None) -> None:
    """Attach a numeric score to an existing trace (evaluation outcome)."""
    if client is None or not trace_id:
        return
    create_score = getattr(client, "score", None)
    if not callable(create_score):
        create_score = getattr(client, "create_score", None)
    if not callable(create_score):
        return
    try:
        kwargs = {"trace_id": trace_id, "name": name, "value": float(value)}
        if comment:
            kwargs["comment"] = comment
        create_score(**kwargs)
    except TypeError:
        try:
            create_score(trace_id=trace_id, name=name, value=float(value))
        except Exception as e:
            log.warning("langfuse.score_failed", error=str(e))
    except Exception as e:
        log.warning("langfuse.score_failed", error=str(e))


def lf_shutdown(client) -> None:
    if client is None:
        return
    fn = getattr(client, "shutdown", None)
    if callable(fn):
        try:
            fn()
        except Exception:
            pass
