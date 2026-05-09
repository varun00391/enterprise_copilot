"""
Analytics Agent — auto-analyzes XLSX/CSV data, detects charts via vision,
and returns structured markdown insights alongside standard citations.
"""
import io
import json
from typing import List, Dict, Any, Optional

import structlog

from app.core.config import settings
from app.agents.reasoning import _sources_from_chunks

log = structlog.get_logger()


def _analyze_dataframe(df_bytes: bytes, file_type: str, query: str) -> str:
    """Generate statistical summary for spreadsheet data."""
    import pandas as pd

    if file_type in ("xlsx", "xls"):
        df = pd.read_excel(io.BytesIO(df_bytes))
    else:
        df = pd.read_csv(io.BytesIO(df_bytes))

    lines = [f"**Dataset Overview**", f"- Rows: {len(df):,}", f"- Columns: {', '.join(df.columns.tolist()[:10])}"]

    # Numeric summary
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if numeric_cols:
        lines.append("\n**Key Statistics**")
        for col in numeric_cols[:5]:
            lines.append(
                f"- **{col}**: min={df[col].min():.2f}, max={df[col].max():.2f}, "
                f"mean={df[col].mean():.2f}, median={df[col].median():.2f}"
            )

    # Detect trends
    if len(numeric_cols) >= 2:
        try:
            corr = df[numeric_cols[:5]].corr().iloc[0, 1]
            if abs(corr) > 0.7:
                lines.append(f"\n**Trend**: Strong {'positive' if corr > 0 else 'negative'} correlation "
                              f"between {numeric_cols[0]} and {numeric_cols[1]} (r={corr:.2f})")
        except Exception:
            pass

    # Top/bottom rows for context
    lines.append("\n**First 3 Rows**")
    try:
        lines.append(df.head(3).to_markdown(index=False))
    except Exception:
        lines.append(df.head(3).to_csv(index=False))

    return "\n".join(lines)


def detect_chart_in_image(image_bytes: bytes) -> Optional[str]:
    """
    Use Llama 4 Scout (Groq) or GPT-4o to describe a chart/graph image.
    Returns description or None if not a chart.
    """
    from app.agents.multimodal import describe_image
    prompt = (
        "Is this image a chart, graph, or data visualization? "
        "If yes, describe the chart type, axes, key values, trends, and any notable data points. "
        "If not a chart, briefly describe what you see. Be concise."
    )
    try:
        return describe_image(image_bytes, prompt)
    except Exception as e:
        log.warning("analytics_agent.chart_detection_failed", error=str(e))
        return None


def generate_analytics_answer(
    query: str,
    chunks: List[Dict[str, Any]],
    spreadsheet_bytes: Optional[bytes] = None,
    spreadsheet_type: Optional[str] = None,
    conversation_history: List[Dict] = None,
    chart_description: Optional[str] = None,
) -> tuple[str, float, List[Dict]]:
    """
    Enriched answer generation for analytics queries.
    Prepends spreadsheet statistics and/or chart vision summary when available.
    """
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

    context_parts = []

    if chart_description:
        context_parts.append(f"**Chart / image analysis (from knowledge base)**\n{chart_description}\n")

    # Add spreadsheet analysis if available
    if spreadsheet_bytes and spreadsheet_type:
        try:
            stats = _analyze_dataframe(spreadsheet_bytes, spreadsheet_type, query)
            context_parts.append(f"**Spreadsheet Analysis**\n{stats}\n")
        except Exception as e:
            log.warning("analytics_agent.df_analysis_failed", error=str(e))

    # Add RAG chunks
    for i, chunk in enumerate(chunks, 1):
        context_parts.append(f"[Source {i}] {chunk.get('doc_name', 'Unknown')} (chunk {chunk.get('chunk_index', 0)}):\n{chunk.get('content', '')}\n")

    context = "\n".join(context_parts) if context_parts else "No relevant data found."

    system_prompt = """You are OrgMind Analytics, an expert data analyst and enterprise knowledge assistant.
When analyzing spreadsheet data:
- Provide clear statistical insights in markdown format
- Use tables to present comparative data
- Highlight trends, anomalies, and key metrics
- Always cite sources with [Source N] references

Response format:
<reasoning>Brief analysis reasoning</reasoning>
<answer>Formatted markdown answer with tables and insights</answer>
<confidence>0.85</confidence>"""

    messages = [{"role": "system", "content": system_prompt}]
    if conversation_history:
        for turn in conversation_history[-6:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": f"Data and context:\n{context}\n\nQuestion: {query}"})

    response = client.chat.completions.create(
        model=settings.OPENAI_CHAT_MODEL,
        messages=messages,
        temperature=0.1,
        max_tokens=2000,
    )

    raw = response.choices[0].message.content or ""

    # Parse answer + confidence
    answer = raw
    confidence = 0.80
    if "<answer>" in raw and "</answer>" in raw:
        answer = raw[raw.index("<answer>") + 8:raw.index("</answer>")].strip()
    if "<confidence>" in raw and "</confidence>" in raw:
        try:
            confidence = float(raw[raw.index("<confidence>") + 12:raw.index("</confidence>")].strip())
            confidence = max(0.0, min(1.0, confidence))
        except ValueError:
            pass

    sources = _sources_from_chunks(chunks)

    return answer, confidence, sources
