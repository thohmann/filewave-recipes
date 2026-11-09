#!/usr/local/autopkg/python
"""Minimal macOS Keychain lookup helper for the FileWave processors.

FW_ADMIN_PASSWORD and FW_API_TOKEN must never be sourced from AutoPkg's own
environment (recipe Input, override, or - the common case in practice -
the global AutoPkg preferences plist via `defaults write com.github.autopkg
...`), since that leaves them in plaintext on disk and makes them show up
verbatim in `-vvv` env dumps and recipe receipts. Instead they are read
fresh, at call time, from the current user's login Keychain via the
`security` CLI (no extra Python dependency - consistent with how the rest
of this codebase shells out to CLI tools).

macOS only. Windows/Linux are out of scope (see KeychainError below).

Keychain items are looked up per FileWave server (FW_SERVER_HOST), so
different environments (e.g. test vs. prod, or different customers) can
hold different credentials without colliding.

get_secret() is the single access path: a process environment variable of
the same name wins, then the Keychain. That keeps the code independent of
whatever starts it - GitLab/Rundeck inject secrets as environment variables
per job, cron/launchd or a developer Mac use the Keychain. This is safe with
respect to AutoPkg: it only imports process environment variables named
AUTOPKG_* into its own env (verified in AutoPkg 3.0's `autopkg` script), so
FW_API_TOKEN etc. never reach receipts or -vvv output - which is also why
get_secret() refuses AUTOPKG_* names.
"""

import os
import platform
import subprocess

SECURITY_BIN = "/usr/bin/security"

ADMIN_SERVICE_TEMPLATE = "AutoPkg FileWave Admin (%s)"
API_TOKEN_SERVICE_TEMPLATE = "AutoPkg FileWave API Token (%s)"
API_TOKEN_ACCOUNT = "api-token"


class KeychainError(Exception):
    """Raised when a Keychain item can't be read: wrong platform, no
    matching item, or a `security` failure. The message always includes the
    exact `security add-generic-password` command needed to provision the
    missing item, so callers can generally just re-raise this as a
    ProcessorError without adding their own guidance."""


def find_generic_password(service: str, account: str = None) -> str:
    """Look up a generic-password Keychain item and return its secret value.

    Raises KeychainError if not running on macOS, or if no matching item is
    found in the login Keychain.
    """
    if platform.system() != "Darwin":
        raise KeychainError(
            "Keychain-based credential lookup is only supported on macOS "
            "(current platform: %s)." % platform.system()
        )

    cmd = [SECURITY_BIN, "find-generic-password", "-s", service]
    if account:
        cmd.extend(["-a", account])
    cmd.append("-w")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        add_cmd = "security add-generic-password -s \"%s\"%s -w '<value>' -U" % (
            service,
            ' -a "%s"' % account if account else "",
        )
        raise KeychainError(
            "No Keychain item found for service '%s'%s. Add it with:\n  %s"
            % (service, " / account '%s'" % account if account else "", add_cmd)
        )
    return result.stdout.rstrip("\n")


def get_secret(name: str, service: str, account: str = None) -> str:
    """Secret `name`: the process environment variable `name` if set and
    non-empty, otherwise the Keychain item `service`/`account`."""
    if name.upper().startswith("AUTOPKG_"):
        raise KeychainError(
            "Refusing secret name '%s': AutoPkg copies AUTOPKG_* environment "
            "variables into its env, receipts and -vvv output." % name
        )
    value = os.environ.get(name)
    if value:
        return value
    return find_generic_password(service, account=account)


def get_admin_password(server_host: str, admin_user: str) -> str:
    """FileWave Admin CLI password for `admin_user` on `server_host`
    (environment variable FW_ADMIN_PASSWORD, else Keychain)."""
    service = ADMIN_SERVICE_TEMPLATE % server_host
    return get_secret("FW_ADMIN_PASSWORD", service, account=admin_user)


def get_api_token(server_host: str) -> str:
    """FileWave REST API token for `server_host` (environment variable
    FW_API_TOKEN, else Keychain)."""
    service = API_TOKEN_SERVICE_TEMPLATE % server_host
    return get_secret("FW_API_TOKEN", service, account=API_TOKEN_ACCOUNT)
