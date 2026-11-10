from recipe_db import youtube
from recipe_db.youtube import _vtt_to_text, _vtt_to_timed_text, fetch_caption_tracks


def test_vtt_to_text_removes_tags_and_overlapping_auto_captions() -> None:
    raw = """WEBVTT
Kind: captions
Language: ko

00:00:00.000 --> 00:00:02.000
먼저<00:00:00.400><c> 양파를</c><00:00:00.800><c> 썰어</c>

00:00:02.000 --> 00:00:04.000
먼저 양파를 썰어
주세요<00:00:02.500><c> 그리고</c><00:00:03.000><c> 볶습니다</c>
"""

    assert _vtt_to_text(raw) == "먼저 양파를 썰어 주세요 그리고 볶습니다"
    assert _vtt_to_timed_text(raw) == (
        "[00:00] 먼저 양파를 썰어\n[00:02] 주세요 그리고 볶습니다"
    )


def test_invidious_captions_use_instance_proxy(monkeypatch) -> None:
    requested: list[str] = []

    def fake_fetch(url: str, timeout: int = 30) -> str:
        requested.append(url)
        return """WEBVTT

00:00:01.000 --> 00:00:03.000
양파를 썰어 볶습니다
"""

    monkeypatch.setattr(youtube, "_fetch_text", fake_fetch)
    tracks = fetch_caption_tracks(
        {
            "id": "video123",
            "_invidious_base_url": "https://example.invalid",
            "captions": [
                {
                    "language_code": "ko",
                    "label": "Korean (auto-generated)",
                    "url": "https://www.youtube.com/api/timedtext?blocked=1",
                }
            ],
        }
    )

    assert requested == [
        "https://example.invalid/api/v1/captions/video123?label=Korean%20%28auto-generated%29"
    ]
    assert tracks["ko:Korean (auto-generated)"] == "[00:01] 양파를 썰어 볶습니다"
