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
- `logs/actions.csv` — action log generated at runtime

## Quick local run

```bash
cd android_automation_demo
python3 main.py --now --mode mock
```

## Serve mock site

```bash
cd android_automation_demo
python3 mock_server.py
```

Then open: `http://127.0.0.1:8000`

## Optional Android mock UI run via ADB

See [`TESTING_ADB.md`](TESTING_ADB.md) for the full phone/laptop setup.

Short version:

```bash
pip install -r requirements.txt
adb devices -l
python3 mock_server.py
# edit config.json mock_site_url to your laptop LAN URL, e.g. http://192.168.1.42:8000
python3 main.py --now --mode android
```

> This driver is intentionally scoped to the included mock site/app. It should not be pointed at LinkedIn or used for real-platform auto-engagement.
