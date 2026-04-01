from __future__ import annotations

import argparse
import json
import time

from app.services.reminder_dispatch_service import ReminderDispatchService


def run_once(*, limit: int = 100) -> dict[str, object]:
    service = ReminderDispatchService()
    return service.dispatch_due_occurrences(limit=limit)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch due reminder occurrences.")
    parser.add_argument("--once", action="store_true", help="scan due reminders once and exit")
    parser.add_argument("--limit", type=int, default=100, help="max occurrences to process per scan")
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=30,
        help="poll interval when running continuously",
    )
    args = parser.parse_args()

    if args.once:
        print(json.dumps(run_once(limit=args.limit), ensure_ascii=False))
        return

    while True:
        print(json.dumps(run_once(limit=args.limit), ensure_ascii=False))
        time.sleep(max(args.poll_seconds, 1))


if __name__ == "__main__":
    main()
