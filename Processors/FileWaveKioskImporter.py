#!/usr/local/autopkg/python
"""See docstring for FileWaveKioskImporter class"""

import os
import re
import sys
from pathlib import Path
from typing import Optional

import requests
from autopkglib import Processor, ProcessorError

# Ensure Keychain.py can be imported the same way CommandLine.py is by
# FWTool.py/FileWaveImporter.py - this processor's own directory isn't on
# sys.path when autopkg imports it directly.
sys.path.append(os.path.dirname(__file__))
import FWRestClient
import Keychain

__version__ = "1.0.0"


class FileWaveKioskImporter(Processor):
    """Sets the Kiosk title, description and icon of an existing FileWave fileset via the FileWave REST API."""

    description = __doc__

    # Same default as every other FileWave processor, so all steps of a
    # recipe talk to the same server when FW_SERVER_HOST isn't set.
    DEFAULT_FW_SERVER_HOST = FWRestClient.DEFAULT_FW_SERVER_HOST
    ID_TAG = "{ID}"
    KIOSK_OPTIONS_URL = f"/payloads/internal/payloads/{ID_TAG}/options"
    KIOSK_ICON_URL = f"/payloads/internal/payloads/{ID_TAG}/icon"

    input_variables = {
        "fileset_id": {
            "required": True,
            "description": (
                "Fileset ID of the Fileset that should be edited. KNOWN "
                "LIMITATION, confirmed against a real FileWave server: this "
                "processor's /options and /icon REST endpoints only accept a "
                "fileset's own ID, which always addresses its 'Initial "
                "Revision' placeholder - never whichever revision is actually "
                "the current default, let alone a specific non-default one. "
                "If this came from a FileWaveImporter run with "
                "fw_create_revision: True, fileset_id is that new revision's "
                "own (different) ID instead, which will fail with HTTP 404 "
                "('No FilesetRevision matches the given query') here. "
                "Reliable only for classic-mode filesets for now; see README.md."
            ),
        },
        "kiosk_title": {
            "required": True,
            "description": "Title shown in kiosk ",
        },
        "kiosk_description": {
            "required": False,
            "description": "Description text shown in kiosk ",
        },
        "kiosk_icon_path": {
            "required": False,
            "description": "Path to the icon shown in kiosk",
        },
        # No FW_API_TOKEN entry here on purpose: the token is never read from
        # the AutoPkg environment (recipe/override/global preferences) - it's
        # looked up fresh from the macOS Keychain, same convention as
        # FileWaveScriptImporter/FileWavePlatformRequirementsImporter. See
        # Keychain.py and FWRestClient.py.
        **FWRestClient.make_common_rest_variables(default_host=DEFAULT_FW_SERVER_HOST),
    }
    output_variables = {}

    @property
    def rest(self) -> FWRestClient.FWRestClient:
        if getattr(self, "_rest", None) is None:
            self._rest = FWRestClient.FWRestClient(self.env, default_host=self.DEFAULT_FW_SERVER_HOST)
        return self._rest

    def get_api_token(self) -> str:
        try:
            return self.rest.get_api_token()
        except Keychain.KeychainError as e:
            raise ProcessorError(str(e))

    def main(self):
        # Defensive scrub: FW_API_TOKEN is not a declared input variable (see
        # input_variables above) so AutoPkg shouldn't populate it, but if it
        # ends up in env anyway, remove it rather than ever reading it.
        self.env.pop("FW_API_TOKEN", None)

        # "" after a skipped FileWaveImporter (AutoPkg substitutes None as "")
        fileset_id = str(self.env.get("fileset_id") or "")
        kiosk_title = self.env.get("kiosk_title")
        kiosk_description = self.env.get("kiosk_description")
        raw_icon_path = self.env.get("kiosk_icon_path")
        kiosk_icon_path = Path(raw_icon_path) if raw_icon_path else None

        if re.match("^[0-9]+$", fileset_id):
            self.api_token = self.get_api_token()
            retcode_options = self.set_kiosk_options(fileset_id, kiosk_title, kiosk_description)
            if not retcode_options:
                raise ProcessorError("Error: Couldn’t set kiosk options.")

            if kiosk_icon_path is not None:
                retcode_icon = self.set_kiosk_icon(fileset_id, kiosk_icon_path)
                if not retcode_icon:
                    raise ProcessorError("Error: Couldn’t set kiosk icon.")
            else:
                print("No kiosk_icon_path provided, skipping kiosk icon upload")
        else:
            print("No Fileset ID found, skipping import of kiosk options and icon")

    def get_base_url(self) -> str:
        return self.rest.base_url

    def get_fw_url(self, suffix: str, id: str) -> str:
        return f"{self.get_base_url()}{suffix}".replace(self.ID_TAG, id)

    def set_kiosk_icon(self, id: str, icon_path: Path) -> bool:
        image_content_types_and_suffix = {
            "image/png": "png",
            "image/jpeg": "jpg",
        }
        suffix = icon_path.suffix[1:]
        if suffix not in image_content_types_and_suffix.values():
            print(f"Invalid kiosk icon suffix: {suffix}.")
            return False
        content_type = [t for t, s in image_content_types_and_suffix.items() if s == suffix][0]

        request_url = self.get_fw_url(self.KIOSK_ICON_URL, id)
        request_headers = {
            "Authorization": self.api_token,
            "Content-Type": content_type,
            "Content-Disposition": f"attachment; filename={icon_path.name}",
        }
        image_data: Optional[bytes] = None
        with open(icon_path, mode="rb") as file:
            image_data = file.read()

        response = requests.patch(
            url=request_url, headers=request_headers, data=image_data,
            verify=self.rest.get_verify(), timeout=15,
        )
        if response.status_code != 200:
            self._log_curl_repro(response)
            print(f"Error code: {response.status_code}. Content: {response.content}")
            return False

        return True

    def set_kiosk_options(self, id: str, title: str, description: str) -> bool:
        request_url = self.get_fw_url(self.KIOSK_OPTIONS_URL, id)
        request_headers = {"Authorization": self.api_token, "Content-Type": "application/json"}
        body = {"kiosk_title": title, "kiosk_description": description}

        response = requests.patch(
            url=request_url, headers=request_headers, json=body,
            verify=self.rest.get_verify(), timeout=15,
        )
        if response.status_code != 200:
            self._log_curl_repro(response)
            print(f"Error code: {response.status_code}. Content: {response.content}")
            return False

        return True

    def _log_curl_repro(self, response) -> None:
        """Best-effort: print a curl repro of the failed request, with the
        Authorization header (the API token) redacted. `curlify` is an
        optional debug helper - if it isn't installed alongside AutoPkg's own
        python, skip the repro line rather than raising ModuleNotFoundError
        for what was otherwise a normal, reportable API error."""
        try:
            import curlify
        except ImportError:
            return
        curl_command = curlify.to_curl(response.request)
        token = getattr(self, "api_token", None)
        if token:
            curl_command = curl_command.replace(token, "***REDACTED***")
        print(curl_command)


if __name__ == "__main__":
    PROCESSOR = FileWaveKioskImporter()
    PROCESSOR.execute_shell()
