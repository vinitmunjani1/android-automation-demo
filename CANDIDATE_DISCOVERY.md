# Candidate Discovery

Candidate discovery is integrated as a modular extension of the existing automation framework. It supports the controlled MockIn harness for safe validation plus a real LinkedIn Android **review assistant** mode that scores visible real profiles/results without auto-connecting.

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

mock_driver.py / android_driver.py / linkedin_review_driver.py
  └─ discover_candidates_for_query(...)    driver-specific UI/data collection
```

### Existing architecture overview

- `main.py` is the CLI entrypoint and driver factory.
- `mock_driver.py` provides fast, no-device validation.
- `android_driver.py` wraps uiautomator2 for the MockIn app/site and already owns navigation, selectors, page signatures, retry/fallback behavior, and human-like gestures.
- `linkedin_review_driver.py` wraps uiautomator2 for the real LinkedIn Android app, reads visible text only, scores candidates, and requires manual connect decisions/clicks.
- `logger.py` appends action logs to CSV; candidate discovery adds structured JSON output instead of overloading the action log.
- Human-like behavior already exists through `think()`, `delay()`, `action_transition_pause()`, `_human_swipe()`, `_scroll_content_down()`, `_type_text_human()`, and page/stuck recovery helpers.

### Integration points

- `main.py`: added `--discover-candidates`, `--search-query`, and `--no-resume`.
- `mock_driver.py`: simulates candidate search against the same mock people dataset.
- `android_driver.py`: preserves the existing search/find/open-profile flow and adds a scoring hook after a profile is opened. It also supports standalone MockIn discovery through existing UI helpers.
- `linkedin_review_driver.py`: captures real LinkedIn visible screen text from a manually opened search/profile screen and scores it without auto-connect.
- `config.json`: added `candidate_discovery`, `linkedin_review_assistant`, and `candidate_scoring` sections.

## Discovery workflow

### MockIn validation workflow

1. Open MockIn/mock site through the selected driver.
2. Focus the existing search box.
3. Type the query with the existing humanized typing behavior.
4. Pause for visible results.
5. Extract visible candidate cards best-effort.
6. Score and deduplicate candidates.
7. Scroll naturally using existing scroll helpers.
8. Stop on candidate limit, no-progress threshold, empty results, or max scrolls.
9. Persist JSON atomically after the discovery pass.

### Existing action-runner profile-finder workflow

1. The normal Android action runner uses `candidate_profile.json` search queries as its people/profile input.
2. `contacts.csv` is disabled by default and only used if `allow_legacy_contacts_csv=true`.
3. Profile-finder actions search each query and click `Show all results`.
4. The flow applies LinkedIn filters: `People` plus connection types `1st` and `2nd`.
5. For real LinkedIn, detected profile result cards are shuffled and opened in random order using selectors only.
6. Each opened profile is scored/saved, then the flow returns to results and continues.
7. The ranked candidates are appended to `output/candidate_discovery/latest.json`, sorted by score.
8. Coordinate filter/result fallbacks are disabled by default for real LinkedIn to avoid accidental random taps.
9. Before major actions, the bottom-menu guard checks whether navigation is visible; if not, it presses Back up to the configured limit before continuing.
10. Auto-connect is skipped; you click Connect manually if you choose.

### Real LinkedIn review-assistant workflow

1. Open/search LinkedIn manually on the connected Android device.
2. Navigate to a real profile or search-results screen.
3. Run `--mode linkedin-review --discover-candidates`.
4. The driver snapshots visible Android text only.
5. Candidate-like text is scored against `candidate_profile.json`.
6. Results are saved to JSON with `manual_connect_required=true`.
7. You decide whether to click Connect manually.

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
"bottom_menu_guard": {
  "enabled": true,
  "max_back_presses": 2,
  "wait_min_seconds": 0.5,
  "wait_max_seconds": 1.1
},
"candidate_discovery": {
  "default_search_query": "founder",
  "output_dir": "output/candidate_discovery",
  "max_candidates_per_query": 25,
  "max_scrolls_per_query": 8,
  "no_progress_scroll_limit": 2,
  "candidate_dwell_min_seconds": 0.4,
  "candidate_dwell_max_seconds": 1.4,
  "score_existing_profile_flow": true,
  "manual_connect_required": false,
  "apply_people_search_filters": true,
  "apply_connection_filters": true,
  "connection_filters": ["1st", "2nd"],
  "collect_search_results_without_opening": true,
  "open_random_profile_results": true,
  "max_profiles_to_open_per_query": 10,
  "result_collection_pages": 4,
  "allow_coordinate_filter_fallbacks": false,
  "allow_coordinate_result_fallbacks": false
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
| Logged-out/session prompts | Real LinkedIn cannot be read | Missing visible candidate text is logged as empty/failure instead of crashing. |
| UI changes | Selectors break | Visible TextView capture plus hierarchy fallback. |

## Usage

```bash
python3 main.py --now --mode mock --discover-candidates --search-query founder
```

For Android MockIn app testing:

```bash
python3 main.py --now --mode android --discover-candidates --search-query founder
```

For real LinkedIn review/scoring:

```bash
python3 main.py --now --mode linkedin-review --discover-candidates --search-query "founder AI India"
```

Open LinkedIn to a real search-results/profile screen first. The assistant scores what is visible and writes JSON; you manually click Connect if you want.

## Safety scope

MockIn mode may automate the included mock app/site. Real LinkedIn mode is review-assistant only: it scores visible candidates and does not auto-connect or run an engagement loop.
