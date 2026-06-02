from __future__ import annotations

import random
import time
from typing import Iterable

from logger import ActionLogger
from mock_driver import Contact


class AndroidMockSiteDriver:
    """Optional Android UI driver for the local mock site only.

    This intentionally uses stable `data-testid` selectors from `mock_site/index.html`.
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
                buttons = self.d.xpath('//*[@data-testid="like-button"]').all()
                if buttons:
                    btn = random.choice(buttons[:3])
                    btn.click()
                    self.logger.log("like_post", f"visible_post_{i}")
                else:
                    self.logger.log("like_post", f"visible_post_{i}", "not_found")
            self.d.swipe_ext("up", scale=random.uniform(0.45, 0.75))
            self.logger.log("scroll_feed", f"post_window_{i}")
        self.logger.log("feed_session_end", "mock_feed")

    def search_and_visit_contacts(self, contacts: Iterable[Contact]) -> None:
        for contact in contacts:
            search = self.d.xpath('//*[@data-testid="search-input"]')
            if not search.exists:
                self.logger.log("search_person", contact.name, "failed", "search input missing")
                continue
            search.click()
            self.d.clear_text()
            self._type_text(contact.name)
            self.logger.log("search_person", contact.name)
            self.delay(1)
            result = self.d.xpath('//*[@data-testid="person-result"]')
            if not result.exists:
                self.logger.log("open_profile", contact.name, "not_found")
                continue
            result.click()
            self.logger.log("open_profile", contact.name, "success", f"{contact.title} at {contact.company}")
            time.sleep(random.uniform(float(self.config["profile_view_min_seconds"]), float(self.config["profile_view_max_seconds"])))
            if random.random() < float(self.config["connect_probability"]):
                connect = self.d.xpath('//*[@data-testid="connect-button"]')
                if connect.exists:
                    connect.click()
                    self.logger.log("connect", contact.name, "clicked", "mock button")
                else:
                    self.logger.log("connect", contact.name, "not_found")
            else:
                self.logger.log("connect", contact.name, "skipped", "random decision")
            home = self.d.xpath('//*[@data-testid="home-button"]')
            if home.exists:
                home.click()
            self.delay()

    def _type_text(self, text: str) -> None:
        # Character-by-character input for mock UI testing. Avoids relying on clipboard.
        for char in text:
            self.d.send_keys(char, clear=False)
            time.sleep(random.uniform(0.03, 0.16))
