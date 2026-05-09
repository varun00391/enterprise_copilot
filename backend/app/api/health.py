from fastapi import APIRouter
from app.schemas.schemas import HealthStatus

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthStatus)
def health_check():
    from app.core.config import settings

    services = {}

    try:
        from app.core.database import engine
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        services["postgres"] = "ok"
    except Exception as e:
        services["postgres"] = f"error: {str(e)[:50]}"

    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=settings.QDRANT_URL, timeout=2)
        client.get_collections()
        services["qdrant"] = "ok"
    except Exception as e:
        services["qdrant"] = f"error: {str(e)[:50]}"

    try:
        import redis
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        r.ping()
        services["redis"] = "ok"
    except Exception as e:
        services["redis"] = f"error: {str(e)[:50]}"

    try:
        from app.services.storage import get_minio_client
        client = get_minio_client()
        client.bucket_exists(settings.MINIO_BUCKET)
        services["minio"] = "ok"
    except Exception as e:
        services["minio"] = f"error: {str(e)[:50]}"

    try:
        if settings.neo4j_configured:
            from app.services.graph_store import ping_graph

            services["neo4j"] = "ok" if ping_graph() else "error: unreachable"
        else:
            services["neo4j"] = "disabled"
    except Exception as e:
        services["neo4j"] = f"error: {str(e)[:50]}"

    required_ok = all(
        services.get(k) == "ok" for k in ("postgres", "qdrant", "redis", "minio")
    )
    overall = "ok" if required_ok else "degraded"
    if settings.graph_rag_active and services.get("neo4j") != "ok":
        overall = "degraded"
    return HealthStatus(status=overall, services=services)
