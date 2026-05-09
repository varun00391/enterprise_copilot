"""
Neo4j graph persistence for Phase 3 knowledge graph.
Schema: (:Entity) nodes keyed by deterministic `eid`; [:RELATES_TO] edges with doc_id/chunk_index alignment.
Technology: Neo4j 5 Community (bolt); optional — leave NEO4J_URI unset to disable.
"""
from __future__ import annotations

import hashlib
import re
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from app.core.config import settings

log = structlog.get_logger()

_driver = None
_driver_lock = threading.Lock()
_schema_ready = False


def _norm_name_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def entity_id(dept_id: str, entity_type: str, name: str) -> str:
    raw = f"{dept_id}|{(entity_type or 'THING').strip().upper()}|{_norm_name_key(name)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def get_graph_driver():
    """Lazy singleton Neo4j driver; None if graph is disabled or unavailable."""
    global _driver
    if not settings.neo4j_configured:
        return None
    with _driver_lock:
        if _driver is not None:
            return _driver
        try:
            from neo4j import GraphDatabase
        except ImportError:
            log.warning("graph_store.neo4j_import_failed")
            return None
        try:
            _driver = GraphDatabase.driver(
                settings.NEO4J_URI.strip(),
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            )
            _driver.verify_connectivity()
            log.info("graph_store.neo4j_connected", uri=settings.NEO4J_URI.split("@")[-1])
        except Exception as e:
            log.error("graph_store.neo4j_connect_failed", error=str(e))
            _driver = None
    return _driver


def ensure_graph_schema() -> None:
    global _schema_ready
    driver = get_graph_driver()
    if not driver or _schema_ready:
        return
    try:
        with driver.session() as session:
            session.run(
                "CREATE CONSTRAINT entity_eid_unique IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE e.eid IS UNIQUE"
            )
        _schema_ready = True
    except Exception as e:
        log.warning("graph_store.schema_ensure_failed", error=str(e))


def delete_graph_for_document(dept_id: str, doc_id: str) -> None:
    driver = get_graph_driver()
    if not driver:
        return
    ensure_graph_schema()
    try:
        with driver.session() as session:
            session.run(
                """
                MATCH ()-[r:RELATES_TO]->()
                WHERE r.doc_id = $doc_id
                DELETE r
                """,
                doc_id=doc_id,
            )
            session.run(
                """
                MATCH (e:Entity {dept_id: $dept_id})
                WHERE NOT (e)-[:RELATES_TO]-()
                DELETE e
                """,
                dept_id=dept_id,
            )
        log.info("graph_store.deleted_doc_edges", doc_id=doc_id, dept_id=dept_id)
    except Exception as e:
        log.warning("graph_store.delete_failed", doc_id=doc_id, error=str(e))


def upsert_chunk_graph(
    dept_id: str,
    doc_id: str,
    chunk_index: int,
    filename: str,
    entities: List[Dict[str, str]],
    relations: List[Dict[str, str]],
) -> None:
    """
    Merge entities and directed relations for one chunk. Relation head/tail must match extracted entity names.
    """
    driver = get_graph_driver()
    if not driver:
        return
    ensure_graph_schema()
    if not entities and not relations:
        return

    by_key: Dict[str, str] = {}
    for ent in entities:
        name = (ent.get("name") or "").strip()
        et = (ent.get("type") or "Concept").strip() or "Concept"
        if not name:
            continue
        eid = entity_id(dept_id, et, name)
        by_key[_norm_name_key(name)] = eid

    try:
        with driver.session() as session:
            for ent in entities:
                name = (ent.get("name") or "").strip()
                et = (ent.get("type") or "Concept").strip() or "Concept"
                if not name:
                    continue
                eid = entity_id(dept_id, et, name)
                nl = _norm_name_key(name)
                session.run(
                    """
                    MERGE (e:Entity {eid: $eid})
                    SET e.canonical_name = $name,
                        e.etype = $etype,
                        e.dept_id = $dept_id,
                        e.name_lower = $nl
                    """,
                    eid=eid,
                    name=name[:500],
                    etype=et[:120],
                    dept_id=dept_id,
                    nl=nl[:500],
                )

            for rel in relations:
                head = (rel.get("head") or "").strip()
                tail = (rel.get("tail") or "").strip()
                rtype = (rel.get("type") or "RELATED_TO").strip().upper().replace(" ", "_")
                if not head or not tail:
                    continue
                heid = by_key.get(_norm_name_key(head))
                teid = by_key.get(_norm_name_key(tail))
                if not heid or not teid or heid == teid:
                    continue
                session.run(
                    """
                    MATCH (a:Entity {eid: $heid}), (b:Entity {eid: $teid})
                    MERGE (a)-[r:RELATES_TO {doc_id: $doc_id, chunk_index: $chunk, rel_type: $rtype}]->(b)
                    SET r.source_filename = $filename
                    """,
                    heid=heid,
                    teid=teid,
                    doc_id=doc_id,
                    chunk=chunk_index,
                    rtype=rtype[:80],
                    filename=(filename or "")[:500],
                )
    except Exception as e:
        log.error("graph_store.upsert_failed", doc_id=doc_id, chunk=chunk_index, error=str(e))


