from recipe_db.db import connect, initialize, next_pending_videos, upsert_discovered_videos


def test_oldest_known_video_is_processed_first(tmp_path) -> None:
    with connect(tmp_path / "test.sqlite") as conn:
        initialize(conn)
        upsert_discovered_videos(
            conn,
            [
                {
                    "video_id": "new",
                    "title": "new",
                    "url": "https://youtube.test/new",
                    "published_at": "2025-01-02T00:00:00+00:00",
                    "playlist_position": 1,
                },
                {
                    "video_id": "old",
                    "title": "old",
                    "url": "https://youtube.test/old",
                    "published_at": "2024-01-02T00:00:00+00:00",
                    "playlist_position": 2,
                },
            ],
        )
        rows = next_pending_videos(conn, 1)

    assert rows[0]["video_id"] == "old"

