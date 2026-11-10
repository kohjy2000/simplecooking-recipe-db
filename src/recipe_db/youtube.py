from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from html import unescape
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlparse


class YouTubeError(RuntimeError):
    pass


DEFAULT_INVIDIOUS_BASE_URLS = ("https://yt.chocolatemoo53.com",)


def _yt_dlp_args() -> list[str]:
    args = [sys.executable, "-m", "yt_dlp", "--impersonate", "chrome"]
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
    attempts = [
        [],
        [
            "--extractor-args",
            "youtube:player_client=android_vr;player_skip=webpage,configs",
        ],
        [
            "--extractor-args",
            "youtube:player_client=web_embedded,tv_samsung;player_skip=webpage,configs",
        ],
    ]
    errors: list[str] = []
    for extra_args in attempts:
        try:
            return _run_json([*extra_args, "--skip-download", video_url])
        except YouTubeError as exc:
            errors.append(str(exc))
    try:
        return _fetch_invidious_video(video_url)
    except YouTubeError as exc:
        errors.append(str(exc))
    raise YouTubeError("All anonymous video sources failed: " + " | ".join(errors)[-3000:])


def _invidious_base_urls() -> tuple[str, ...]:
    configured = os.environ.get("INVIDIOUS_BASE_URLS", "")
    if configured.strip():
        return tuple(item.strip().rstrip("/") for item in configured.split(",") if item.strip())
    return DEFAULT_INVIDIOUS_BASE_URLS


def _fetch_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except OSError as exc:
        raise YouTubeError(f"HTTP fetch failed for {urlparse(url).netloc}: {exc}") from exc


def _fetch_invidious_video(video_url: str) -> dict[str, Any]:
    video_id = parse_qs(urlparse(video_url).query).get("v", [""])[0]
    if not video_id:
        raise YouTubeError(f"Could not parse video id from {video_url}")
    errors: list[str] = []
    for base_url in _invidious_base_urls():
        try:
            payload = json.loads(_fetch_text(f"{base_url}/api/v1/videos/{quote(video_id)}"))
            if payload.get("error"):
                raise YouTubeError(str(payload["error"]))
            thumbnails = payload.get("videoThumbnails") or []
            payload.update(
                {
                    "id": video_id,
                    "channel": payload.get("author"),
                    "channel_id": payload.get("authorId"),
                    "duration": payload.get("lengthSeconds"),
                    "thumbnail": thumbnails[0].get("url") if thumbnails else None,
                    "_invidious_base_url": base_url,
                }
            )
            return payload
        except (json.JSONDecodeError, YouTubeError) as exc:
            errors.append(f"{base_url}: {exc}")
    raise YouTubeError("Invidious fallback failed: " + " | ".join(errors))


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
    if base_url := metadata.get("_invidious_base_url"):
        tracks = metadata.get("captions") or []
        track = next(
            (
                item
                for item in tracks
                if str(item.get("language_code") or item.get("languageCode") or "").startswith("ko")
            ),
            None,
        )
        if not track or not track.get("url"):
            return ""
        raw = _fetch_text(urljoin(f"{base_url}/", track["url"]))
        return _vtt_to_text(raw)

    candidates = _caption_candidates(metadata)
    if not candidates:
        return ""
    preferred = next((item for item in candidates if item.get("ext") == "json3"), candidates[0])
    url = preferred.get("url")
    if not url:
        return ""
    raw = _fetch_text(url)
    if preferred.get("ext") == "json3":
        payload = json.loads(raw)
        chunks: list[str] = []
        for event in payload.get("events") or []:
            text = "".join(seg.get("utf8", "") for seg in event.get("segs") or [])
            text = text.replace("\n", " ").strip()
            if text:
                chunks.append(text)
        return " ".join(chunks)
    return _vtt_to_text(raw)


