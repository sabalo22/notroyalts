# Security Policy

## Supported version

Security fixes are currently targeted at the latest public release.

## Reporting a vulnerability

Please do not post sensitive vulnerability details, credentials, private keys,
host inventories, or unredacted diagnostic captures in a public issue.

Use GitHub's private vulnerability reporting / Security Advisory mechanism for
the repository when available. If private reporting is not available, open a
minimal public issue asking the maintainers for a private contact channel
without including exploit details.

## Credential handling

NotRoyalTs:

- invokes macOS `/usr/bin/ssh`
- stores SSH key paths, not key contents
- does not provide its own password vault
- stores connection metadata in an unencrypted local SQLite database
- exports connection metadata as unencrypted JSON
- intentionally ignores Royal TS password fields during import
- can optionally require an App Lock password before displaying the connection UI
- stores only a salted password verifier for App Lock in macOS Keychain

App Lock is an application-access barrier only. It does not encrypt the local
SQLite connection database, exported JSON backups, SSH private keys, or other
files on disk.

Users should rely on normal macOS account security, disk encryption, OpenSSH
permissions, and key-management practices.
