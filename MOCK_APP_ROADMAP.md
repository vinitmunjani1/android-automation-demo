# MockIn Native App Detail Roadmap

Goal: make `mock_android_app/` a richer professional-network mock for safe Android UI automation testing, without copying real LinkedIn branding/assets or targeting real platforms.

## Phase 1 — Feed realism

- Add richer post types:
  - text-only posts
  - image placeholder posts
  - repost-style cards
  - hiring/job update cards
  - poll-style cards
- Add realistic feed metadata:
  - reaction counts
  - comment counts
  - timestamps
  - visibility labels
  - follow/connect labels
- Make feed author area reliably clickable:
  - stable `feed_profile_link` resource ID
  - clickable author header row
  - clickable avatar/name area
  - automation fallback coordinate taps

## Phase 2 — Profile depth

- Add profile sections:
  - cover banner
  - avatar
  - headline
  - location
  - connection count
  - About
  - Experience
  - Education
  - Skills
  - Activity
- Add profile actions:
  - Connect
  - Message
  - More
  - Follow
- Add profile-review automation:
  - variable profile scroll depth
  - occasional reverse scroll
  - pauses on About/Experience sections
  - optional connect decision

## Phase 3 — Search and people discovery

- Improve search screen:
  - recent searches
  - result filters
  - people cards
  - company cards
  - no-result state
- Add deterministic test IDs:
  - `search_input`
  - `person_result`
  - `company_result`
  - `connect_button`
  - `profile_page`

## Phase 4 — Navigation surfaces

- Expand bottom tabs:
  - Home
  - Network
  - Post
  - Notifications
  - Jobs
- Add lightweight mock screens for each tab.
- Add automation actions that randomly visit tabs and return home.

## Phase 5 — Automation observability

- Add screenshots on failure.
- Add structured action summaries.
- Add per-run seed logging for reproducibility.
- Add config options for action probabilities.
- Add a simple `--smoke-test` mode with short deterministic actions.

## Phase 6 — QA polish

- Add Android UI tests or a small smoke build check.
- Add release/debug APK build instructions.
- Add troubleshooting for common ADB/uiautomator issues.
- Keep all behavior mock-only and safe.
