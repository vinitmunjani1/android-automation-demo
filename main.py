from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from logger import ActionLogger
from mock_driver import Contact, MockDriver
from scheduler import random_time_in_window, sleep_until


ROOT = Path(__file__).resolve().parent


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    required = [
        "time_window", "feed_scroll_min", "feed_scroll_max", "like_probability",
        "connect_probability", "profile_view_min_seconds", "profile_view_max_seconds",
        "delay_min_seconds", "delay_max_seconds",
    ]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing config keys: {', '.join(missing)}")
    return config


def load_contacts(path: Path, max_contacts: int | None = None) -> list[Contact]:
    seen: set[str] = set()
    contacts: list[Contact] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            name = (row.get("name") or "").strip()
            title = (row.get("title") or "").strip()
            company = (row.get("company") or "").strip()
            if not name:
                print(f"Skipping row {row_num}: missing name", file=sys.stderr)
                continue
            key = name.lower()
            if key in seen:
                print(f"Skipping duplicate contact: {name}", file=sys.stderr)
                continue
            seen.add(key)
            contacts.append(Contact(name=name, title=title, company=company))
            if max_contacts and len(contacts) >= max_contacts:
                break
    return contacts


def build_driver(mode: str, config: dict, logger: ActionLogger):
    if mode == "mock":
        return MockDriver(config, logger)
    if mode == "android":
        from android_driver import AndroidMockSiteDriver
        return AndroidMockSiteDriver(config, logger)
    raise ValueError(f"Unsupported mode: {mode}")


def run_once(mode: str, config: dict, contacts: list[Contact], logger: ActionLogger) -> None:
    driver = build_driver(mode, config, logger)
    try:
        driver.open_app()
        if config.get("action_order", "sequential") == "random" and hasattr(driver, "run_random_journey"):
            driver.run_random_journey(contacts)
        else:
            driver.scroll_feed()
            driver.search_and_visit_contacts(contacts)
        logger.log("run_complete", mode, "success", f"contacts={len(contacts)}")
    except KeyboardInterrupt:
        logger.log("run_interrupted", mode, "stopped", "KeyboardInterrupt")
        raise
    except Exception as exc:
        logger.log("run_failed", mode, "error", repr(exc))
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safe mock Android automation proof-of-concept")
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--contacts", default=str(ROOT / "contacts.csv"))
    parser.add_argument("--mode", choices=["mock", "android"], default=None)
    parser.add_argument("--now", action="store_true", help="Run immediately instead of waiting for random time window")
    parser.add_argument("--dry-run", action="store_true", help="Validate config/contacts only")
    parser.add_argument(
        "--log-file",
        default=None,
        help="Write runtime logs to this CSV file instead of the branch-specific default",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config))
    mode = args.mode or config.get("mode", "mock")
    max_contacts = int(config.get("max_contacts_per_run", 0)) or None
    contacts = load_contacts(Path(args.contacts), max_contacts=max_contacts)
    log_file = Path(args.log_file) if args.log_file else Path(
        config.get("log_file", ROOT / "logs" / "actions_linkedin_id_migration.csv")
    )
    logger = ActionLogger(log_file)

    logger.log("validate", "config", "success", f"mode={mode},log_file={log_file}")
    logger.log("validate", "contacts", "success", f"count={len(contacts)}")

    if args.dry_run:
        return 0

    if not args.now:
        window = config["time_window"]
        target = random_time_in_window(window["start"], window["end"])
        logger.log("scheduled", "run_once", "waiting", target.isoformat(timespec="seconds"))
        sleep_until(target)

    run_once(mode, config, contacts, logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
