# NotRoyalTs

A lightweight, open-source SSH connection manager for macOS.

NotRoyalTs grew out of a very simple requirement: manage a lot of SSH
connections in folders, open them in tabs, and keep the terminal experience
close to the normal macOS Terminal without carrying around a large remote
management suite.

It uses the system `/usr/bin/ssh` client under a real PTY. NotRoyalTs does not
implement SSH cryptography itself and does not copy private keys into its
database.

> **Current source version:** `v1.0.1`.
>
> **Primary target:** Apple Silicon Macs (`arm64`). The run and build scripts
> intentionally reject Rosetta on Apple Silicon so NotRoyalTs is not
> accidentally built as an Intel-only application.

## Features

- Nested folders for SSH connections
- Tabbed embedded SSH sessions
- Local terminal tabs
- Connection search
- Custom SSH ports
- External private-key paths
- `ProxyJump` support
- Extra SSH arguments
- Connection notes
- ANSI/xterm colors
- Tab completion and terminal control keys
- `vi` / `vim`, `less`, `top`, and alternate-screen handling
- 10,000-line terminal scrollback
- Mouse / trackpad and Shift+PageUp / Shift+PageDown scrollback
- macOS Command-C / Command-V
- Reconnect and duplicate-session actions
- Backup and restore using readable JSON
- Royal TS document import for SSH connections
- Automatic migration from the earlier SSHDesk development builds

## Requirements

- macOS
- Apple Silicon (`arm64`) recommended and the primary target
- Python 3.10+; Python 3.12 is recommended
- `/usr/bin/ssh`
- PySide6
- pyte

On Apple Silicon, native Homebrew normally lives under:

```text
/opt/homebrew
```

If you use Homebrew, Python 3.12 can be installed with:

```bash
brew install python@3.12
```

NotRoyalTs is currently macOS-specific because it uses macOS paths, keyboard
behavior, application packaging, and the system SSH client directly.

## Run from source

Clone the repository:

```bash
git clone https://github.com/sabalo22/notroyalts.git
cd notroyalts
```

Then run:

```bash
./run.sh
```

`run.sh`:

- detects the current CPU architecture
- rejects a Rosetta-translated shell on Apple Silicon
- prefers native Homebrew Python under `/opt/homebrew` on Apple Silicon
- requires Python 3.10 or newer
- replaces an incompatible project `.venv`
- installs the runtime requirements and starts NotRoyalTs

If an Apple Silicon Mac reports `x86_64` from `uname -m`, the shell is running
under Rosetta. Start a native shell first:

```bash
arch -arm64 /bin/zsh --login
```

Then verify:

```bash
uname -m
```

It should report:

```text
arm64
```

### Manual Apple Silicon setup

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python app.py
```

## Build the macOS app

On Apple Silicon, run the build from a native `arm64` shell:

```bash
./build-macos.sh
```

The build script refuses to create an Intel/Rosetta build on Apple Silicon. It
selects a native Python for the current architecture, creates a clean build
environment, runs PyInstaller, and prints the architecture of the resulting app
executable.

The resulting application is written to:

```text
dist/NotRoyalTs.app
```

To copy it into `/Applications`:

```bash
./install-app.sh
```

### Signing

The build script applies an ad-hoc signature when `codesign` is available. This
is useful for locally built copies, but it is **not** Apple Developer ID signing
or notarization.

Public binary releases should be Developer ID signed and notarized before users
are encouraged to bypass normal Gatekeeper protections.

## Data and security model

The connection database is stored at:

```text
~/Library/Application Support/NotRoyalTs/notroyalts.db
```

NotRoyalTs stores connection metadata such as:

- connection and folder names
- hostnames / IP addresses
- ports
- usernames
- private-key **paths**
- ProxyJump values
- extra SSH arguments
- notes

The SQLite database is **not encrypted**. Backup files are also plain JSON. Do
not put passwords, private key contents, or other secrets in connection notes or
extra arguments.

SSH private keys stay where you keep them, normally under `~/.ssh`. NotRoyalTs
passes the selected key path to `/usr/bin/ssh`.

The Royal TS importer intentionally does **not** import stored password fields.

## Backup and restore

Use:

- **File → Export NotRoyalTs Backup…**
- **File → Import NotRoyalTs Backup…**

Backups preserve folder hierarchy and connection definitions but do not include
private key files.

Because backup files are readable JSON, treat them as sensitive if your saved
hostnames, usernames, notes, or network information are sensitive.

## Royal TS import

NotRoyalTs can import SSH connection definitions from Royal TS XML / `.rtsz`
documents when the document content is XML.

Imported fields include connection name, host, port, username, key path,
description, and folder placement where available. Password fields are ignored.

Existing matching folders are reused and existing matching connections are
skipped, making repeat imports safer.

NotRoyalTs is an independent project and is not affiliated with, endorsed by, or
sponsored by Royal Apps or Royal TS. Royal TS is a trademark of its respective
owner.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| Command/Ctrl + N | New connection |
| Command/Ctrl + Shift + T | Open local terminal |
| Command/Ctrl + W | Close current tab |
| Command/Ctrl + R | Reconnect current tab |
| Command/Ctrl + Shift + D | Duplicate current session |
| Command/Ctrl + K | Focus connection search |
| Command/Ctrl + 1…9 | Go to tab 1…9 |

On macOS, Qt's modifier mapping is a little unusual internally; NotRoyalTs
contains explicit handling so physical Command and Control keys behave as
expected in the terminal.

## Why another SSH manager?

Because sometimes you want folders, search, tabs, key paths, and a terminal —
and not much else.

The project started as a small personal replacement for a larger connection
manager and gradually became a surprisingly serious exercise in PTYs, terminal
escape sequences, scrollback, readline redraws, resize behavior, and macOS Qt
keyboard handling.

If it saves somebody else a little time, it did its job.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

A quick syntax check is:

```bash
python -m py_compile app.py db.py
```

## License

MIT. See [LICENSE](LICENSE).
