from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Iterable

from logger import ActionLogger


@dataclass(frozen=True)
class Contact:
    name: str
    title: str
    company: str


class MockDriver:
    """No-device simulation of the Android/UI flow for safe local validation."""

    def __init__(self, config: dict, logger: ActionLogger) -> None:
        self.config = config
        self.logger = logger

    def delay(self, multiplier: float = 1.0) -> None:
        lo = float(self.config["delay_min_seconds"])
        hi = float(self.config["delay_max_seconds"])
        time.sleep(random.uniform(lo, hi) * multiplier)

    def open_app(self) -> None:
        self.logger.log("open_mock_app", self.config.get("mock_site_url", "mock_site"))
        self.delay()

    def scroll_feed(self) -> None:
        count = random.randint(int(self.config["feed_scroll_min"]), int(self.config["feed_scroll_max"]))
        like_probability = float(self.config["like_probability"])
        self.logger.log("feed_session_start", "mock_feed", "success", f"scrolls={count}")
        for i in range(1, count + 1):
            self._scroll_one(i, like_probability)
        self.logger.log("feed_session_end", "mock_feed")

    def search_and_visit_contacts(self, contacts: Iterable[Contact]) -> None:
        connect_probability = float(self.config["connect_probability"])
        min_view = float(self.config["profile_view_min_seconds"])
        max_view = float(self.config["profile_view_max_seconds"])
        for contact in contacts:
            if not contact.name.strip():
                self.logger.log("search_person", "<blank>", "skipped", "missing name")
                continue
            self._type_search(contact.name)
            self.logger.log("open_profile", contact.name, "success", f"{contact.title} at {contact.company}")
            time.sleep(random.uniform(min_view, max_view))
            if random.random() < connect_probability:
                self.logger.log("connect", contact.name, "clicked", "mock button")
            else:
                self.logger.log("connect", contact.name, "skipped", "random decision")
            self.delay()

    def run_random_journey(self, contacts: list[Contact]) -> None:
        """Randomized mock QA journey with bounded action counts."""
        settings = self.config.get("random_journey", {})
        min_actions = int(settings.get("min_actions", 8))
        max_actions = int(settings.get("max_actions", 18))
        action_count = random.randint(min_actions, max_actions)
        remaining_contacts = contacts[:]
        random.shuffle(remaining_contacts)
        like_probability = float(self.config["like_probability"])
        self.logger.log("random_journey_start", "mock", "success", f"actions={action_count}")

        for step in range(1, action_count + 1):
            choices = ["feed", "pause", "home"]
            if remaining_contacts:
                choices.extend(["search", "search"])
            action = random.choice(choices)
            self.logger.log("random_action", f"step_{step}", "selected", action)

            if action == "feed":
                for _ in range(random.randint(1, 3)):
                    self._scroll_one(step, like_probability)
            elif action == "search" and remaining_contacts:
                self.search_and_visit_contacts([remaining_contacts.pop(0)])
            elif action == "home":
                self.logger.log("home", "mock_feed", "success", "random navigation")
                self.delay(random.uniform(0.8, 1.7))
            else:
                self.logger.log("idle_pause", "mock", "success", "random reading/thinking pause")
                self.delay(random.uniform(1.2, 3.5))

        self.logger.log("random_journey_end", "mock", "success", f"remaining_contacts={len(remaining_contacts)}")

    def _scroll_one(self, index: int, like_probability: float) -> None:
        self.delay(random.uniform(0.7, 1.8))
        self.logger.log("scroll_feed", f"post_window_{index}", "success", "distance=randomized")
        if random.random() < like_probability:
            self.delay(0.5)
            self.logger.log("like_post", f"visible_post_{index}")

    def _type_search(self, text: str) -> None:
        typed = ""
        for char in text:
            typed += char
            time.sleep(random.uniform(0.02, 0.12))
        self.logger.log("search_person", text, "success", f"typed_chars={len(typed)}")
