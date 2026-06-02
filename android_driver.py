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
            self.think(
                float(self.human.get("feed_read_min_seconds", 1.8)),
                float(self.human.get("feed_read_max_seconds", 5.2)),
            )

            if random.random() < float(self.config["like_probability"]):
                self.think(0.5, 1.7)
                if self._click_like_button():
                    self.logger.log("like_post", f"visible_post_{i}")
                    self.think(0.3, 1.0)
                else:
                    self.logger.log("like_post", f"visible_post_{i}", "not_found")

            self._human_swipe(direction="up")
            self.logger.log("scroll_feed", f"post_window_{i}", "success", "humanized=random_delay+random_distance")
            if random.random() < 0.25:
                self.think(0.8, 2.0)
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

    def _human_swipe(self, direction: str = "up") -> None:
        width, height = self.d.window_size()
        center_x = int(width * random.uniform(0.42, 0.58))
        horizontal_drift = int(width * random.uniform(-0.035, 0.035))

        if direction == "up":
            start_y = int(height * random.uniform(0.72, 0.86))
            end_y = int(height * random.uniform(0.24, 0.48))
        else:
            start_y = int(height * random.uniform(0.28, 0.42))
            end_y = int(height * random.uniform(0.68, 0.84))

        duration = random.uniform(
            float(self.human.get("swipe_duration_min_seconds", 0.45)),
            float(self.human.get("swipe_duration_max_seconds", 1.15)),
        )
        self.d.swipe(center_x, start_y, center_x + horizontal_drift, end_y, duration=duration)

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
            try:
                result = self.d(resourceId=self.rid("person_result"), textContains=name)
                if result.exists(timeout=0.8):
                    result.click()
                    return True
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
