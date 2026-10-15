# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

LogDog is a PySide6 (Qt6) desktop app for QA engineers to stream, filter, and analyze logs from iOS devices (via `pymobiledevice3`, no external binaries) and Unity Player TCP sockets, in real time. Cross-platform (Windows/Linux/macOS), packaged with PyInstaller.

## Commands

```bash
# Setup
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run the app
python main.py

# Run all tests
pytest

# Run a single test file / test
pytest tests/test_filter/test_level.py
pytest tests/test_filter/test_level.py::test_some_case -v

# Build locally (onedir via LogDog.spec, output in dist/) — release builds are done by CI
pip install pyinstaller
python build.py

# After changing requirements*.txt: regenerate the hash-locked file CI installs from
# (needs `pip install uv`; Dependabot also refreshes it weekly)
uv pip compile requirements-lock.in --universal --python-version 3.12 --generate-hashes --output-file requirements-lock.txt

# Regenerate README images (hero, animated demos, screenshots, both themes) from the real UI
python tools/readme_assets.py    # offscreen; output in assets/readme/ — rerun after visible UI changes
# The hero's mascots (assets/readme/mascot-girl.png, mascot-dog.png — the dog is the old app icon's dog) are
# fixed art, not produced by the script: generated locally (ComfyUI + WAI-Illustrious SDXL, whose license
# allows commercial use of images), background cut with rembg isnet-anime. Keep them as they are.

# Run tests on Windows/macOS without releasing (installer swap tests only run on Windows)
gh workflow run tests.yml -f os=windows-latest   # or os=all
```

Linux requires `usbmuxd` running (`sudo systemctl start usbmuxd`) for iOS device access.

Tests use `pytest-qt`/`pytest-mock`; a session-scoped `qapp` fixture (see `tests/conftest.py`) provides a `QApplication` instance for widget tests, and a `filter_obj` fixture provides a fresh `LogFilter`. Logger output is silenced automatically via an autouse fixture.

## Architecture

Four top-level packages, layered `transports → core → gui`, plus `utils`:

- **`transports/`** — background `QThread` subclasses that produce raw log lines or perform device operations. `transports/base.py` defines `BaseReader(QThread)`, the abstract base for streaming transports, with signals `lines_ready`, `error_occurred`, `status_changed` and a `stop()`/`_is_running` cooperative-cancellation pattern used throughout the codebase (all long-running threads follow this same stop/quit/wait/terminate pattern — see cleanup in `MainWindow`).
  - `syslog_device.py` — `IosDevicePoller` (polls connected iOS devices) and `IosSyslogReader` (streams syslog via `pymobiledevice3`, auto-reconnects on drop).
  - `unity_socket.py` — `UnityTCPReader`, connects to a Unity Development Build over TCP. Port discovery, in order: explicit `ip:port` → Unity's own UDP multicast announce (`225.0.0.222:54997`, `AnnounceListener`, listened to the whole time while waiting) → last successful port per IP (`settings.last_unity_port`) → a full sweep of 55000–55511 **at most once per «Подключиться» click**. Don't add periodic re-scans: repeated sweeps of hundreds of ports look like a port scan to corporate IDS/NDR. The stream is split into text runs (ASCII + whole UTF-8 sequences) between binary Player Connection headers; a run touching the end of a `recv` is held back and glued to the next packet (`extract_text_runs`), flushed after 0.5 s of silence. **Over USB**: target `usb:<serial>` — ports are probed and the stream is read through usbmux (`find_usb_games`, `usb_scan`, `usb_connect`; a local cable, so probing all 512 ports is fine and takes ~0.1 s). Over USB the player first sends the same `[IP] … [ProjectName] …` "business card" as its UDP announce (project name is followed by binary data). `GameDiscovery` lists cable-connected iPhones (even with no game running) and their games first (rescan every 3 s), plus Wi-Fi announces. UI: `MainWindow.unity_combo` («откуда читать»: iPhone по USB / игра в Wi-Fi / прошлый IP / IP вручную) — choosing a target connects and the reader *waits for the game* (`_wait_usb_game`: last port + 55000 every 0.25 s plus a rotating 64-port slice, ≤2 s for a new port at ~6% of one core; a full 512-port sweep costs ~130 ms CPU) so logs are caught from game start; a single USB iPhone is armed automatically unless the user pressed stop. Verified on a real iPhone with a dev build where Wi-Fi discovery didn't see the game (blocked inbound UDP on the PC and/or iOS multicast limits).
  - `crash_reporter.py`, `ipa_installer.py`, `developer_mode.py`, `device_info.py`, `app_list.py` — one-shot worker threads for the auxiliary Tools window (crash report download, .ipa install via `InstallationProxyService`, enabling developer mode via `AmfiService`, device diagnostics, installed-app listing). All guard their `pymobiledevice3` imports with `try/except ImportError` and expose a `HAS_PYMOBILEDEVICE3` flag so the app still runs (Unity-only) when that optional dependency is missing.
  - `device_tools.py` — newer device actions as small `async def job(lockdown)` functions (uninstall, reboot/shutdown, language/locale, provisioning & configuration profiles, pairing reset, app container via `HouseArrestService`: clear/pull/Unity `output.log`) run by one generic `DeviceTask(QThread)`; GUI runs them through `gui/dialogs/device_tasks.py` `TaskRunner` (keeps references, disables buttons, same stop/quit/wait/terminate cleanup). Add new one-shot device actions this way rather than a new QThread class each. Also `IconLoader` (app icons via SpringBoard, cached per serial) and `CrashWatcher` (lists crash report names every 15 s while an iOS device is connected; first listing is the baseline). App containers: iOS opens TestFlight and development builds, refuses App Store apps (`InstallationLookupFailed` → `AppDataUnavailable` with a clear message) — verified on a real iOS 27 device. Clearing keeps `/Documents`, `/Library`, `/Library/Preferences`, `/Library/Caches`, `/Library/Application Support`, `/tmp` themselves and never touches `/SystemData` or the container metadata plist. `reset_pairing` runs with `DeviceTask(connect=False)` (the normal auto-pairing connect is exactly what may be broken).
