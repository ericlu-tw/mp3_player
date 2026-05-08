"""JSON-backed persistence for settings, library, transcripts, and analysis."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .config import (
    ANALYSIS_FILE,
    AVAILABLE_ASR_MODELS,
    AUDIO_CACHE_DIR,
    DEFAULT_ASR_MODEL,
    DEFAULT_CHAT_MODEL,
    LIBRARY_FILE,
    SETTINGS_FILE,
    TRANSCRIPT_FILE,
    ensure_dirs,
)


SCHEMA_VERSION = 1


def _read_json(path: Path, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            return json.load(file_obj)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data: Any) -> None:
    ensure_dirs()
    tmp_path = str(path) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def load_settings() -> dict[str, Any]:
    defaults = {
        "schema_version": SCHEMA_VERSION,
        "hf_token": "",
        "asr_model": DEFAULT_ASR_MODEL,
        "chat_model": DEFAULT_CHAT_MODEL,
        "theme": "light",
        "privacy_acknowledged": False,
        "auto_resume": True,
        "volume": 80,
        "playback_rate": 1.0,
    }
    data = _read_json(SETTINGS_FILE, {})
    if not isinstance(data, dict):
        return defaults
    merged = defaults.copy()
    merged.update(data)
    if str(merged.get("asr_model", "")).strip() not in AVAILABLE_ASR_MODELS:
        merged["asr_model"] = DEFAULT_ASR_MODEL
    return merged


def save_settings(settings: dict[str, Any]) -> None:
    payload = dict(settings)
    if str(payload.get("asr_model", "")).strip() not in AVAILABLE_ASR_MODELS:
        payload["asr_model"] = DEFAULT_ASR_MODEL
    payload["schema_version"] = SCHEMA_VERSION
    _write_json(SETTINGS_FILE, payload)


def load_library() -> dict[str, dict[str, Any]]:
    data = _read_json(LIBRARY_FILE, {})
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def save_library(library: dict[str, dict[str, Any]]) -> None:
    _write_json(LIBRARY_FILE, library)


def upsert_audio_source(source: dict[str, Any]) -> dict[str, Any]:
    library = load_library()
    audio_id = str(source["id"])
    existing = library.get(audio_id, {})
    merged = dict(existing)
    merged.update(source)
    merged.setdefault("created_ts", int(time.time()))
    merged["updated_ts"] = int(time.time())
    library[audio_id] = merged
    save_library(library)
    return merged


def update_playback_state(audio_id: str, position_ms: int, duration_ms: int | None = None) -> None:
    library = load_library()
    entry = library.get(audio_id)
    if not entry:
        return
    entry["last_position_ms"] = max(0, int(position_ms or 0))
    if duration_ms is not None and duration_ms > 0:
        entry["duration_ms"] = int(duration_ms)
    entry["last_played_ts"] = int(time.time())
    save_library(library)


def update_analysis_status(audio_id: str, status: str, last_error: str = "") -> None:
    library = load_library()
    entry = library.get(audio_id)
    if not entry:
        return
    entry["analysis_status"] = status
    if last_error:
        entry["last_error"] = str(last_error)
    elif status in {"not_started", "transcribing", "analyzing", "completed"}:
        entry.pop("last_error", None)
    entry["updated_ts"] = int(time.time())
    save_library(library)


def load_transcripts() -> dict[str, dict[str, Any]]:
    data = _read_json(TRANSCRIPT_FILE, {})
    return data if isinstance(data, dict) else {}


def save_transcript(audio_id: str, transcript: dict[str, Any]) -> None:
    data = load_transcripts()
    payload = dict(transcript)
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_ts"] = int(time.time())
    data[audio_id] = payload
    _write_json(TRANSCRIPT_FILE, data)


def get_transcript(audio_id: str) -> dict[str, Any] | None:
    entry = load_transcripts().get(audio_id)
    return entry if isinstance(entry, dict) else None


def load_analysis() -> dict[str, dict[str, Any]]:
    data = _read_json(ANALYSIS_FILE, {})
    return data if isinstance(data, dict) else {}


def save_analysis(audio_id: str, analysis: dict[str, Any]) -> None:
    data = load_analysis()
    payload = dict(analysis)
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_ts"] = int(time.time())
    data[audio_id] = payload
    _write_json(ANALYSIS_FILE, data)
    update_analysis_status(audio_id, "completed")


def get_analysis(audio_id: str) -> dict[str, Any] | None:
    entry = load_analysis().get(audio_id)
    return entry if isinstance(entry, dict) else None


def delete_audio_source(audio_id: str, delete_cached_file: bool = True) -> dict[str, Any] | None:
    library = load_library()
    removed = library.pop(str(audio_id), None)
    if removed is None:
        return None
    save_library(library)

    transcripts = load_transcripts()
    if str(audio_id) in transcripts:
        transcripts.pop(str(audio_id), None)
        _write_json(TRANSCRIPT_FILE, transcripts)

    analysis = load_analysis()
    if str(audio_id) in analysis:
        analysis.pop(str(audio_id), None)
        _write_json(ANALYSIS_FILE, analysis)

    if delete_cached_file:
        local_path = Path(str(removed.get("local_path", "")))
        try:
            if local_path.exists() and AUDIO_CACHE_DIR in local_path.resolve().parents:
                local_path.unlink()
        except Exception:
            pass
    return removed