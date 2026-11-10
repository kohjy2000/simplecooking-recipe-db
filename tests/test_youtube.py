from recipe_db.youtube import _vtt_to_text, _vtt_to_timed_text


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
