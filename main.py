from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from candidate_discovery import CandidateDiscoveryService
from logger import ActionLogger
from mock_driver import Contact, MockDriver
from scheduler import random_time_in_window, sleep_until


ROOT = Path(__file__).resolve().parent


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    profile_path = Path(config.get("candidate_profile_file", path.parent / "candidate_profile.json"))
    if not profile_path.is_absolute():
        profile_path = path.parent / profile_path
    if profile_path.exists():
        with profile_path.open("r", encoding="utf-8") as f:
            profile = json.load(f)
        config["candidate_profile_file"] = str(profile_path)
        if profile.get("search_queries"):
            config.setdefault("candidate_discovery", {})["search_queries"] = profile["search_queries"]
            config.setdefault("candidate_discovery", {})["default_search_query"] = profile["search_queries"][0]
        if profile.get("candidate_scoring"):
            merged_scoring = {**config.get("candidate_scoring", {}), **profile["candidate_scoring"]}
            if "weights" in config.get("candidate_scoring", {}) or "weights" in profile["candidate_scoring"]:
                merged_scoring["weights"] = {
                    **config.get("candidate_scoring", {}).get("weights", {}),
                    **profile["candidate_scoring"].get("weights", {}),
                }
            config["candidate_scoring"] = merged_scoring
    discovery = config.setdefault("candidate_discovery", {})
    output_dir = Path(discovery.get("output_dir", path.parent / "output" / "candidate_discovery"))
    if not output_dir.is_absolute():
        output_dir = path.parent / output_dir
    discovery["output_dir"] = str(output_dir)
    required = [
        "time_window", "feed_scroll_min", "feed_scroll_max", "like_probability",
        "connect_probability", "profile_view_min_seconds", "profile_view_max_seconds",
        "delay_min_seconds", "delay_max_seconds",
    ]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing config keys: {', '.join(missing)}")
    return config


