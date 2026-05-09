from typing import TypedDict, Optional, List, Any
from uuid import UUID


class AgentState(TypedDict, total=False):
    query: str
    dept_id: str
    user_id: str
    session_id: str
    conversation_history: List[dict]
    retrieved_chunks: List[dict]
    reranked_chunks: List[dict]
    answer: str
    confidence: float
    sources: List[dict]
    error: Optional[str]
    intent: str
    entities: List[str]
