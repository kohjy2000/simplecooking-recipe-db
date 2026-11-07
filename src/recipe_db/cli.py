from __future__ import annotations

import argparse
import json

from .db import connect, initialize
from .exporter import export_all
from .pipeline import discover, process_pending

DEFAULT_CHANNEL = "https://www.youtube.com/@자취요리신simplecooking"
DEFAULT_DB = "data/recipes.sqlite"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YouTube recipe database builder")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create or migrate the database")
    init_parser.set_defaults(handler=_init)

    discover_parser = subparsers.add_parser("discover", help="Discover channel videos")
    discover_parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    discover_parser.set_defaults(handler=_discover)

    ingest_parser = subparsers.add_parser("ingest", help="Discover and process pending videos")
    ingest_parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    ingest_parser.add_argument("--max-new", type=int, default=10)
    ingest_parser.add_argument("--skip-discovery", action="store_true")
    ingest_parser.add_argument("--export-dir", default="exports")
    ingest_parser.set_defaults(handler=_ingest)

    export_parser = subparsers.add_parser("export", help="Export JSON and CSV")
    export_parser.add_argument("--output-dir", default="exports")
    export_parser.set_defaults(handler=_export)

    status_parser = subparsers.add_parser("status", help="Show ingestion status")
    status_parser.set_defaults(handler=_status)
    return parser


def _init(args: argparse.Namespace) -> None:
    with connect(args.db) as conn:
        initialize(conn)
    print(f"Initialized {args.db}")


def _discover(args: argparse.Namespace) -> None:
    with connect(args.db) as conn:
        initialize(conn)
        count = discover(conn, args.channel)
    print(json.dumps({"discovered_or_updated": count}, ensure_ascii=False))


def _ingest(args: argparse.Namespace) -> None:
    if args.max_new < 1:
        raise SystemExit("--max-new must be at least 1")
    with connect(args.db) as conn:
        initialize(conn)
        run_id = conn.execute(
            "INSERT INTO ingestion_runs (channel_url) VALUES (?)", (args.channel,)
        ).lastrowid
        conn.commit()
        discovered = 0
        try:
            if not args.skip_discovery:
                discovered = discover(conn, args.channel)
            stats = process_pending(conn, args.max_new)
            exported = export_all(conn, args.export_dir)
            conn.execute(
                """
                UPDATE ingestion_runs SET finished_at = CURRENT_TIMESTAMP,
                    discovered_count = ?, processed_count = ?, completed_count = ?,
                    failed_count = ? WHERE run_id = ?
                """,
                (discovered, stats["processed"], stats["completed"], stats["failed"], run_id),
            )
            conn.commit()
        except Exception as exc:
            conn.execute(
                "UPDATE ingestion_runs SET finished_at = CURRENT_TIMESTAMP, notes = ? WHERE run_id = ?",
                (str(exc)[-2000:], run_id),
            )
            conn.commit()
            raise
    print(
        json.dumps(
            {"discovered_or_updated": discovered, **stats, "exported": exported},
            ensure_ascii=False,
        )
    )


def _export(args: argparse.Namespace) -> None:
    with connect(args.db) as conn:
        initialize(conn)
        count = export_all(conn, args.output_dir)
    print(json.dumps({"exported": count}, ensure_ascii=False))


def _status(args: argparse.Namespace) -> None:
    with connect(args.db) as conn:
        initialize(conn)
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM videos GROUP BY status ORDER BY status"
        ).fetchall()
        review = conn.execute("SELECT COUNT(*) FROM recipes WHERE needs_review = 1").fetchone()[0]
        recipes = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    print(
        json.dumps(
            {
                "videos": {row["status"]: row["count"] for row in rows},
                "recipes": recipes,
                "needs_review": review,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    args = _parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()

