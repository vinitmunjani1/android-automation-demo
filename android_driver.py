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

        last_action = ""
        repeated = 0
        for step in range(1, action_count + 1):
            choices = ["feed", "feed", "pause", "home"]
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
            else:
                self.logger.log("idle_pause", self.target, "success", "random reading/thinking pause")
                self.think(
                    float(settings.get("idle_min_seconds", 1.2)),
                    float(settings.get("idle_max_seconds", 4.5)),
                )

        self.logger.log("random_journey_end", self.target, "success", f"remaining_contacts={len(remaining_contacts)}")

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

        if random.random() < float(self.config["like_probability"]):
            self.think(0.5, 1.7)
            if self._click_like_button():
                self.logger.log("like_post", f"visible_post_{index}")
                self.think(0.3, 1.0)
            else:
                self.logger.log("like_post", f"visible_post_{index}", "not_found")

        self._human_swipe(direction="up")
        self.logger.log("scroll_feed", f"post_window_{index}", "success", "humanized=random_delay+random_distance")
        if random.random() < 0.25:
            self.think(0.8, 2.0)

    def _human_swipe(self, direction: str = "up") -> None:
        width, height = self.d.window_size()
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
                start_y = int(height * random.uniform(0.62, 0.78))
                end_y = int(height * random.uniform(0.42, 0.58))
            elif gesture_type == "medium":
                start_y = int(height * random.uniform(0.70, 0.86))
                end_y = int(height * random.uniform(0.30, 0.48))
            else:
                start_y = int(height * random.uniform(0.78, 0.90))
                end_y = int(height * random.uniform(0.18, 0.34))
        else:
            start_y = int(height * random.uniform(0.28, 0.42))
            end_y = int(height * random.uniform(0.68, 0.84))

        duration = random.uniform(
            float(self.human.get("swipe_duration_min_seconds", 0.22)),
            float(self.human.get("swipe_duration_max_seconds", 1.45)),
        )
        self.d.swipe(center_x, start_y, center_x + horizontal_drift, end_y, duration=duration)

        # Small imperfect follow-up motions make the scroll less mechanically
        # smooth: a tiny nudge, a settling pause, or a slight reverse correction.
        roll = random.random()
        if roll < 0.22:
            time.sleep(random.uniform(0.12, 0.45))
            nudge_start = int(height * random.uniform(0.55, 0.72))
            nudge_end = int(nudge_start - height * random.uniform(0.06, 0.16))
            self.d.swipe(
                int(width * random.uniform(0.44, 0.56)),
                nudge_start,
                int(width * random.uniform(0.43, 0.57)),
                nudge_end,
                duration=random.uniform(0.12, 0.35),
            )
        elif roll < 0.34:
            time.sleep(random.uniform(0.18, 0.55))
            correction_start = int(height * random.uniform(0.38, 0.52))
            correction_end = int(correction_start + height * random.uniform(0.04, 0.11))
            self.d.swipe(
                int(width * random.uniform(0.44, 0.56)),
                correction_start,
                int(width * random.uniform(0.43, 0.57)),
                correction_end,
                duration=random.uniform(0.10, 0.28),
            )
        else:
            time.sleep(random.uniform(0.08, 0.32))

    def _click_like_button(self) -> bool:
        if self.target == "app":
            try:
                buttons = self.d(resourceId=self.rid("like_button"))
                if buttons.exists(timeout=0.8):
                    buttons.click()
                    return True
            except Exception:
                pass
        return self._click_text("Like") or self._click_xpath_text("Like")

    def _click_connect_button(self) -> bool:
        if self.target == "app":
            try:
                button = self.d(resourceId=self.rid("connect_button"))
                if button.exists(timeout=0.8):
                    button.click()
                    return True
            except Exception:
                pass
        return self._click_text("Connect")

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

        width, height = self.d.window_size()
        x = int(width * random.uniform(0.34, 0.62))
        y = int(height * random.uniform(0.15, 0.23))
        self.d.click(x, y)
        time.sleep(random.uniform(0.35, 0.9))
        try:
            self.d.clear_text()
        except Exception:
            pass
        return True

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

            if char == " " or (index > 1 and random.random() < 0.12):
                time.sleep(random.uniform(0.25, 0.9))
