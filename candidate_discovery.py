from __future__ import annotations

import json
import os
import random
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

from logger import ActionLogger


@dataclass
class Candidate:
    linkedin_id: str | None = None
    profile_url: str | None = None
    name: str | None = None
    headline: str | None = None
    location: str | None = None
    company: str | None = None
    connection_degree: str | None = None
    search_keyword: str | None = None
    timestamp: str | None = None
    source_page: str | None = None
    additional_metadata: dict[str, Any] = field(default_factory=dict)
    score: int | None = None

    def identity_key(self) -> str:
        for value in (self.linkedin_id, self.profile_url):
            if value:
                return value.strip().lower()
        return "|".join(
            str(part or "").strip().lower()
            for part in (self.name, self.company, self.headline, self.search_keyword)
        )


@dataclass
class DiscoveryRun:
    run_id: str
    created_at: str
    search_query: str
    candidates: list[Candidate] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)


class CandidateDiscoveryDriver(Protocol):
    def discover_candidates_for_query(self, search_query: str, state: dict[str, Any]) -> Iterable[Candidate]:
        ...


class CandidateDeduplicator:
    def merge(self, existing: Iterable[Candidate], incoming: Iterable[Candidate]) -> list[Candidate]:
        by_key: dict[str, Candidate] = {}
        for candidate in list(existing) + list(incoming):
            key = candidate.identity_key()
            if not key.strip("|"):
                key = f"anonymous:{uuid.uuid4()}"
            if key not in by_key:
                by_key[key] = candidate
                continue
            by_key[key] = self._prefer_richer(by_key[key], candidate)
        return list(by_key.values())

    def _prefer_richer(self, left: Candidate, right: Candidate) -> Candidate:
        left_score = self._richness(left)
        right_score = self._richness(right)
        if right_score > left_score:
            winner, fallback = right, left
        else:
            winner, fallback = left, right
        merged = asdict(winner)
        for key, value in asdict(fallback).items():
            if key == "additional_metadata":
                merged[key] = {**(value or {}), **(merged.get(key) or {})}
            elif merged.get(key) in (None, "") and value not in (None, ""):
                merged[key] = value
        return Candidate(**merged)

    def _richness(self, candidate: Candidate) -> int:
        data = asdict(candidate)
        score = sum(1 for value in data.values() if value not in (None, "", {}, []))
        score += len(candidate.additional_metadata or {})
        return score


