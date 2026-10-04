# Architecture

NotRoyalTs intentionally delegates SSH to the operating system and concentrates
on connection management plus terminal presentation.

## Main pieces

### `app.py`

Contains the PySide6 user interface, terminal widget, PTY lifecycle, SSH command
construction, Royal TS import, and backup/restore UI.

Each terminal session starts `/usr/bin/ssh` (or a local login shell) beneath a
real pseudo-terminal created with `pty.fork()`.

### `pyte`

`pyte.HistoryScreen` maintains terminal state and a 10,000-line history buffer.
NotRoyalTs renders the current screen into `QPlainTextEdit`, including per-cell
ANSI color attributes.

### PTY reader

A dedicated background thread continuously drains the PTY. Bytes are queued for
the Qt thread, which parses them in bounded slices. This prevents a very noisy
remote command from starving keyboard events.

Control-C handling intentionally drops stale display backlog so an interrupted
command does not keep visually "running" for seconds after the remote process
has already stopped.

### Terminal resizing

The initial slave PTY geometry is set before `exec()` starts SSH. Qt scrollbar
geometry is kept stable so later UI layout changes do not unexpectedly shrink
the pyte screen and move visible lines into history.

### Cursor

The visible blinking cursor is rendered by NotRoyalTs as a Qt extra selection.
Tab activation explicitly restores focus and cursor state because QTabWidget can
change the selected page after a close without always producing the focus event
sequence a software cursor expects.

### Database

SQLite lives at:

```text
~/Library/Application Support/NotRoyalTs/notroyalts.db
```

The database stores connection metadata only. Private key files remain external.

## Security boundary

NotRoyalTs does not implement the SSH protocol or cryptography. Authentication,
host-key verification, ciphers, agents, and transport security are handled by
the system OpenSSH client.

That design is deliberate: terminal emulation is already enough trouble.
