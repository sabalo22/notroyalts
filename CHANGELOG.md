# Changelog

All notable public changes to NotRoyalTs will be documented here.

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
