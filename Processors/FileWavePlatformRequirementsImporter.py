#!/usr/local/autopkg/python
"""See docstring for FileWavePlatformRequirementsImporter class"""

import os
import plistlib
import sys

import requests
from autopkglib import Processor, ProcessorError

# Ensure Keychain.py can be imported the same way CommandLine.py is by
# FWTool.py/FileWaveImporter.py - this processor's own directory isn't on
# sys.path when autopkg imports it directly.
sys.path.append(os.path.dirname(__file__))
import FWRestClient
import Keychain

__version__ = "1.2.0"

PLATFORM_REQUIREMENTS_URL = "/payloads/internal/payloads/{fileset_id}/platform-requirements"
PAYLOAD_URL = "/payloads/v1/payloads/{fileset_id}"

# FileWave stores requirements internally as one flat list ("requirements" in
# the revision's properties_xml plist) with switch flags next to the keys:
# platformCheck/archCheck/systemCheck = the "Plattform"/"Architektur"/
# "Systemversion" boxes in FileWave Admin. The platform-requirements endpoint
# always adds systemCheck as soon as osxKey is sent (verified live, even for
# an empty list) and doesn't show these flags in its GET response. The only
# way found to untick "Systemversion" is to drop the flag from properties_xml
# via PATCH on the payload - see clear_system_version_check().
SYSTEM_VERSION_FLAG = "systemCheck"

# Architecture keys the platform-requirements endpoint accepts (verified
# live: case-sensitive, mixed casing; anything else -> HTTP 400 "Unsupported
# architecture key"). Recipe values are matched case-insensitively against
# these and sent in FileWave's own spelling.
ARCHITECTURE_KEYS = ("intel", "silicon", "32Bit", "64Bit")
_ARCHITECTURE_LOOKUP = {key.lower(): key for key in ARCHITECTURE_KEYS}

# Always added on top of the recipe's architectures (the "64-bit"/"32-bit"
# boxes in FileWave Admin); not a recipe setting, per project decision.
ALWAYS_ARCHITECTURES = ["32Bit", "64Bit"]

# Platform "macOS" without a system-version restriction: FileWave Admin stores
# that as every macOS version key plus no systemCheck flag (see
# SYSTEM_VERSION_FLAG above - the PUT alone always sets the flag).
# These are all keys the server accepts (verified live; older ones such as
# 'yosemite' -> HTTP 400). 'goldenGate' is the "andere" (other) box. An
# empty list ({"osxKey": []}, the state of a freshly imported fileset) is
# NOT the same thing.
MACOS_VERSION_KEYS = [
    "goldenGate", "tahoe", "sequoia", "sonoma", "ventura", "monterey",
    "bigSur", "catalina", "mojave", "highSierra", "sierra", "elCapitan",
]
REQUIRED_PLATFORMS = {"osxKey": MACOS_VERSION_KEYS}

# Neutral global_options, matching what FileWave itself returns for a fresh
# fileset. Used when the current state can't be read - see
# get_current_platform_requirements().
DEFAULT_GLOBAL_OPTIONS = {
    "futureCompat": False,
    "minimumMemory": 0,
    "minimumMemoryEnabled": False,
    "applyToActive": False,
}


def normalize_architectures(values) -> list:
    """Map the recipe's fw_required_architectures (string or list, any case)
    to FileWave's keys, append ALWAYS_ARCHITECTURES, drop duplicates.
    Raises ValueError on an unknown value."""
    if isinstance(values, str):
        values = [values]
    result = []
    for value in list(values) + ALWAYS_ARCHITECTURES:
        key = _ARCHITECTURE_LOOKUP.get(str(value).strip().lower())
        if key is None:
            raise ValueError(
                f"Unsupported architecture '{value}' - use one of {', '.join(ARCHITECTURE_KEYS)}."
            )
        if key not in result:
            result.append(key)
    return result


