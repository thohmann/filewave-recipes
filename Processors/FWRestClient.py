#!/usr/local/autopkg/python
"""Shared FileWave REST API client helpers.

Used by FileWaveScriptImporter, FileWaveKioskImporter and
FileWavePlatformRequirementsImporter - all three talk to the same FileWave
REST API with identical conventions (base URL, Keychain-sourced
Authorization token, TLS verification), which would otherwise be
triplicated per-processor boilerplate.

This module is deliberately autopkglib-independent (like CommandLine.py and
Keychain.py): it raises Keychain.KeychainError, not ProcessorError, and
callers are expected to catch that and re-raise as ProcessorError with
whatever context makes sense for that call site.
"""

import os
import sys

sys.path.append(os.path.dirname(__file__))
import Keychain

DEFAULT_FW_SERVER_HOST = "localhost"


def make_common_rest_variables(default_host: str = DEFAULT_FW_SERVER_HOST) -> dict:
    """Returns the FW_SERVER_HOST/FW_API_VERIFY_SSL input_variables dict
    shared by every FileWave REST API processor, with FW_SERVER_HOST's
    default set to `default_host`. All processors use the same default
    (localhost, like FWTool), so every step of a recipe talks to the same
    server when FW_SERVER_HOST isn't set.

    Merge into a processor's own input_variables with
    `**FWRestClient.make_common_rest_variables()` (or with an explicit
    default_host to override it).
    """
    return {
        "FW_SERVER_HOST": {
            "required": False,
            "default": default_host,
            "description": (
                "Hostname of the FileWave server (same variable as used by "
                "FWTool/FileWaveImporter and the other FileWave REST API "
                "processors). Can be set globally via the AutoPkg preferences "
                "plist."
            ),
        },
        "FW_API_VERIFY_SSL": {
            "required": False,
            "default": True,
            "description": (
                "TLS certificate verification for FileWave REST API calls. "
                "True (default): normal strict verification. False: disable "
                "verification entirely - only for a trusted local/internal "
                "test server with a self-signed certificate, never for "
                "production. A path to a CA bundle/certificate file: verify "
                "against that instead of the system trust store (same "
                "semantics as requests' own verify= parameter). Meant to be "
                "set once globally via `defaults write com.github.autopkg "
                "FW_API_VERIFY_SSL ...` for a test machine, not per recipe."
            ),
        },
    }


class FWRestClient:
    """Wraps the FileWave REST API conventions shared across processors:
    base URL, Keychain-sourced Authorization token (cached per instance),
    and TLS verification (FW_API_VERIFY_SSL).

    `env` is the owning Processor's self.env, read live (not copied) - a
    change to FW_SERVER_HOST/FW_API_VERIFY_SSL made before a request is
    picked up. `default_host` is used when FW_SERVER_HOST isn't set - pass
    the same value given to make_common_rest_variables() for that processor.
    """

    def __init__(self, env, default_host: str = DEFAULT_FW_SERVER_HOST):
        self.env = env
        self.default_host = default_host
        self._api_token = None
        self._verify_notice_printed = False

    @property
    def base_url(self) -> str:
        host = self.env.get("FW_SERVER_HOST") or self.default_host
        return f"https://{host}/api"

    def get_api_token(self) -> str:
        """Raises Keychain.KeychainError if no matching Keychain item is
        found - callers should catch that and raise ProcessorError."""
        if self._api_token is None:
            host = self.env.get("FW_SERVER_HOST") or self.default_host
            self._api_token = Keychain.get_api_token(host)
        return self._api_token

    def get_headers(self) -> dict:
        return {
            "Authorization": self.get_api_token(),
            "Content-Type": "application/json",
        }

    def get_verify(self):
        """Value to pass as requests' verify= kwarg for every FileWave REST
        API call. See COMMON_REST_VARIABLES['FW_API_VERIFY_SSL'] above for
        the full semantics."""
        verify = self.env.get("FW_API_VERIFY_SSL")
        if verify is None or verify is True:
            return True
        # Notice printed once per client, not on every request - a release
        # run makes hundreds of calls.
        print_notice = not self._verify_notice_printed
        self._verify_notice_printed = True
        if verify is False:
            if print_notice:
                print(
                    "WARNING: FW_API_VERIFY_SSL is False - TLS certificate "
                    "verification is disabled for FileWave REST API calls. Only "
                    "use this against a trusted local/internal test server, "
                    "never in production."
                )
            return False
        if print_notice:
            print(
                f"FW_API_VERIFY_SSL: verifying against custom CA bundle "
                f"'{verify}' instead of the system trust store."
            )
        return verify
