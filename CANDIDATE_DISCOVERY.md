# Candidate Discovery

Candidate discovery is integrated as a modular extension of the existing MockIn automation framework. It remains scoped to the controlled mock LinkedIn-style site/app that ships with this repository.

## Repository analysis

```text
main.py
  ├─ load_config / load_contacts
  ├─ build_driver(mode)
  ├─ run_once(...)                         existing feed/search/contact journey
  └─ run_candidate_discovery(...)          candidate discovery entrypoint

candidate_discovery.py
  ├─ Candidate / DiscoveryRun              JSON schema models
  ├─ CandidateDiscoveryService             orchestration
  ├─ SearchResultNavigator                 progressive discovery coordinator
  ├─ CandidateExtractor                    visible card/profile extraction
  ├─ CandidateDeduplicator                 identity merge + rich-record preference
  ├─ CandidatePersistenceService           atomic JSON + latest pointer
  └─ DiscoveryStateManager                 resume-aware run state

mock_driver.py / android_driver.py
  └─ discover_candidates_for_query(...)    driver-specific UI/data collection
```

### Existing architecture overview

- `main.py` is the CLI entrypoint and driver factory.
- `mock_driver.py` provides fast, no-device validation.
- `android_driver.py` wraps uiautomator2 and already owns navigation, selectors, page signatures, retry/fallback behavior, and human-like gestures.
- `logger.py` appends action logs to CSV; candidate discovery adds structured JSON output instead of overloading the action log.
- Human-like behavior already exists through `think()`, `delay()`, `action_transition_pause()`, `_human_swipe()`, `_scroll_content_down()`, `_type_text_human()`, and page/stuck recovery helpers.

### Integration points

- `main.py`: added `--discover-candidates`, `--search-query`, and `--no-resume`.
- `mock_driver.py`: simulates candidate search against the same mock people dataset.
- `android_driver.py`: searches through existing UI helpers, pauses on visible result cards, extracts visible data, scrolls progressively, and stops after configurable no-progress thresholds.
- `config.json`: added `candidate_discovery` and `candidate_scoring` sections.

## Discovery workflow

1. Open MockIn/mock site through the selected driver.
2. Focus the existing search box.
3. Type the query with the existing humanized typing behavior.
4. Pause for visible results.
5. Extract visible candidate cards best-effort.
6. Score and deduplicate candidates.
7. Scroll naturally using existing scroll helpers.
8. Stop on candidate limit, no-progress threshold, empty results, or max scrolls.
9. Persist JSON atomically after the discovery pass.

## JSON schema

```json
{
  "run_id": "candidate_discovery_...",
  "created_at": "2026-...Z",
  "search_query": "founder",
  "state": {
    "last_search_query": "founder",
    "candidate_count": 1,
    "seen_candidate_keys": []
  },
  "candidates": [
    {
      "linkedin_id": "mock stable id or null",
      "profile_url": "mockin://profile/... or null",
      "name": "Amit Sharma",
      "headline": "Founder at TechCorp",
      "location": null,
      "company": "TechCorp",
      "connection_degree": "2nd",
      "search_keyword": "founder",
      "timestamp": "2026-...+00:00",
      "source_page": "mock_search_results_page_1",
      "additional_metadata": {},
      "score": 85
    }
  ]
}
```

Output files:

```text
output/candidate_discovery/
  ├─ run_001.json
  ├─ run_002.json
  └─ latest.json
```

## Editable candidate profile

Edit `candidate_profile.json` any time to change the audience and scoring rules without changing Python code. The app loads it automatically from `config.json` via:

```json
"candidate_profile_file": "candidate_profile.json"
```

Example editable profile:

```json
{
  "search_queries": ["founder", "ceo startup", "hr manager hiring"],
  "candidate_scoring": {
    "minimum_recommended_score": 75,
    "strong_recommend_score": 85,
    "title_keywords": ["founder", "ceo", "co-founder", "head", "vp", "manager", "director"],
    "company_keywords": ["startup", "saas", "ai", "automation"],
    "location_keywords": ["india", "united states", "remote"],
    "positive_keywords": ["hiring", "growth", "b2b", "sales", "recruiting"],
    "negative_keywords": ["student", "intern", "freelancer"],
    "weights": {
      "title_keyword_match": 25,
      "negative_keyword_penalty": -25
    }
  }
}
```

If `--search-query` is omitted, discovery uses the first `search_queries` value from `candidate_profile.json`.

## Configuration

```json
"candidate_discovery": {
  "default_search_query": "founder",
  "output_dir": "output/candidate_discovery",
  "max_candidates_per_query": 25,
  "max_scrolls_per_query": 8,
  "no_progress_scroll_limit": 2,
  "candidate_dwell_min_seconds": 0.4,
  "candidate_dwell_max_seconds": 1.4
},
"candidate_scoring": {
  "title_keywords": ["founder", "ceo", "head", "vp", "manager", "director"],
  "company_keywords": [],
  "location_keywords": []
}
```

## Recovery and resume behavior

- Writes are atomic: data is written to a temporary file, flushed, fsynced, and moved into place.
- `latest.json` is maintained for simple resume.
- Corrupted JSON is moved aside with a `.corrupt.<timestamp>` suffix before raising an error.
- Deduplication prefers stable IDs/profile URLs, then falls back to name/company/headline/query.
- Interrupted discovery saves the run state before re-raising.

## Edge case matrix

| Scenario | Impact | Handling strategy |
|---|---|---|
| Empty results | No candidates | Log `candidate_search_empty`; persist empty run. |
| Lazy-loaded content | Partial extraction | Progressive scroll + no-progress threshold. |
| Infinite scrolling | Run may never end | `max_scrolls_per_query` and `max_candidates_per_query`. |
| Missing elements | Extraction failure | Best-effort selectors, hierarchy fallback, null fields. |
| Partial cards | Incomplete candidate | Store null for unavailable fields; do not break. |
| Duplicate candidates | Inflated output | `CandidateDeduplicator` identity merge. |
| Missing IDs/URLs | Weak identity | Stable mock IDs where possible; fallback composite key. |
| Corrupted output | Resume failure | Move corrupt file aside and raise clear error. |
| Interrupted run | Lost progress | Save state on `KeyboardInterrupt`. |
| Scroll failure/no movement | Stuck discovery | Existing page signature checks + no-progress stop. |
| Unexpected navigation | Wrong page | Existing page classifier/recovery remains available in android driver. |
| Loading delays/network latency | Flaky reads | Existing randomized `think()` delays before extraction. |
| Logged-out/session prompts | Not expected in mock harness | Missing search/results are logged as failure instead of crashing. |
| UI changes | Selectors break | Resource-id selectors plus hierarchy fallback. |

## Usage

```bash
python3 main.py --now --mode mock --discover-candidates --search-query founder
```

For Android MockIn app testing:

```bash
python3 main.py --now --mode android --discover-candidates --search-query founder
```

## Safety scope

This feature is intentionally implemented for the included mock environment only. Do not repoint this repository at real LinkedIn or any real social platform.
