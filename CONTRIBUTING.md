# Contributing to NotRoyalTs

Thanks for helping make NotRoyalTs better.

## Before opening a pull request

1. Keep changes focused.
2. Run:

   ```bash
   python -m py_compile app.py db.py
   ```

3. Test the change on macOS using at least one real SSH session.
4. Do not commit connection databases, SSH keys, host inventories, diagnostic
   captures containing private infrastructure details, or exported backups.

## Terminal bugs

Terminal bugs can be unusually sensitive to shell, timing, and byte sequences.
A useful bug report includes:

- macOS version
- Python version
- PySide6 version
- pyte version
- local architecture (Intel or Apple Silicon)
- remote shell (`bash`, `zsh`, etc.)
- `$TERM`
- whether the issue also occurs in macOS Terminal
- exact reproduction steps
- whether it happens only at login, after resize, under heavy output, or inside
  an alternate-screen program

Please sanitize hostnames, usernames, IP addresses, and other infrastructure
details before posting logs publicly.

## Style

The codebase intentionally stays small and direct. Prefer understandable fixes
over large abstractions unless the abstraction clearly reduces terminal-state
risk.

The PTY reader and terminal parser are latency-sensitive. Changes there should
be tested with:

```bash
find /usr -type f 2>/dev/null
```

and interrupted with physical Control-C to make sure queued output does not make
the terminal feel stuck.

Also test:

- tab completion
- Command-C / Command-V
- `vi` or `vim`
- `less`
- `top`
- terminal resizing
- tab switching and tab closing
- scrollback

## Pull requests

Describe what changed, why it changed, and how you tested it. Screenshots are
welcome for UI changes, but terminal-behavior fixes are better accompanied by
clear reproduction steps.

By contributing, you agree that your contribution is licensed under the MIT
License.
