from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from typing import Any


class YouTubeError(RuntimeError):
    pass


def _yt_dlp_args() -> list[str]:
    args = [sys.executable, "-m", "yt_dlp"]
    cookies = os.environ.get("YTDLP_COOKIES_FILE")
    if cookies:
        args.extend(["--cookies", cookies])
    return args


def _run_json(args: list[str], timeout: int = 300) -> dict[str, Any]:
    command = [*_yt_dlp_args(), "--no-warnings", "--dump-single-json", *args]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise YouTubeError(f"yt-dlp timed out after {timeout}s") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "unknown yt-dlp error").strip()
        raise YouTubeError(detail[-2000:]) from exc
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise YouTubeError("yt-dlp returned invalid JSON") from exc


def _iso_date(entry: dict[str, Any]) -> str | None:
    timestamp = entry.get("timestamp") or entry.get("release_timestamp")
    if timestamp:
        return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()
    upload_date = entry.get("upload_date")
    if upload_date and len(upload_date) == 8:
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}T00:00:00+00:00"
    return None


def discover_channel(channel_url: str) -> list[dict[str, Any]]:
    url = channel_url.rstrip("/")
    if not url.endswith("/videos"):
        url += "/videos"
    payload = _run_json(["--flat-playlist", url], timeout=600)
    entries = payload.get("entries") or []
    videos: list[dict[str, Any]] = []
    for position, entry in enumerate(entries, start=1):
        if not entry or not entry.get("id"):
            continue
        video_id = str(entry["id"])
        thumbnails = entry.get("thumbnails") or []
        thumbnail = thumbnails[-1].get("url") if thumbnails else entry.get("thumbnail")
        videos.append(
            {
                "video_id": video_id,
                "channel_id": entry.get("channel_id") or payload.get("channel_id"),
                "channel_name": entry.get("channel") or payload.get("channel"),
                "title": entry.get("title") or video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "published_at": _iso_date(entry),
                "duration_seconds": entry.get("duration"),
                "playlist_position": position,
                "thumbnail_url": thumbnail,
            }
        )
    if not videos:
        raise YouTubeError("No videos were discovered for the channel")
    return videos


def fetch_video(video_url: str) -> dict[str, Any]:
    return _run_json(["--skip-download", video_url])


def _caption_candidates(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source in (metadata.get("subtitles") or {}, metadata.get("automatic_captions") or {}):
        for language in ("ko", "ko-KR"):
            candidates.extend(source.get(language) or [])
        if not candidates:
            for language, tracks in source.items():
                if language.startswith("ko"):
                    candidates.extend(tracks or [])
        if candidates:
            break
    return candidates


def fetch_korean_caption(metadata: dict[str, Any]) -> str:
    candidates = _caption_candidates(metadata)
    if not candidates:
        return ""
    preferred = next((item for item in candidates if item.get("ext") == "json3"), candidates[0])
    url = preferred.get("url")
    if not url:
        return ""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except OSError as exc:
        raise YouTubeError(f"Caption download failed: {exc}") from exc
    if preferred.get("ext") == "json3":
        payload = json.loads(raw)
        chunks: list[str] = []
        for event in payload.get("events") or []:
            text = "".join(seg.get("utf8", "") for seg in event.get("segs") or [])
            text = text.replace("\n", " ").strip()
            if text:
                chunks.append(text)
        return " ".join(chunks)
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")):
            continue
        if "-->" in stripped or stripped.isdigit():
            continue
        if stripped != (lines[-1] if lines else None):
            lines.append(stripped)
    return " ".join(lines)

