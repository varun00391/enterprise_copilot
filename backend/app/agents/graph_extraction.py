"""LLM-assisted entity and relation extraction for knowledge graph build (Phase 3)."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

import structlog
from openai import OpenAI

from app.core.config import settings

log = structlog.get_logger()

_EXTRACT_SYS = """You are a knowledge graph extractor for enterprise documents.
From the text chunk, output ONLY valid JSON with keys "entities" and "relations".
Each entity: {{"name": string, "type": string}}.
Each relation: {{"head": string, "tail": string, "type": "UPPER_SNAKE_CASE"}}.
Rules:
- entity names: short phrases as written in the text (people, orgs, products, locations, key concepts).
- relation types: concrete verbs or relations (e.g. WORKS_FOR, LOCATED_IN, OWNS, PART_OF, REQUIRES).
- Omit empty arrays; max {max_ent} entities and {max_rel} relations.
- If nothing extractable, return {{"entities":[],"relations":[]}}.
"""

_QUERY_ENTITY_SYS = """From the user's question, list short phrases useful to look up in a knowledge graph.
Output ONLY JSON: {{"entities":["phrase1",...]}} with max {max_q} items (people, orgs, products, key concepts)."""


def _strip_json_fence(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```\w*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _parse_json_obj(raw: str) -> Dict[str, Any]:
    s = _strip_json_fence(raw)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def extract_graph_from_text(chunk_text: str) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Returns (entities, relations); skips on missing API key."""
    if not settings.OPENAI_API_KEY.strip():
        return [], []
    text = (chunk_text or "").strip()
    if len(text) < 40:
        return [], []

    max_ent = int(settings.GRAPH_MAX_ENTITIES_PER_CHUNK)
    max_rel = int(settings.GRAPH_MAX_RELATIONS_PER_CHUNK)
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    sys_msg = _EXTRACT_SYS.format(max_ent=max_ent, max_rel=max_rel)
    try:
        resp = client.chat.completions.create(
            model=settings.graph_extraction_model,
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": text[:12000]},
            ],
            temperature=0.1,
            max_tokens=900,
        )
        raw = resp.choices[0].message.content or ""
        data = _parse_json_obj(raw)
        entities = []
        for e in data.get("entities") or []:
            if not isinstance(e, dict):
                continue
            name = str(e.get("name", "")).strip()
            et = str(e.get("type", "Concept")).strip() or "Concept"
            if name:
                entities.append({"name": name[:500], "type": et[:120]})
        relations = []
        for r in data.get("relations") or []:
            if not isinstance(r, dict):
                continue
            head = str(r.get("head", "")).strip()
            tail = str(r.get("tail", "")).strip()
            rt = str(r.get("type", "RELATED_TO")).strip().upper().replace(" ", "_")
            if head and tail:
                relations.append({"head": head[:500], "tail": tail[:500], "type": rt[:80]})
        return entities[:max_ent], relations[:max_rel]
    except Exception as e:
        log.warning("graph_extraction.chunk_failed", error=str(e))
        return [], []


def extract_query_graph_terms(user_query: str) -> List[str]:
    """Entity phrases from the user question for graph seeding."""
    if not settings.OPENAI_API_KEY.strip():
        return []
    q = (user_query or "").strip()
    if len(q) < 3:
        return []
    max_q = int(settings.GRAPH_QUERY_ENTITY_LIMIT)
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    try:
        resp = client.chat.completions.create(
            model=settings.graph_extraction_model,
            messages=[
                {"role": "system", "content": _QUERY_ENTITY_SYS.format(max_q=max_q)},
                {"role": "user", "content": q[:2000]},
            ],
            temperature=0.0,
            max_tokens=200,
        )
        data = _parse_json_obj(resp.choices[0].message.content or "")
        out = []
        for x in data.get("entities") or []:
            s = str(x).strip()
            if s and s not in out:
                out.append(s[:200])
        return out[:max_q]
    except Exception as e:
        log.warning("graph_extraction.query_terms_failed", error=str(e))
        return []
