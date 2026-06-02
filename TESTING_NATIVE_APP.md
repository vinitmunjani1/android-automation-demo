# Native Mock App Testing Guide

This repo includes a native Android mock app in `mock_android_app/`.

It is a controlled **LinkedIn-style professional-network mock**, but it does not use LinkedIn branding/assets and should not be used against real platforms.

## 1) Build/install the mock app

### Easiest: Android Studio

1. Open Android Studio.
2. File → Open → select:

```text
mock_android_app/
```

3. Let Gradle sync.
4. Connect your Android phone with USB debugging enabled.
5. Click **Run** to install `MockIn` on the phone.

### CLI if you have Gradle/Android SDK configured

From repo root:

```powershell
cd mock_android_app
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

On Windows, if Android Studio creates/uses a wrapper:

```powershell
cd mock_android_app
.\gradlew.bat assembleDebug
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

## 2) Verify app package

```powershell
adb shell pm list packages | findstr mockin
```

Expected:

```text
package:com.mockin.app
```

Launch manually:

```powershell
adb shell monkey -p com.mockin.app 1
```

## 3) Switch automation to native app target

Edit `config.json`:

```json
"android_target": "app",
"mock_app_package": "com.mockin.app"
```

You do **not** need `mock_server.py` for native app mode.

## 4) Run automation

From repo root:

```powershell
py main.py --dry-run --mode android
py main.py --now --mode android
```

Logs are written to:

```text
logs/actions.csv
```

## Why native app mode is better

Browser mode uses Chrome's accessibility layer, which can hide raw HTML selectors. Native app mode exposes stable Android resource IDs:

- `com.mockin.app:id/search_input`
- `com.mockin.app:id/home_button`
- `com.mockin.app:id/like_button`
- `com.mockin.app:id/person_result`
- `com.mockin.app:id/connect_button`

That makes the automation much closer to real app UI testing while staying safe and mock-only.
