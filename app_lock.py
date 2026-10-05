import base64
import hashlib
import hmac
import os
import subprocess

KEYCHAIN_SERVICE = "com.notroyalts.app-lock"
KEYCHAIN_ACCOUNT = "NotRoyalTs"
RECORD_VERSION = "v1"
PBKDF2_ITERATIONS = 390000


class KeychainError(RuntimeError):
    pass


def _encode(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode(text):
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def _make_record(password, salt=None, iterations=PBKDF2_ITERATIONS):
    if not password:
        raise ValueError("Password cannot be empty.")

    if salt is None:
        salt = os.urandom(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        int(iterations),
    )

    return "$".join(
        (
            RECORD_VERSION,
            str(int(iterations)),
            _encode(salt),
            _encode(digest),
        )
    )


def _verify_record(password, record):
    try:
        version, iterations_text, salt_text, digest_text = record.split("$", 3)
        if version != RECORD_VERSION:
            return False

        iterations = int(iterations_text)
        if iterations <= 0:
            return False

        salt = _decode(salt_text)
        expected = _decode(digest_text)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _security(args):
    try:
        return subprocess.run(
            ["/usr/bin/security", *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise KeychainError(f"Could not run macOS Keychain utility: {exc}") from exc


def _read_record():
    result = _security(
        [
            "find-generic-password",
            "-a",
            KEYCHAIN_ACCOUNT,
            "-s",
            KEYCHAIN_SERVICE,
            "-w",
        ]
    )

    if result.returncode != 0:
        return None

    record = result.stdout.strip()
    return record or None


def is_configured():
    return _read_record() is not None


def verify_password(password):
    record = _read_record()
    if record is None:
        return False
    return _verify_record(password, record)


def set_password(password):
    record = _make_record(password)

    result = _security(
        [
            "add-generic-password",
            "-U",
            "-a",
            KEYCHAIN_ACCOUNT,
            "-s",
            KEYCHAIN_SERVICE,
            "-l",
            "NotRoyalTs App Lock",
            "-w",
            record,
        ]
    )

    if result.returncode != 0:
        message = result.stderr.strip() or "Unknown Keychain error."
        raise KeychainError(f"Could not save App Lock verifier: {message}")


def clear_password():
    result = _security(
        [
            "delete-generic-password",
            "-a",
            KEYCHAIN_ACCOUNT,
            "-s",
            KEYCHAIN_SERVICE,
        ]
    )

    # security(1) returns a non-zero status if the item does not exist.
    # Treat that as already cleared.
    if result.returncode != 0 and _read_record() is not None:
        message = result.stderr.strip() or "Unknown Keychain error."
        raise KeychainError(f"Could not remove App Lock verifier: {message}")