def fetch_caption_tracks(
    metadata: dict[str, Any], languages: tuple[str, ...] = ("en", "ko")
) -> dict[str, str]:
    """Return timestamped caption tracks for AI-assisted recipe curation."""
    result: dict[str, str] = {}
    if base_url := metadata.get("_invidious_base_url"):
        for track in metadata.get("captions") or []:
            code = str(track.get("language_code") or track.get("languageCode") or "")
            label = str(track.get("label") or code or "caption")
            if not any(code.startswith(language) for language in languages):
                continue
            url = track.get("url")
            if not url:
                continue
            raw = _fetch_text(urljoin(f"{base_url}/", url))
            transcript = _vtt_to_timed_text(raw)
            if transcript:
                result[f"{code or label}:{label}"] = transcript
        return result

    for language in languages:
        candidates: list[dict[str, Any]] = []
        for source in (metadata.get("subtitles") or {}, metadata.get("automatic_captions") or {}):
            for code, tracks in source.items():
                if code.startswith(language):
                    candidates.extend(tracks or [])
            if candidates:
                break
        if not candidates:
            continue
        preferred = next((item for item in candidates if item.get("ext") == "json3"), candidates[0])
        url = preferred.get("url")
        if not url:
            continue
        raw = _fetch_text(url)
        transcript = (
            _json3_to_timed_text(raw)
            if preferred.get("ext") == "json3"
            else _vtt_to_timed_text(raw)
        )
        if transcript:
            result[language] = transcript
    return result


def _timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def _vtt_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except ValueError:
        return 0
    return 0


def _append_new_words(transcript: list[str], words: list[str]) -> list[str]:
    overlap = 0
    for size in range(min(len(transcript), len(words)), 0, -1):
        if transcript[-size:] == words[:size]:
            overlap = size
            break
    additions = words[overlap:]
    transcript.extend(additions)
    return additions


def _vtt_to_timed_text(raw: str) -> str:
    entries: list[tuple[float, str]] = []
    start_seconds: float | None = None
    current: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if "-->" in stripped:
            if current and start_seconds is not None:
                entries.append((start_seconds, " ".join(current)))
            current = []
            start_seconds = _vtt_seconds(stripped.split("-->", 1)[0].strip())
            continue
        if not stripped:
            if current and start_seconds is not None:
                entries.append((start_seconds, " ".join(current)))
            current = []
            start_seconds = None
            continue
        if stripped.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")) or stripped.isdigit():
            continue
        cleaned = unescape(re.sub(r"<[^>]+>", "", stripped))
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            current.append(cleaned)
    if current and start_seconds is not None:
        entries.append((start_seconds, " ".join(current)))

    transcript: list[str] = []
    timed_lines: list[str] = []
    for seconds, cue in entries:
        additions = _append_new_words(transcript, cue.split())
        if additions:
            timed_lines.append(f"[{_timestamp(seconds)}] {' '.join(additions)}")
    return "\n".join(timed_lines)


def _json3_to_timed_text(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise YouTubeError("Caption JSON was invalid") from exc
    transcript: list[str] = []
    timed_lines: list[str] = []
    for event in payload.get("events") or []:
        text = "".join(segment.get("utf8", "") for segment in event.get("segs") or [])
        words = text.replace("\n", " ").split()
        additions = _append_new_words(transcript, words)
        if additions:
            timed_lines.append(
                f"[{_timestamp(float(event.get('tStartMs') or 0) / 1000)}] {' '.join(additions)}"
            )
    return "\n".join(timed_lines)


def _vtt_to_text(raw: str) -> str:
    cues: list[str] = []
    current: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                cues.append(" ".join(current))
                current = []
            continue
        if stripped.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")):
            continue
        if "-->" in stripped or stripped.isdigit():
            continue
        cleaned = unescape(re.sub(r"<[^>]+>", "", stripped))
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            current.append(cleaned)
    if current:
        cues.append(" ".join(current))

    transcript: list[str] = []
    for cue in cues:
        words = cue.split()
        overlap = 0
        for size in range(min(len(transcript), len(words)), 0, -1):
            if transcript[-size:] == words[:size]:
                overlap = size
                break
        if overlap == 0 and words and len(words) <= len(transcript):
            joined = " ".join(words)
            if joined in " ".join(transcript[-max(len(words) * 3, 30) :]):
                continue
        transcript.extend(words[overlap:])
    return " ".join(transcript)