class CandidateScorer:
    """Small, configurable relevance scorer for mock discovery results."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config.get("candidate_scoring", {})
        self.weights = {
            "has_name": 10,
            "has_profile_identity": 20,
            "has_headline": 20,
            "has_company": 10,
            "has_connection_degree": 5,
            "title_keyword_match": 25,
            "company_keyword_match": 10,
            "location_keyword_match": 10,
            "positive_keyword_match": 10,
            "negative_keyword_penalty": -25,
            **self.config.get("weights", {}),
        }
        self.title_keywords = self._lower_list(self.config.get("title_keywords", ["founder", "ceo", "head", "vp", "manager", "director"]))
        self.company_keywords = self._lower_list(self.config.get("company_keywords", []))
        self.location_keywords = self._lower_list(self.config.get("location_keywords", []))
        self.positive_keywords = self._lower_list(self.config.get("positive_keywords", []))
        self.negative_keywords = self._lower_list(self.config.get("negative_keywords", []))
        self.minimum_recommended_score = int(self.config.get("minimum_recommended_score", 75))
        self.strong_recommend_score = int(self.config.get("strong_recommend_score", 85))

    def score(self, candidate: Candidate) -> int:
        points = 0
        haystack = " ".join(str(v or "") for v in [candidate.name, candidate.headline, candidate.company, candidate.location, candidate.additional_metadata]).lower()
        if candidate.name:
            points += int(self.weights["has_name"])
        if candidate.profile_url or candidate.linkedin_id:
            points += int(self.weights["has_profile_identity"])
        if candidate.headline:
            points += int(self.weights["has_headline"])
        if candidate.company:
            points += int(self.weights["has_company"])
        if candidate.connection_degree:
            points += int(self.weights["has_connection_degree"])
        if self._matches(haystack, self.title_keywords):
            points += int(self.weights["title_keyword_match"])
        if self._matches(haystack, self.company_keywords):
            points += int(self.weights["company_keyword_match"])
        if self._matches(haystack, self.location_keywords):
            points += int(self.weights["location_keyword_match"])
        if self._matches(haystack, self.positive_keywords):
            points += int(self.weights["positive_keyword_match"])
        if self._matches(haystack, self.negative_keywords):
            points += int(self.weights["negative_keyword_penalty"])
        return max(0, min(points, 100))

    def recommendation_label(self, score: int | None) -> str:
        if score is None:
            return "unknown"
        if score >= self.strong_recommend_score:
            return "strong_recommend"
        if score >= self.minimum_recommended_score:
            return "recommend"
        return "review_later"

    def _lower_list(self, values: Iterable[Any]) -> list[str]:
        return [str(value).strip().lower() for value in values if str(value).strip()]

    def _matches(self, haystack: str, keywords: list[str]) -> bool:
        return bool(keywords) and any(keyword in haystack for keyword in keywords)


class CandidateExtractor:
    """Best-effort extractor for visible search-result text/hierarchy."""

    DEGREE_PATTERN = re.compile(r"\b(1st|2nd|3rd)\b", re.IGNORECASE)

    def __init__(self, scorer: CandidateScorer) -> None:
        self.scorer = scorer

    def from_mock_person(self, person: Any, search_query: str, source_page: str = "mock_search_results") -> Candidate:
        name = self._value(person, "name")
        title = self._value(person, "title")
        company = self._value(person, "company")
        location = self._value(person, "location")
        linkedin_id = self._stable_id(name, company)
        candidate = Candidate(
            linkedin_id=linkedin_id,
            profile_url=f"mockin://profile/{linkedin_id}" if linkedin_id else None,
            name=name,
            headline=" at ".join(part for part in [title, company] if part),
            location=location,
            company=company,
            connection_degree="2nd",
            search_keyword=search_query,
            timestamp=utc_now(),
            source_page=source_page,
            additional_metadata={"source": "mock_dataset"},
        )
        candidate.score = self.scorer.score(candidate)
        candidate.additional_metadata["recommendation"] = self.scorer.recommendation_label(candidate.score)
        return candidate

    def from_visible_text(self, text: str, search_query: str, source_page: str, sequence: int) -> Candidate | None:
        clean = re.sub(r"\s+", " ", text).strip()
        if not clean or len(clean) < 3:
            return None
        fragments = [part.strip() for part in re.split(r"\s{2,}|\n|•", text) if part.strip()]
        name = fragments[0] if fragments else clean[:80]
        headline = None
        company = None
        for fragment in fragments[1:]:
            if " at " in fragment:
                headline = fragment
                company = fragment.split(" at ")[-1].strip() or None
                break
        degree = self.DEGREE_PATTERN.search(clean)
        linkedin_id = self._stable_id(name, company or search_query)
        candidate = Candidate(
            linkedin_id=linkedin_id,
            profile_url=f"mockin://profile/{linkedin_id}" if linkedin_id else None,
            name=name,
            headline=headline,
            company=company,
            connection_degree=degree.group(1) if degree else None,
            search_keyword=search_query,
            timestamp=utc_now(),
            source_page=source_page,
            additional_metadata={"raw_visible_text": clean[:500], "sequence": sequence},
        )
        candidate.score = self.scorer.score(candidate)
        candidate.additional_metadata["recommendation"] = self.scorer.recommendation_label(candidate.score)
        return candidate

    def _value(self, source: Any, key: str) -> Any:
        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)

    def _stable_id(self, name: str | None, company: str | None) -> str | None:
        key = "|".join(part.strip().lower() for part in [name or "", company or ""] if part)
        if not key:
            return None
        import hashlib
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


class CandidatePersistenceService:
    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def next_run_path(self) -> Path:
        existing = sorted(self.output_dir.glob("run_*.json"))
        next_index = len(existing) + 1
        while True:
            path = self.output_dir / f"run_{next_index:03d}.json"
            if not path.exists():
                return path
            next_index += 1

    def load_latest(self) -> DiscoveryRun | None:
        return self.load(self.output_dir / "latest.json")

    def load(self, path: str | Path) -> DiscoveryRun | None:
        file_path = Path(path)
        if not file_path.exists():
            return None
        try:
            with file_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            candidates = [Candidate(**item) for item in payload.get("candidates", [])]
            return DiscoveryRun(
                run_id=payload.get("run_id") or file_path.stem,
                created_at=payload.get("created_at") or utc_now(),
                search_query=payload.get("search_query") or "",
                candidates=candidates,
                state=payload.get("state") or {},
            )
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            corrupt_path = file_path.with_suffix(file_path.suffix + f".corrupt.{int(datetime.now().timestamp())}")
            try:
                file_path.rename(corrupt_path)
            except OSError:
                pass
            raise RuntimeError(f"Corrupted candidate output moved aside: {file_path}") from exc

    def save(self, run: DiscoveryRun, run_path: Path) -> None:
        payload = {
            "run_id": run.run_id,
            "created_at": run.created_at,
            "search_query": run.search_query,
            "state": run.state,
            "candidates": [asdict(candidate) for candidate in run.candidates],
        }
        self._atomic_write(run_path, payload)
        self._atomic_write(self.output_dir / "latest.json", payload)

    def _atomic_write(self, path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)


class DiscoveryStateManager:
    def __init__(self, resume: bool, persistence: CandidatePersistenceService, search_query: str) -> None:
        self.resume = resume
        self.persistence = persistence
        self.search_query = search_query

    def start(self) -> DiscoveryRun:
        if self.resume:
            latest = self.persistence.load_latest()
            if latest and latest.search_query == self.search_query:
                latest.state.setdefault("resumed_at", utc_now())
                return latest
        return DiscoveryRun(run_id=f"candidate_discovery_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}", created_at=utc_now(), search_query=self.search_query)


class SearchResultNavigator:
    """Coordinates progressive query execution while drivers own UI details."""

    def __init__(self, driver: CandidateDiscoveryDriver, logger: ActionLogger) -> None:
        self.driver = driver
        self.logger = logger

    def discover(self, search_query: str, state: dict[str, Any]) -> list[Candidate]:
        self.logger.log("candidate_search_start", search_query, "started", f"resume_state={bool(state)}")
        candidates = list(self.driver.discover_candidates_for_query(search_query, state))
        self.logger.log("candidate_search_end", search_query, "success", f"visible_candidates={len(candidates)}")
        return candidates


class CandidateDiscoveryService:
    def __init__(self, driver: CandidateDiscoveryDriver, config: dict[str, Any], logger: ActionLogger, output_dir: str | Path) -> None:
        self.driver = driver
        self.config = config
        self.logger = logger
        self.persistence = CandidatePersistenceService(output_dir)
        self.deduplicator = CandidateDeduplicator()
        self.navigator = SearchResultNavigator(driver, logger)

    def run(self, search_query: str, resume: bool = True) -> DiscoveryRun:
        state_manager = DiscoveryStateManager(resume, self.persistence, search_query)
        run = state_manager.start()
        run_path = self.persistence.next_run_path() if not resume or not (self.persistence.output_dir / "latest.json").exists() else self.persistence.next_run_path()
        try:
            discovered = self.navigator.discover(search_query, run.state)
            run.candidates = self.deduplicator.merge(run.candidates, discovered)
            run.state.update({"last_search_query": search_query, "last_saved_at": utc_now(), "candidate_count": len(run.candidates)})
            self.persistence.save(run, run_path)
            self.logger.log("candidate_discovery_saved", str(run_path), "success", f"candidates={len(run.candidates)}")
            return run
        except KeyboardInterrupt:
            run.state.update({"interrupted_at": utc_now()})
            self.persistence.save(run, run_path)
            self.logger.log("candidate_discovery_interrupted", search_query, "saved", f"candidates={len(run.candidates)}")
            raise


def query_matches_person(search_query: str, name: str, title: str, company: str) -> bool:
    terms = [term for term in re.split(r"\s+", search_query.lower().strip()) if term]
    if not terms:
        return True
    haystack = f"{name} {title} {company}".lower()
    return any(term in haystack for term in terms)


def human_dwell(config: dict[str, Any], min_key: str = "candidate_dwell_min_seconds", max_key: str = "candidate_dwell_max_seconds") -> None:
    import time

    discovery = config.get("candidate_discovery", {})
    lo = float(discovery.get(min_key, 0.4))
    hi = float(discovery.get(max_key, 1.4))
    time.sleep(random.uniform(lo, hi))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
