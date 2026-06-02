# Android Automation Mock Demo

Safe proof-of-concept for Android UI automation using a **mock LinkedIn-style environment**.
It demonstrates scheduling, feed scrolling, randomized interactions, CSV-driven search/profile visits, connect-button clicks, logging, resume-safe progress, and edge-case handling without targeting LinkedIn or any real platform.

## Files

- `main.py` — CLI entrypoint
- `config.json` — timing/probability limits
- `contacts.csv` — demo contact list
- `mock_site/index.html` — mock social feed/profile UI
- `mock_server.py` — local HTTP server for mock site
- `mock_driver.py` — no-device simulation driver for fast validation
- `android_driver.py` — optional uiautomator2 driver for mock site/app only
- `linkedin_review_driver.py` — real LinkedIn visible-screen review assistant for scoring candidates without auto-connect
- `candidate_discovery.py` — candidate discovery, scoring, dedupe, and JSON persistence
- `candidate_profile.json` — editable ICP/search/scoring rules
- `CANDIDATE_DISCOVERY.md` — discovery architecture, schema, config, and edge-case handling
- `logs/actions.csv` — action log generated at runtime

## Quick run

```bash
cd android_automation_demo
python3 main.py --now
```

The feature branch defaults to Android mode and uses `candidate_profile.json` search queries as the profile-finder input. `contacts.csv` is no longer used unless `allow_legacy_contacts_csv` is explicitly enabled.

For mock validation only:

```bash
python3 main.py --now --mode mock --discover-candidates --search-query founder
```

## Candidate discovery

Run a mock candidate discovery pass and write crash-safe JSON output under `output/candidate_discovery/`:

```bash
python3 main.py --now --mode mock --discover-candidates --search-query founder
```

Edit `candidate_profile.json` whenever you want to change search queries, keywords, weights, and score thresholds.

The existing Android action runner now includes profile-finder actions that use `candidate_profile.json` search queries, click **Show all results**, apply LinkedIn search filters for People + 1st/2nd connections, open detected profile result cards in shuffled order, score/save each opened profile, then return to results. If `mock_app_package`/the active app package is `com.linkedin.android`, it does not use random coordinate taps or auto-connect.

Run it with:

```bash
python3 main.py --now
```

or explicitly:

```bash
python3 main.py --now --mode android
```

To score real LinkedIn profiles/results without running the existing finder, manually open the LinkedIn Android app to a search result or profile screen, then run:

```bash
python3 main.py --now --mode linkedin-review --discover-candidates --search-query "founder AI India"
```

This captures and scores visible real LinkedIn text, saves JSON output, and leaves connect decisions/clicks to you.

See [`CANDIDATE_DISCOVERY.md`](CANDIDATE_DISCOVERY.md) for architecture, schema, editable scoring profile, configuration, resume behavior, and edge-case handling.

## Serve mock site

```bash
cd android_automation_demo
python3 mock_server.py
```

Then open: `http://127.0.0.1:8000`

## Optional Android mock UI run via ADB

Two Android targets are available:

1. **Browser mock site** — see [`TESTING_ADB.md`](TESTING_ADB.md)
2. **Native mock app** — see [`TESTING_NATIVE_APP.md`](TESTING_NATIVE_APP.md)

Browser short version:

```bash
pip install -r requirements.txt
adb devices -l
python3 mock_server.py
# edit config.json mock_site_url to your laptop LAN URL, e.g. http://192.168.1.42:8000
python3 main.py --now --mode android
```

Native app short version:

```bash
# Build/install mock_android_app/ with Android Studio first.
# Then set config.json: "android_target": "app"
python3 main.py --now --mode android
```

### Randomized mock QA journey

By default, `config.json` uses:

```json
"action_order": "random"
```

That makes each run choose a different bounded sequence of mock actions: feed reading, scrolling, likes, searches, profile visits, home navigation, and idle pauses. Set it back to `"sequential"` if you want the older feed-then-search flow.

> This driver is intentionally scoped to the included mock site/app. It should not be pointed at LinkedIn or used for real-platform auto-engagement.
