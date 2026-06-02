from __future__ import annotations

import random
import shlex
import time
from typing import Iterable

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
        self.app_package = config.get("mock_app_package", "com.mockin.app")
        self.logger = logger

    def delay(self, multiplier: float = 1.0) -> None:
        lo = float(self.config["delay_min_seconds"])
        hi = float(self.config["delay_max_seconds"])
        jitter = random.uniform(0.85, 1.35)
        time.sleep(random.uniform(lo, hi) * multiplier * jitter)

    def think(self, min_seconds: float = 0.8, max_seconds: float = 2.4) -> None:
        time.sleep(random.uniform(min_seconds, max_seconds))

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
            self._go_home()
            self.think(0.7, 1.8)
            if not self._focus_search_box():
                self.logger.log("search_person", contact.name, "failed", "search input missing")
                continue
            self.think(0.2, 0.8)
            self._type_text_human(contact.name)
            self.logger.log("search_person", contact.name, "success", "typed_humanized=true")
            self.think(1.2, 3.0)

            if not self._click_contact(contact.name):
                self.logger.log("open_profile", contact.name, "not_found")
                continue
            self.logger.log("open_profile", contact.name, "success", f"{contact.title} at {contact.company}")
            self._analyze_open_profile(contact.name)
            self._return_profile_to_top(contact.name)

            min_view = float(self.config["profile_view_min_seconds"])
            max_view = float(self.config["profile_view_max_seconds"])
            time.sleep(random.uniform(min_view, max_view) + random.uniform(0.8, 2.8))

            if random.random() < float(self.config["connect_probability"]):
                self.think(0.5, 1.8)
                if self._click_connect_button():
                    self.logger.log("connect", contact.name, "clicked", "mock button")
                else:
                    self.logger.log("connect", contact.name, "not_found")
            else:
                self.logger.log("connect", contact.name, "skipped", "random decision")
            self.think(1.0, 2.8)

    def run_random_journey(self, contacts: list[Contact]) -> None:
        """Run a randomized, bounded mock QA journey.

        This varies test coverage order for the controlled mock app/site. It is
        not intended for stealth or for use on real social platforms.
        """
        settings = self.config.get("random_journey", {})
        min_actions = int(settings.get("min_actions", 8))
        max_actions = int(settings.get("max_actions", 18))
        action_count = random.randint(min_actions, max_actions)
        remaining_contacts = contacts[:]
        random.shuffle(remaining_contacts)
        self.logger.log("random_journey_start", self.target, "success", f"actions={action_count}")

        if self.target == "app" and self.config.get("check_notifications_on_start", True):
            self._check_notifications()

        last_action = ""
        repeated = 0
        for step in range(1, action_count + 1):
            choices = ["feed", "feed", "pause", "home"]
            if self.target == "app":
                choices.extend(["notifications", "network", "messages", "repost"])
            if remaining_contacts:
                choices.extend(["search", "search"])
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
            elif action == "search" and remaining_contacts:
                self._visit_contact(remaining_contacts.pop(0))
            elif action == "home":
                self._go_home()
                self.logger.log("home", self.target, "success", "random navigation")
                self.think(0.8, 2.4)
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

        self.logger.log("random_journey_end", self.target, "success", f"remaining_contacts={len(remaining_contacts)}")

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
        self._go_home()
        self.think(0.7, 1.8)
        if not self._focus_search_box():
            self.logger.log("search_person", contact.name, "failed", "search input missing")
            return
        self.think(0.2, 0.8)
        self._type_text_human(contact.name)
        self.logger.log("search_person", contact.name, "success", "typed_humanized=true")
        # Do not press Back here. On some Android devices the keyboard is not
        # considered open after adb text input, so Back closes the mock app.
        self.think(1.2, 3.0)

        if not self._click_contact(contact.name):
            self.logger.log("open_profile", contact.name, "not_found")
            return
        self.logger.log("open_profile", contact.name, "success", f"{contact.title} at {contact.company}")
        self._analyze_open_profile(contact.name)
        self._return_profile_to_top(contact.name)

        min_view = float(self.config["profile_view_min_seconds"])
        max_view = float(self.config["profile_view_max_seconds"])
        time.sleep(random.uniform(min_view, max_view) + random.uniform(0.8, 2.8))

        if random.random() < float(self.config["connect_probability"]):
            self.think(0.5, 1.8)
            if self._click_connect_button():
                self.logger.log("connect", contact.name, "clicked", "mock button")
            else:
                self.logger.log("connect", contact.name, "not_found")
        else:
            self.logger.log("connect", contact.name, "skipped", "random decision")
        self.think(1.0, 2.8)

    def _scroll_feed_once(self, index: int) -> None:
        self.think(
            float(self.human.get("feed_read_min_seconds", 1.8)),
            float(self.human.get("feed_read_max_seconds", 5.2)),
        )

        if self.target == "app" and random.random() < float(self.config.get("feed_profile_open_probability", 0.18)):
            if self._open_profile_from_feed():
                self.logger.log("open_profile_from_feed", f"visible_post_{index}", "success", "random feed profile open")
                self._analyze_open_profile(f"feed_profile_{index}")
                self._go_home()
                self.think(0.8, 2.0)
            else:
                self.logger.log("open_profile_from_feed", f"visible_post_{index}", "not_found", "no visible feed profile link")

        if random.random() < float(self.config["like_probability"]):
            self.think(0.5, 1.7)
            if self._click_like_button():
                self.logger.log("like_post", f"visible_post_{index}")
                self.think(0.3, 1.0)
            else:
                self.logger.log("like_post", f"visible_post_{index}", "not_found")

        self._scroll_content_down()
        self.logger.log("scroll_feed", f"post_window_{index}", "success", "content_down_safe_scroll")
        if random.random() < 0.25:
            self.think(0.8, 2.0)

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

    def _click_like_button(self) -> bool:
        if self.target == "app":
            selectors = [
                self.d(resourceId=self.rid("like_button"), text="Like"),
                self.d(text="Like"),
                self.d(description="Like"),
            ]
            for selector in selectors:
                try:
                    if selector.exists(timeout=0.8):
                        selector.click()
                        return True
                except Exception:
                    pass

            # Coordinate fallback for the first visible feed action row.
            try:
                width, height = self.d.window_size()
                self.d.click(int(width * random.uniform(0.12, 0.22)), int(height * random.uniform(0.55, 0.78)))
                self.think(0.2, 0.5)
                return True
            except Exception:
                pass
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
            self._scroll_content_down()
            self.logger.log("profile_scroll", f"{label}_{i}", "success", "content_down_safe_scroll")
        if random.random() < 0.45:
            self.think(0.8, 2.0)
        self.logger.log("profile_analysis_end", label, "success", "humanized_profile_review")

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
        width, height = self.d.window_size()
        start_x = int(width * random.uniform(0.42, 0.58))
        start_y = int(height * random.uniform(0.12, 0.30))
        end_x = start_x + int(width * random.uniform(-0.04, 0.04))
        end_y = int(height * random.uniform(0.86, 0.97))
        self._natural_drag(
            start_x,
            start_y,
            end_x,
            end_y,
            random.uniform(0.10, 0.32),
            small=True,
        )

    def _click_connect_button(self) -> bool:
        if self.target == "app":
            selectors = [
                self.d(resourceId=self.rid("connect_button")),
                self.d(resourceId=self.rid("connect_button"), textContains="Connect"),
                self.d(text="Connect"),
                self.d(textContains="Connect"),
                self.d(descriptionContains="Connect"),
            ]
            for selector in selectors:
                try:
                    if selector.exists(timeout=1.0):
                        selector.click()
                        self.think(0.3, 0.8)
                        return True
                except Exception:
                    pass

            # If the profile is slightly scrolled, bring top actions back into
            # view and retry once before using coordinates.
            try:
                self._fast_profile_reverse_swipe()
                self.think(0.4, 0.9)
                button = self.d(resourceId=self.rid("connect_button"))
                if button.exists(timeout=1.0):
                    button.click()
                    return True
            except Exception:
                pass

            # Mock profile top-card fallback: Connect is the left primary CTA.
            try:
                width, height = self.d.window_size()
                for y_ratio in (0.34, 0.40, 0.46):
                    self.d.click(int(width * random.uniform(0.18, 0.34)), int(height * y_ratio))
                    self.think(0.3, 0.8)
                    return True
            except Exception:
                pass
        return self._click_text("Connect")

    def _check_notifications(self) -> None:
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
        try:
            tab = self.d(resourceId=self.rid("notifications_tab"))
            if tab.exists(timeout=1.0):
                tab.click()
                self.think(1.0, 2.2)
                if self.d(resourceId=self.rid("notifications_page")).exists(timeout=1.0):
                    return True
        except Exception:
            pass

        for selector in [self.d(resourceId=self.rid("notifications_tab")), self.d(textContains="Notifications"), self.d(textContains="Alerts"), self.d(descriptionContains="Notifications")]:
            try:
                if selector.exists(timeout=0.8):
                    selector.click()
                    self.think(1.0, 2.2)
                    if self.d(resourceId=self.rid("notifications_page")).exists(timeout=1.0):
                        return True
            except Exception:
                pass

        # Bottom nav fallback. Notifications is the 4th of 5 tabs, around 70% width.
        try:
            width, height = self.d.window_size()
            for x_ratio in (0.70, 0.72, 0.68):
                self.d.click(int(width * x_ratio), int(height * 0.955))
                self.think(0.9, 1.8)
                if self.d(resourceId=self.rid("notifications_page")).exists(timeout=1.0):
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
        if self.target != "app":
            return False
        self.logger.log("repost", self.target, "started", "visible_post")
        self.think(0.8, 2.0)
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
        if self.target != "app":
            return
        self.logger.log("network_open", self.target, "started", "browse_suggestions")
        if not self._open_network_tab():
            self.logger.log("network_open", self.target, "failed", "network tab not clickable")
            return
        self.think(1.4, 3.8)
        if random.random() < 0.45:
            self._human_swipe(direction="up")
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
        for selector in [self.d(resourceId=self.rid("network_tab")), self.d(textContains="Network"), self.d(descriptionContains="Network")]:
            try:
                if selector.exists(timeout=0.8):
                    selector.click()
                    self.think(0.9, 1.8)
                    if self.d(resourceId=self.rid("network_page")).exists(timeout=1.0):
                        return True
            except Exception:
                pass
        try:
            width, height = self.d.window_size()
            self.d.click(int(width * 0.30), int(height * 0.955))
            self.think(0.9, 1.8)
            return self.d(resourceId=self.rid("network_page")).exists(timeout=1.0)
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
        if self.target != "app":
            return
        self.logger.log("messages_open", self.target, "started", "browse_inbox")
        if not self._open_messages_page():
            self.logger.log("messages_open", self.target, "failed", "messages not clickable")
            return
        self.think(1.4, 3.5)
        if not self._open_conversation():
            self.logger.log("conversation_open", self.target, "not_found", "no conversation")
            return
        self.think(1.2, 3.2)
        self._type_mock_message_and_send()

    def _open_messages_page(self) -> bool:
        for selector in [self.d(resourceId=self.rid("messages_button")), self.d(descriptionContains="Messaging")]:
            try:
                if selector.exists(timeout=0.8):
                    selector.click()
                    self.think(1.0, 2.0)
                    if self.d(resourceId=self.rid("messages_page")).exists(timeout=1.0):
                        return True
            except Exception:
                pass
        try:
            width, height = self.d.window_size()
            self.d.click(int(width * 0.93), int(height * 0.055))
            self.think(1.0, 2.0)
            return self.d(resourceId=self.rid("messages_page")).exists(timeout=1.0)
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

    def _click_contact(self, name: str) -> bool:
        if self.target == "app":
            selectors = [
                self.d(resourceId=self.rid("person_result"), text=name),
                self.d(resourceId=self.rid("person_result"), textContains=name),
                self.d(description=f"Open profile {name}"),
                self.d(descriptionContains=name),
                self.d(text=name),
                self.d(textContains=name),
            ]
            for selector in selectors:
                try:
                    if selector.exists(timeout=1.2):
                        self.think(0.2, 0.7)
                        selector.click()
                        return True
                except Exception:
                    pass

            # Last-resort native app fallback: tap the first search-result row area.
            # This is only for the controlled MockIn app where the first result card
            # appears directly below the top search header.
            try:
                width, height = self.d.window_size()
                self.d.click(int(width * 0.42), int(height * 0.28))
                self.think(0.5, 1.0)
                return self.d(resourceId=self.rid("profile_page")).exists(timeout=1.0)
            except Exception:
                pass
        return self._click_text(name)

    def _go_home(self) -> None:
        if self.target == "app":
            try:
                home = self.d(resourceId=self.rid("home_button"))
                if home.exists(timeout=0.8):
                    home.click()
                    time.sleep(random.uniform(0.5, 1.2))
                    return
            except Exception:
                pass
        self._click_text("Home")
        time.sleep(random.uniform(0.5, 1.2))
        for _ in range(random.randint(1, 2)):
            self._human_swipe(direction="down")
            time.sleep(random.uniform(0.25, 0.75))

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
                    try:
                        search.clear_text()
                    except Exception:
                        self.d.clear_text()
                    return True
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
                        self.d.clear_text()
                        return True
                except Exception:
                    pass

            # Top-bar coordinate fallback. Previous fallback clicked too low and
            # could hit the profile banner; keep this inside the search field row.
            width, height = self.d.window_size()
            x = int(width * random.uniform(0.28, 0.66))
            y = int(height * random.uniform(0.045, 0.085))
            self.d.click(x, y)
            time.sleep(random.uniform(0.35, 0.9))
            try:
                self.d.clear_text()
            except Exception:
                pass
            return True

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
                    self.d.clear_text()
                    return True
            except Exception:
                pass
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

    def _type_text_human(self, text: str) -> None:
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
