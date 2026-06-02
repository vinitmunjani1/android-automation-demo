from __future__ import annotations

import random
import shlex
import time
from typing import Iterable

from logger import ActionLogger
from mock_driver import Contact


class AndroidMockSiteDriver:
    """Optional Android UI driver for the local mock site only.

    uiautomator2 controls Android's accessibility/UI layer, not the raw browser
    DOM. For mobile Chrome/web pages, text selectors and coordinate fallbacks are
    more reliable than HTML-only attributes such as data-testid.

    Do not repoint this at real social platforms.
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

    def delay(self, multiplier: float = 1.0) -> None:
        lo = float(self.config["delay_min_seconds"])
        hi = float(self.config["delay_max_seconds"])
        time.sleep(random.uniform(lo, hi) * multiplier)

    def open_app(self) -> None:
        url = self.config.get("mock_site_url", "http://127.0.0.1:8000")
        self.d.shell(f'am start -a android.intent.action.VIEW -d "{url}"')
        self.logger.log("open_android_browser", url)
        self.delay(2)

    def scroll_feed(self) -> None:
        count = random.randint(int(self.config["feed_scroll_min"]), int(self.config["feed_scroll_max"]))
        self.logger.log("feed_session_start", "mock_feed", "success", f"scrolls={count}")
        for i in range(1, count + 1):
            self.delay(random.uniform(0.8, 1.8))
            if random.random() < float(self.config["like_probability"]):
                if self._click_like_button():
                    self.logger.log("like_post", f"visible_post_{i}")
                else:
                    self.logger.log("like_post", f"visible_post_{i}", "not_found")
            self.d.swipe_ext("up", scale=random.uniform(0.45, 0.75))
            self.logger.log("scroll_feed", f"post_window_{i}")
        self.logger.log("feed_session_end", "mock_feed")

    def search_and_visit_contacts(self, contacts: Iterable[Contact]) -> None:
        for contact in contacts:
            self._go_home()
            if not self._focus_search_box():
                self.logger.log("search_person", contact.name, "failed", "search input missing")
                continue
            self._type_text(contact.name)
            self.logger.log("search_person", contact.name)
            self.delay(1)

            if not self._click_text(contact.name):
                self.logger.log("open_profile", contact.name, "not_found")
                continue
            self.logger.log("open_profile", contact.name, "success", f"{contact.title} at {contact.company}")

            time.sleep(random.uniform(float(self.config["profile_view_min_seconds"]), float(self.config["profile_view_max_seconds"])))
            if random.random() < float(self.config["connect_probability"]):
                if self._click_text("Connect"):
                    self.logger.log("connect", contact.name, "clicked", "mock button")
                else:
                    self.logger.log("connect", contact.name, "not_found")
            else:
                self.logger.log("connect", contact.name, "skipped", "random decision")
            self.delay()

    def _click_like_button(self) -> bool:
        # Prefer accessibility text. Fall back to XPath text variants if needed.
        return self._click_text("Like") or self._click_xpath_text("Like")

    def _go_home(self) -> None:
        self._click_text("Home")
        time.sleep(0.5)
        # Ensure the sticky header/search bar is visible even after feed scrolling.
        for _ in range(2):
            self.d.swipe_ext("down", scale=0.85)
            time.sleep(0.2)

    def _focus_search_box(self) -> bool:
        # Try common Android/browser accessibility representations first.
        candidates = [
            self.d(description="Search people"),
            self.d(text="Search people"),
            self.d(className="android.widget.EditText"),
        ]
        for candidate in candidates:
            try:
                if candidate.exists(timeout=0.5):
                    candidate.click()
                    self.d.clear_text()
                    return True
            except Exception:
                pass

        # Mobile Chrome often exposes little of the page DOM. The mock site's
        # search field is in the sticky header, so tap the header search area.
        width, height = self.d.window_size()
        for y_ratio in (0.16, 0.20, 0.24):
            self.d.click(int(width * 0.48), int(height * y_ratio))
            time.sleep(0.3)
            try:
                self.d.clear_text()
            except Exception:
                pass
            # If keyboard appears or an EditText is focused, typing will work.
            return True
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
                if selector.exists(timeout=0.7):
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
                    item.click()
                    return True
            except Exception:
                pass
        return False

    def _type_text(self, text: str) -> None:
        # ADB input text is more reliable for browser fields than per-character
        # accessibility typing. Spaces must be escaped as %s.
        safe = text.replace(" ", "%s")
        self.d.shell(f"input text {shlex.quote(safe)}")
        time.sleep(random.uniform(0.2, 0.5))
