"""
Video Agent — LangGraph subgraph for decode → frames → transcript → embeddings → Qdrant.

Uses ffmpeg for demux/normalization (any format the installed codecs support).
Transcripts use the same STT stack as batch audio (Groq / OpenAI); sampled frames get
vision captions then text embeddings so they share the departmental vector collection.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, TypedDict

import structlog
from langgraph.graph import END, StateGraph

from app.core.config import settings
from app.agents.ingestion import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    ensure_collection,
    get_qdrant_client,
)
from app.agents.multimodal import describe_image
from app.agents.voice import transcribe_audio_with_segments
from app.services.embeddings import embed_texts

log = structlog.get_logger()


_FRAME_PROMPT = (
    "Describe this video frame briefly for enterprise search indexing. "
    "Mention readable text, people, actions, objects, diagrams, slides, charts, UI, logos, locations."
)


def _format_ts(sec: float) -> str:
    if sec < 0:
        sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:05.2f}"
    return f"{m}:{s:05.2f}"


def _which_ffmpeg() -> str:
    path = shutil.which("ffmpeg") or shutil.which("avconv")
    if not path:
        raise RuntimeError(
            "ffmpeg is not installed. Install ffmpeg locally or use the OrgMind backend Docker image."
        )
    return path


def probe_video(video_path: str) -> Dict[str, Any]:
    fb = shutil.which("ffprobe")
    cmd = []
    if fb:
        cmd = [fb]
    else:
        ff = _which_ffmpeg()
        cmd = [ff.replace("ffmpeg", "ffprobe")]
    cmd.extend(
        [
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type",
            "-of",
            "json",
            video_path,
        ]
    )
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            timeout=settings.VIDEO_PROBE_TIMEOUT_SEC,
            text=True,
            check=False,
        )
        if p.returncode != 0:
            raise RuntimeError(p.stderr.strip() or "ffprobe failed")
        data = json.loads(p.stdout or "{}")
    except json.JSONDecodeError as e:
        raise RuntimeError("ffprobe returned invalid JSON") from e

    duration = float((data.get("format") or {}).get("duration") or 0)
    streams = data.get("streams") or []
    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    return {"duration_sec": duration, "has_video": has_video, "has_audio": has_audio}


def extract_wav_16k_mono(video_path: str, out_wav: str) -> None:
    ff = _which_ffmpeg()
    cmd = [
        ff,
        "-y",
        "-i",
        video_path,
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        out_wav,
    ]
    p = subprocess.run(
        cmd,
        capture_output=True,
        timeout=settings.VIDEO_FFMPEG_TIMEOUT_SEC,
        check=False,
    )
    if p.returncode != 0:
        log.warning("video_agent.audio_extract_failed", stderr=(p.stderr or b"")[:500].decode(errors="replace"))


def extract_sample_frames(video_path: str, out_dir: str, duration_sec: float) -> List[float]:
    """
    Write PNG frames under out_dir; return sorted timestamps (sec) for each frame.
    """
    os.makedirs(out_dir, exist_ok=True)
    interval = max(1.0, float(settings.VIDEO_FRAME_SAMPLE_INTERVAL_SEC))
    cap = max(1, int(settings.VIDEO_MAX_SAMPLE_FRAMES))
    if duration_sec <= 0:
        max_f = 1
    else:
        raw_n = int(math.ceil(duration_sec / interval)) + 1
        max_f = min(cap, max(1, raw_n))

    ff = _which_ffmpeg()
    vf = f"fps=1/{interval},scale='min(1280,iw)':-2"
    cmd = [
        ff,
        "-y",
        "-i",
        video_path,
        "-vf",
        vf,
        "-frames:v",
        str(max_f),
        os.path.join(out_dir, "frame_%04d.png"),
    ]
    p = subprocess.run(
        cmd,
        capture_output=True,
        timeout=settings.VIDEO_FFMPEG_TIMEOUT_SEC,
        check=False,
    )
    if p.returncode != 0:
        log.warning("video_agent.frame_extract_failed", stderr=(p.stderr or b"")[:500].decode(errors="replace"))
        return []

    files = sorted(f for f in os.listdir(out_dir) if f.startswith("frame_") and f.endswith(".png"))
    times: List[float] = []
    for i, _fn in enumerate(files):
        times.append(min(duration_sec, i * interval) if duration_sec > 0 else float(i * interval))
    return times


def _split_segment_to_chunks(
    text: str,
    t_start: float,
    t_end: float,
) -> List[tuple[str, float, float]]:
    """Word-split a segment into ~CHUNK_SIZE windows; interpolate time ranges."""
    words = text.split()
    if not words:
        return []
    span = max(0.001, t_end - t_start)
    out: List[tuple[str, float, float]] = []
    start = 0
    while start < len(words):
        end = min(start + CHUNK_SIZE, len(words))
        chunk = " ".join(words[start:end])
        if chunk.strip():
            frac_lo = start / len(words)
            frac_hi = end / len(words)
            out.append(
                (
                    chunk.strip(),
                    t_start + span * frac_lo,
                    t_start + span * frac_hi,
                )
            )
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return out


def _caption_one_frame(args: tuple[str, float, int]) -> Optional[tuple[str, Dict[str, Any]]]:
    path, t_sec, frame_idx = args
    try:
        with open(path, "rb") as f:
            data = f.read()
        cap = describe_image(data, _FRAME_PROMPT).strip()
        if not cap:
            return None
        label = _format_ts(t_sec)
        content = f"[Video frame @ {label}] {cap}"
        extra = {
            "modality": "video_frame",
            "t_start_sec": round(t_sec, 3),
            "t_end_sec": round(t_sec, 3),
            "frame_index": frame_idx,
        }
        return content, extra
    except Exception as e:
        log.warning("video_agent.frame_caption_failed", frame=frame_idx, error=str(e))
        return None


class VideoIngestState(TypedDict, total=False):
    scratch_root: str
    file_bytes: bytes
    filename: str
    file_type: str
    doc_id: str
    dept_id: str
    metadata: Dict[str, Any]
    tmp_video_path: str
    wav_path: str
    frames_dir: str
    probe_meta: Dict[str, Any]
    transcript_segments: List[Dict[str, Any]]
    frame_timestamps: List[float]
    texts: List[str]
    payload_extras: List[Dict[str, Any]]
    indexed: int
    error: str


def node_write_temp(state: VideoIngestState) -> VideoIngestState:
    suf = state.get("file_type", "mp4").lstrip(".")
    path = os.path.join(state["scratch_root"], f"input.{suf}")
    with open(path, "wb") as f:
        f.write(state["file_bytes"])
    return {"tmp_video_path": path}


def node_probe(state: VideoIngestState) -> VideoIngestState:
    p = probe_video(state["tmp_video_path"])
    if not p["has_video"] and not p["has_audio"]:
        raise ValueError("File has no readable video or audio stream (unsupported or corrupt).")
    return {"probe_meta": p}


def node_extract_media(state: VideoIngestState) -> VideoIngestState:
    base = state["scratch_root"]
    wav = os.path.join(base, "audio.wav")
    frames = os.path.join(base, "frames")
    dur = float(state["probe_meta"]["duration_sec"] or 0)
    if state["probe_meta"].get("has_audio"):
        extract_wav_16k_mono(state["tmp_video_path"], wav)
    fts: List[float] = []
    if state["probe_meta"].get("has_video"):
        fts = extract_sample_frames(state["tmp_video_path"], frames, dur)
    return {"wav_path": wav, "frames_dir": frames, "frame_timestamps": fts}


def node_transcribe(state: VideoIngestState) -> VideoIngestState:
    use_groq = bool(settings.GROQ_API_KEY)
    segs: List[Dict[str, Any]] = []
    dur = float(state["probe_meta"]["duration_sec"] or 0)
    wav = state.get("wav_path") or ""
    if state["probe_meta"].get("has_audio") and os.path.isfile(wav) and os.path.getsize(wav) > 44:
        with open(wav, "rb") as f:
            audio_bytes = f.read()
        segs = transcribe_audio_with_segments(
            audio_bytes,
            filename="extracted.wav",
            duration_sec=dur if dur > 0 else None,
            use_groq=use_groq,
        )
    if not segs and not state["probe_meta"].get("has_video"):
        raise ValueError("No speech could be transcribed from the video audio track.")
    return {"transcript_segments": segs}


def node_build_points(state: VideoIngestState) -> VideoIngestState:
    texts: List[str] = []
    extras: List[Dict[str, Any]] = []
    dur = float(state["probe_meta"]["duration_sec"] or 0)

    for seg in state.get("transcript_segments") or []:
        t0 = float(seg.get("start", 0))
        t1 = float(seg.get("end", t0))
        if dur > 0:
            t1 = min(t1, dur)
            t0 = min(t0, dur)
        tx = (seg.get("text") or "").strip()
        if not tx:
            continue
        for chunk, c0, c1 in _split_segment_to_chunks(tx, t0, t1):
            label0, label1 = _format_ts(c0), _format_ts(c1)
            texts.append(f"[Video transcript {label0} – {label1}] {chunk}")
            extras.append(
                {
                    "modality": "video_transcript",
                    "t_start_sec": round(c0, 3),
                    "t_end_sec": round(c1, 3),
                    "frame_index": None,
                }
            )

    frames_dir = state.get("frames_dir") or ""
    fts = state.get("frame_timestamps") or []
    if frames_dir and os.path.isdir(frames_dir):
        files = sorted(f for f in os.listdir(frames_dir) if f.startswith("frame_") and f.endswith(".png"))
        jobs: List[tuple[str, float, int]] = []
        for i, fn in enumerate(files):
            tsec = fts[i] if i < len(fts) else float(i * settings.VIDEO_FRAME_SAMPLE_INTERVAL_SEC)
            jobs.append((os.path.join(frames_dir, fn), tsec, i))
        max_workers = min(6, max(1, len(jobs)))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_caption_one_frame, j): j for j in jobs}
            for fut in as_completed(futs):
                got = fut.result()
                if got:
                    content, extra = got
                    texts.append(content)
                    extras.append(extra)

    if not texts:
        raise ValueError("Video produced no searchable text (no speech and no frame captions).")

    return {"texts": texts, "payload_extras": extras}


def node_embed_and_upsert(state: VideoIngestState) -> VideoIngestState:
    from qdrant_client.models import PointStruct
    import uuid as uuid_mod

    client = get_qdrant_client()
    dept_id = state["dept_id"]
    ensure_collection(client, dept_id)
    collection_name = f"dept_{dept_id}"
    doc_id = state["doc_id"]
    filename = state["filename"]
    file_type = state["file_type"]
    meta = state.get("metadata") or {}
    texts = state["texts"]
    extras = state["payload_extras"]

    total = 0
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        batch_t = texts[i : i + batch_size]
        batch_e = extras[i : i + batch_size]
        vectors = embed_texts(batch_t)
        points = []
        for j, (content, vector) in enumerate(zip(batch_t, vectors)):
            idx = i + j
            extra = batch_e[j] if j < len(batch_e) else {}
            payload = {
                "doc_id": doc_id,
                "dept_id": dept_id,
                "filename": filename,
                "chunk_index": idx,
                "content": content,
                "file_type": file_type,
                "timestamp": meta.get("created_at", ""),
                "category": meta.get("category", ""),
                "author": meta.get("author", ""),
                **extra,
            }
            points.append(
                PointStruct(
                    id=str(uuid_mod.uuid4()),
                    vector=vector,
                    payload=payload,
                )
            )
        client.upsert(collection_name=collection_name, points=points)
        total += len(points)

    return {"indexed": total}


def _build_graph() -> StateGraph:
    g = StateGraph(VideoIngestState)
    g.add_node("write_temp", node_write_temp)
    g.add_node("probe", node_probe)
    g.add_node("extract", node_extract_media)
    g.add_node("transcribe", node_transcribe)
    g.add_node("build_points", node_build_points)
    g.add_node("upsert", node_embed_and_upsert)

    g.set_entry_point("write_temp")
    g.add_edge("write_temp", "probe")
    g.add_edge("probe", "extract")
    g.add_edge("extract", "transcribe")
    g.add_edge("transcribe", "build_points")
    g.add_edge("build_points", "upsert")
    g.add_edge("upsert", END)
    return g


_compiled = None


def run_video_ingestion_graph(
    file_bytes: bytes,
    file_type: str,
    filename: str,
    doc_id: str,
    dept_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Execute the Video Agent subgraph. Returns chunk/point count written to Qdrant.
    """
    global _compiled
    if _compiled is None:
        _compiled = _build_graph().compile()

    log.info(
        "video_agent.start",
        doc_id=doc_id,
        dept_id=dept_id,
        filename=filename,
        bytes=len(file_bytes),
    )

    with tempfile.TemporaryDirectory(prefix="orgmind_vid_") as scratch:
        initial: VideoIngestState = {
            "scratch_root": scratch,
            "file_bytes": file_bytes,
            "file_type": file_type.lstrip("."),
            "filename": filename,
            "doc_id": doc_id,
            "dept_id": dept_id,
            "metadata": metadata or {},
        }
        try:
            out = _compiled.invoke(initial)
        except Exception as e:
            log.error("video_agent.failed", error=str(e))
            raise
        indexed = int(out.get("indexed", 0))
        log.info("video_agent.complete", doc_id=doc_id, chunks=indexed)
        return indexed