def load_legacy_csv_contacts(path: Path, max_contacts: int | None = None) -> list[Contact]:
    """Optional backwards-compatible CSV loader.

    Candidate/profile-finder runs use candidate_profile.json by default. This
    CSV path is only used when config enables allow_legacy_contacts_csv.
    """
    if not path.exists():
        return []
    seen: set[str] = set()
    contacts: list[Contact] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            title = (row.get("title") or "").strip()
            company = (row.get("company") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            contacts.append(Contact(name=name, title=title, company=company))
            if max_contacts and len(contacts) >= max_contacts:
                break
    return contacts


def load_candidate_profile_targets(config: dict, legacy_contacts: list[Contact] | None = None) -> list[Contact]:
    discovery = config.get("candidate_discovery", {})
    queries = discovery.get("search_queries") or []
    max_queries = int(discovery.get("max_search_queries_per_run", 0)) or None
    targets = [Contact(name=str(query), title="candidate profile finder", company="") for query in queries if str(query).strip()]
    if max_queries:
        targets = targets[:max_queries]
    if targets:
        return targets
    if config.get("allow_legacy_contacts_csv", False):
        return legacy_contacts or []
    raise ValueError("No candidate_profile.json search_queries configured; CSV contacts are disabled by default")


def build_driver(mode: str, config: dict, logger: ActionLogger):
    if mode == "mock":
        return MockDriver(config, logger)
    if mode == "android":
        from android_driver import AndroidMockSiteDriver
        return AndroidMockSiteDriver(config, logger)
    if mode == "linkedin-review":
        from linkedin_review_driver import LinkedInReviewAssistantDriver
        return LinkedInReviewAssistantDriver(config, logger)
    raise ValueError(f"Unsupported mode: {mode}")


def run_candidate_discovery(mode: str, config: dict, search_query: str, logger: ActionLogger, resume: bool = True) -> None:
    driver = build_driver(mode, config, logger)
    driver.open_app()
    output_dir = Path(config.get("candidate_discovery", {}).get("output_dir", ROOT / "output" / "candidate_discovery"))
    service = CandidateDiscoveryService(driver, config, logger, output_dir)
    run = service.run(search_query, resume=resume)
    status = "success" if run.candidates else "empty"
    logger.log("candidate_discovery_complete", search_query, status, f"run_id={run.run_id},candidates={len(run.candidates)}")


def run_candidate_profile_finder(mode: str, config: dict, targets: list[Contact], logger: ActionLogger) -> None:
    driver = build_driver(mode, config, logger)
    search_contacts = targets
    try:
        driver.open_app()
        driver.search_and_visit_contacts(search_contacts)
        logger.log("candidate_profile_finder_complete", mode, "success", f"queries={len(search_contacts)}")
    except KeyboardInterrupt:
        logger.log("candidate_profile_finder_interrupted", mode, "stopped", "KeyboardInterrupt")
        raise
    except Exception as exc:
        logger.log("candidate_profile_finder_failed", mode, "error", repr(exc))
        raise


def run_once(mode: str, config: dict, targets: list[Contact], logger: ActionLogger) -> None:
    driver = build_driver(mode, config, logger)
    try:
        driver.open_app()
        if config.get("action_order", "sequential") == "random" and hasattr(driver, "run_random_journey"):
            driver.run_random_journey(targets)
        else:
            driver.scroll_feed()
            driver.search_and_visit_contacts(targets)
        logger.log("run_complete", mode, "success", f"profile_targets={len(targets)}")
    except KeyboardInterrupt:
        logger.log("run_interrupted", mode, "stopped", "KeyboardInterrupt")
        raise
    except Exception as exc:
        logger.log("run_failed", mode, "error", repr(exc))
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Android automation proof-of-concept with mock mode and LinkedIn review-assistant scoring")
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--contacts", default=str(ROOT / "contacts.csv"), help="Legacy CSV input; disabled unless allow_legacy_contacts_csv=true")
    parser.add_argument("--mode", choices=["mock", "android", "linkedin-review"], default=None)
    parser.add_argument("--now", action="store_true", help="Run immediately instead of waiting for random time window")
    parser.add_argument("--dry-run", action="store_true", help="Validate config/contacts only")
    parser.add_argument("--discover-candidates", action="store_true", help="Run candidate discovery instead of the default contact/engagement journey")
    parser.add_argument("--search-query", default=None, help="Candidate discovery search query, e.g. 'founder SaaS'. If omitted, uses candidate_profile.json search_queries[0].")
    parser.add_argument("--no-resume", action="store_true", help="Start candidate discovery without merging the latest matching output")
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
    legacy_contacts = load_legacy_csv_contacts(Path(args.contacts), max_contacts=max_contacts) if config.get("allow_legacy_contacts_csv", False) else []
    profile_targets = load_candidate_profile_targets(config, legacy_contacts)
    log_file = Path(args.log_file) if args.log_file else Path(
        config.get("log_file", ROOT / "logs" / "actions_linkedin_id_migration.csv")
    )
    logger = ActionLogger(log_file)

    logger.log("validate", "config", "success", f"mode={mode},log_file={log_file}")
    logger.log("validate", "candidate_profile_queries", "success", f"count={len(profile_targets)}")
    if legacy_contacts:
        logger.log("validate", "legacy_csv_contacts", "loaded", f"count={len(legacy_contacts)}")

    if args.dry_run:
        return 0

    if not args.now:
        window = config["time_window"]
        target = random_time_in_window(window["start"], window["end"])
        logger.log("scheduled", "run_once", "waiting", target.isoformat(timespec="seconds"))
        sleep_until(target)

    if args.discover_candidates:
        search_query = args.search_query or config.get("candidate_discovery", {}).get("default_search_query")
        if not search_query:
            raise ValueError("Candidate discovery requires --search-query or candidate_discovery.default_search_query")
        run_candidate_discovery(mode, config, search_query, logger, resume=not args.no_resume)
    elif mode == "android" and config.get("candidate_discovery", {}).get("profile_finder_default", False):
        run_candidate_profile_finder(mode, config, profile_targets, logger)
    else:
        run_once(mode, config, profile_targets, logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
