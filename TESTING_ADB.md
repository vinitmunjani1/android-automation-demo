# ADB Testing Guide

This project is a safe mock Android UI automation demo. It targets only the included mock site, not any real social platform.

## 1) Install dependencies on your laptop

### Ubuntu/Debian

```bash
sudo apt update
sudo apt install -y python3 python3-pip android-tools-adb
python3 -m pip install -r requirements.txt
```

### macOS

```bash
brew install android-platform-tools python
python3 -m pip install -r requirements.txt
```

## 2) Enable ADB on Android

On the phone:

1. Settings → About phone → tap **Build number** 7 times.
2. Settings → Developer options → enable **USB debugging**.
3. Connect phone by USB.
4. Accept the **Allow USB debugging?** prompt.

Verify:

```bash
adb devices -l
```

You should see a device listed as `device`, not `unauthorized`.

## 3) Start the mock site on your laptop

```bash
python3 mock_server.py
```

Find your laptop LAN IP:

```bash
hostname -I   # Linux
ipconfig getifaddr en0   # macOS Wi-Fi
```

Open this URL on the Android phone browser to confirm it loads:

```text
http://<YOUR_LAPTOP_LAN_IP>:8000
```

Example:

```text
http://192.168.1.42:8000
```

> Important: `127.0.0.1` on Android means the phone itself, not your laptop.

## 4) Configure the mock site URL

Edit `config.json`:

```json
"mock_site_url": "http://<YOUR_LAPTOP_LAN_IP>:8000"
```

## 5) Run Android automation test

In another terminal:

```bash
python3 main.py --dry-run --mode android
python3 main.py --now --mode android
```

Logs are written to:

```text
logs/actions.csv
```

## Optional: wireless ADB

Only use this on a trusted LAN or private VPN. Do **not** expose ADB publicly.

Android 11+:

1. Developer options → Wireless debugging → Pair device with pairing code.
2. Run:

```bash
adb pair <PHONE_IP>:<PAIR_PORT>
adb connect <PHONE_IP>:<ADB_PORT>
adb devices -l
```

Then run the same test command:

```bash
python3 main.py --now --mode android
```

## Troubleshooting

- `unauthorized`: unlock phone and accept the USB debugging prompt.
- no devices: try another cable/USB port, or run `adb kill-server && adb start-server`.
- site does not load on phone: ensure laptop and phone are on same Wi-Fi; check firewall allows port `8000`.
- automation opens browser but cannot find elements: confirm the phone loaded the included mock site, not an error page.