- Crash notifications: `core/crash_alerts.py` (Qt-free: report-name parsing, resource reports skipped, `AlertPolicy` — only processes the user muted are hidden; nothing is suppressed automatically — the user asked to decide himself. While a process's toast is visible, its new crashes bump a counter on it; once closed or auto-hidden, the next crash shows again; from `FREQUENT_CRASHES` the toast suggests «Не показывать от …») → `gui/crash_alerts.py` `CrashAlerts` (owns the watcher, max 3 `gui/widgets/crash_toast.py` toasts top-right; they are child widgets of the main window, never take focus, auto-hide after 8 s). `MainWindow` only calls `crash_alerts.start(serial)` in `_connect`, `stop()` in `_disconnect`, `shutdown()` in `closeEvent`.
- `core/ipa_info.py` — Qt-free `.ipa` reading (Info.plist + the plist inside the CMS-wrapped `embedded.mobileprovision`) and `check()` warnings shown by `gui/dialogs/ipa_check.py` before installing.
- **`core/`** — transport-agnostic business logic, no Qt widgets:
  - `filter.py` — the RPN-based log filter engine: `_tokenize` → `_to_rpn` (shunting-yard, `AND`/`OR`/`NOT` + parens) → `_eval_rpn`. Supports field queries (`level:`, `proc:`, `pid:`, `text:`) and plain substring search. `get_log_level()` is a multi-stage heuristic (AppLovin-specific regex exceptions → Unity `[LogType:x]` → C# `*Exception` → syslog numeric priority `<0-7>` → bracketed markers → XML tags → keyword lists with word boundaries) used to color/classify log lines whose declared level is unreliable (e.g. Unity logs shipped as `Info`).
  - `processor.py` — `LogProcessor(QThread)` consumes raw lines off a `Queue`, groups multi-line entries into blocks (a new block starts on a recognized timestamp-prefixed line), attaches extracted `props` via `LogFilter.extract_props`, and emits `processed_blocks` for the GUI to render. Runs independently of whichever transport is active.
  - `settings.py` — `Settings` wraps `QSettings` pointed at an INI file in the platform app-data dir (via `utils.helpers.get_app_data_dir`); exposes typed getters/setters (theme, colors, font size, last filter, etc.) and a module-level `settings` singleton used everywhere instead of touching `QSettings` directly.
  - `updater.py` — update check (`UpdaterThread`, reads `latest.json` of the latest GitHub release) and `UpdateDownloadThread` (downloads the installer for this OS, verifies SHA-256). See "Releases and in-app updates" below.
  - `update_install.py` — Qt-free installer swap for a downloaded update. Windows folder / macOS `.app`: the archive is unpacked next to the program and the NEW version, started from there as `LogDog --apply-update …` (handled in `main.py` before Qt is imported), waits for the old one to exit and swaps itself in (`apply_update`), then starts the swapped-in copy with `--finish-update <staging>` to delete the staging folder. Linux AppImage: atomic `os.replace`. The SHA-256 is re-checked right before the swap.
- **`gui/`** — all Qt widgets/dialogs. `main_window.py` (`MainWindow`) owns the transport lifecycle: it creates/destroys the active `IosSyslogReader`/`UnityTCPReader` in `transport_thread`, wires its signals into `self.processor.enqueue_lines`, and owns `poller_thread` (device discovery) and `updater_thread`. `dialogs/tools.py` (`ToolsWindow`) is a separate non-modal window hosting the auxiliary device tools listed above; new tools are added by appending to its `_TOOLS` table rather than restructuring the window. `theme.py` holds all colors: `TOKENS` per theme, `LOG_COLORS` (per-theme log-level defaults; `settings.custom_color` overrides them), one stylesheet template for both themes, and `theme_signals.theme_changed` — widgets that bake colors in (icons, swatches) re-apply on it. Style variants are dynamic properties (`variant="primary" | "ghost" | "card"`, `role="muted" | "title" | "chip"`), not inline `setStyleSheet` with hex colors; call `theme.repolish(w)` after changing one. `icons.py` — the app's own line icons (SVG rendered via QtSvg, tinted from the theme); don't use emoji for UI icons, they render differently on every OS.
- **`utils/`** — `helpers.py` (PyInstaller-safe resource/app-data path resolution) and `logger.py` (app-wide logger setup).

### Threading model

Every long-lived background operation is a `QThread` subclass communicating with the GUI thread exclusively via Qt signals (never shared mutable state). The consistent shutdown sequence — `stop()` (flips `_is_running`) → `quit()` → `wait(timeout)` → `terminate()` fallback — exists specifically to avoid SIGABRT on close; follow this pattern for any new background thread rather than inventing a different cancellation mechanism.

### Filter syntax (user-facing, implemented in `core/filter.py`)

`level:error|warn|info|debug` (with `e`/`w`/`i`/`d`/`err`/`warning` aliases), `proc:`, `pid:`, `text:"exact phrase"`, plain substrings, combined with `AND`/`OR`/`NOT` and parentheses. Adjacent operands get an implicit `AND` (`with_implicit_and`); a `(` attached to a word is part of it (`proc:MyGame(UnityFramework)` is one operand, iOS process names look like that), only a `(` starting a token opens a group; an operand whose prefix before `:` isn't a known field is searched as plain text including the colon (`Exception:`, `http://…`). `tokenize_with_positions` is the single tokenizer for both `LogFilter` and the filter field: `core/filter_syntax.py` (Qt-free: highlight spans, problems, context completion) → `gui/widgets/filter_edit.py` (`FilterLineEdit`, a plain `QLineEdit`; colors via `QInputMethodEvent` `TextFormat` attributes; IDE-style suggestion list `SuggestionPopup` — a focus-less CHILD widget of the main window, not a `Qt.Popup`/`Qt.Tool` window: on Wayland those got refused or misplaced when opened from typing; problems show in its footer after an 800 ms pause). The filter applies itself 350 ms after typing stops (`MainWindow._filter_timer`, skipped while the field has errors); history gets it on Enter/editingFinished only. An earlier attempt (`QPlainTextEdit` forced to one line + a top-level popup; branch deleted) hit scroll drift and Wayland popup issues — keep the plain `QLineEdit` and the child-widget list.

### Log view features

`gui/widgets/log_view.py` (`LogView`: time-delta gutter painted like line numbers — delta seconds live in `QTextBlock.userState()` of an entry's first block; word highlights via a `QSyntaxHighlighter` background overlay; right-click «Подсветить»/«Отслеживать»), `gui/widgets/side_panel.py` (details/JSON, watch, highlights tabs), `core/watch.py` (watch rules = filter expressions counted over all entries), `core/log_entry.py` (entry time, `message_key` = text without the timestamp, used to collapse exact repeats into «×N»). Every stored entry has an increasing `id`; `MainWindow._shown_ids` parallels `_entry_sizes`, so entry ↔ document block mapping is a prefix sum. Markers are entries with `props["level"] == "marker"` and always pass the filter. Tests get an isolated `settings.ini`/history via an autouse fixture in `tests/conftest.py` — never let tests touch the developer's real settings.

### Log pipeline performance

Transport → `LogProcessor` → `MainWindow` is batched end to end: `IosSyslogReader` emits lines every 50 ms (`_pump`, also makes `stop()` take ≤0.1 s), `LogProcessor` coalesces everything queued within 50 ms into one `processed_blocks` emit, `MainWindow._insert_entries` inserts consecutive same-color entries with one `insertText`. Per-line signals made the GUI fall seconds behind on slower Windows machines at a few thousand lines/s (reproduced: 4–7 s event-loop lag before, <50 ms after). `MainWindow._entries` (≤100k, raw + props, chronological) is the single store the filter selects from — don't re-derive props from the document. `get_log_level` uses precompiled, per-stage merged regexes; keep any change behavior-identical (it was verified against the old version on 200k random lines).

## Notes

- GPL-3.0 licensed; derivative works must stay open source.
- UI-facing strings (status messages, dialog labels) are in Russian — match this convention in existing files rather than switching to English.
- `pymobiledevice3` is optional at runtime (Unity-only usage doesn't need it) — always guard new iOS-only imports the same way existing transport modules do.
- `CHANGELOG.md` is the user-facing release notes: `.github/workflows/release.yml` publishes the `## [X.Y]` section matching the pushed tag `vX.Y` as the GitHub release body, and the app's update dialog shows it. A tag push fails if that section is missing. Whenever a change is user-visible, update the upcoming version's section in the same commit — in Russian, written for QA users (what they'll notice), not as a commit log.
- Versioning: `core/version.py` stays `0.0.0-dev` in the repo; the release workflow overwrites it with the tag. Don't bump it by hand. To release: finalize the CHANGELOG section (replace `pending` with the date), then `git tag vX.Y && git push origin master vX.Y`.

## Releases and in-app updates

The check/download part was ported from an internal sibling tool; the Windows/macOS swap was reworked here (no PowerShell, see below). Adapted to a **public** repo: no Google Apps Script / Drive — everything lives in GitHub Releases.

- **Build** (`.github/workflows/release.yml`, on tag `v*` or manual dispatch): `prepare` creates a draft release with the body from `CHANGELOG.md` (via `.github/scripts/release.py notes`; fails fast before the expensive macOS/Windows runners if the section is missing) → `build` (3 OS in parallel: tests, PyInstaller onedir by `LogDog.spec`, Windows zip of the `LogDog/` folder, macOS zip of `LogDog.app`, Linux AppImage via `packaging/`; uploads `LogDog-X.Y-<os>.<ext>` + `.sha256` straight into the draft, not into Actions artifacts) → `publish` (builds `latest.json` from the `.sha256` files via `release.py manifest`, uploads it, un-drafts). Manual dispatch builds are published as **pre-release**, so they never become `releases/latest` and apps never get offered a test build.
- **Check**: the app fetches `https://github.com/<REPO>/releases/latest/download/latest.json` (`core/updater.py`, `REPO` constant) — a plain release-asset download, deliberately not the GitHub API (60 req/h per IP without a token would silently fail in an office behind one NAT). No `latest.json` (e.g. the old v1.0 release) = 404 = no update. Dev version `0.0.0-dev` never checks.
- **Semi-automatic install, not auto-update**: the user clicks "Скачать обновление" (app downloads to temp, verifies SHA-256 while streaming), then "Установить и перезапустить" — nothing is installed or restarted without that second click. Running from sources / not from AppImage → only the "Страница релиза" button. SHA-256 protects against corrupted/partial downloads, not against a compromised release (same trust boundary as a manual download).
- **Asset names and layout are a contract**: `release.py` maps `-windows-setup.exe` → `windows_setup`, `-windows-portable.zip` → `windows` (key kept: released copies look it up), `-macos.zip`, `-linux.AppImage` to `latest.json` keys; `update_install.py` expects `LogDog/LogDog.exe` inside the Windows zip and `LogDog.app` inside the macOS zip. Change them together. The command line `LogDog --apply-update <kind> <target> <staged> <pid> <archive>` is a contract too: the OLD installed version builds it and the NEW one parses it, so every future version must keep accepting it.
- **Windows installer** (`packaging/windows/LogDog.iss`, Inno Setup 6 — preinstalled on GitHub windows runners): per-user install to `%LOCALAPPDATA%\Programs\LogDog`, `PrivilegesRequired=lowest` (no admin/UAC; the in-app swap couldn't write to Program Files anyway). **Never change its `AppId`** — that's what makes a new version install over the old one with a single «Установленные приложения» entry. `[InstallDelete]` wipes `{app}\_internal` so old libraries don't linger. Uninstall asks whether to delete `%LOCALAPPDATA%\LogDog` (settings/history), default No, never in silent mode. A copy is "installed" iff `unins000.exe` sits next to `LogDog.exe` (`update_install.windows_installed`); such copies update by running the new `-windows-setup.exe` with `/SILENT /RELAUNCH=1` (Inno's progress window), portable copies by the folder swap below. `release.yml` smoke-tests every built setup on the runner: install, install over (one entry, stale files gone), silent uninstall keeps settings.
- **Windows swap pitfalls**: no PowerShell/shell scripts for the swap (the original port used a hidden `powershell -ExecutionPolicy Bypass` from `%TEMP%`; EDR/antivirus in companies flag exactly that pattern). The `--apply-update` process runs from the staging folder, so that folder can't be moved as a whole on Windows — `_move_tree` moves file by file and copies busy files; it is started with cwd = temp (a folder that is the cwd of a live process can't be moved either). Never use `os.kill(pid, 0)` to probe a process on Windows — it terminates it (`_wait_for_exit` uses `OpenProcess`/`WaitForSingleObject`). `--finish-update` only deletes a `<program>.update*` sibling of the install folder — it's a command-line argument, don't let it delete arbitrary paths. Downloads go to a fresh `mkdtemp` (not a shared fixed `/tmp` path: on multi-user Linux another user could pre-create it and swap the file after the checksum check). Log: `%TEMP%\logdog-update.log` (`$TMPDIR` on macOS).
- **Linux frozen builds**: `main.py` restores `LD_LIBRARY_PATH` from `LD_LIBRARY_PATH_ORIG` at startup so child processes (`xdg-open` for links, AppImage relaunch after update) don't load PyInstaller's bundled libs.
- **Supply chain** (CI): dependencies install only from `requirements-lock.txt` with `--require-hashes` (input: `requirements-lock.in` → `requirements.txt` + `-test` + `-build`; `tests/test_release_script.py` checks the lock still satisfies them); `prepare` runs pip-audit on the lock and fails the release on known vulnerabilities; actions are pinned by commit SHA, appimagetool and the AppImage runtime by release + SHA-256 (recompute the sums when bumping); the manual-dispatch version is validated against `^v[0-9]+(\.[0-9]+)*(-[0-9A-Za-z.-]+)?$` before anything uses it. Dependabot (`.github/dependabot.yml`, uv + github-actions, weekly, 7-day cooldown) keeps the pins fresh.
- **`LogDog.spec`**: don't add `excludes` for size — `pymobiledevice3` imports e.g. `IPython` at top level, and excluding it silently disables iOS (`HAS_PYMOBILEDEVICE3 = False`; verified on a build).

