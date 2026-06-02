from __future__ import annotations

import re
import time
from typing import Iterable

from candidate_discovery import Candidate, CandidateExtractor, CandidateScorer, utc_now
from logger import ActionLogger


class LinkedInReviewAssistantDriver:
    """Human-in-the-loop scorer for the real LinkedIn Android app.

    This driver intentionally does not auto-connect or run an engagement loop.
    The user controls LinkedIn search/browsing; the assistant reads visible UI
    text, extracts likely candidate snippets, scores them, and persists JSON.
    """

    def __init__(self, config: dict, logger: ActionLogger) -> None:
        try:
            import uiautomator2 as u2  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Install optional dependency: pip install uiautomator2") from exc
        self.u2 = u2
        self.d = u2.connect()
        self.config = config
        self.logger = logger
        self.app_package = config.get("linkedin_app_package", "com.linkedin.android")
        self.extractor = CandidateExtractor(CandidateScorer(config))

    def open_app(self) -> None:
        self.d.app_start(self.app_package)
        self.logger.log("open_linkedin_app", self.app_package, "success", "review_assistant=true")
        self._pause("open_wait_seconds", default=2.5)

    def discover_candidates_for_query(self, search_query: str, state: dict) -> Iterable[Candidate]:
        """Score real candidates visible on the current LinkedIn screen.

        Usage expectation:
        1. Open/search LinkedIn manually, or let this method open the app.
        2. Navigate to a search-results or profile screen.
        3. Run discovery; it snapshots visible text and saves scored candidates.
        """
        settings = self.config.get("linkedin_review_assistant", {})
        scans = int(settings.get("visible_screen_scans", 1))
        pause_between_scans = float(settings.get("pause_between_scans_seconds", 1.5))
        max_candidates = int(settings.get("max_candidates_per_scan", 20))
        seen: set[str] = set(state.get("seen_candidate_keys", []))
        yielded = 0

        self.logger.log("linkedin_review_scan_start", search_query, "started", f"scans={scans}")
        for scan_index in range(1, scans + 1):
            text_blocks = self._visible_text_blocks()
            candidates = self._candidates_from_text_blocks(text_blocks, search_query, scan_index)
            for candidate in candidates:
                key = candidate.identity_key()
                if key in seen:
                    continue
                seen.add(key)
                yielded += 1
                candidate.additional_metadata.update(
                    {
                        "source": "real_linkedin_visible_screen",
                        "driver_mode": "linkedin_review",
                        "captured_at": utc_now(),
                        "manual_connect_required": True,
                    }
                )
                candidate.profile_url = candidate.profile_url if candidate.profile_url and not candidate.profile_url.startswith("mockin://") else None
                self.logger.log(
                    "linkedin_candidate_scored",
                    candidate.name or "visible_candidate",
                    "success",
                    f"score={candidate.score},recommendation={candidate.additional_metadata.get('recommendation')}",
                )
                yield candidate
                if yielded >= max_candidates:
                    state["seen_candidate_keys"] = sorted(seen)
                    state["last_scan_index"] = scan_index
                    return
            if scan_index < scans:
                time.sleep(pause_between_scans)

        if yielded == 0:
            self.logger.log("linkedin_review_scan_empty", search_query, "empty", "no_candidate_like_visible_text")
        state["seen_candidate_keys"] = sorted(seen)
        state["last_scan_index"] = scans

    def _visible_text_blocks(self) -> list[str]:
        blocks: list[str] = []
        try:
            for node in self.d(className="android.widget.TextView"):
                info = node.info or {}
                text = str(info.get("text") or info.get("contentDescription") or "").strip()
                if text and self._is_useful_text(text):
                    blocks.append(text)
        except Exception as exc:
            self.logger.log("linkedin_visible_text", "uiautomator_textviews", "failed", repr(exc))

        if not blocks:
            try:
                hierarchy = self.d.dump_hierarchy(compressed=True)
                blocks = self._extract_text_from_hierarchy(hierarchy)
            except Exception as exc:
                self.logger.log("linkedin_visible_text", "hierarchy", "failed", repr(exc))
        return self._dedupe_keep_order(blocks)

    def _candidates_from_text_blocks(self, blocks: list[str], search_query: str, scan_index: int) -> list[Candidate]:
        candidates: list[Candidate] = []
        if not blocks:
            return candidates

        joined = "\n".join(blocks)
        # Profile page or compact result card fallback: use a sliding window so
        # name/headline/company/location-like text near each other stays grouped.
        windows: list[str] = []
        for index in range(0, len(blocks), 3):
            window = "\n".join(blocks[index : index + 5])
            if self._looks_candidate_like(window):
                windows.append(window)
        if not windows and self._looks_candidate_like(joined):
            windows.append(joined)

        for sequence, window in enumerate(windows, start=1):
            candidate = self.extractor.from_visible_text(
                window,
                search_query,
                f"linkedin_visible_screen_scan_{scan_index}",
                sequence,
            )
            if candidate:
                candidate.profile_url = None
                candidate.additional_metadata["raw_visible_text"] = window[:500]
                candidates.append(candidate)
        return candidates

    def _looks_candidate_like(self, text: str) -> bool:
        lowered = text.lower()
        reject_terms = ["home", "jobs", "notifications", "messaging", "premium", "advertisement", "promoted"]
        if any(term == lowered.strip() for term in reject_terms):
            return False
        profile_signals = ["1st", "2nd", "3rd", "connect", "follow", "message", " at ", "followers", "connections"]
        preference_terms = []
        scoring = self.config.get("candidate_scoring", {})
        for key in ("title_keywords", "company_keywords", "location_keywords", "positive_keywords"):
            preference_terms.extend(str(value).lower() for value in scoring.get(key, []))
        return any(signal in lowered for signal in profile_signals + preference_terms)

    def _is_useful_text(self, text: str) -> bool:
        cleaned = text.strip()
        if len(cleaned) < 2 or len(cleaned) > 220:
            return False
        noise = {"home", "my network", "post", "notifications", "jobs", "messaging", "search"}
        return cleaned.lower() not in noise

    def _extract_text_from_hierarchy(self, hierarchy: str) -> list[str]:
        values = re.findall(r'text="([^"]+)"|content-desc="([^"]+)"', hierarchy)
        return [self._xml_unescape(a or b) for a, b in values if self._is_useful_text(self._xml_unescape(a or b))]

    def _xml_unescape(self, value: str) -> str:
        return (
            value.replace("&amp;", "&")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .strip()
        )

    def _dedupe_keep_order(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            key = value.strip().lower()
            if key and key not in seen:
                seen.add(key)
                result.append(value.strip())
        return result

    def _pause(self, key: str, default: float) -> None:
        value = float(self.config.get("linkedin_review_assistant", {}).get(key, default))
        time.sleep(value)
