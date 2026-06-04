from __future__ import annotations

import hashlib
import random
import re
import shlex
import time
from pathlib import Path
from typing import Iterable

from candidate_discovery import (
    Candidate,
    CandidateDeduplicator,
    CandidateExtractor,
    CandidatePersistenceService,
    CandidateScorer,
    DiscoveryRun,
    human_dwell,
    utc_now,
)
from logger import ActionLogger
from mock_driver import Contact


class AndroidMockSiteDriver:
    """Optional Android UI driver for mock targets only.

    Supports two safe test targets:
    - android_target=web: opens the included mock site in the Android browser.
    - android_target=app: launches the included native MockIn app.

    The target app/site is a controlled test harness. Do not repoint this at real
    social platforms.
    """

    def __init__(self, config: dict, logger: ActionLogger) -> None:
        try:
            import uiautomator2 as u2  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Install optional dependency: pip install uiautomator2") from exc
        self.u2 = u2
        self.d = u2.connect()
        self.config = config
        self.human = config.get("humanization", {})
        self.target = config.get("android_target", "web")
        self.app_package = config.get("android_app_package", config.get("mock_app_package", "com.mockin.app"))
        self.logger = logger
        self.candidate_extractor = CandidateExtractor(CandidateScorer(config))
        self._candidate_deduplicator = CandidateDeduplicator()
        self._profile_flow_run: DiscoveryRun | None = None
        self._profile_flow_run_path: Path | None = None
        self._candidate_persistence: CandidatePersistenceService | None = None
        self._last_page_signature = ""
        self._same_page_count = 0
        self._stuck_recovery_count = 0
        self._feed_likes_this_run = 0
        self._last_feed_like_at = 0.0
        self._liked_feed_post_signatures: set[str] = set()

    def delay(self, multiplier: float = 1.0) -> None:
        lo = float(self.config["delay_min_seconds"])
        hi = float(self.config["delay_max_seconds"])
        jitter = random.uniform(0.85, 1.35)
        time.sleep(random.uniform(lo, hi) * multiplier * jitter)

    def think(self, min_seconds: float = 0.8, max_seconds: float = 2.4) -> None:
        time.sleep(random.uniform(min_seconds, max_seconds))

    def action_transition_pause(self) -> None:
        settings = self.config.get("action_transition", {})
        lo = float(settings.get("min_seconds", 0.05))
        hi = float(settings.get("max_seconds", 0.20))
        time.sleep(random.uniform(lo, hi))

    def rid(self, name: str) -> str:
        return f"{self.app_package}:id/{name}"

    def open_app(self) -> None:
        if self.target == "app":
            self.d.app_start(self.app_package)
            self.logger.log("open_mock_native_app", self.app_package)
        else:
            url = self.config.get("mock_site_url", "http://127.0.0.1:8000")
            self.d.shell(f'am start -a android.intent.action.VIEW -d "{url}"')
            self.logger.log("open_android_browser", url)
        self.think(2.2, 4.2)
        self._initial_orientation()

    def scroll_feed(self) -> None:
        count = random.randint(int(self.config["feed_scroll_min"]), int(self.config["feed_scroll_max"]))
        self.logger.log("feed_session_start", "mock_feed", "success", f"scrolls={count},target={self.target}")
        for i in range(1, count + 1):
            self._scroll_feed_once(i)
        self.logger.log("feed_session_end", "mock_feed")

    def search_and_visit_contacts(self, contacts: Iterable[Contact]) -> None:
        for contact in contacts:
            self._guard_bottom_menu_before_step(f"search_{contact.name}")
            self._go_home()
            self.think(0.7, 1.8)
            if not self._focus_search_box():
                self.logger.log("search_person", contact.name, "failed", "search input missing")
                continue
            self.think(0.2, 0.8)
            if not self._type_text_human(contact.name):
                self.logger.log("search_person", contact.name, "failed", "typing_not_verified")
                self._leave_search_page(contact.name)
                continue
            self.logger.log("search_person", contact.name, "success", "typed_humanized=true,verified=true")
            self.think(1.2, 3.0)
            self._open_all_search_results(contact.name)
            self._apply_candidate_search_filters(contact.name)
            if self._collect_search_results_instead_of_opening():
                collected = self._collect_and_score_visible_search_results(contact.name)
                if collected == 0 and self._retry_search_with_profile_filter_only(contact.name):
                    collected = self._collect_and_score_visible_search_results(contact.name)
                    self.logger.log("candidate_results_profile_only_retry", contact.name, "success" if collected else "empty", f"candidates={collected}")
                self.logger.log("candidate_results_ranked", contact.name, "success" if collected else "empty", f"candidates={collected}")
                if collected == 0:
                    self._leave_search_page(contact.name)
                self.action_transition_pause()
                continue

            if not self._click_contact(contact.name):
                if self._retry_search_with_profile_filter_only(contact.name) and self._click_contact(contact.name):
                    self.logger.log("open_profile", contact.name, "fallback_success", "profile_filter_only")
                else:
                    self.logger.log("open_profile", contact.name, "not_found")
                    self._leave_search_page(contact.name)
                    continue
            self.logger.log("open_profile", contact.name, "success", f"{contact.title} at {contact.company}")
            self._analyze_open_profile(contact.name)
            scored_candidate = self._score_open_profile_candidate(contact.name)
            self._return_profile_to_top(contact.name)

            min_view = float(self.config["profile_view_min_seconds"])
            max_view = float(self.config["profile_view_max_seconds"])
            time.sleep(random.uniform(min_view, max_view) + random.uniform(0.8, 2.8))

            if self._maybe_connect_scored_profile(scored_candidate, contact.name):
                self.action_transition_pause()
                continue
            if scored_candidate is not None:
                self.action_transition_pause()
                continue

            if self._manual_connect_required_when_scoring():
                self.logger.log("connect", contact.name, "manual_required", "candidate_scoring_enabled")
                self.action_transition_pause()
                continue

            if random.random() < float(self.config["connect_probability"]):
                self.think(0.5, 1.8)
                if self._click_connect_button():
                    self.logger.log("connect", contact.name, "clicked", "button")
                else:
                    self.logger.log("connect", contact.name, "not_found")
            else:
                self.logger.log("connect", contact.name, "skipped", "random decision")
            self.action_transition_pause()

    def discover_candidates_for_query(self, search_query: str, state: dict) -> Iterable[Candidate]:
        """Discover visible mock candidates while reusing existing UI behavior.

        This stays inside the controlled MockIn/mock-site harness. It mimics a
        recruiter reviewing search results: search, pause on visible cards,
        extract visible details, scroll progressively, and stop on no progress.
        """
        self._go_home()
        self.think(0.7, 1.8)
        if not self._focus_search_box():
            self.logger.log("candidate_search", search_query, "failed", "search input missing")
            return []

        if not self._type_text_human(search_query):
            self.logger.log("candidate_search", search_query, "failed", "typing_not_verified")
            self._leave_search_page(search_query)
            return []
        self.logger.log("candidate_search", search_query, "success", "typed_humanized=true,verified=true")
        self.think(1.2, 2.8)

        self._open_all_search_results(search_query)
        self._apply_candidate_search_filters(search_query)
        self._wait_for_profile_results(search_query)

        discovery_config = self.config.get("candidate_discovery", {})
        max_candidates = int(discovery_config.get("max_candidates_per_query", 25))
        max_scrolls = int(discovery_config.get("max_scrolls_per_query", 8))
        no_progress_limit = int(discovery_config.get("no_progress_scroll_limit", 2))
        seen_keys: set[str] = set(state.get("seen_candidate_keys", []))
        no_progress = 0
        yielded = 0

        for page_index in range(1, max_scrolls + 1):
            page_candidates = self._extract_visible_candidate_cards(search_query, page_index)
            new_on_page = 0
            for candidate in page_candidates:
                key = candidate.identity_key()
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                new_on_page += 1
                yielded += 1
                human_dwell(self.config)
                self.logger.log("candidate_card_detected", candidate.name or "unknown", "success", f"score={candidate.score},page={page_index}")
                yield candidate
                if yielded >= max_candidates:
                    state["seen_candidate_keys"] = sorted(seen_keys)
                    state["last_source_page"] = page_index
                    return

            if new_on_page == 0:
                no_progress += 1
                self.logger.log("candidate_discovery_progress", search_query, "no_change", f"page={page_index},streak={no_progress}")
            else:
                no_progress = 0

            if no_progress >= no_progress_limit:
                break
            before = self._page_signature() if self.target == "app" else self._visible_hierarchy()
            self._scroll_content_down()
            self.think(0.8, 2.0)
            after = self._page_signature() if self.target == "app" else self._visible_hierarchy()
            if before == after:
                no_progress += 1

        if yielded == 0:
            self.logger.log("candidate_search_empty", search_query, "empty", "no_visible_candidates")
        state["seen_candidate_keys"] = sorted(seen_keys)
        state["last_source_page"] = page_index if 'page_index' in locals() else 0
        return []

    def _extract_visible_candidate_cards(self, search_query: str, page_index: int) -> list[Candidate]:
        candidates: list[Candidate] = []
        if self.target == "app":
            selectors = [
                self.d(resourceId=self.rid("person_result")),
                self.d(resourceId=self.rid("network_person_card")),
                self.d(descriptionContains="Person result"),
                self.d(descriptionContains="Network suggestion"),
            ]
            sequence = 0
            for selector in selectors:
                try:
                    if not selector.exists(timeout=0.2):
                        continue
                    try:
                        nodes = list(selector) or [selector]
                    except Exception:
                        nodes = [selector]
                    for node in nodes:
                        sequence += 1
                        info = node.info or {}
                        text = "\n".join(str(info.get(key) or "") for key in ("text", "contentDescription"))
                        if not text.strip():
                            continue
                        candidate = self.candidate_extractor.from_visible_text(text, search_query, f"mock_app_search_page_{page_index}", sequence)
                        if candidate:
                            candidate.additional_metadata.update({"driver_mode": "android", "target": self.target})
                            candidates.append(candidate)
                except Exception as exc:
                    self.logger.log("candidate_extract_card", search_query, "failed", repr(exc))

        if not candidates:
            xml = self._visible_hierarchy()
            # Fallback for UIAutomator variants: extract candidates from visible
            # content descriptions generated by the mock app/site.
            markers = []
            for marker in ("Person result ", "Open profile ", "Network suggestion "):
                start = 0
                while True:
                    idx = xml.find(marker, start)
                    if idx == -1:
                        break
                    fragment = xml[idx: idx + 220]
                    fragment = fragment.replace("&amp;", "&").replace("&quot;", '"')
                    markers.append(fragment)
                    start = idx + len(marker)
            for sequence, fragment in enumerate(markers, start=1):
                candidate = self.candidate_extractor.from_visible_text(fragment, search_query, f"visible_hierarchy_page_{page_index}", sequence)
                if candidate:
                    candidate.additional_metadata.update({"driver_mode": "android", "target": self.target, "extractor": "hierarchy_fallback"})
                    candidates.append(candidate)
        return candidates

    def run_random_journey(self, contacts: list[Contact]) -> None:
        """Run a randomized, bounded journey.

        For real LinkedIn package runs, keep the action mix limited to profile
        finder/search, home, and pauses. Mock-only engagement actions remain
        available for the controlled MockIn harness.
        """
        settings = self.config.get("random_journey", {})
        min_actions = int(settings.get("min_actions", 8))
        max_actions = int(settings.get("max_actions", 18))
        action_count = random.randint(min_actions, max_actions)
        remaining_contacts = contacts[:]
        random.shuffle(remaining_contacts)
        self.logger.log("random_journey_start", self.target, "success", f"actions={action_count}")

        if self.target == "app" and self.config.get("check_notifications_on_start", True):
            if self._has_new_notifications_indicator():
                self._check_notifications()
            else:
                self.logger.log("notifications_start_check", self.target, "skipped", "no_unread_indicator")

        self._record_page_progress("journey_start", recover=False)

        last_action = ""
        repeated = 0
        for step in range(1, action_count + 1):
            self._guard_bottom_menu_before_step(f"step_{step}_pre_action")
            choices = ["pause", "home"]
            real_linkedin = self.app_package == self.config.get("linkedin_app_package", "com.linkedin.android")
            if remaining_contacts:
                choices.extend(["profile_finder", "profile_finder", "profile_finder"])
            if not real_linkedin:
                choices.extend(["feed", "feed"])
                if self.target == "app":
                    choices.extend(["notifications", "network", "messages", "repost"])
            elif self.config.get("allow_real_linkedin_feed_review", True):
                choices.extend(["feed", "feed"])
            action = random.choice(choices)

            # Avoid comically long same-action streaks while keeping the order varied.
            if action == last_action:
                repeated += 1
                if repeated >= 3:
                    action = random.choice([c for c in choices if c != last_action])
                    repeated = 0
            else:
                repeated = 0
            last_action = action

            self.logger.log("random_action", f"step_{step}", "selected", action)
            if action == "feed":
                for _ in range(random.randint(1, int(settings.get("max_feed_scrolls_per_action", 3)))):
                    self._scroll_feed_once(step)
            elif action in {"search", "profile_finder"} and remaining_contacts:
                self._visit_contact(remaining_contacts.pop(0))
            elif action == "home":
                home_ok = self._go_home()
                self.logger.log("home", self.target, "success" if home_ok else "not_confirmed", "random navigation")
                self.action_transition_pause()
            elif action == "notifications":
                self._check_notifications()
            elif action == "network":
                self._browse_network_and_connect()
            elif action == "messages":
                self._open_messages_and_reply()
            elif action == "repost":
                self._try_repost_visible_post()
            else:
                self.logger.log("idle_pause", self.target, "success", "random reading/thinking pause")
                self.think(
                    float(settings.get("idle_min_seconds", 1.2)),
                    float(settings.get("idle_max_seconds", 4.5)),
                )

            self._record_page_progress(f"step_{step}_{action}")

        self.logger.log("random_journey_end", self.target, "success", f"remaining_contacts={len(remaining_contacts)}")

    def _record_page_progress(self, label: str, recover: bool = True) -> None:
        """Detect repeated no-progress screen states and recover safely."""
        if self.target != "app" or not self.config.get("stuck_page_watchdog_enabled", True):
            return

        signature = self._page_signature()
        if not signature:
            return

        current_page = signature.split(":", 1)[0]
        self.logger.log("current_page", label, "observed", f"page={current_page},signature={signature}")

        if signature == self._last_page_signature:
            self._same_page_count += 1
        else:
            self._last_page_signature = signature
            self._same_page_count = 0
            return

        threshold = int(self.config.get("stuck_page_same_signature_threshold", 2))
        self.logger.log(
            "page_progress",
            label,
            "same_page",
            f"same_count={self._same_page_count},signature={signature}",
        )
        if recover and self._same_page_count >= threshold:
            self.logger.log(
                "stuck_page_detected",
                label,
                "recovering",
                f"same_count={self._same_page_count},signature={signature}",
            )
            self._recover_from_stuck_page(label)
            self._last_page_signature = self._page_signature()
            self._same_page_count = 0

    def _page_signature(self) -> str:
        """Return a compact fingerprint of the currently visible app screen."""
        try:
            page = self._current_mock_page_name()
            xml = self._visible_hierarchy()
            # Strip volatile size by hashing the visible hierarchy; include page
            # name so logs remain readable.
            digest = hashlib.sha1(xml.encode("utf-8", errors="ignore")).hexdigest()[:12]
            return f"{page}:{digest}"
        except Exception as exc:
            self.logger.log("page_signature", self.target, "failed", repr(exc))
            return ""

    def _visible_hierarchy(self) -> str:
        try:
            return self.d.dump_hierarchy(compressed=True) or ""
        except Exception:
            return ""

    def _current_mock_page_name(self) -> str:
        """Classify the current visible screen from resource IDs/text.

        UIAutomator selectors can return false negatives when the bottom nav is
        hidden or the app is mid-transition. The hierarchy string is more useful
        for deciding where the bot actually is before taking an action.
        """
        if self.target == "app" and self._is_real_linkedin_app():
            return self._current_real_linkedin_page_name()

        xml = self._visible_hierarchy()
        low = xml.lower()
        rid = self.rid

        # Strong resource-id / unique-text matches first. Avoid generic words
        # like Connect/Follow by themselves because they can appear on multiple
        # screens.
        strong_checks = [
            ("profile", [rid("profile_page"), "profile page"]),
            ("notifications", [rid("notifications_page"), "mock connection requests", "review request profiles", rid("connection_request")]),
            ("network", [rid("network_page"), "my network", "people you may know", rid("network_person_card"), "network suggestion"]),
            ("messages", [rid("messages_page"), rid("conversation_item"), "conversation with"]),
            ("search_results", [rid("results_list"), rid("person_result"), "show all results", "see all results"]),
            ("home_feed", [rid("feed_list"), "start a professional update"]),
        ]
        for name, needles in strong_checks:
            if any(str(needle).lower() in low for needle in needles):
                return name

        # Weaker composite checks. These require multiple hints.
        if ("follow" in low or "connect" in low) and ("about" in low or "activity" in low or "experience" in low):
            return "profile"
        if rid("post_card").lower() in low or rid("like_button").lower() in low:
            return "home_feed"
        if "messages" in low and ("focused" in low or "conversation" in low):
            return "messages"

        # Selector fallback for cases where hierarchy is unexpectedly sparse.
        selector_checks = [
            ("profile", lambda: self.d(resourceId=rid("profile_page")).exists(timeout=0.1)),
            ("notifications", lambda: self._is_notifications_page_open(timeout=0.1)),
            ("network", lambda: self._is_network_page_open(timeout=0.1)),
            ("messages", lambda: self._is_messages_page_open(timeout=0.1)),
            ("search_results", lambda: self.d(resourceId=rid("results_list")).exists(timeout=0.1)),
            ("home_feed", lambda: self.d(resourceId=rid("feed_list")).exists(timeout=0.1)),
        ]
        for name, check in selector_checks:
            try:
                if check():
                    return name
            except Exception:
                pass
        return "unknown"

    def _current_real_linkedin_page_name(self) -> str:
        """Classify real LinkedIn screens without treating bottom-nav labels as pages."""
        xml = self._visible_hierarchy()
        low = xml.lower()

        # Home can contain "Recommended for you" profile cards with Connect/
        # Follow/1st/2nd text. Treat active Home as Home before any generic
        # people/result-row heuristics, otherwise recommendations are mistaken
        # for search results.
        if self._is_real_home_context(low):
            return "home_feed"

        if self._has_results_or_typeahead_signal(low):
            return "search_results"

        # Profile pages have both profile actions and sections. Avoid generic
        # bottom-nav/profile labels, which can appear on Home.
        if self._has_real_profile_signal(low):
            return "profile"

        if any(term in low for term in ("people you may know", "manage my network", "invitations", "grow your network")):
            return "network"
        if any(term in low for term in ("search messages", "conversations", "new message")):
            return "messages"
        if any(term in low for term in ("notification", "notifications")) and any(term in low for term in ("reacted", "viewed", "mentioned", "posted")):
            return "notifications"
        return "unknown"

    def _is_real_home_context(self, low_xml: str | None = None) -> bool:
        low = low_xml if low_xml is not None else self._visible_hierarchy().lower()
        explicit_home_terms = (
            "start a post",
            "start a professional update",
            "share your thoughts",
            "what do you want to talk about",
        )
        if any(term in low for term in explicit_home_terms):
            return True
        non_home_terms = (
            "show all results", "see all results", "all filters", "connection degree",
            "people you may know", "manage my network", "invitations", "grow your network",
            "search messages", "conversations", "notification", "notifications",
        )
        if "recommended for you" in low and not any(term in low for term in non_home_terms):
            return True
        return self._is_real_home_tab_selected() and not any(term in low for term in non_home_terms)

    def _is_home_feed_ready(self) -> bool:
        if self.target != "app":
            return True
        if self._is_real_linkedin_app():
            return self._is_real_home_context()
        return self._current_mock_page_name() == "home_feed"

    def _is_real_home_tab_selected(self) -> bool:
        try:
            width, height = self.d.window_size()
            for selector in [self.d(descriptionContains="Home"), self.d(text="Home"), self.d(textContains="Home")]:
                try:
                    if not selector.exists(timeout=0.1):
                        continue
                    info = selector.info or {}
                    bounds = info.get("bounds") or {}
                    top = int(bounds.get("top", 0))
                    bottom = int(bounds.get("bottom", 0))
                    left = int(bounds.get("left", 0))
                    right = int(bounds.get("right", 0))
                    center_y = (top + bottom) // 2 if bottom > top else 0
                    center_x = (left + right) // 2 if right > left else 0
                    if center_y < int(height * 0.82) or center_x > int(width * 0.28):
                        continue
                    label = " ".join(str(info.get(key) or "") for key in ("text", "contentDescription")).lower()
                    if info.get("selected") or info.get("checked") or any(term in label for term in ("selected", "active", "current")):
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    def _has_results_or_typeahead_signal(self, low_xml: str | None = None) -> bool:
        low = low_xml if low_xml is not None else self._visible_hierarchy().lower()
        if self._is_real_linkedin_app() and self._is_real_home_context(low):
            return False
        if any(term in low for term in ("show all results", "see all results", "search results", "people results")):
            return True
        if any(self.rid(name).lower() in low for name in ("results_list", "person_result")):
            return True
        has_filter_context = any(term in low for term in ("all filters", "connection degree", "people"))
        has_connection_chip = any(term in low for term in ("1st", "2nd", "3rd"))
        has_row_action = any(term in low for term in ("connect", "follow", "message"))
        if has_filter_context and has_connection_chip and has_row_action:
            return True
        return False

    def _has_real_profile_signal(self, low_xml: str | None = None) -> bool:
        low = low_xml if low_xml is not None else self._visible_hierarchy().lower()
        action_terms = ("connect", "follow", "message", "more")
        section_terms = ("about", "activity", "experience", "education", "contact info", "open to", "featured", "posts")
        headline_terms = ("followers", "connections", "mutual", "top voice", "creator mode")
        has_action = any(term in low for term in action_terms)
        has_section = any(term in low for term in section_terms)
        has_headline = any(term in low for term in headline_terms)
        strong_profile = (has_action and (has_section or has_headline)) or (has_section and has_headline)
        if strong_profile:
            return True
        if any(noise in low for noise in ("show all results", "see all results", self.rid("results_list").lower())):
            return False
        return False

    def _is_bottom_menu_visible(self) -> bool:
        if self.target != "app":
            return True
        try:
            xml = self._visible_hierarchy().lower()
            bottom_markers = [
                self.rid("home_button").lower(),
                self.rid("home_tab").lower(),
                self.rid("network_tab").lower(),
                self.rid("messages_button").lower(),
                self.rid("messages_tab").lower(),
                self.rid("notifications_button").lower(),
                self.rid("notifications_tab").lower(),
            ]
            if any(marker in xml for marker in bottom_markers):
                return True
            width, height = self.d.window_size()
            bottom_cutoff = int(height * 0.82)
            for selector in [
                self.d(descriptionContains="Home"),
                self.d(descriptionContains="My Network"),
                self.d(descriptionContains="Network"),
                self.d(descriptionContains="Messaging"),
                self.d(descriptionContains="Notifications"),
                self.d(textContains="Home"),
                self.d(textContains="My Network"),
                self.d(textContains="Messaging"),
                self.d(textContains="Notifications"),
            ]:
                try:
                    if not selector.exists(timeout=0.1):
                        continue
                    bounds = selector.info.get("bounds") or {}
                    bottom = int(bounds.get("bottom", 0))
                    top = int(bounds.get("top", 0))
                    if bottom >= bottom_cutoff or top >= bottom_cutoff:
                        return True
                except Exception:
                    pass
        except Exception:
            return False
        return False

    def _guard_bottom_menu_before_step(self, label: str) -> None:
        settings = self.config.get("bottom_menu_guard", {})
        if self.target != "app" or not settings.get("enabled", True):
            return
        if self._is_bottom_menu_visible():
            return
        max_backs = int(settings.get("max_back_presses", 2))
        self.logger.log("bottom_menu_guard", label, "missing", f"back_presses={max_backs},safe_reveal_first=true")

        # First try non-destructive recovery. On real LinkedIn, pressing Back on
        # Home closes the app, so reveal/tap Home before considering Back.
        for attempt in range(1, 3):
            self._reveal_bottom_nav()
            if self._is_bottom_menu_visible():
                self.logger.log("bottom_menu_guard", label, "recovered", f"method=reveal,attempt={attempt}")
                return
            if self._tap_home_tab():
                self.think(0.4, 0.9)
                if self._is_bottom_menu_visible() or self._current_mock_page_name() == "home_feed":
                    self.logger.log("bottom_menu_guard", label, "recovered", f"method=home_tab,attempt={attempt}")
                    return

        current = self._current_mock_page_name()
        if self._is_real_linkedin_app():
            self.logger.log("bottom_menu_guard", label, "still_missing", f"no_back_on_real_linkedin,current={current}")
            return
        if current in {"home_feed", "network", "messages", "notifications", "unknown"}:
            self.logger.log("bottom_menu_guard", label, "still_missing", f"no_back_on_root_like_page,current={current}")
            return

        for attempt in range(1, max_backs + 1):
            try:
                self.d.press("back")
                self.think(
                    float(settings.get("wait_min_seconds", 0.5)),
                    float(settings.get("wait_max_seconds", 1.1)),
                )
                if self._is_bottom_menu_visible():
                    self.logger.log("bottom_menu_guard", label, "recovered", f"attempt={attempt}")
                    return
            except Exception as exc:
                self.logger.log("bottom_menu_guard", label, "failed", repr(exc))
                return
        self.logger.log("bottom_menu_guard", label, "still_missing", f"continuing_without_extra_back,current={current}")

    def _ensure_current_page(self, expected: str, label: str) -> bool:
        current = self._current_mock_page_name()
        if current == expected:
            return True
        self.logger.log("current_page_guard", label, "blocked", f"expected={expected},actual={current}")
        self._recover_from_stuck_page(label)
        return False

    def _recover_from_stuck_page(self, label: str) -> None:
        """Escape a stuck UI state without closing the app from Home."""
        self._stuck_recovery_count += 1
        try:
            current = self._current_mock_page_name()
            if self._is_real_linkedin_app():
                self._go_home()
                method = "home_tab_no_back"
            elif current in {"home_feed", "network", "messages", "notifications", "unknown"}:
                self._go_home()
                method = "home_tab"
            else:
                self.d.press("back")
                self.think(0.6, 1.2)
                method = "back"
            self.logger.log(
                "stuck_page_recovery",
                label,
                "success",
                f"method={method},from={current},total_recoveries={self._stuck_recovery_count}",
            )
        except Exception as exc:
            self.logger.log("stuck_page_recovery", label, "failed", repr(exc))

    def _initial_orientation(self) -> None:
        """First-open orientation for the mock app/site: pause, scan, tiny scroll."""
        self.logger.log("orientation_start", self.target, "success", "first_open_scan")
        self.think(
            float(self.config.get("orientation_min_seconds", 2.0)),
            float(self.config.get("orientation_max_seconds", 5.0)),
        )
        if random.random() < 0.85:
            self._human_swipe(direction="up")
            self.logger.log("orientation_scroll", self.target, "success", "tiny_initial_scan")
            self.think(0.8, 2.2)
        if random.random() < 0.35:
            self._human_swipe(direction="down")
            self.logger.log("orientation_correction", self.target, "success", "small_reverse_scan")
        self.logger.log("orientation_end", self.target, "success", "ready_for_next_action")

    def _visit_contact(self, contact: Contact) -> None:
        self._guard_bottom_menu_before_step(f"profile_finder_{contact.name}")
        self._go_home()
        self.think(0.7, 1.8)
        if not self._focus_search_box():
            self.logger.log("search_person", contact.name, "failed", "search input missing")
            return
        self.think(0.2, 0.8)
        if not self._type_text_human(contact.name):
            self.logger.log("search_person", contact.name, "failed", "typing_not_verified")
            self._leave_search_page(contact.name)
            return
        self.logger.log("search_person", contact.name, "success", "typed_humanized=true,verified=true")
        # Do not press Back here. On some Android devices the keyboard is not
        # considered open after adb text input, so Back closes the mock app.
        self.think(1.2, 3.0)
        self._open_all_search_results(contact.name)
        self._apply_candidate_search_filters(contact.name)
        if self._collect_search_results_instead_of_opening():
            collected = self._collect_and_score_visible_search_results(contact.name)
            if collected == 0 and self._retry_search_with_profile_filter_only(contact.name):
                collected = self._collect_and_score_visible_search_results(contact.name)
                self.logger.log("candidate_results_profile_only_retry", contact.name, "success" if collected else "empty", f"candidates={collected}")
            self.logger.log("candidate_results_ranked", contact.name, "success" if collected else "empty", f"candidates={collected}")
            if collected == 0:
                self._leave_search_page(contact.name)
            self.action_transition_pause()
            return

        if not self._click_contact(contact.name):
            if self._retry_search_with_profile_filter_only(contact.name) and self._click_contact(contact.name):
                self.logger.log("open_profile", contact.name, "fallback_success", "profile_filter_only")
            else:
                self.logger.log("open_profile", contact.name, "not_found")
                self._leave_search_page(contact.name)
                return
        self.logger.log("open_profile", contact.name, "success", f"{contact.title} at {contact.company}")
        self._analyze_open_profile(contact.name)
        scored_candidate = self._score_open_profile_candidate(contact.name)
        self._return_profile_to_top(contact.name)

        min_view = float(self.config["profile_view_min_seconds"])
        max_view = float(self.config["profile_view_max_seconds"])
        time.sleep(random.uniform(min_view, max_view) + random.uniform(0.8, 2.8))

        if self._maybe_connect_scored_profile(scored_candidate, contact.name):
            self.action_transition_pause()
            return
        if scored_candidate is not None:
            self.action_transition_pause()
            return

        if self._manual_connect_required_when_scoring():
            self.logger.log("connect", contact.name, "manual_required", "candidate_scoring_enabled")
            self.action_transition_pause()
            return

        if random.random() < float(self.config["connect_probability"]):
            self.think(0.5, 1.8)
            if self._click_connect_button():
                self.logger.log("connect", contact.name, "clicked", "button")
            else:
                self.logger.log("connect", contact.name, "not_found")
        else:
            self.logger.log("connect", contact.name, "skipped", "random decision")
        self.action_transition_pause()

    def _scroll_feed_once(self, index: int) -> None:
        self._guard_bottom_menu_before_step(f"feed_{index}")
        if self.target == "app" and not self._is_home_feed_ready():
            self._go_home()
            self.think(0.6, 1.2)
            if not self._is_home_feed_ready():
                self.logger.log("current_page_guard", f"feed_{index}", "blocked", f"expected=home_feed,actual={self._current_mock_page_name()},home_ready={self._is_home_feed_ready()}")
                return

        self.think(
            float(self.human.get("feed_read_min_seconds", 1.8)),
            float(self.human.get("feed_read_max_seconds", 5.2)),
        )

        if self.target == "app":
            self.think(
                float(self.config.get("feed_like_after_scroll_min_seconds", 0.8)),
                float(self.config.get("feed_like_after_scroll_max_seconds", 2.4)),
            )
            self._maybe_like_visible_feed_post(index)

        if self.target == "app" and random.random() < float(self.config.get("feed_profile_open_probability", 0.18)):
            if self._open_profile_from_feed():
                self.logger.log("open_profile_from_feed", f"visible_post_{index}", "success", "random feed profile open")
                self._analyze_open_profile(f"feed_profile_{index}")
                self._go_home()
                self.action_transition_pause()
            else:
                self.logger.log("open_profile_from_feed", f"visible_post_{index}", "not_found", "no visible feed profile link")

        if self.target != "app" and random.random() < float(self.config["like_probability"]):
            self.think(0.5, 1.7)
            if self._click_like_button():
                self.logger.log("like_post", f"visible_post_{index}")
                self.think(0.3, 1.0)
            else:
                self.logger.log("like_post", f"visible_post_{index}", "not_found")

        before = self._page_signature() if self.target == "app" else ""
        self._scroll_content_down()
        after = self._page_signature() if self.target == "app" else ""
        if self.target != "app" or before != after:
            self.logger.log("scroll_feed", f"post_window_{index}", "success", "content_down_safe_scroll")
        else:
            self.logger.log("scroll_feed", f"post_window_{index}", "no_change", "page_signature_unchanged")
        if random.random() < 0.25:
            self.action_transition_pause()

    def _scroll_content_down(self) -> None:
        """Scroll page content downward without triggering pull-to-refresh.

        In Android gesture terms this is a finger swipe up. Keep the gesture
        away from the very top/status area and bottom nav so pages don't
        refresh or tap navigation while trying to read more content.
        """
        if self.target == "app":
            try:
                width, height = self.d.window_size()
                x = int(width * random.uniform(0.46, 0.56))
                start_y = int(height * random.uniform(0.76, 0.84))
                end_y = int(height * random.uniform(0.30, 0.40))
                self.d.swipe(x, start_y, x + random.randint(-18, 18), end_y, duration=random.uniform(0.25, 0.55))
                time.sleep(random.uniform(0.25, 0.75))
                return
            except Exception:
                pass
        self._human_swipe(direction="up")

    def _scroll_profile_content_down(self) -> None:
        """Scroll profile content without tapping the profile banner/top card."""
        if self.target == "app":
            try:
                width, height = self.d.window_size()
                # Use the right side of the screen and a mid/lower gesture so
                # the path avoids avatar/banner/primary action zones.
                x = int(width * random.uniform(0.78, 0.90))
                start_y = int(height * random.uniform(0.80, 0.86))
                end_y = int(height * random.uniform(0.50, 0.58))
                self.d.swipe(x, start_y, x + random.randint(-10, 10), end_y, duration=random.uniform(0.35, 0.65))
                time.sleep(random.uniform(0.30, 0.80))
                return
            except Exception:
                pass
        self._scroll_content_down()

    def _reveal_bottom_nav(self) -> None:
        """Reveal a hidden bottom navigation bar before tapping a tab."""
        if self.target != "app":
            return
        try:
            width, height = self.d.window_size()
            # Short finger-down gesture from the middle of the content area.
            # This reveals auto-hidden bottom nav without starting from the top
            # edge, which avoids pull-to-refresh.
            x = int(width * random.uniform(0.45, 0.55))
            start_y = int(height * random.uniform(0.52, 0.62))
            end_y = int(height * random.uniform(0.70, 0.78))
            self.d.swipe(x, start_y, x + random.randint(-10, 10), end_y, duration=random.uniform(0.18, 0.35))
            time.sleep(random.uniform(0.25, 0.55))
        except Exception:
            pass

    def _is_notifications_page_open(self, timeout: float = 1.0) -> bool:
        try:
            return (
                self.d(resourceId=self.rid("notifications_page")).exists(timeout=timeout)
                or self.d(textContains="Mock connection requests").exists(timeout=0.3)
                or self.d(textContains="Review request profiles").exists(timeout=0.3)
                or self.d(resourceId=self.rid("connection_request")).exists(timeout=0.3)
            )
        except Exception:
            return False

    def _has_new_notifications_indicator(self) -> bool:
        """Open Notifications on startup only when the nav exposes unread state."""
        if self.target != "app":
            return False
        try:
            xml = self._visible_hierarchy().lower()
            unread_needles = [
                "unread notifications",
                "new notifications",
                "notification badge",
                "notifications badge",
                self.rid("notifications_badge").lower(),
                self.rid("notification_badge").lower(),
                self.rid("unread_badge").lower(),
            ]
            if any(needle in xml for needle in unread_needles):
                return True
            for selector in [self.d(descriptionContains="Notifications"), self.d(textContains="Notifications")]:
                try:
                    if not selector.exists(timeout=0.2):
                        continue
                    info = selector.info or {}
                    label = " ".join(str(info.get(key) or "") for key in ("text", "contentDescription")).lower()
                    if "badge" in label or "unread" in label or "new notification" in label or re.search(r"\b\d+\s+(new|unread)\b", label):
                        return True
                except Exception:
                    pass
        except Exception as exc:
            self.logger.log("notifications_start_check", self.target, "failed", repr(exc))
        return False

    def _is_network_page_open(self, timeout: float = 1.0) -> bool:
        try:
            return (
                self.d(resourceId=self.rid("network_page")).exists(timeout=timeout)
                or self.d(textContains="My Network").exists(timeout=0.3)
                or self.d(textContains="People you may know").exists(timeout=0.3)
                or self.d(descriptionContains="Network suggestion").exists(timeout=0.3)
            )
        except Exception:
            return False

    def _is_messages_page_open(self, timeout: float = 1.0) -> bool:
        try:
            return (
                self.d(resourceId=self.rid("messages_page")).exists(timeout=timeout)
                or self.d(textContains="Messages").exists(timeout=0.3)
                or self.d(descriptionContains="Conversation with").exists(timeout=0.3)
            )
        except Exception:
            return False

    def _is_search_page_open(self, timeout: float = 0.5) -> bool:
        try:
            if self.d(resourceId=self.rid("results_list")).exists(timeout=timeout):
                return True
            if self.d(resourceId=self.rid("person_result")).exists(timeout=0.2):
                return True
            if self.d(textContains="Show all results").exists(timeout=0.2) or self.d(textContains="See all results").exists(timeout=0.2):
                return True
            return self._has_results_or_typeahead_signal()
        except Exception:
            return False

    def _leave_search_page(self, label: str) -> None:
        """Recover when profile selection returns to/stalls on search."""
        if self.target != "app":
            return
        try:
            if self._is_real_linkedin_app():
                if self._is_home_feed_ready():
                    self.logger.log("search_recovery", label, "skipped", "already_home_no_back")
                    return
                home_ok = self._go_home()
                self.logger.log("search_recovery", label, "success" if home_ok else "not_confirmed", f"method=home_tab_no_back,current={self._current_mock_page_name()}")
                return

            if not self._is_search_page_open(timeout=0.4):
                if self._current_mock_page_name() != "home_feed":
                    self._go_home()
                self.logger.log("search_recovery", label, "skipped", f"not_search,current={self._current_mock_page_name()}")
                return

            self.d.press("back")
            self.think(0.4, 0.9)
            current = self._current_mock_page_name()
            if current in {"home_feed", "network", "messages", "notifications", "unknown"}:
                self.logger.log("search_recovery", label, "success", f"left_search,current={current}")
                return
            if self._is_search_page_open(timeout=0.4):
                self.d.press("back")
                self.think(0.4, 0.9)
            self.logger.log("search_recovery", label, "success", f"left_search_after_profile_reject,current={self._current_mock_page_name()}")
        except Exception as exc:
            self.logger.log("search_recovery", label, "failed", repr(exc))

    def _human_swipe(self, direction: str = "up") -> None:
        width, height = self.d.window_size()

        if self.target == "app" and random.random() < float(self.human.get("burst_scroll_probability", 0.32)):
            self._burst_scroll(direction, width, height)
            return

        center_x = int(width * random.uniform(0.40, 0.60))
        horizontal_drift = int(width * random.uniform(-0.055, 0.055))

        if direction == "up":
            # Humans rarely do identical full-screen swipes. Mix short nudges,
            # medium scrolls, and occasional longer drags.
            gesture_type = random.choices(
                ["short", "medium", "long"],
                weights=[0.38, 0.47, 0.15],
                k=1,
            )[0]
            if gesture_type == "short":
                start_y = int(height * random.uniform(0.64, 0.80))
                end_y = int(height * random.uniform(0.36, 0.54))
            elif gesture_type == "medium":
                start_y = int(height * random.uniform(0.74, 0.90))
                end_y = int(height * random.uniform(0.22, 0.44))
            else:
                start_y = int(height * random.uniform(0.84, 0.94))
                end_y = int(height * random.uniform(0.08, 0.28))
        else:
            gesture_type = random.choices(
                ["short", "medium", "long"],
                weights=[0.42, 0.45, 0.13],
                k=1,
            )[0]
            if gesture_type == "short":
                start_y = int(height * random.uniform(0.28, 0.48))
                end_y = int(height * random.uniform(0.58, 0.76))
            elif gesture_type == "medium":
                start_y = int(height * random.uniform(0.16, 0.38))
                end_y = int(height * random.uniform(0.68, 0.90))
            else:
                start_y = int(height * random.uniform(0.08, 0.24))
                end_y = int(height * random.uniform(0.84, 0.96))

        duration = random.uniform(
            float(self.human.get("swipe_duration_min_seconds", 0.22)),
            float(self.human.get("swipe_duration_max_seconds", 1.45)),
        )
        self._natural_drag(center_x, start_y, center_x + horizontal_drift, end_y, duration)

        # Small imperfect follow-up motions make the scroll less mechanically
        # smooth: a tiny nudge, a settling pause, or a slight reverse correction.
        roll = random.random()
        if roll < 0.22:
            time.sleep(random.uniform(0.12, 0.45))
            if direction == "up":
                nudge_start = int(height * random.uniform(0.55, 0.72))
                nudge_end = int(nudge_start - height * random.uniform(0.06, 0.16))
            else:
                nudge_start = int(height * random.uniform(0.34, 0.50))
                nudge_end = int(nudge_start + height * random.uniform(0.06, 0.16))
            self._natural_drag(
                int(width * random.uniform(0.44, 0.56)),
                nudge_start,
                int(width * random.uniform(0.43, 0.57)),
                nudge_end,
                random.uniform(0.12, 0.35),
                small=True,
            )
        elif roll < 0.34:
            time.sleep(random.uniform(0.18, 0.55))
            if direction == "up":
                correction_start = int(height * random.uniform(0.38, 0.52))
                correction_end = int(correction_start + height * random.uniform(0.04, 0.11))
            else:
                correction_start = int(height * random.uniform(0.54, 0.68))
                correction_end = int(correction_start - height * random.uniform(0.04, 0.11))
            self._natural_drag(
                int(width * random.uniform(0.44, 0.56)),
                correction_start,
                int(width * random.uniform(0.43, 0.57)),
                correction_end,
                random.uniform(0.10, 0.28),
                small=True,
            )
        else:
            time.sleep(random.uniform(0.08, 0.32))

    def _burst_scroll(self, direction: str, width: int, height: int) -> None:
        """Abrupt human-like scroll burst for the controlled mock app.

        Pattern: quick movement, sudden stop, optional reverse adjustment, then
        a content-centering nudge. This makes occasional scrolls less smooth
        without making every gesture chaotic.
        """
        segments = random.randint(2, 4)
        current_y = int(height * (random.uniform(0.72, 0.88) if direction == "up" else random.uniform(0.22, 0.38)))
        current_x = int(width * random.uniform(0.42, 0.58))
        self.logger.log("burst_scroll", direction, "started", f"segments={segments}")

        for segment in range(segments):
            travel = int(height * random.uniform(
                float(self.human.get("burst_travel_min_ratio", 0.16)),
                float(self.human.get("burst_travel_max_ratio", 0.48)),
            ))
            if direction == "up":
                next_y = max(int(height * 0.16), current_y - travel)
            else:
                next_y = min(int(height * 0.90), current_y + travel)
            next_x = current_x + int(width * random.uniform(-0.045, 0.045))
            self._natural_drag(
                current_x,
                current_y,
                next_x,
                next_y,
                random.uniform(
                    float(self.human.get("burst_segment_min_seconds", 0.08)),
                    float(self.human.get("burst_segment_max_seconds", 0.42)),
                ),
                small=segment > 0,
            )
            current_x, current_y = next_x, next_y

            # Sudden stop / content processing pause.
            time.sleep(random.uniform(
                float(self.human.get("burst_pause_min_seconds", 0.05)),
                float(self.human.get("burst_pause_max_seconds", 0.55)),
            ))

            # Sometimes reverse mid-flow to bring content back to the center.
            if random.random() < float(self.human.get("mid_scroll_reverse_probability", 0.38)):
                reverse_travel = int(height * random.uniform(0.04, 0.16))
                reverse_y = current_y + reverse_travel if direction == "up" else current_y - reverse_travel
                reverse_y = max(int(height * 0.16), min(int(height * 0.90), reverse_y))
                reverse_x = current_x + int(width * random.uniform(-0.025, 0.025))
                self._natural_drag(
                    current_x,
                    current_y,
                    reverse_x,
                    reverse_y,
                    random.uniform(0.07, 0.30),
                    small=True,
                )
                current_x, current_y = reverse_x, reverse_y
                self.logger.log("burst_scroll_adjust", direction, "success", "mid_scroll_reverse")
                time.sleep(random.uniform(0.10, 0.65))

        # Final small centering nudge after reading.
        if random.random() < 0.55:
            time.sleep(random.uniform(0.18, 0.90))
            nudge_direction = "down" if direction == "up" else "up"
            nudge = int(height * random.uniform(0.035, 0.10))
            final_y = current_y + nudge if nudge_direction == "down" else current_y - nudge
            final_y = max(int(height * 0.16), min(int(height * 0.90), final_y))
            self._natural_drag(current_x, current_y, current_x + random.randint(-10, 10), final_y, random.uniform(0.08, 0.28), small=True)
            self.logger.log("burst_scroll_adjust", direction, "success", "final_content_centering")

    def _natural_drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float, small: bool = False) -> None:
        """Less-linear drag for the controlled mock app.

        UIAutomator's basic swipe is a straight, constant-looking motion. This
        tries a multi-point curved path first, then falls back to normal swipe if
        the installed uiautomator2 version/device does not support it.
        """
        if not small and random.random() < 0.10:
            # A tiny pre-movement/hesitation: users often adjust their thumb
            # before committing to a longer drag.
            try:
                self.d.swipe(
                    start_x + random.randint(-8, 8),
                    start_y + random.randint(-8, 8),
                    start_x + random.randint(-18, 18),
                    start_y + random.randint(-18, 18),
                    duration=random.uniform(0.05, 0.14),
                )
                time.sleep(random.uniform(0.08, 0.24))
            except Exception:
                pass

        points = self._curved_points(start_x, start_y, end_x, end_y, small=small)
        try:
            self.d.swipe_points(points, duration=duration)
        except Exception:
            # Fallback still uses varied endpoints/duration from _human_swipe.
            self.d.swipe(start_x, start_y, end_x, end_y, duration=duration)

    def _curved_points(self, start_x: int, start_y: int, end_x: int, end_y: int, small: bool = False) -> list[tuple[int, int]]:
        steps = random.randint(4, 7) if not small else random.randint(3, 5)
        points: list[tuple[int, int]] = []
        curve = random.uniform(-0.10, 0.10)
        for i in range(steps):
            t = i / (steps - 1)
            # Ease-out/ease-in mixture: quick middle, slower start/end.
            eased = (1 - (1 - t) * (1 - t)) if random.random() < 0.55 else (t * t * (3 - 2 * t))
            x = start_x + (end_x - start_x) * eased
            y = start_y + (end_y - start_y) * eased
            perpendicular = (t - 0.5) * curve
            x += (end_y - start_y) * perpendicular
            y -= (end_x - start_x) * perpendicular
            x += random.uniform(-7, 7) if not small else random.uniform(-3, 3)
            y += random.uniform(-7, 7) if not small else random.uniform(-3, 3)
            points.append((int(x), int(y)))
        points[0] = (start_x, start_y)
        points[-1] = (end_x, end_y)
        return points

    def _maybe_like_visible_feed_post(self, feed_index: int) -> bool:
        if self.target != "app":
            return False
        current_page = self._current_mock_page_name()
        if not self._is_home_feed_ready():
            self.logger.log("feed_like_skipped", f"feed_{feed_index}", "not_home", f"page={current_page},home_ready={self._is_home_feed_ready()}")
            return False

        max_likes = int(self.config.get("max_feed_likes_per_run", 3))
        if self._feed_likes_this_run >= max_likes:
            self.logger.log("feed_like_limit_reached", f"feed_{feed_index}", "skipped", f"likes={self._feed_likes_this_run},limit={max_likes}")
            return False

        cooldown = float(self.config.get("feed_like_min_cooldown_seconds", 45))
        elapsed = time.time() - self._last_feed_like_at if self._last_feed_like_at else None
        if elapsed is not None and elapsed < cooldown:
            self.logger.log("feed_like_skipped", f"feed_{feed_index}", "cooldown", f"elapsed={elapsed:.1f},cooldown={cooldown:.1f}")
            return False

        like_probability = float(self.config.get("feed_like_probability", self.config.get("like_probability", 0.20)))
        if random.random() >= like_probability:
            self.logger.log("feed_like_skipped", f"feed_{feed_index}", "random_window_skip", f"like_probability={like_probability}")
            return False

        self.think(
            float(self.config.get("feed_like_read_min_seconds", 2.5)),
            float(self.config.get("feed_like_read_max_seconds", 7.5)),
        )

        targets = self._visible_feed_post_like_targets()
        self.logger.log("feed_like_candidate_count", f"feed_{feed_index}", "observed", f"count={len(targets)}")
        if not targets:
            self.logger.log("feed_like_skipped", f"feed_{feed_index}", "not_found", "no_eligible_like_buttons")
            return False

        max_per_action = int(self.config.get("max_feed_likes_per_action", 1))
        liked_this_action = 0
        for target in random.sample(targets[: min(len(targets), 3)], k=min(len(targets), 3)):
            if liked_this_action >= max_per_action:
                break
            signature = str(target.get("signature") or "")
            if signature in self._liked_feed_post_signatures:
                self.logger.log("feed_like_skipped", f"feed_{feed_index}", "duplicate", signature[:80])
                continue
            post_skip_probability = float(self.config.get("feed_like_skip_probability", 0.55))
            if random.random() < post_skip_probability:
                self.logger.log("feed_like_skipped", f"feed_{feed_index}", "post_skip", f"skip_probability={post_skip_probability},signature={signature[:80]}")
                continue
            if not self._click_feed_like_target(target):
                self.logger.log("feed_like_skipped", f"feed_{feed_index}", "click_failed", signature[:80])
                continue
            self._liked_feed_post_signatures.add(signature)
            self._feed_likes_this_run += 1
            self._last_feed_like_at = time.time()
            liked_this_action += 1
            self.logger.log("feed_like_clicked", f"feed_{feed_index}", "clicked", f"post_signature={signature[:120]},likes_this_run={self._feed_likes_this_run}")
            self.think(
                float(self.config.get("feed_like_after_click_min_seconds", 1.2)),
                float(self.config.get("feed_like_after_click_max_seconds", 3.6)),
            )
            return True

        self.logger.log("feed_like_skipped", f"feed_{feed_index}", "no_post_selected", "all_candidates_skipped")
        return False

    def _visible_feed_post_like_targets(self) -> list[dict]:
        if self.target != "app" or not self._is_home_feed_ready():
            return []
        targets: list[dict] = []
        seen: set[str] = set()
        try:
            width, height = self.d.window_size()
        except Exception:
            width, height = 0, 0

        for class_name in ("android.widget.Button", "android.widget.TextView", "android.view.ViewGroup", "android.view.View"):
            try:
                nodes = list(self.d(className=class_name))
            except Exception:
                nodes = []
            for node in nodes:
                try:
                    info = node.info or {}
                    text = self._xml_unescape(" ".join(str(info.get(key) or "") for key in ("text", "contentDescription")).strip())
                    target = self._feed_like_target_from_info(text, info, width, height)
                    if not target:
                        continue
                    if target["signature"] in seen:
                        continue
                    seen.add(target["signature"])
                    targets.append(target)
                except Exception:
                    pass

        targets.extend(self._visible_feed_post_like_targets_from_xml(seen, width, height))
        return sorted(targets, key=lambda item: (int(item.get("y", 0)), int(item.get("x", 0))))

    def _visible_feed_post_like_targets_from_xml(self, seen: set[str], width: int, height: int) -> list[dict]:
        targets: list[dict] = []
        xml = self._visible_hierarchy()
        for match in re.finditer(r"<node\b[^>]*>", xml):
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', match.group(0)))
            label = self._xml_unescape(" ".join(part for part in [attrs.get("text", ""), attrs.get("content-desc", "")] if part).strip())
            bounds_text = attrs.get("bounds", "")
            bounds_match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_text)
            if not bounds_match:
                continue
            left, top, right, bottom = [int(value) for value in bounds_match.groups()]
            info = {"bounds": {"left": left, "top": top, "right": right, "bottom": bottom}, "text": label, "contentDescription": label}
            target = self._feed_like_target_from_info(label, info, width, height)
            if not target or target["signature"] in seen:
                continue
            seen.add(target["signature"])
            targets.append(target)
        return targets

    def _feed_like_target_from_info(self, label: str, info: dict, width: int, height: int) -> dict | None:
        if not self._is_eligible_feed_like_label(label):
            return None
        if info.get("selected") or info.get("checked"):
            return None
        bounds = info.get("bounds") or {}
        left = int(bounds.get("left", 0))
        right = int(bounds.get("right", 0))
        top = int(bounds.get("top", 0))
        bottom = int(bounds.get("bottom", 0))
        if right <= left or bottom <= top:
            return None
        center_x = (left + right) // 2
        center_y = (top + bottom) // 2
        if width and center_x > int(width * 0.58):
            return None
        if height and not (int(height * 0.24) <= center_y <= int(height * 0.84)):
            return None
        signature = self._feed_like_signature(label, bounds)
        return {"x": center_x, "y": center_y, "bounds": bounds, "label": label, "signature": signature}

    def _is_eligible_feed_like_label(self, label: str) -> bool:
        clean = re.sub(r"\s+", " ", label.strip()).lower()
        if not clean:
            return False
        if any(term in clean for term in ("liked", "unlike", "likes", "comment", "reply", "notification")):
            return False
        return clean == "like" or clean.startswith("like ") or clean.startswith("like,") or "react like" in clean

    def _feed_like_signature(self, label: str, bounds: dict) -> str:
        center_y = (int(bounds.get("top", 0)) + int(bounds.get("bottom", 0))) // 2
        center_x = (int(bounds.get("left", 0)) + int(bounds.get("right", 0))) // 2
        return f"{self._page_signature()}|{label.strip().lower()[:40]}|x={center_x // 40}|y={center_y // 40}"

    def _click_feed_like_target(self, target: dict) -> bool:
        try:
            bounds = target.get("bounds") or {}
            left = int(bounds.get("left", target.get("x", 0)))
            right = int(bounds.get("right", target.get("x", 0)))
            top = int(bounds.get("top", target.get("y", 0)))
            bottom = int(bounds.get("bottom", target.get("y", 0)))
            width = max(1, right - left)
            height = max(1, bottom - top)
            min_x = left + int(width * 0.30)
            max_x = right - max(1, int(width * 0.20))
            min_y = top + int(height * 0.25)
            max_y = bottom - max(1, int(height * 0.20))
            x = random.randint(min_x, max_x) if width > 8 and min_x <= max_x else int(target["x"])
            y = random.randint(min_y, max_y) if height > 8 and min_y <= max_y else int(target["y"])
            self.d.click(x, y)
            return True
        except Exception:
            return False

    def _click_like_button(self) -> bool:
        if self.target == "app":
            selectors = [
                self.d(resourceId=self.rid("like_button"), text="Like"),
                self.d(text="Like"),
                self.d(description="Like"),
                self.d(descriptionContains="Like"),
            ]
            for selector in selectors:
                try:
                    if selector.exists(timeout=0.8):
                        info = selector.info or {}
                        label = " ".join(str(info.get(key) or "") for key in ("text", "contentDescription")).lower()
                        if "liked" in label or "unlike" in label:
                            continue
                        selector.click()
                        return True
                except Exception:
                    pass

            try:
                width, height = self.d.window_size()
                for selector in self.d(className="android.widget.TextView"):
                    info = selector.info or {}
                    text = self._xml_unescape(str(info.get("text") or info.get("contentDescription") or ""))
                    if text.strip().lower() != "like":
                        continue
                    bounds = info.get("bounds") or {}
                    cy = (int(bounds.get("top", 0)) + int(bounds.get("bottom", 0))) // 2
                    cx = (int(bounds.get("left", 0)) + int(bounds.get("right", 0))) // 2
                    if int(height * 0.35) <= cy <= int(height * 0.86):
                        self.d.click(cx or int(width * 0.22), cy)
                        return True
            except Exception:
                pass

            self.logger.log("like_post", self.target, "not_found", "like_button_not_visible_on_current_page")
        return self._click_text("Like") or self._click_xpath_text("Like")

    def _open_profile_from_feed(self) -> bool:
        if self.target != "app":
            return False
        selectors = [
            self.d(descriptionContains="Open feed profile"),
            self.d(resourceId=self.rid("feed_profile_link")),
            self.d(resourceId=self.rid("post_card")),
        ]
        for selector in selectors:
            try:
                if selector.exists(timeout=0.8):
                    self.think(0.3, 1.0)
                    selector.click()
                    self.think(0.8, 1.8)
                    return self.d(resourceId=self.rid("profile_page")).exists(timeout=1.2)
            except Exception:
                pass

        # Fallback: tap likely author/header zones on visible feed cards. This is
        # more robust on devices where duplicate resource IDs resolve to an
        # off-screen node or where only part of the row is exposed to UIAutomator.
        try:
            width, height = self.d.window_size()
            for y_ratio in (0.24, 0.34, 0.44, 0.54):
                self.d.click(int(width * random.uniform(0.18, 0.42)), int(height * y_ratio))
                self.think(0.6, 1.3)
                if self.d(resourceId=self.rid("profile_page")).exists(timeout=0.8):
                    return True
        except Exception:
            pass
        return False

    def _analyze_open_profile(self, label: str) -> None:
        """Scroll an opened mock profile like a human QA reviewer."""
        if self.target == "app":
            try:
                if not self.d(resourceId=self.rid("profile_page")).exists(timeout=0.8):
                    return
            except Exception:
                return

        passes = random.randint(
            int(self.config.get("profile_scroll_min", 2)),
            int(self.config.get("profile_scroll_max", 5)),
        )
        self.logger.log("profile_analysis_start", label, "success", f"scrolls={passes}")
        for i in range(1, passes + 1):
            self.think(1.0, 3.2)
            self._scroll_profile_content_down()
            self.logger.log("profile_scroll", f"{label}_{i}", "success", "profile_right_side_safe_scroll")
        if random.random() < 0.45:
            self.action_transition_pause()
        self.logger.log("profile_analysis_end", label, "success", "humanized_profile_review")

    def _score_open_profile_candidate(self, search_query: str) -> Candidate | None:
        """Score and save the currently opened profile without changing navigation.

        This is the integration hook for the existing profile-finding flow: once
        the branch has already found/opened a profile, snapshot visible text,
        score it, and persist it. Connect decisions are handled after the profile
        is returned to the top where the Connect button is reachable.
        """
        discovery = self.config.get("candidate_discovery", {})
        if not discovery.get("score_existing_profile_flow", True):
            return None
        try:
            if self.target == "app" and self._current_mock_page_name() != "profile":
                self.logger.log("candidate_profile_score", search_query, "skipped", f"not_profile_page={self._current_mock_page_name()}")
                return None
            visible_text = self._visible_text_for_candidate_scoring()
            if not visible_text.strip():
                self.logger.log("candidate_profile_score", search_query, "empty", "no_visible_text")
                return None
            candidate = self.candidate_extractor.from_visible_text(
                visible_text,
                search_query,
                "existing_profile_flow",
                int(time.time()),
            )
            if not candidate:
                self.logger.log("candidate_profile_score", search_query, "empty", "extractor_returned_none")
                return None
            if self._is_generic_candidate_name(candidate.name):
                self.logger.log("candidate_profile_score", search_query, "skipped", f"generic_name={candidate.name}")
                return None
            if candidate.profile_url and candidate.profile_url.startswith("mockin://") and self.app_package == self.config.get("linkedin_app_package", "com.linkedin.android"):
                candidate.profile_url = None
            candidate.additional_metadata.update(
                {
                    "source": "existing_profile_flow",
                    "driver_mode": "android_existing_flow",
                    "app_package": self.app_package,
                    "manual_connect_required": self._manual_connect_required_when_scoring(),
                    "auto_connect_threshold": self._auto_connect_score_threshold(),
                    "captured_at": utc_now(),
                }
            )
            self._save_scored_profile_candidate(candidate, search_query)
            self.logger.log(
                "candidate_profile_scored",
                candidate.name or search_query,
                "success",
                f"score={candidate.score},recommendation={candidate.additional_metadata.get('recommendation')}",
            )
            return candidate
        except Exception as exc:
            self.logger.log("candidate_profile_score", search_query, "failed", repr(exc))
        return None

    def _visible_text_for_candidate_scoring(self) -> str:
        blocks: list[str] = []
        try:
            for node in self.d(className="android.widget.TextView"):
                info = node.info or {}
                text = str(info.get("text") or info.get("contentDescription") or "").strip()
                if 1 < len(text) < 260 and not self._is_generic_candidate_name(text):
                    blocks.append(text)
        except Exception:
            pass
        if not blocks:
            xml = self._visible_hierarchy()
            values = re.findall(r'text="([^"]+)"|content-desc="([^"]+)"', xml)
            for left, right in values:
                value = self._xml_unescape(left or right)
                if 1 < len(value) < 260 and not self._is_generic_candidate_name(value):
                    blocks.append(value)
        return "\n".join(self._dedupe_text_blocks(blocks))

    def _is_generic_candidate_name(self, value: str | None) -> bool:
        if not value:
            return True
        normalized = re.sub(r"\s+", " ", str(value)).strip().lower()
        if not normalized:
            return True
        generic_exact = {
            "people", "posts", "jobs", "companies", "groups", "schools", "courses", "services", "events",
            "1st", "2nd", "3rd", "connections", "all filters", "show results", "apply", "search", "home",
            "my network", "messaging", "notifications", "connect", "follow", "message", "like", "comment", "share",
        }
        if normalized in generic_exact:
            return True
        if normalized.startswith(("people ", "posts ", "jobs ", "companies ", "groups ")):
            return True
        return False

    def _save_scored_profile_candidate(self, candidate: Candidate, search_query: str) -> None:
        output_dir = Path(self.config.get("candidate_discovery", {}).get("output_dir", "output/candidate_discovery"))
        if self._candidate_persistence is None:
            self._candidate_persistence = CandidatePersistenceService(output_dir)
        if self._profile_flow_run is None:
            self._profile_flow_run = DiscoveryRun(
                run_id=f"existing_profile_flow_{int(time.time())}",
                created_at=utc_now(),
                search_query=search_query,
                candidates=[],
                state={"source": "existing_profile_flow"},
            )
            self._profile_flow_run_path = self._candidate_persistence.next_run_path()
        self._profile_flow_run.search_query = search_query
        self._profile_flow_run.candidates = sorted(
            self._candidate_deduplicator.merge(
                self._profile_flow_run.candidates,
                [candidate],
            ),
            key=lambda item: item.score or 0,
            reverse=True,
        )
        self._profile_flow_run.state.update(
            {
                "last_search_query": search_query,
                "last_saved_at": utc_now(),
                "candidate_count": len(self._profile_flow_run.candidates),
                "manual_connect_required": self._manual_connect_required_when_scoring(),
            }
        )
        self._candidate_persistence.save(self._profile_flow_run, self._profile_flow_run_path or self._candidate_persistence.next_run_path())

    def _auto_connect_score_threshold(self) -> int:
        discovery = self.config.get("candidate_discovery", {})
        return int(discovery.get("auto_connect_min_score", discovery.get("connect_score_threshold", 70)))

    def _maybe_connect_scored_profile(self, candidate: Candidate | None, search_query: str) -> bool:
        discovery = self.config.get("candidate_discovery", {})
        if not discovery.get("auto_connect_scored_profiles", True):
            return False
        if candidate is None or candidate.score is None:
            return False
        if self._is_real_linkedin_app() and not discovery.get("allow_real_linkedin_auto_connect", False):
            self.logger.log("connect", candidate.name or search_query, "manual_required", "real_linkedin_auto_connect_disabled")
            return False

        threshold = self._auto_connect_score_threshold()
        if candidate.score < threshold:
            self.logger.log(
                "connect",
                candidate.name or search_query,
                "skipped",
                f"score={candidate.score}<threshold={threshold}",
            )
            return False

        self.think(0.5, 1.8)
        clicked = self._click_connect_button()
        candidate.additional_metadata.update(
            {
                "auto_connect_attempted_at": utc_now(),
                "auto_connect_threshold": threshold,
                "auto_connect_status": "clicked" if clicked else "not_found",
            }
        )
        self._save_scored_profile_candidate(candidate, search_query)
        if clicked:
            self.logger.log(
                "connect",
                candidate.name or search_query,
                "clicked",
                f"score={candidate.score}>=threshold={threshold}",
            )
        else:
            self.logger.log(
                "connect",
                candidate.name or search_query,
                "not_found",
                f"score={candidate.score}>=threshold={threshold}",
            )
        return True

    def _manual_connect_required_when_scoring(self) -> bool:
        discovery = self.config.get("candidate_discovery", {})
        if not discovery.get("score_existing_profile_flow", True):
            return False
        linkedin_package = self.config.get("linkedin_app_package", "com.linkedin.android")
        if self.app_package == linkedin_package:
            return bool(discovery.get("manual_connect_required", True)) or not discovery.get("allow_real_linkedin_auto_connect", False)
        return bool(discovery.get("manual_connect_required", False))

    def _dedupe_text_blocks(self, blocks: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for block in blocks:
            clean = self._xml_unescape(block).strip()
            key = clean.lower()
            if clean and key not in seen:
                seen.add(key)
                result.append(clean)
        return result

    def _xml_unescape(self, value: str) -> str:
        return (
            value.replace("&amp;", "&")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .strip()
        )

    def _return_profile_to_top(self, label: str) -> None:
        """After reviewing a mock profile, move back near the top before connect."""
        if self.target == "app":
            try:
                if not self.d(resourceId=self.rid("profile_page")).exists(timeout=0.8):
                    return
            except Exception:
                return

        self.think(
            float(self.config.get("profile_top_return_wait_min_seconds", 1.2)),
            float(self.config.get("profile_top_return_wait_max_seconds", 3.8)),
        )
        swipes = random.randint(
            int(self.config.get("profile_top_return_min_swipes", 2)),
            int(self.config.get("profile_top_return_max_swipes", 4)),
        )
        self.logger.log("profile_return_top_start", label, "success", f"swipes={swipes}")
        for i in range(1, swipes + 1):
            # direction="down" means finger moves down, content returns upward
            # toward the top of the profile.
            self._fast_profile_reverse_swipe()
            self.logger.log("profile_return_top_scroll", f"{label}_{i}", "success", "fast_reverse_to_top")
            time.sleep(random.uniform(0.08, 0.35))
        self.think(0.5, 1.4)
        self.logger.log("profile_return_top_end", label, "success", "ready_to_connect")

    def _fast_profile_reverse_swipe(self) -> None:
        """Move profile content back toward the top without tapping cover image.

        Previous implementation started at 12-30% screen height, which overlaps
        the profile cover/hero image. The natural-drag pre-movement could be
        interpreted as a cover-image tap. Start in the lower content area and
        use a direct swipe to avoid opening the banner/photo viewer.
        """
        width, height = self.d.window_size()
        start_x = int(width * random.uniform(0.72, 0.88))
        start_y = int(height * random.uniform(0.58, 0.70))
        end_x = start_x + int(width * random.uniform(-0.02, 0.02))
        end_y = int(height * random.uniform(0.82, 0.90))
        try:
            self.d.swipe(start_x, start_y, end_x, end_y, duration=random.uniform(0.18, 0.36))
        except Exception:
            self._natural_drag(start_x, start_y, end_x, end_y, random.uniform(0.18, 0.36), small=True)

    def _click_connect_button(self) -> bool:
        if self.target == "app":
            selectors = [
                self.d(resourceId=self.rid("connect_button")),
                self.d(resourceId=self.rid("connect_button"), textContains="Connect"),
                self.d(resourceId=self.rid("connect_button"), textContains="Follow"),
                self.d(text="Connect"),
                self.d(textContains="Connect"),
                self.d(descriptionContains="Connect"),
                self.d(text="Follow"),
                self.d(textContains="Follow"),
                self.d(descriptionContains="Follow"),
            ]
            for selector in selectors:
                try:
                    if selector.exists(timeout=1.0):
                        selector.click()
                        self.think(0.5, 1.0)
                        self._dismiss_follow_notification_popup()
                        return self._connect_click_confirmed() if self._is_real_linkedin_app() else True
                except Exception:
                    pass

            # If the profile is slightly scrolled, bring top actions back into
            # view and retry once before using coordinates.
            try:
                self._fast_profile_reverse_swipe()
                self.think(0.4, 0.9)
                for button in [
                    self.d(resourceId=self.rid("connect_button")),
                    self.d(textContains="Connect"),
                    self.d(textContains="Follow"),
                    self.d(descriptionContains="Connect"),
                    self.d(descriptionContains="Follow"),
                ]:
                    if button.exists(timeout=1.0):
                        button.click()
                        self.think(0.5, 1.0)
                        self._dismiss_follow_notification_popup()
                        return self._connect_click_confirmed() if self._is_real_linkedin_app() else True
            except Exception:
                pass

            if self._is_real_linkedin_app() and not self.config.get("candidate_discovery", {}).get("allow_coordinate_connect_fallbacks", False):
                self.logger.log("connect", self.target, "not_found", "coordinate_connect_fallback_disabled")
                return False

            # Mock profile top-card fallback: Connect is the left primary CTA.
            try:
                width, height = self.d.window_size()
                for y_ratio in (0.34, 0.40, 0.46):
                    self.d.click(int(width * random.uniform(0.18, 0.34)), int(height * y_ratio))
                    self.think(0.5, 1.0)
                    self._dismiss_follow_notification_popup()
                    return self._connect_click_confirmed() if self._is_real_linkedin_app() else True
            except Exception:
                pass
        clicked = self._click_text("Connect") or self._click_text("Follow")
        if clicked:
            self.think(0.5, 1.0)
            self._dismiss_follow_notification_popup()
            if self.target == "app" and self._is_real_linkedin_app():
                return self._connect_click_confirmed()
        return clicked

    def _connect_click_confirmed(self) -> bool:
        xml = self._visible_hierarchy().lower()
        confirmed_terms = (
            "pending",
            "invitation sent",
            "invitation has been sent",
            "following",
            "withdraw",
            "add a note",
            "send without a note",
        )
        return any(term in xml for term in confirmed_terms)

    def _dismiss_follow_notification_popup(self) -> bool:
        """If a follow-notification dialog appears, choose Off."""
        if self.target != "app":
            return False

        popup_markers = [
            self.d(textContains="notification"),
            self.d(textContains="Notification"),
            self.d(descriptionContains="notification"),
            self.d(descriptionContains="Notification"),
        ]
        popup_visible = False
        for marker in popup_markers:
            try:
                if marker.exists(timeout=0.6):
                    popup_visible = True
                    break
            except Exception:
                pass

        off_selectors = [
            self.d(text="Off"),
            self.d(text="off"),
            self.d(textContains="Off"),
            self.d(description="Off"),
            self.d(descriptionContains="Off"),
        ]
        for selector in off_selectors:
            try:
                if selector.exists(timeout=0.8):
                    selector.click()
                    self.logger.log("follow_notification_popup", self.target, "clicked", "off")
                    self.think(0.3, 0.8)
                    return True
            except Exception:
                pass

        if popup_visible:
            # Last-resort: many three-option sheets place Off as the bottom or
            # right-most option. Try safe lower-sheet coordinates, then continue.
            try:
                width, height = self.d.window_size()
                for x_ratio, y_ratio in ((0.50, 0.78), (0.82, 0.72), (0.50, 0.84)):
                    self.d.click(int(width * x_ratio), int(height * y_ratio))
                    self.think(0.3, 0.7)
                    if not self.d(textContains="Notification").exists(timeout=0.3):
                        self.logger.log("follow_notification_popup", self.target, "clicked", "off_coordinate_fallback")
                        return True
            except Exception:
                pass
            self.logger.log("follow_notification_popup", self.target, "not_found", "off_option_missing")
        return False

    def _check_notifications(self) -> None:
        self._guard_bottom_menu_before_step("notifications")
        if self.target != "app":
            return
        self.logger.log("notifications_open", self.target, "started", "checking_mock_alerts")
        self.think(
            float(self.config.get("pre_notifications_wait_min_seconds", 1.6)),
            float(self.config.get("pre_notifications_wait_max_seconds", 4.2)),
        )
        if not self._open_notifications_tab():
            self.logger.log("notifications_open", self.target, "failed", "notifications tab not clickable")
            return

        self.logger.log("notifications_scan", self.target, "success", "processing_visible_notifications")
        self.think(
            float(self.config.get("notifications_scan_min_seconds", 2.2)),
            float(self.config.get("notifications_scan_max_seconds", 6.0)),
        )

        if self._open_connection_request_profile():
            self._analyze_open_profile("connection_request_profile")
            self._open_notifications_again()
            self._accept_connection_request()
            self._go_home()
            self.logger.log("notifications_home", self.target, "success", "returned_home_after_request_check")
        else:
            self.logger.log("connection_request", self.target, "not_found", "no visible mock request")
            self._go_home()
            self.logger.log("notifications_home", self.target, "success", "returned_home_empty_notifications")

    def _open_notifications_again(self) -> None:
        self._open_notifications_tab()

    def _open_notifications_tab(self) -> bool:
        if self._is_notifications_page_open(timeout=0.4):
            return True
        self._reveal_bottom_nav()
        try:
            tab = self.d(resourceId=self.rid("notifications_tab"))
            if tab.exists(timeout=1.0):
                tab.click()
                self.think(1.0, 2.2)
                if self._is_notifications_page_open(timeout=1.2):
                    self.logger.log("notifications_open", self.target, "success", "resource_id_tab")
                    return True
        except Exception:
            pass

        for selector in [self.d(resourceId=self.rid("notifications_tab")), self.d(textContains="Notifications"), self.d(textContains="Alerts"), self.d(descriptionContains="Notifications")]:
            try:
                if selector.exists(timeout=0.8):
                    selector.click()
                    self.think(1.0, 2.2)
                    if self._is_notifications_page_open(timeout=1.2):
                        self.logger.log("notifications_open", self.target, "success", "selector_tab")
                        return True
            except Exception:
                pass

        # Bottom nav fallback. Notifications is the 4th of 5 tabs, around 70% width.
        try:
            width, height = self.d.window_size()
            for x_ratio in (0.70, 0.72, 0.68):
                self.d.click(int(width * x_ratio), int(height * 0.955))
                self.think(0.9, 1.8)
                if self._is_notifications_page_open(timeout=1.2):
                    self.logger.log("notifications_open", self.target, "success", "coordinate_fallback")
                    return True
        except Exception:
            pass
        return False

    def _open_connection_request_profile(self) -> bool:
        # Prefer a random visible request card. This better covers the mock UI
        # than always selecting the first request.
        try:
            width, height = self.d.window_size()
            candidate_rows = [0.30, 0.42, 0.54]
            random.shuffle(candidate_rows)
            for y_ratio in candidate_rows:
                self.think(0.4, 1.3)
                self.d.click(int(width * random.uniform(0.18, 0.48)), int(height * y_ratio))
                self.think(1.0, 2.2)
                if self.d(resourceId=self.rid("profile_page")).exists(timeout=1.2):
                    self.logger.log("connection_request_profile", self.target, "opened", f"random_row_y={y_ratio}")
                    return True
        except Exception:
            pass

        selectors = [
            self.d(resourceId=self.rid("connection_request")),
            self.d(descriptionContains="Connection request from"),
            self.d(textContains="sent you a connection request"),
        ]
        for selector in selectors:
            try:
                if selector.exists(timeout=1.0):
                    self.think(0.6, 1.6)
                    selector.click()
                    self.think(1.0, 2.2)
                    if self.d(resourceId=self.rid("profile_page")).exists(timeout=1.2):
                        self.logger.log("connection_request_profile", self.target, "opened", "review_before_accept")
                        return True
            except Exception:
                pass
        return False

    def _accept_connection_request(self) -> bool:
        selectors = [
            self.d(resourceId=self.rid("accept_button"), text="Accept"),
            self.d(text="Accept"),
            self.d(descriptionContains="Accept request"),
        ]
        for selector in selectors:
            try:
                if selector.exists(timeout=1.0):
                    self.think(0.7, 1.8)
                    selector.click()
                    self.logger.log("connection_request_accept", self.target, "clicked", "mock request accepted")
                    self.think(0.7, 1.5)
                    return True
            except Exception:
                pass
        self.logger.log("connection_request_accept", self.target, "not_found", "accept button missing")
        return False

    def _try_repost_visible_post(self) -> bool:
        self._guard_bottom_menu_before_step("repost")
        if self.target != "app":
            return False
        self.logger.log("repost", self.target, "started", "visible_post")
        self.action_transition_pause()
        selectors = [
            self.d(resourceId=self.rid("repost_button"), text="Repost"),
            self.d(text="Repost"),
            self.d(description="Repost"),
        ]
        for selector in selectors:
            try:
                if selector.exists(timeout=1.0):
                    selector.click()
                    self.logger.log("repost", self.target, "clicked", "mock repost toggled")
                    self.think(0.6, 1.4)
                    return True
            except Exception:
                pass
        # Fallback: action row third button zone.
        try:
            width, height = self.d.window_size()
            self.d.click(int(width * random.uniform(0.50, 0.62)), int(height * random.uniform(0.55, 0.78)))
            self.logger.log("repost", self.target, "clicked", "coordinate_fallback")
            self.think(0.5, 1.2)
            return True
        except Exception:
            self.logger.log("repost", self.target, "failed", "not_found")
            return False

    def _browse_network_and_connect(self) -> None:
        self._guard_bottom_menu_before_step("network")
        if self.target != "app":
            return
        self.logger.log("network_open", self.target, "started", "browse_suggestions")
        if not self._open_network_tab():
            self.logger.log("network_open", self.target, "failed", f"network tab not clickable,current_page={self._current_mock_page_name()}")
            self._record_page_progress("network_open_failed")
            return
        self.action_transition_pause()
        if random.random() < 0.45:
            self._scroll_content_down()
            self.think(0.8, 2.2)
        if random.random() < 0.65:
            if self._click_connect_button():
                self.logger.log("network_connect", self.target, "clicked", "suggestion connect")
            else:
                self.logger.log("network_connect", self.target, "not_found", "connect missing")
        else:
            if self._open_network_profile():
                self.logger.log("network_profile", self.target, "opened", "review suggestion")
                self._analyze_open_profile("network_profile")
                self._return_profile_to_top("network_profile")
                if self._click_connect_button():
                    self.logger.log("network_connect", self.target, "clicked", "after_profile_review")

    def _open_network_tab(self) -> bool:
        if self._is_network_page_open(timeout=0.4):
            return True
        self._reveal_bottom_nav()
        for selector in [self.d(resourceId=self.rid("network_tab")), self.d(textContains="Network"), self.d(descriptionContains="Network")]:
            try:
                if selector.exists(timeout=0.8):
                    selector.click()
                    self.think(1.0, 2.0)
                    if self._is_network_page_open(timeout=1.3):
                        self.logger.log("network_open", self.target, "success", "selector_tab")
                        return True
            except Exception:
                pass
        try:
            self._reveal_bottom_nav()
            width, height = self.d.window_size()
            for x_ratio in (0.30, 0.28, 0.32):
                self.d.click(int(width * x_ratio), int(height * 0.955))
                self.think(1.0, 2.0)
                if self._is_network_page_open(timeout=1.3):
                    self.logger.log("network_open", self.target, "success", "coordinate_fallback")
                    return True
            return False
        except Exception:
            return False

    def _open_network_profile(self) -> bool:
        selectors = [self.d(resourceId=self.rid("network_person_card")), self.d(descriptionContains="Network suggestion")]
        for selector in selectors:
            try:
                if selector.exists(timeout=1.0):
                    selector.click()
                    self.think(1.0, 2.0)
                    return self.d(resourceId=self.rid("profile_page")).exists(timeout=1.0)
            except Exception:
                pass
        return False

    def _open_messages_and_reply(self) -> None:
        self._guard_bottom_menu_before_step("messages")
        if self.target != "app":
            return
        self.logger.log("messages_open", self.target, "started", "browse_inbox")
        if not self._open_messages_page():
            self.logger.log("messages_open", self.target, "failed", "messages not clickable")
            return
        self.action_transition_pause()
        if not self._open_conversation():
            self.logger.log("conversation_open", self.target, "not_found", "no conversation")
            return
        self.action_transition_pause()
        self._type_mock_message_and_send()

    def _open_messages_page(self) -> bool:
        if self._is_messages_page_open(timeout=0.4):
            return True
        self._reveal_bottom_nav()
        for selector in [self.d(resourceId=self.rid("messages_button")), self.d(descriptionContains="Messaging")]:
            try:
                if selector.exists(timeout=0.8):
                    selector.click()
                    self.think(1.0, 2.0)
                    if self._is_messages_page_open(timeout=1.2):
                        return True
            except Exception:
                pass
        try:
            width, height = self.d.window_size()
            self.d.click(int(width * 0.93), int(height * 0.055))
            self.think(1.0, 2.0)
            return self._is_messages_page_open(timeout=1.2)
        except Exception:
            return False

    def _open_conversation(self) -> bool:
        selectors = [self.d(resourceId=self.rid("conversation_item")), self.d(descriptionContains="Conversation with")]
        for selector in selectors:
            try:
                if selector.exists(timeout=1.0):
                    selector.click()
                    self.think(1.0, 2.0)
                    self.logger.log("conversation_open", self.target, "opened", "mock inbox")
                    return True
            except Exception:
                pass
        return False

    def _type_mock_message_and_send(self) -> bool:
        try:
            input_box = self.d(resourceId=self.rid("message_input"))
            if input_box.exists(timeout=1.0):
                input_box.click()
                self.think(0.4, 1.0)
                text = random.choice([
                    "Thanks for connecting",
                    "Great to connect here",
                    "Appreciate the message",
                    "Happy to discuss this mock workflow",
                ])
                self._type_text_human(text)
                self.think(0.6, 1.5)
                send = self.d(resourceId=self.rid("send_message_button"))
                if send.exists(timeout=1.0):
                    send.click()
                    self.logger.log("message_send", self.target, "clicked", "mock reply sent")
                    return True
        except Exception:
            pass
        self.logger.log("message_send", self.target, "failed", "input_or_send_missing")
        return False

    def _is_real_linkedin_app(self) -> bool:
        return self.app_package == self.config.get("linkedin_app_package", "com.linkedin.android")

    def _collect_search_results_instead_of_opening(self) -> bool:
        discovery = self.config.get("candidate_discovery", {})
        return bool(self._is_real_linkedin_app() and discovery.get("collect_search_results_without_opening", True))

    def _open_all_search_results(self, search_query: str) -> bool:
        selectors = [
            self.d(text="Show all results"),
            self.d(textContains="Show all results"),
            self.d(descriptionContains="Show all results"),
            self.d(textContains="See all results"),
            self.d(descriptionContains="See all results"),
        ]
        for selector in selectors:
            try:
                if selector.exists(timeout=1.2):
                    selector.click()
                    self.logger.log("search_show_all_results", search_query, "clicked", "before_filters")
                    self.think(1.0, 2.0)
                    return True
            except Exception:
                pass
        self.logger.log("search_show_all_results", search_query, "not_found", "maybe_already_on_results")
        return False

    def _collect_and_score_visible_search_results(self, search_query: str) -> int:
        settings = self.config.get("candidate_discovery", {})
        if settings.get("open_random_profile_results", True):
            return self._open_random_profile_results_and_score(search_query)
        return self._score_visible_result_cards_without_opening(search_query)

    def _score_visible_result_cards_without_opening(self, search_query: str) -> int:
        settings = self.config.get("candidate_discovery", {})
        pages = int(settings.get("result_collection_pages", 4))
        max_candidates = int(settings.get("max_candidates_per_query", 25))
        seen: set[str] = set()
        collected = 0
        no_progress = 0
        previous_signature = ""

        for page in range(1, pages + 1):
            candidates = self._extract_people_result_candidates(search_query, page)
            page_new = 0
            for candidate in candidates:
                key = candidate.identity_key()
                if key in seen:
                    continue
                seen.add(key)
                candidate.profile_url = None
                candidate.additional_metadata.update(
                    {
                        "source": "linkedin_people_results_list",
                        "driver_mode": "android_results_collector",
                        "app_package": self.app_package,
                        "manual_connect_required": True,
                        "captured_at": utc_now(),
                    }
                )
                self._save_scored_profile_candidate(candidate, search_query)
                collected += 1
                page_new += 1
                self.logger.log(
                    "candidate_result_scored",
                    candidate.name or search_query,
                    "success",
                    f"score={candidate.score},page={page},recommendation={candidate.additional_metadata.get('recommendation')}",
                )
                if collected >= max_candidates:
                    return collected

            signature = self._page_signature()
            if page_new == 0 or signature == previous_signature:
                no_progress += 1
            else:
                no_progress = 0
            if no_progress >= int(settings.get("no_progress_scroll_limit", 2)):
                break
            previous_signature = signature
            self._safe_results_scroll_down()
            self.think(0.8, 1.6)
        return collected

    def _open_random_profile_results_and_score(self, search_query: str) -> int:
        settings = self.config.get("candidate_discovery", {})
        pages = int(settings.get("result_collection_pages", 4))
        max_profiles = int(settings.get("max_profiles_to_open_per_query", settings.get("max_candidates_per_query", 25)))
        opened = 0
        seen_signatures: set[str] = set()
        no_progress = 0
        previous_page_signature = ""

        for page in range(1, pages + 1):
            candidates = self._visible_profile_result_selectors()
            random.shuffle(candidates)
            page_opened = 0
            for target in candidates:
                if opened >= max_profiles:
                    return opened
                try:
                    signature = str(target.get("signature") or "")
                    if signature in seen_signatures:
                        continue
                    seen_signatures.add(signature)
                    self.d.click(int(target["x"]), int(target["y"]))
                    self.think(1.2, 2.2)
                    if not self._looks_like_open_profile():
                        self.logger.log("candidate_profile_open", search_query, "skipped", "click_did_not_open_profile")
                        self._return_to_results_if_needed()
                        continue
                    scored_candidate = self._score_open_profile_candidate(search_query)
                    opened += 1
                    if scored_candidate is None:
                        self.logger.log("candidate_profile_open", search_query, "opened_unscored", f"opened={opened},page={page}")
                    else:
                        self._maybe_connect_scored_profile(scored_candidate, search_query)
                        page_opened += 1
                        self.logger.log("candidate_profile_open", search_query, "scored", f"opened={opened},page={page}")
                    self._return_to_results_if_needed()
                    self.think(0.6, 1.2)
                except Exception as exc:
                    self.logger.log("candidate_profile_open", search_query, "failed", repr(exc))
                    self._return_to_results_if_needed()

            page_signature = self._page_signature()
            if page_opened == 0 or page_signature == previous_page_signature:
                no_progress += 1
            else:
                no_progress = 0
            if no_progress >= int(settings.get("no_progress_scroll_limit", 2)):
                break
            previous_page_signature = page_signature
            self._safe_results_scroll_down()
            self.think(0.8, 1.6)
        return opened

    def _visible_profile_result_selectors(self):
        if self._is_real_linkedin_app() and self._is_real_home_context():
            return []
        selectors = []
        seen: set[str] = set()
        candidates = []
        try:
            width, height = self.d.window_size()
        except Exception:
            width, height = 0, 0
        try:
            candidates.extend(list(self.d(className="android.widget.TextView")))
            candidates.extend(list(self.d(className="android.view.ViewGroup")))
            candidates.extend(list(self.d(className="android.widget.Button")))
        except Exception:
            pass
        for selector in candidates:
            try:
                info = selector.info or {}
                text = self._xml_unescape(str(info.get("text") or info.get("contentDescription") or ""))
                if not self._looks_like_profile_result_text(text):
                    continue
                if not self._looks_like_result_row_bounds(info, width, height):
                    continue
                signature = self._selector_signature(info)
                if signature in seen:
                    continue
                seen.add(signature)
                bounds = info.get("bounds") or {}
                left = int(bounds.get("left", 0))
                right = int(bounds.get("right", 0))
                top = int(bounds.get("top", 0))
                bottom = int(bounds.get("bottom", 0))
                x = max(int(width * 0.18), min(int(width * 0.62), left + int((right - left) * 0.35))) if width else (left + right) // 2
                y = max(int(height * 0.24), min(int(height * 0.84), (top + bottom) // 2)) if height else (top + bottom) // 2
                selectors.append({"signature": signature, "x": x, "y": y, "text": text})
            except Exception:
                pass
        selectors.extend(self._visible_profile_result_selectors_from_xml(seen, width, height))
        return sorted(selectors, key=lambda item: (int(item.get("y", 0)), str(item.get("signature", ""))))

    def _visible_profile_result_selectors_from_xml(self, seen: set[str], width: int, height: int) -> list[dict]:
        selectors: list[dict] = []
        xml = self._visible_hierarchy()
        for match in re.finditer(r"<node\b[^>]*>", xml):
            tag = match.group(0)
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', tag))
            text = self._xml_unescape(" ".join(part for part in [attrs.get("text", ""), attrs.get("content-desc", "")] if part).strip())
            if not self._looks_like_profile_result_text(text):
                continue
            bounds_text = attrs.get("bounds", "")
            bounds_match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_text)
            if not bounds_match:
                continue
            left, top, right, bottom = [int(value) for value in bounds_match.groups()]
            info = {"bounds": {"left": left, "top": top, "right": right, "bottom": bottom}, "text": text}
            if not self._looks_like_result_row_bounds(info, width, height):
                continue
            signature = f"{text[:120]}|{bounds_text}"
            if signature in seen:
                continue
            seen.add(signature)
            x = max(int(width * 0.18), min(int(width * 0.62), left + int((right - left) * 0.35))) if width else (left + right) // 2
            y = max(int(height * 0.24), min(int(height * 0.84), (top + bottom) // 2)) if height else (top + bottom) // 2
            selectors.append({"signature": signature, "x": x, "y": y, "text": text})
        return selectors

    def _looks_like_profile_result_text(self, text: str) -> bool:
        if not self._is_candidate_result_text(text):
            return False
        clean = text.strip()
        lowered = clean.lower()
        blocked_exact = {
            "1st", "2nd", "3rd", "people", "connections", "all filters", "show results", "apply",
            "posts", "jobs", "companies", "groups", "schools", "courses", "services", "events",
        }
        if lowered in blocked_exact:
            return False
        blocked = ["job", "hiring now", "company", "group", "school", "course"]
        if any(term == lowered or lowered.startswith(term + " ") for term in blocked):
            return False
        scoring = self.config.get("candidate_scoring", {})
        profile_terms = ["1st", "2nd", "connect", "follow", "message", "followers", "connections", "view profile"]
        for key in ("title_keywords", "company_keywords", "positive_keywords"):
            profile_terms.extend(str(value).lower() for value in scoring.get(key, []))
        if any(term and term in lowered for term in profile_terms):
            return True
        return self._looks_like_person_name_text(clean) or self._looks_like_profile_headline_text(clean)

    def _looks_like_person_name_text(self, text: str) -> bool:
        clean = re.sub(r"\s+", " ", text.strip())
        if not 3 <= len(clean) <= 80:
            return False
        if any(char.isdigit() for char in clean):
            return False
        words = clean.split()
        if not 2 <= len(words) <= 5:
            return False
        alpha_words = [re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'’-]", "", word) for word in words]
        if any(len(word) < 2 for word in alpha_words):
            return False
        return sum(1 for word in alpha_words if word[:1].isupper()) >= min(2, len(alpha_words))

    def _looks_like_profile_headline_text(self, text: str) -> bool:
        lowered = text.lower()
        headline_signals = ["founder", "co-founder", "ceo", "cto", "engineer", "developer", "manager", "director", "student", " at ", "@"]
        return any(signal in lowered for signal in headline_signals)

    def _looks_like_result_row_bounds(self, info: dict, width: int, height: int) -> bool:
        if not height:
            return True
        bounds = info.get("bounds") or {}
        top = int(bounds.get("top", 0))
        bottom = int(bounds.get("bottom", 0))
        if bottom <= top:
            return False
        center_y = (top + bottom) // 2
        # Exclude search bar/filter chips/header tabs and bottom nav.
        return int(height * 0.22) <= center_y <= int(height * 0.86)

    def _selector_signature(self, info: dict) -> str:
        bounds = info.get("bounds") or {}
        text = str(info.get("text") or info.get("contentDescription") or "")[:120]
        return f"{text}|{bounds}"

    def _looks_like_open_profile(self) -> bool:
        if self.target == "app":
            try:
                if self.d(resourceId=self.rid("profile_page")).exists(timeout=0.4):
                    return True
            except Exception:
                pass
            try:
                xml = self._visible_hierarchy().lower()
                if self._is_real_linkedin_app():
                    return self._has_real_profile_signal(xml)
                return "profile page" in xml or self.rid("profile_page").lower() in xml
            except Exception:
                return False
        return False

    def _return_to_results_if_needed(self) -> None:
        try:
            if self._is_real_linkedin_app() and self._is_home_feed_ready():
                self.logger.log("return_to_results", self.target, "skipped", "already_home_no_back")
                return
            if self._is_search_page_open(timeout=0.3):
                return
            if self._looks_like_open_profile() or self._current_mock_page_name() == "profile":
                for attempt in range(1, 3):
                    self.d.press("back")
                    self.think(0.8, 1.5)
                    if self._is_search_page_open(timeout=0.6):
                        self.logger.log("return_to_results", self.target, "success", f"attempt={attempt}")
                        return
                self.logger.log("return_to_results", self.target, "failed", f"current={self._current_mock_page_name()}")
                return
        except Exception:
            pass

    def _extract_people_result_candidates(self, search_query: str, page: int) -> list[Candidate]:
        if self._is_real_linkedin_app() and self._is_real_home_context():
            self.logger.log("candidate_extract", search_query, "skipped", "home_recommendations_not_search_results")
            return []
        row_windows = [str(item.get("text") or "") for item in self._visible_profile_result_selectors() if str(item.get("text") or "").strip()]
        blocks = self._visible_result_text_blocks()
        candidates: list[Candidate] = []
        windows = row_windows + [window for window in self._candidate_windows_from_blocks(blocks) if window not in row_windows]
        for sequence, window in enumerate(windows, start=1):
            candidate = self.candidate_extractor.from_visible_text(
                window,
                search_query,
                f"linkedin_people_results_page_{page}",
                sequence,
            )
            if candidate:
                if self._is_generic_candidate_name(candidate.name):
                    continue
                candidate.additional_metadata["raw_visible_text"] = window[:500]
                candidates.append(candidate)
        return candidates

    def _visible_result_text_blocks(self) -> list[str]:
        blocks: list[str] = []
        try:
            for node in self.d(className="android.widget.TextView"):
                info = node.info or {}
                text = self._xml_unescape(str(info.get("text") or info.get("contentDescription") or ""))
                if self._is_candidate_result_text(text):
                    blocks.append(text)
        except Exception:
            pass
        xml = self._visible_hierarchy()
        values = re.findall(r'text="([^"]+)"|content-desc="([^"]+)"', xml)
        for left, right in values:
            text = self._xml_unescape(left or right)
            if self._is_candidate_result_text(text):
                blocks.append(text)
        return self._dedupe_text_blocks(blocks)

    def _is_candidate_result_text(self, text: str) -> bool:
        clean = text.strip()
        if len(clean) < 2 or len(clean) > 240:
            return False
        if self._is_generic_candidate_name(clean):
            return False
        noise_exact = {
            "home", "people", "jobs", "my network", "notifications", "messaging", "search", "premium",
            "posts", "companies", "groups", "events", "services", "schools", "courses",
        }
        if clean.lower() in noise_exact:
            return False
        return True

    def _candidate_windows_from_blocks(self, blocks: list[str]) -> list[str]:
        windows: list[str] = []
        if not blocks:
            return windows
        for index in range(0, len(blocks), 3):
            window = "\n".join(blocks[index : index + 5])
            lowered = window.lower()
            signals = ["1st", "2nd", "connect", "follow", "message", " at ", "followers", "connections"]
            if any(signal in lowered for signal in signals):
                windows.append(window)
        return windows

    def _safe_results_scroll_down(self) -> None:
        try:
            width, height = self.d.window_size()
            x = int(width * 0.50)
            self.d.swipe(x, int(height * 0.78), x, int(height * 0.34), duration=0.45)
            time.sleep(0.5)
        except Exception:
            self._scroll_content_down()

    def _retry_search_with_profile_filter_only(self, search_query: str) -> bool:
        settings = self.config.get("candidate_discovery", {})
        if not settings.get("fallback_to_profile_filter_only_when_empty", True):
            return False
        if self.target != "app" or not settings.get("apply_people_search_filters", True):
            return False
        try:
            self.logger.log("candidate_search_fallback", search_query, "started", "profile_filter_only")
            self._log_ui_snapshot("fallback_before_profile_only", search_query)
            if not self._is_search_page_open(timeout=0.8):
                self.logger.log("candidate_search_fallback", search_query, "failed", f"not_on_results,current={self._current_mock_page_name()}")
                return False
            self._open_all_search_results(search_query)
            self._apply_candidate_search_filters(search_query, include_connections=False)
            cleared = self._clear_connection_type_filters(search_query)
            self._wait_for_profile_results(search_query)
            self._log_ui_snapshot("fallback_after_profile_only", search_query)
            self.logger.log("candidate_search_fallback", search_query, "applied", f"profile_filter_only,cleared={','.join(cleared) or 'none'}")
            return True
        except Exception as exc:
            self.logger.log("candidate_search_fallback", search_query, "failed", repr(exc))
            return False

    def _clear_connection_type_filters(self, search_query: str) -> list[str]:
        cleared: list[str] = []
        configured = [str(label) for label in self.config.get("candidate_discovery", {}).get("connection_filters", ["1st", "2nd"])]

        # On LinkedIn result pages selected connection chips are usually visible
        # near the top filter row. Only tap those top chips; broad textContains
        # matches can hit "1st/2nd" badges inside profile rows.
        for label in configured:
            if self._click_top_filter_chip(label, timeout=0.25):
                cleared.append(label)
                self.think(0.25, 0.7)
        if cleared:
            self.logger.log("search_filter_connections", search_query, "cleared", f"direct={','.join(cleared)}")
            return cleared

        if not self._open_connection_filter_menu(search_query):
            self.logger.log("search_filter_connections", search_query, "clear_skipped", "menu_not_found")
            return cleared
        for label in configured:
            if self._click_filter_option(label, timeout=0.5):
                cleared.append(label)
                self.think(0.2, 0.6)
        if cleared:
            self._apply_open_filter_dialog(search_query)
            self.logger.log("search_filter_connections", search_query, "cleared", f"menu={','.join(cleared)}")
        else:
            if self._is_real_linkedin_app():
                self.logger.log("search_filter_connections", search_query, "clear_skipped", "selected_filters_not_found_no_back")
                return cleared
            try:
                self.d.press("back")
                self.think(0.4, 0.9)
            except Exception:
                pass
            self.logger.log("search_filter_connections", search_query, "clear_skipped", "selected_filters_not_found")
        return cleared

    def _wait_for_profile_results(self, search_query: str, timeout_seconds: float = 4.0) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self._visible_profile_result_selectors() or self._extract_people_result_candidates(search_query, page=0):
                self.logger.log("candidate_search_results_wait", search_query, "success", "profiles_visible")
                return True
            self.think(0.4, 0.8)
        self.logger.log("candidate_search_results_wait", search_query, "empty", "profiles_not_detected")
        return False

    def _log_ui_snapshot(self, label: str, target: str) -> None:
        if self.target != "app":
            return
        try:
            page = self._current_mock_page_name()
            results = len(self._visible_profile_result_selectors())
            bottom_nav = self._is_bottom_menu_visible()
            search_open = self._is_search_page_open(timeout=0.2)
            self.logger.log(
                "ui_snapshot",
                target,
                "observed",
                f"label={label},page={page},visible_results={results},search_open={search_open},bottom_nav={bottom_nav}",
            )
        except Exception as exc:
            self.logger.log("ui_snapshot", target, "failed", f"label={label},error={exc!r}")

    def _apply_candidate_search_filters(self, search_query: str, include_connections: bool = True) -> None:
        settings = self.config.get("candidate_discovery", {})
        if self.target != "app" or not settings.get("apply_people_search_filters", True):
            return
        try:
            if self._select_people_results_filter(search_query):
                self.think(0.7, 1.5)
            if include_connections and settings.get("apply_connection_filters", True):
                selected = self._select_connection_type_filters(search_query)
                self.logger.log("candidate_search_filters", search_query, "applied", f"people=true,connections={','.join(selected) or 'none'}")
            else:
                detail = "people=true,connections=disabled" if include_connections else "people=true,connections=profile_filter_only"
                self.logger.log("candidate_search_filters", search_query, "applied", detail)
        except Exception as exc:
            self.logger.log("candidate_search_filters", search_query, "failed", repr(exc))

    def _select_people_results_filter(self, search_query: str) -> bool:
        selectors = [
            self.d(text="People"),
            self.d(textContains="People"),
            self.d(description="People"),
            self.d(descriptionContains="People"),
        ]
        for selector in selectors:
            try:
                if selector.exists(timeout=0.8):
                    selector.click()
                    self.logger.log("search_filter_people", search_query, "clicked", "selector")
                    return True
            except Exception:
                pass
        if self.config.get("candidate_discovery", {}).get("allow_coordinate_filter_fallbacks", False) or not self._is_real_linkedin_app():
            try:
                # Coordinate fallback is disabled by default on real LinkedIn to
                # avoid random taps when the UI layout changes.
                width, height = self.d.window_size()
                for x_ratio in (0.18, 0.28, 0.38):
                    self.d.click(int(width * x_ratio), int(height * 0.16))
                    self.think(0.3, 0.8)
                    if self.d(textContains="People").exists(timeout=0.2) or self.d(textContains="Connect").exists(timeout=0.2):
                        self.logger.log("search_filter_people", search_query, "clicked", f"coordinate_x={x_ratio}")
                        return True
            except Exception:
                pass
        self.logger.log("search_filter_people", search_query, "not_found", "continuing")
        return False

    def _select_connection_type_filters(self, search_query: str) -> list[str]:
        selected: list[str] = []
        configured = [str(label) for label in self.config.get("candidate_discovery", {}).get("connection_filters", ["1st", "2nd"])]

        # Some LinkedIn result layouts expose 1st/2nd as chips directly after
        # tapping People. Select only top filter chips; result rows also contain
        # 1st/2nd badges and must not be tapped here.
        for label in configured:
            if self._click_top_filter_chip(label, timeout=0.35):
                selected.append(label)
                self.think(0.2, 0.6)
        if selected:
            self.logger.log("search_filter_connections", search_query, "clicked", f"direct={','.join(selected)}")
            return selected

        if not self._open_connection_filter_menu(search_query):
            return selected
        for label in configured:
            if self._click_filter_option(label):
                selected.append(label)
                self.think(0.2, 0.6)
            else:
                self.logger.log("search_filter_option", search_query, "not_found", label)
        if selected:
            self._apply_open_filter_dialog(search_query)
        else:
            if self._is_real_linkedin_app():
                self.logger.log("search_filter_connections", search_query, "not_found", "no_options_selected_no_back")
                return selected
            try:
                self.d.press("back")
                self.think(0.4, 0.9)
            except Exception:
                pass
        return selected

    def _open_connection_filter_menu(self, search_query: str) -> bool:
        for label in ("Connections", "Connection degree", "All filters", "Filters"):
            if self._click_top_filter_chip(label, timeout=0.35, fuzzy=True):
                self.think(0.6, 1.2)
                self.logger.log("search_filter_connections", search_query, "opened", f"top_chip={label}")
                return True

        selectors = [
            self.d(text="Connections"),
            self.d(textContains="Connections"),
            self.d(descriptionContains="Connections"),
            self.d(text="Connection degree"),
            self.d(textContains="Connection degree"),
            self.d(descriptionContains="Connection degree"),
            self.d(text="All filters"),
            self.d(textContains="All filters"),
            self.d(descriptionContains="All filters"),
            self.d(text="Filters"),
            self.d(textContains="Filters"),
            self.d(descriptionContains="Filters"),
        ]
        for attempt in range(1, 3):
            for selector in selectors:
                try:
                    if selector.exists(timeout=0.8) and self._selector_is_top_filter_chip(selector):
                        selector.click()
                        self.think(0.6, 1.2)
                        self.logger.log("search_filter_connections", search_query, "opened", f"selector_attempt={attempt}")
                        return True
                except Exception:
                    pass
            if attempt == 1:
                self._horizontal_filter_chip_scroll()
        if self.config.get("candidate_discovery", {}).get("allow_coordinate_filter_fallbacks", False) or not self._is_real_linkedin_app():
            try:
                width, height = self.d.window_size()
                # Top filter chips often sit just below the search bar.
                for x_ratio in (0.48, 0.62, 0.76):
                    self.d.click(int(width * x_ratio), int(height * 0.16))
                    self.think(0.5, 1.0)
                    if self.d(textContains="1st").exists(timeout=0.3) or self.d(textContains="2nd").exists(timeout=0.3):
                        self.logger.log("search_filter_connections", search_query, "opened", f"coordinate_x={x_ratio}")
                        return True
            except Exception:
                pass
        self.logger.log("search_filter_connections", search_query, "not_found", "continuing")
        return False

    def _click_top_filter_chip(self, label: str, timeout: float = 0.5, fuzzy: bool = False) -> bool:
        option_texts = [label, f"{label} connections", f"{label} degree", f"{label}-degree"]
        selectors = []
        for text in option_texts:
            selectors.extend([self.d(text=text), self.d(description=text)])
            if fuzzy:
                selectors.extend([self.d(textContains=text), self.d(descriptionContains=text)])
        for selector in selectors:
            try:
                if selector.exists(timeout=timeout) and self._selector_is_top_filter_chip(selector):
                    selector.click()
                    return True
            except Exception:
                pass
        return False

    def _selector_is_top_filter_chip(self, selector) -> bool:
        try:
            info = selector.info or {}
            width, height = self.d.window_size()
            return self._bounds_are_top_filter_chip(info.get("bounds") or {}, width, height)
        except Exception:
            return False

    def _bounds_are_top_filter_chip(self, bounds: dict, width: int, height: int) -> bool:
        if not height:
            return False
        top = int(bounds.get("top", 0))
        bottom = int(bounds.get("bottom", 0))
        left = int(bounds.get("left", 0))
        right = int(bounds.get("right", 0))
        if bottom <= top or right <= left:
            return False
        center_y = (top + bottom) // 2
        center_x = (left + right) // 2
        return int(height * 0.09) <= center_y <= int(height * 0.24) and int(width * 0.03) <= center_x <= int(width * 0.97)

    def _horizontal_filter_chip_scroll(self) -> None:
        try:
            width, height = self.d.window_size()
            y = int(height * 0.16)
            self.d.swipe(int(width * 0.82), y, int(width * 0.28), y, duration=0.25)
            self.think(0.3, 0.7)
        except Exception:
            pass

    def _click_filter_option(self, label: str, timeout: float = 0.6) -> bool:
        option_texts = [label, f"{label} connections", f"{label} degree", f"{label}-degree"]
        selectors = []
        for text in option_texts:
            selectors.extend([self.d(text=text), self.d(description=text), self.d(textContains=text), self.d(descriptionContains=text)])
        for attempt in range(1, 3):
            for selector in selectors:
                try:
                    if selector.exists(timeout=timeout):
                        selector.click()
                        return True
                except Exception:
                    pass
            if attempt == 1:
                try:
                    width, height = self.d.window_size()
                    self.d.swipe(int(width * 0.72), int(height * 0.76), int(width * 0.72), int(height * 0.46), duration=0.25)
                    self.think(0.3, 0.7)
                except Exception:
                    pass
        return False

    def _apply_open_filter_dialog(self, search_query: str) -> None:
        for selector in [
            self.d(text="Show results"),
            self.d(textContains="Show results"),
            self.d(text="Apply"),
            self.d(textContains="Apply"),
            self.d(descriptionContains="Show results"),
            self.d(descriptionContains="Apply"),
        ]:
            try:
                if selector.exists(timeout=0.7):
                    selector.click()
                    self.logger.log("search_filter_apply", search_query, "clicked", "selector")
                    self.think(0.8, 1.5)
                    return
            except Exception:
                pass
        try:
            if self._is_real_linkedin_app():
                self.logger.log("search_filter_apply", search_query, "skipped", "apply_not_found_no_back")
                return
            self.d.press("back")
            self.think(0.5, 1.0)
        except Exception:
            pass

    def _click_contact(self, name: str) -> bool:
        if self.target == "app":
            for attempt in range(1, 3):
                if self._click_visible_profile_result(name):
                    return True

                # LinkedIn-like search screens may first show a typeahead row plus
                # "Show all results". Open full results, then retry profile rows.
                for selector in [
                    self.d(text="Show all results"),
                    self.d(textContains="Show all results"),
                    self.d(descriptionContains="Show all results"),
                    self.d(textContains="See all results"),
                    self.d(descriptionContains="See all results"),
                ]:
                    try:
                        if selector.exists(timeout=0.9):
                            selector.click()
                            self.logger.log("search_show_all_results", name, "clicked", f"attempt={attempt}")
                            self.think(1.0, 2.0)
                            self._apply_candidate_search_filters(name)
                            if self._click_visible_profile_result(name):
                                return True
                    except Exception:
                        pass

                # If the app rejected navigation and returned to search, clear the
                # transient state with Back, then retry once.
                if attempt == 1 and self._is_search_page_open(timeout=0.5):
                    self.logger.log("search_profile_rejected", name, "retrying", "returned_to_search_after_result_click")
                    try:
                        if self._is_real_linkedin_app():
                            self._open_all_search_results(name)
                            self._wait_for_profile_results(name)
                        else:
                            self.d.press("back")
                            self.think(0.5, 1.0)
                            self._focus_search_box()
                            self._type_text_human(name)
                            self.think(1.0, 2.0)
                    except Exception:
                        pass
                    continue

            # Last-resort coordinate result taps are disabled on real LinkedIn;
            # they caused accidental random clicks when result layouts shifted.
            if not self._is_real_linkedin_app() or self.config.get("candidate_discovery", {}).get("allow_coordinate_result_fallbacks", False):
                try:
                    width, height = self.d.window_size()
                    for y_ratio in (0.32, 0.40, 0.48):
                        self.d.click(int(width * random.uniform(0.30, 0.70)), int(height * y_ratio))
                        self.think(0.6, 1.2)
                        if self.d(resourceId=self.rid("profile_page")).exists(timeout=1.0):
                            return True
                except Exception:
                    pass
        return self._click_text(name)

    def _click_visible_profile_result(self, name: str) -> bool:
        selectors = [
            self.d(resourceId=self.rid("person_result"), text=name),
            self.d(resourceId=self.rid("person_result"), textContains=name),
            self.d(resourceId=self.rid("person_result")),
            self.d(description=f"Open profile {name}"),
            self.d(descriptionContains=f"Open profile {name}"),
            self.d(descriptionContains=name),
            self.d(text=name),
            self.d(textContains=name),
        ]
        for selector in selectors:
            try:
                if selector.exists(timeout=1.2):
                    self.think(0.2, 0.7)
                    selector.click()
                    self.think(0.7, 1.4)
                    if self.d(resourceId=self.rid("profile_page")).exists(timeout=1.0):
                        return True
                    if self._looks_like_open_profile():
                        return True
                    if self._is_search_page_open(timeout=0.3):
                        self.logger.log("search_result_click", name, "rejected", "still_on_search_page")
                        continue
            except Exception:
                pass

        for target in self._visible_profile_result_selectors()[:5]:
            try:
                self.d.click(int(target["x"]), int(target["y"]))
                self.think(0.9, 1.8)
                if self._looks_like_open_profile():
                    self.logger.log("search_result_click", name, "opened", f"row_target={target.get('text', '')[:80]}")
                    return True
                if self._is_search_page_open(timeout=0.3):
                    self.logger.log("search_result_click", name, "rejected", "row_target_still_on_search_page")
                    continue
            except Exception:
                pass
        return False

    def _go_home(self) -> bool:
        if self.target == "app":
            if self._is_real_linkedin_app() and self._is_home_feed_ready():
                self.logger.log("home", self.target, "success", "already_home")
                return True
            for attempt in range(1, 4):
                self._reveal_bottom_nav()
                if self._tap_home_tab():
                    self.think(0.6, 1.2)
                    if self._is_home_feed_ready():
                        return True
                # If a profile/search overlay swallowed the Home tap, back out
                # once and retry against the bottom nav. Avoid swipe-down here;
                # it can trigger refresh or scroll the wrong page.
                try:
                    current = self._current_mock_page_name()
                    if not self._is_real_linkedin_app() and (current in {"search_results", "search"} or current == "profile"):
                        self.d.press("back")
                        self.think(0.5, 1.0)
                except Exception:
                    pass
                self._reveal_bottom_nav()
            self.logger.log("home", self.target, "not_confirmed", f"page={self._current_mock_page_name()}")
            return False
        self._click_text("Home")
        time.sleep(random.uniform(0.5, 1.2))
        return True

    def _tap_home_tab(self) -> bool:
        selectors = [
            self.d(resourceId=self.rid("home_button")),
            self.d(resourceId=self.rid("home_tab")),
            self.d(description="Home"),
            self.d(descriptionContains="Home"),
            self.d(text="Home"),
        ]
        for selector in selectors:
            try:
                if selector.exists(timeout=0.6) and (not self._is_real_linkedin_app() or self._selector_is_bottom_nav_item(selector)):
                    selector.click()
                    return True
            except Exception:
                pass
        try:
            width, height = self.d.window_size()
            for x_ratio in (0.10, 0.12, 0.08):
                self.d.click(int(width * x_ratio), int(height * 0.955))
                self.think(0.4, 0.8)
                if self._is_home_feed_ready() or (self._is_real_linkedin_app() and self._is_bottom_menu_visible()):
                    return True
        except Exception:
            pass
        return False

    def _selector_is_bottom_nav_item(self, selector) -> bool:
        try:
            info = selector.info or {}
            bounds = info.get("bounds") or {}
            width, height = self.d.window_size()
            top = int(bounds.get("top", 0))
            bottom = int(bounds.get("bottom", 0))
            left = int(bounds.get("left", 0))
            right = int(bounds.get("right", 0))
            if bottom <= top or right <= left:
                return False
            center_y = (top + bottom) // 2
            center_x = (left + right) // 2
            return center_y >= int(height * 0.82) and int(width * 0.00) <= center_x <= int(width * 0.28)
        except Exception:
            return False

    def _focus_search_box(self) -> bool:
        if self.target == "app":
            try:
                search = self.d(resourceId=self.rid("search_input"))
                if search.exists(timeout=1.2):
                    try:
                        bounds = search.info.get("bounds") or {}
                        left, top = int(bounds.get("left", 0)), int(bounds.get("top", 0))
                        right, bottom = int(bounds.get("right", 0)), int(bounds.get("bottom", 0))
                        if right > left and bottom > top:
                            self.d.click((left + right) // 2, (top + bottom) // 2)
                        else:
                            search.click()
                    except Exception:
                        search.click()
                    self.think(0.2, 0.6)
                    self._clear_focused_text_field()
                    return self._confirm_text_entry_focus("resource_id_search_input")
            except Exception:
                pass

            candidates = [
                self.d(description="Search people"),
                self.d(text="Search"),
                self.d(text="Search people"),
                self.d(className="android.widget.EditText"),
            ]
            for candidate in candidates:
                try:
                    if candidate.exists(timeout=0.7):
                        candidate.click()
                        self.think(0.2, 0.6)
                        self._clear_focused_text_field()
                        return self._confirm_text_entry_focus("selector_search_input")
                except Exception:
                    pass

            # Top-bar coordinate fallback. Previous fallback clicked too low and
            # could hit the profile banner; keep this inside the search field row.
            width, height = self.d.window_size()
            x = int(width * random.uniform(0.28, 0.66))
            y = int(height * random.uniform(0.045, 0.085))
            self.d.click(x, y)
            time.sleep(random.uniform(0.35, 0.9))
            self._clear_focused_text_field()
            return self._confirm_text_entry_focus("coordinate_search_input")

        candidates = [
            self.d(description="Search people"),
            self.d(text="Search people"),
            self.d(className="android.widget.EditText"),
        ]
        for candidate in candidates:
            try:
                if candidate.exists(timeout=0.7):
                    candidate.click()
                    self.think(0.2, 0.6)
                    self._clear_focused_text_field()
                    return True
            except Exception:
                pass
        return False

    def _clear_focused_text_field(self) -> None:
        try:
            self.d.clear_text()
            self.think(0.1, 0.25)
        except Exception:
            try:
                focused = self.d(focused=True)
                if focused.exists(timeout=0.2):
                    focused.clear_text()
                    self.think(0.1, 0.25)
            except Exception:
                pass

    def _confirm_text_entry_focus(self, label: str) -> bool:
        if self.target != "app" or not self._is_real_linkedin_app():
            return True
        deadline = time.time() + 1.2
        while time.time() < deadline:
            try:
                focused = self.d(focused=True)
                if focused.exists(timeout=0.15):
                    info = focused.info or {}
                    class_name = str(info.get("className") or "")
                    visible_label = " ".join(str(info.get(key) or "") for key in ("text", "contentDescription")).lower()
                    if "edittext" in class_name.lower() or "search" in visible_label:
                        self.logger.log("search_focus", label, "verified", class_name or visible_label[:80])
                        return True
            except Exception:
                pass
            try:
                if self.d(className="android.widget.EditText", focused=True).exists(timeout=0.15):
                    self.logger.log("search_focus", label, "verified", "focused_edittext")
                    return True
            except Exception:
                pass
            try:
                edit = self.d(className="android.widget.EditText")
                if edit.exists(timeout=0.15):
                    info = edit.info or {}
                    width, height = self.d.window_size()
                    bounds = info.get("bounds") or {}
                    top = int(bounds.get("top", 0))
                    bottom = int(bounds.get("bottom", 0))
                    center_y = (top + bottom) // 2 if bottom > top else 0
                    if center_y and center_y <= int(height * 0.22):
                        self.logger.log("search_focus", label, "verified", "top_edittext_visible")
                        return True
            except Exception:
                pass
            xml = self._visible_hierarchy()
            if re.search(r'class="android\.widget\.EditText"[^>]*focused="true"', xml):
                self.logger.log("search_focus", label, "verified", "hierarchy_focused_edittext")
                return True
            self.think(0.12, 0.25)
        self.logger.log("search_focus", label, "failed", "no_focused_text_field")
        return False

    def _click_text(self, text: str) -> bool:
        selectors = [
            self.d(text=text),
            self.d(textContains=text),
            self.d(description=text),
            self.d(descriptionContains=text),
        ]
        for selector in selectors:
            try:
                if selector.exists(timeout=random.uniform(0.6, 1.2)):
                    self.think(0.2, 0.7)
                    selector.click()
                    return True
            except Exception:
                pass
        return self._click_xpath_text(text)

    def _click_xpath_text(self, text: str) -> bool:
        escaped = text.replace('"', '\\"')
        xpaths = [
            f'//*[@text="{escaped}"]',
            f'//*[contains(@text, "{escaped}")]',
            f'//*[@content-desc="{escaped}"]',
            f'//*[contains(@content-desc, "{escaped}")]',
        ]
        for xpath in xpaths:
            try:
                item = self.d.xpath(xpath)
                if item.exists:
                    self.think(0.2, 0.7)
                    item.click()
                    return True
            except Exception:
                pass
        return False

    def _type_text_human(self, text: str) -> bool:
        if self.target == "app" and self._is_real_linkedin_app():
            return self._type_text_human_real_app(text)

        typo_probability = float(self.human.get("typo_probability", 0.0))
        rethink_probability = float(self.human.get("typing_rethink_probability", 0.0))
        for index, char in enumerate(text):
            token = "%s" if char == " " else char

            if typo_probability > 0 and char.isalpha() and random.random() < typo_probability:
                wrong = random.choice("abcdefghijklmnopqrstuvwxyz")
                self.d.shell(f"input text {shlex.quote(wrong)}")
                time.sleep(random.uniform(0.12, 0.35))
                self.d.shell("input keyevent DEL")
                time.sleep(random.uniform(0.15, 0.45))

            self.d.shell(f"input text {shlex.quote(token)}")
            time.sleep(random.uniform(
                float(self.human.get("typing_delay_min_seconds", 0.09)),
                float(self.human.get("typing_delay_max_seconds", 0.32)),
            ))

            # Occasionally erase a correctly typed character and retype it, like
            # a human second-guessing a keystroke. Mock QA only.
            if char.isalpha() and index > 1 and random.random() < rethink_probability:
                time.sleep(random.uniform(0.12, 0.45))
                self.d.shell("input keyevent DEL")
                time.sleep(random.uniform(0.18, 0.65))
                self.d.shell(f"input text {shlex.quote(token)}")
                time.sleep(random.uniform(0.12, 0.45))

            if char == " " or (index > 1 and random.random() < 0.12):
                time.sleep(random.uniform(0.25, 0.9))
        return True

    def _type_text_human_real_app(self, text: str) -> bool:
        """Human-paced text entry for real LinkedIn runs.

        Keep it safe for the real app: type progressively with varied pauses but
        avoid typo/rethink loops that can accidentally trigger keyboard actions.
        """
        min_delay = float(self.human.get("real_app_typing_delay_min_seconds", self.human.get("typing_delay_min_seconds", 0.12)))
        max_delay = float(self.human.get("real_app_typing_delay_max_seconds", self.human.get("typing_delay_max_seconds", 0.32)))
        chunk_probability = float(self.human.get("real_app_typing_chunk_probability", 0.0))
        for attempt in range(1, 3):
            if attempt > 1:
                self._clear_focused_text_field()
                self.think(0.2, 0.45)
            index = 0
            while index < len(text):
                if text[index] != " " and chunk_probability > 0 and random.random() < chunk_probability:
                    chunk = text[index : min(len(text), index + random.randint(2, 3))]
                    if " " in chunk:
                        chunk = chunk.split(" ", 1)[0]
                    self._input_text_token(chunk)
                    index += len(chunk)
                    time.sleep(random.uniform(min_delay * 1.4, max_delay * 2.0))
                    continue
                self._input_text_token(text[index])
                index += 1
                time.sleep(random.uniform(min_delay, max_delay))
                if index > 1 and (text[index - 1] == " " or random.random() < 0.12):
                    time.sleep(random.uniform(0.22, 0.75))
            if self._typed_text_visible(text):
                self.logger.log("typing_verify", text[:40], "success", f"attempt={attempt}")
                return True
            self.logger.log("typing_verify", text[:40], "retrying" if attempt == 1 else "failed", f"attempt={attempt}")
        return False

    def _typed_text_visible(self, expected: str, timeout_seconds: float = 1.8) -> bool:
        expected_clean = re.sub(r"\s+", " ", expected.strip()).lower()
        if not expected_clean:
            return True
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            for selector in [self.d(focused=True), self.d(className="android.widget.EditText")]:
                try:
                    if selector.exists(timeout=0.15):
                        info = selector.info or {}
                        visible = " ".join(str(info.get(key) or "") for key in ("text", "contentDescription")).lower()
                        if expected_clean in re.sub(r"\s+", " ", visible):
                            return True
                except Exception:
                    pass
            try:
                if self.d(textContains=expected).exists(timeout=0.15) or self.d(descriptionContains=expected).exists(timeout=0.15):
                    return True
            except Exception:
                pass
            xml = self._visible_hierarchy().lower()
            if expected_clean in re.sub(r"\s+", " ", self._xml_unescape(xml)):
                return True
            self.think(0.15, 0.30)
        return False

    def _input_text_token(self, token: str) -> None:
        escaped = token.replace("%", "%25").replace(" ", "%s")
        self.d.shell(f"input text {shlex.quote(escaped)}")

    def _type_text_stable(self, text: str) -> None:
        """Keyboard-safe text entry fallback."""
        try:
            self._input_text_token(text)
            time.sleep(random.uniform(0.25, 0.55))
        except Exception:
            for char in text:
                self._input_text_token(char)
                time.sleep(random.uniform(0.03, 0.08))
