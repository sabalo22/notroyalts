# Changelog

All notable public changes to NotRoyalTs will be documented here.

## 1.1.1 - Unreleased

### Fixed

- Clipboard pastes into vi/vim no longer risk truncation when the non-blocking PTY accepts only part of a write
- queued terminal input now preserves byte ordering and drains asynchronously, including bracketed-paste terminators

## 1.1.0 - Unreleased

Optional application lock.

### Added

- Optional password prompt before the main NotRoyalTs UI is created
- macOS Keychain-backed password verifier using PBKDF2-SHA256
- **Security → App Lock Settings…** for enabling, disabling, or changing the App Lock password
- **Security → Lock NotRoyalTs** for manually locking an open application
- brief retry delay after repeated failed unlock attempts
- automated tests for App Lock verifier creation and validation

### Security

- App Lock protects access to the NotRoyalTs interface but does not encrypt the SQLite database, exported JSON backups, or SSH private keys
- changing or disabling App Lock requires the current App Lock password

## 1.0.1 - 2026-10-04

Apple Silicon build and launcher fix.

### Changed

- Apple Silicon is now the primary macOS target.
- `run.sh` and `build-macos.sh` detect the active CPU architecture.
- Native Apple Silicon builds prefer Homebrew Python under `/opt/homebrew`.
- The launcher recreates a project virtual environment when it was created by an incompatible Python or CPU architecture.
- The README now documents native Apple Silicon setup, Rosetta detection, backup/restore, and Royal TS import behavior more explicitly.

### Fixed

- Prevented Apple Silicon Macs from accidentally launching or building NotRoyalTs as an Intel-only application under Rosetta.
- Prevented very old Python installations, such as Python 3.6, from being selected for the project environment.
- Added an architecture check to the macOS build output.

## 1.0.0 - 2026-10-04

First public release.

### Added

- Nested connection folders and search
- Embedded tabbed SSH sessions using macOS `/usr/bin/ssh`
- Local terminal tabs
- ANSI/xterm color rendering
- 10,000-line scrollback
- Alternate-screen support for programs such as `vi`, `less`, and `top`
- macOS copy/paste and terminal control-key handling
- Custom ports, key paths, ProxyJump, extra arguments, and notes
- Reconnect and duplicate-session actions
- JSON backup and restore
- Royal TS SSH connection importer
- PyInstaller macOS build scripts

### Fixed

- Heavy-output Ctrl-C responsiveness
- Startup prompt redraw behavior on some remote shells
- Terminal geometry changes that could push the `Last login` line into history
- Software cursor restoration when switching tabs or closing a neighboring tab