def resolve_seed_entities(dept_id: str, terms: List[str], limit: int = 10) -> List[str]:
    """Match entity ids whose canonical name contains any of the query terms."""
    driver = get_graph_driver()
    if not driver or not terms:
        return []
    ensure_graph_schema()
    lowered = [t.strip().lower() for t in terms if t and len(t.strip()) >= 2]
    if not lowered:
        return []
    try:
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (e:Entity {dept_id: $dept_id})
                WHERE ANY(t IN $terms WHERE e.name_lower CONTAINS t OR toLower(e.canonical_name) CONTAINS t)
                RETURN DISTINCT e.eid AS eid
                LIMIT $limit
                """,
                dept_id=dept_id,
                terms=lowered[:20],
                limit=limit,
            )
            return [r["eid"] for r in rows if r.get("eid")]
    except Exception as e:
        log.warning("graph_store.seed_resolve_failed", error=str(e))
        return []


def subgraph_to_text(dept_id: str, seed_eids: List[str]) -> str:
    """
    Bounded neighborhood: undirected 1–2 hop RELATES_TO edges, dept-scoped.
    """
    driver = get_graph_driver()
    if not driver or not seed_eids:
        return ""
    ensure_graph_schema()
    depth = max(1, min(3, int(settings.GRAPH_TRAVERSAL_DEPTH)))
    lim = max(10, int(settings.GRAPH_TRAVERSAL_REL_LIMIT))
    lines: List[str] = []
    seen: Set[Tuple[str, str, str, str, int]] = set()

    def add_line(a: str, rel: str, b: str, doc: str, ch: int) -> None:
        key = (a, rel, b, doc, ch)
        if key in seen:
            return
        seen.add(key)
        doc_short = (doc or "")[:8]
        lines.append(f"- {a} —[{rel}]→ {b} (doc …{doc_short}, chunk {ch})")

    try:
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (s:Entity)-[r:RELATES_TO]-(o:Entity)
                WHERE s.eid IN $eids AND s.dept_id = $dept_id AND o.dept_id = $dept_id
                RETURN s.canonical_name AS a, r.rel_type AS rel, o.canonical_name AS b,
                       r.doc_id AS doc_id, r.chunk_index AS chunk
                LIMIT $lim
                """,
                eids=seed_eids,
                dept_id=dept_id,
                lim=lim,
            )
            for rec in rows:
                add_line(
                    rec["a"] or "",
                    rec["rel"] or "RELATED",
                    rec["b"] or "",
                    str(rec["doc_id"] or ""),
                    int(rec["chunk"] if rec["chunk"] is not None else -1),
                )

            if depth >= 2:
                rows2 = session.run(
                    """
                    MATCH (s:Entity)-[:RELATES_TO]-(m:Entity)-[r2:RELATES_TO]-(o:Entity)
                    WHERE s.eid IN $eids AND s.dept_id = $dept_id AND m.dept_id = $dept_id
                      AND o.dept_id = $dept_id AND s <> o
                    RETURN m.canonical_name AS mid, r2.rel_type AS rel, o.canonical_name AS b,
                           r2.doc_id AS doc_id, r2.chunk_index AS chunk
                    LIMIT $lim
                    """,
                    eids=seed_eids,
                    dept_id=dept_id,
                    lim=lim,
                )
                for rec in rows2:
                    mid = rec["mid"] or ""
                    add_line(
                        mid,
                        rec["rel"] or "RELATED",
                        rec["b"] or "",
                        str(rec["doc_id"] or ""),
                        int(rec["chunk"] if rec["chunk"] is not None else -1),
                    )
    except Exception as e:
        log.warning("graph_store.subgraph_failed", error=str(e))
        return ""

    if not lines:
        return ""
    return "\n".join(lines[: lim // 2])


def ping_graph() -> bool:
    d = get_graph_driver()
    if not d:
        return False
    try:
        d.verify_connectivity()
        return True
    except Exception:
        return False
