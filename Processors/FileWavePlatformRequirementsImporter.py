#!/usr/local/autopkg/python
"""See docstring for FileWavePlatformRequirementsImporter class"""

import os
import sys

import requests
from autopkglib import Processor, ProcessorError

# Ensure Keychain.py can be imported the same way CommandLine.py is by
# FWTool.py/FileWaveImporter.py - this processor's own directory isn't on
# sys.path when autopkg imports it directly.
sys.path.append(os.path.dirname(__file__))
import FWRestClient
import Keychain

__version__ = "1.0.0"

PLATFORM_REQUIREMENTS_URL = "/payloads/internal/payloads/{fileset_id}/platform-requirements"

# Neutral ("no restriction") values, matching what FileWave itself returns
# for a fresh/unrestricted fileset. Used to fill in the fields this
# processor doesn't currently set (required_platforms, global_options) when
# the current state can't be read - see get_current_platform_requirements().
# Extension point: to manage more fields (required_platforms, minimum
# memory, ...) later, add more input_variables and merge them into
# `payload` in main() the same way fw_required_architectures is handled.
DEFAULT_REQUIRED_PLATFORMS = {"osxKey": []}
DEFAULT_GLOBAL_OPTIONS = {
    "futureCompat": False,
    "minimumMemory": 0,
    "minimumMemoryEnabled": False,
    "applyToActive": False,
}


