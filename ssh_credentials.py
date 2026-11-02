import subprocess

KEYCHAIN_SERVICE = "com.notroyalts.ssh-password"


class KeychainError(RuntimeError):
    pass


def _account(connection_id):
    return f"connection-{int(connection_id)}"


def _security(args):
    try:
        return subprocess.run(
            ["/usr/bin/security", *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise KeychainError(
            f"Could not run macOS Keychain utility: {exc}"
        ) from exc


def get_password(connection_id):
    result=_security([
        "find-generic-password",
        "-a",_account(connection_id),
        "-s",KEYCHAIN_SERVICE,
        "-w",
    ])
    if result.returncode != 0:
        return None
    password=result.stdout.rstrip("\r\n")
    return password or None


def has_password(connection_id):
    result=_security([
        "find-generic-password",
        "-a",_account(connection_id),
        "-s",KEYCHAIN_SERVICE,
    ])
    return result.returncode == 0


def set_password(connection_id,password,label=None):
    if not password:
        raise ValueError("Password cannot be empty.")

    result=_security([
        "add-generic-password",
        "-U",
        "-a",_account(connection_id),
        "-s",KEYCHAIN_SERVICE,
        "-l",label or f"NotRoyalTs SSH connection {int(connection_id)}",
        "-w",password,
    ])
    if result.returncode != 0:
        message=result.stderr.strip() or "Unknown Keychain error."
        raise KeychainError(
            f"Could not save SSH password in macOS Keychain: {message}"
        )


def clear_password(connection_id):
    result=_security([
        "delete-generic-password",
        "-a",_account(connection_id),
        "-s",KEYCHAIN_SERVICE,
    ])
    if result.returncode != 0 and get_password(connection_id) is not None:
        message=result.stderr.strip() or "Unknown Keychain error."
        raise KeychainError(
            f"Could not remove SSH password from macOS Keychain: {message}"
        )