class FileWavePlatformRequirementsImporter(Processor):
    """Sets platform/architecture requirements on a FileWave fileset via the FileWave REST API.

    Sets required_architectures (the recipe's fw_required_architectures plus
    32Bit/64Bit, always) and required_platforms (macOS, no system-version
    restriction - see MACOS_VERSION_KEYS and SYSTEM_VERSION_FLAG). global_options is read from the
    fileset's current state and passed through unchanged, since FileWave's
    PUT endpoint expects the full object.
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
                "string or a list of strings, matched case-insensitively "
                "against FileWave's keys (intel, silicon, 32Bit, 64Bit). "
                "32Bit and 64Bit are always added. Replaces the fileset's "
                "full required_architectures list on FileWave's side (it is "
                "not merged with what's already set there). If absent/None, "
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
        object, used so global_options (not managed by this processor)
        survives the PUT unchanged. Falls back to an empty dict (=>
        DEFAULT_GLOBAL_OPTIONS gets used instead) on any error, with a
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

    def clear_system_version_check(self, base_url: str, fileset_id: str) -> bool:
        """Remove SYSTEM_VERSION_FLAG from the internal requirements list of
        the revision the platform-requirements endpoint addresses (the
        fileset's Initial Revision, id == fileset_id). Returns True if the
        flag was removed, False if it wasn't set. Raises ProcessorError on
        any HTTP/parse error."""
        url = f"{base_url}{PAYLOAD_URL.format(fileset_id=fileset_id)}"
        try:
            response = requests.get(url, headers=self.get_headers(), verify=self.rest.get_verify(), timeout=15)
        except requests.RequestException as e:
            raise ProcessorError(f"Error reading fileset {fileset_id}: {e}")
        if response.status_code != 200:
            raise ProcessorError(
                f"Error reading fileset {fileset_id}: HTTP {response.status_code} - {response.text}"
            )
        revisions = response.json().get("fileset_revisions") or []
        revision = next((r for r in revisions if str(r.get("id")) == fileset_id), None)
        if revision is None or not revision.get("properties_xml"):
            raise ProcessorError(
                f"Fileset {fileset_id} has no revision {fileset_id} with properties_xml - "
                "cannot clear the system-version requirement."
            )
        try:
            properties = plistlib.loads(revision["properties_xml"].encode("utf-8"))
        except Exception as e:  # plistlib raises several unrelated types
            raise ProcessorError(f"Cannot parse properties_xml of fileset {fileset_id}: {e}")
        requirements = properties.get("requirements") or []
        if SYSTEM_VERSION_FLAG not in requirements:
            return False
        properties["requirements"] = [r for r in requirements if r != SYSTEM_VERSION_FLAG]
        body = {"fileset_revisions": [{
            "id": revision["id"],
            "properties_xml": plistlib.dumps(properties).decode("utf-8"),
        }]}
        try:
            response = requests.patch(url, headers=self.get_headers(), json=body, verify=self.rest.get_verify(), timeout=15)
        except requests.RequestException as e:
            raise ProcessorError(f"Error clearing the system-version requirement on fileset {fileset_id}: {e}")
        if response.status_code not in (200, 204):
            raise ProcessorError(
                f"Error clearing the system-version requirement on fileset {fileset_id}: "
                f"HTTP {response.status_code} - {response.text}"
            )
        return True

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
        try:
            required_architectures = normalize_architectures(required_architectures)
        except ValueError as e:
            raise ProcessorError(str(e))

        base_url = self.get_base_url()
        current = self.get_current_platform_requirements(base_url, fileset_id)

        payload = {
            "required_architectures": required_architectures,
            "required_platforms": REQUIRED_PLATFORMS,
            "global_options": current.get("global_options", DEFAULT_GLOBAL_OPTIONS),
        }

        self.put_platform_requirements(base_url, fileset_id, payload)
        self.clear_system_version_check(base_url, fileset_id)
        self.output(
            f"Set required_architectures={required_architectures} and platform macOS "
            f"(no system-version restriction) on fileset {fileset_id}."
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