class FileWavePlatformRequirementsImporter(Processor):
    """Sets platform/architecture requirements on a FileWave fileset via the FileWave REST API.

    Currently only manages required_architectures (which client CPU
    architectures may install this fileset); required_platforms and
    global_options are read from the fileset's current state and passed
    through unchanged, since FileWave's PUT endpoint expects the full
    object. See the module docstring for how to extend this to more fields.
    """

    description = __doc__

    input_variables = {
        "fw_fileset_id": {
            "required": False,
            "default": None,
            "description": (
                "ID of the fileset to update, e.g. the fw_fileset_id output of "
                "FileWaveImporter. If absent/empty (e.g. FileWaveImporter skipped "
                "because no fileset was created/imported this run), this processor "
                "does nothing. KNOWN LIMITATION, confirmed against a real FileWave "
                "server: when FileWaveImporter ran with fw_create_revision: True, "
                "fw_fileset_id is that new revision's own ID, and the "
                "platform-requirements REST endpoint only accepts a fileset's own "
                "ID (which addresses its 'Initial Revision', not the current "
                "default) - so this call will currently fail with HTTP 404 in that "
                "case. There is no confirmed-working way to set platform "
                "requirements on a freshly created revision via this API yet; see "
                "README.md."
            ),
        },
        "fw_required_architectures": {
            "required": False,
            "default": None,
            "description": (
                "Restricts which client CPU architectures may install this "
                "fileset, e.g. 'silicon' or ['intel', 'silicon']. A single "
                "string or a list of strings; values are lowercased before "
                "being sent to FileWave. Replaces the fileset's full "
                "required_architectures list on FileWave's side (it is not "
                "merged with what's already set there). If absent/None, "
                "this processor does nothing."
            ),
        },
        **FWRestClient.make_common_rest_variables(),
    }
    output_variables = {
        "fw_platform_requirements_summary_result": {
            "description": "Summary of the platform requirements that were set on the fileset."
        }
    }

    @property
    def rest(self) -> FWRestClient.FWRestClient:
        if getattr(self, "_rest", None) is None:
            self._rest = FWRestClient.FWRestClient(self.env)
        return self._rest

    def get_base_url(self) -> str:
        return self.rest.base_url

    def get_api_token(self) -> str:
        try:
            return self.rest.get_api_token()
        except Keychain.KeychainError as e:
            raise ProcessorError(str(e))

    def get_headers(self) -> dict:
        try:
            return self.rest.get_headers()
        except Keychain.KeychainError as e:
            raise ProcessorError(str(e))

    def get_current_platform_requirements(self, base_url: str, fileset_id: str) -> dict:
        """Best-effort read of the fileset's current platform-requirements
        object, used so fields this processor doesn't manage (
        required_platforms, global_options) survive the PUT unchanged.
        Falls back to an empty dict (=> DEFAULT_REQUIRED_PLATFORMS/
        DEFAULT_GLOBAL_OPTIONS get used instead) on any error, with a
        visible warning - by design, per project decision, rather than
        aborting the run."""
        url = f"{base_url}{PLATFORM_REQUIREMENTS_URL.format(fileset_id=fileset_id)}"
        try:
            response = requests.get(url, headers=self.get_headers(), verify=self.rest.get_verify(), timeout=15)
            if response.status_code != 200:
                self.output(
                    f"WARNING: could not read current platform requirements for "
                    f"fileset {fileset_id} (HTTP {response.status_code}) - "
                    f"proceeding with defaults for any field not set by this recipe."
                )
                return {}
            return response.json() or {}
        except (requests.RequestException, ValueError) as e:
            self.output(
                f"WARNING: could not read current platform requirements for "
                f"fileset {fileset_id} ({e}) - proceeding with defaults for any "
                f"field not set by this recipe."
            )
            return {}

    def put_platform_requirements(self, base_url: str, fileset_id: str, payload: dict) -> None:
        url = f"{base_url}{PLATFORM_REQUIREMENTS_URL.format(fileset_id=fileset_id)}"
        response = requests.put(url, headers=self.get_headers(), json=payload, verify=self.rest.get_verify(), timeout=15)
        if response.status_code not in (200, 201, 204):
            raise ProcessorError(
                f"Error setting platform requirements on fileset {fileset_id}: "
                f"HTTP {response.status_code} - {response.text}"
            )

    def main(self):
        # Defensive scrub: FW_API_TOKEN is not a declared input variable (see
        # input_variables above) so AutoPkg shouldn't populate it, but if it
        # ends up in env anyway, remove it rather than ever reading it.
        self.env.pop("FW_API_TOKEN", None)
        # A skipped run must not repeat the previous step's summary (AutoPkg
        # reports every output variable that is set after each step).
        self.env.pop("fw_platform_requirements_summary_result", None)

        fileset_id = self.env.get("fw_fileset_id")
        if not fileset_id:
            self.output("fw_fileset_id is not set (no fileset was created/imported this run) - skipping.")
            return
        fileset_id = str(fileset_id)
        if "%" in fileset_id:
            raise ProcessorError(
                f"fw_fileset_id is unresolved ('{fileset_id}'). This usually means it was "
                "passed via an unresolved %VAR% reference in the recipe's Arguments - pass "
                "it through unset instead and let FileWavePlatformRequirementsImporter read "
                "it from env."
            )

        required_architectures = self.env.get("fw_required_architectures")
        if required_architectures is None:
            self.output("fw_required_architectures is not set, nothing to do.")
            return
        if isinstance(required_architectures, str):
            required_architectures = [required_architectures]
        required_architectures = [str(a).lower() for a in required_architectures]

        base_url = self.get_base_url()
        current = self.get_current_platform_requirements(base_url, fileset_id)

        payload = {
            "required_architectures": required_architectures,
            "required_platforms": current.get("required_platforms", DEFAULT_REQUIRED_PLATFORMS),
            "global_options": current.get("global_options", DEFAULT_GLOBAL_OPTIONS),
        }

        self.put_platform_requirements(base_url, fileset_id, payload)
        self.output(
            f"Set required_architectures={required_architectures} on fileset {fileset_id}."
        )

        self.env["fw_platform_requirements_summary_result"] = {
            "summary_text": "Platform requirements were updated on the fileset:",
            "report_fields": ["fw_fileset_id", "fw_required_architectures"],
            "data": {
                "fw_fileset_id": fileset_id,
                "fw_required_architectures": ", ".join(required_architectures),
            },
        }


if __name__ == "__main__":
    PROCESSOR = FileWavePlatformRequirementsImporter()
    PROCESSOR.execute_shell()
