#!/usr/local/autopkg/python
"""See docstring for FileWaveScriptImporter class"""

import os
import re
import sys
from pathlib import Path

import requests
from autopkglib import Processor, ProcessorError

# Ensure Keychain.py can be imported the same way CommandLine.py is by
# FWTool.py/FileWaveImporter.py - this processor's own directory isn't on
# sys.path when autopkg imports it directly.
sys.path.append(os.path.dirname(__file__))
import FWRestClient
import Keychain

__version__ = "1.0.0"

DEFAULT_FW_SERVER_HOST = "localhost"

SCRIPTS_OVERVIEW_URL = "/payloads/internal/payloads/{fileset_id}/scripts/overview"
SCRIPTS_COLLECTION_URL = "/payloads/internal/payloads/{fileset_id}/scripts"
SCRIPT_ITEM_URL = "/payloads/internal/payloads/{fileset_id}/scripts/{script_id}"

# Known FileWave fileset script types (as seen in the FileWave Admin web UI).
VALID_SCRIPT_TYPES = {
    "activationScripts",
    "requirementScripts",
    "preflightScripts",
    "postflightScripts",
    "preUninstallationScripts",
    "postUninstallationScripts",
    "verificationScripts",
}

# Built-in script templates shipped next to this processor, addressable by name
# (independent of script_type - the same template can be used as e.g. both a
# preflightScripts and a requirementScripts entry).
VORLAGEN_DIR = Path(__file__).parent / "vorlagen"
TEMPLATE_REGISTRY = {
    "app_running_check": "app_running_check.sh",
    "install_update_requirement": "install_update_requirement.sh",
    "cleanup_paths_and_receipts": "cleanup_paths_and_receipts.sh",
    "adobe_uninstall": "adobe_uninstall.sh",
}

# AutoPkg-style %VAR% placeholders.
PLACEHOLDER_RE = re.compile(r"%([A-Za-z0-9_]+)%")
# Characters that are still special inside a double-quoted bash string.
DOUBLE_QUOTE_SPECIAL_RE = re.compile(r'([\\"$`])')


def shell_escape(value) -> str:
    """str(value), escaped for use inside a double-quoted bash string (the
    templates always write "%VAR%"), so a value such as a vendor's version
    string can't break out of the quotes and run code on the clients."""
    return DOUBLE_QUOTE_SPECIAL_RE.sub(r"\\\1", str(value))


class FileWaveScriptImporter(Processor):
    """Uploads one or more scripts to a FileWave fileset via the FileWave REST API.

    Each entry in fw_scripts is read from disk, has %VAR% placeholders substituted
    using the AutoPkg environment (plus fw_script_variables), and is then created or
    (if a script with the same name/type already exists on the fileset) updated.
    """

    description = __doc__

    input_variables = {
        "fw_fileset_id": {
            "required": False,
            "default": None,
            "description": (
                "ID of the fileset the scripts should be attached to, e.g. the "
                "fw_fileset_id output of FileWaveImporter. If absent/empty (e.g. "
                "FileWaveImporter skipped because no fileset was created/imported "
                "this run), this processor does nothing. Note: when FileWaveImporter "
                "ran with fw_create_revision: True, fw_fileset_id is that specific "
                "new revision's own ID (not the parent fileset's) - confirmed "
                "against a real FileWave server that this, not the fileset's own "
                "ID, is what correctly attaches scripts to that revision via the "
                "REST API, regardless of fw_set_revision_as_default."
            ),
        },
        "fw_scripts": {
            "required": True,
            "description": (
                "List of dicts describing the scripts to upload. Each dict requires "
                "'script_type' (one of: %s) and exactly one of the following sources: "
                "'template' (name of a built-in template, one of: %s), "
                "'path' (path to a script file, e.g. relative to %%RECIPE_DIR%%), or "
                "'content' (the script text inline). 'name' (upload file name) is "
                "derived from 'template'/'path' if omitted, but required with 'content'. "
                "'order' is optional. 'variables' (optional dict) is merged on top of "
                "fw_script_variables for %%VAR%% substitution in this script only - use it "
                "to document which variables a given script actually consumes."
                % (
                    ", ".join(sorted(VALID_SCRIPT_TYPES)),
                    ", ".join(sorted(TEMPLATE_REGISTRY)),
                )
            ),
        },
        "fw_script_variables": {
            "required": False,
            "default": {},
            "description": (
                "Dict of additional key/value pairs used for %VAR% substitution in "
                "script content, on top of the AutoPkg environment variables. Values "
                "are escaped for use inside double quotes (write \"%VAR%\" in the "
                "script); list values are rendered as a bash array literal, e.g. "
                "\"a\" \"b\"."
            ),
        },
        # No FW_API_TOKEN entry here on purpose: the token is never read from
        # the AutoPkg environment (recipe/override/global preferences) - it's
        # looked up fresh from the macOS Keychain, same convention as
        # FileWaveKioskImporter/FileWavePlatformRequirementsImporter. See
        # Keychain.py and FWRestClient.py.
        **FWRestClient.make_common_rest_variables(),
    }
    output_variables = {
        "fw_script_import_summary_result": {
            "description": "Summary of the scripts that were created/updated on the fileset."
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

    def substitute_variables(self, content: str, script_variables: dict = None) -> str:
        variables = dict(self.env)
        variables.update(self.env.get("fw_script_variables") or {})
        variables.update(script_variables or {})

        def replace(match: "re.Match") -> str:
            key = match.group(1)
            if key not in variables:
                return match.group(0)
            value = variables[key]
            if isinstance(value, (list, tuple)):
                return " ".join(f'"{shell_escape(item)}"' for item in value)
            return shell_escape(value)

        return PLACEHOLDER_RE.sub(replace, content)

    def resolve_script_source(self, script_def: dict) -> tuple:
        """Returns (raw_content, default_name) for a fw_scripts entry, reading from
        exactly one of 'template', 'path' or 'content'."""
        sources = [key for key in ("template", "path", "content") if script_def.get(key)]
        if len(sources) != 1:
            raise ProcessorError(
                f"Script definition needs exactly one of 'template', 'path' or 'content': {script_def}"
            )
        source = sources[0]

        if source == "template":
            template_name = script_def["template"]
            filename = TEMPLATE_REGISTRY.get(template_name)
            if filename is None:
                raise ProcessorError(
                    f"Unknown template '{template_name}'. Valid templates: "
                    f"{', '.join(sorted(TEMPLATE_REGISTRY))}"
                )
            template_path = VORLAGEN_DIR / filename
            if not template_path.is_file():
                raise ProcessorError(f"Template file not found: {template_path}")
            return template_path.read_text(encoding="utf-8"), template_path.name

        if source == "path":
            script_path = Path(script_def["path"])
            if not script_path.is_file():
                raise ProcessorError(f"Script file not found: {script_path}")
            return script_path.read_text(encoding="utf-8"), script_path.name

        # source == "content"
        if not script_def.get("name"):
            raise ProcessorError(f"'name' is required when using 'content': {script_def}")
        return script_def["content"], None

    def get_existing_scripts(self, base_url: str, fileset_id: str) -> list:
        """Best-effort lookup of scripts already present on the fileset, used to
        decide create vs. update.

        Confirmed against real FileWave servers: .../scripts/overview returns
        scripts grouped by type (e.g. {"requirementScripts": [...], ...}), and
        - unlike creating/updating a script itself, which needs a specific
        revision's own ID (see fw_fileset_id's description) - only resolves
        for a *fileset's* ID, where it reflects whatever is currently that
        fileset's default revision. That means this lookup is only meaningful
        in classic (fw_create_revision: false) mode, where fileset_id already
        is the fileset's own ID; in revision mode fileset_id is the new
        revision's own ID instead, which 404s here - falling back to an empty
        list (=> always create) is correct in that case anyway, since a
        freshly created revision can't have any pre-existing scripts on it."""
        url = f"{base_url}{SCRIPTS_OVERVIEW_URL.format(fileset_id=fileset_id)}"
        try:
            response = requests.get(url, headers=self.get_headers(), verify=self.rest.get_verify(), timeout=15)
            if response.status_code != 200:
                return []
            overview = response.json() or {}
            scripts = []
            for script_type, entries in overview.items():
                if script_type not in VALID_SCRIPT_TYPES or not entries:
                    continue
                for entry in entries:
                    entry = dict(entry)
                    entry.setdefault("script_type", script_type)
                    scripts.append(entry)
            return scripts
        except (requests.RequestException, ValueError):
            return []

    def upload_script(
        self,
        base_url: str,
        fileset_id: str,
        existing_scripts: list,
        name: str,
        content: str,
        script_type: str,
        order,
    ) -> str:
        headers = self.get_headers()
        verify = self.rest.get_verify()
        match = next(
            (
                s
                for s in existing_scripts
                if s.get("name") == name and s.get("script_type") == script_type
            ),
            None,
        )

        if match:
            script_id = match.get("id")
            body = {"id": script_id, "name": name, "content": content, "script_type": script_type, "order": order}
            url = f"{base_url}{SCRIPT_ITEM_URL.format(fileset_id=fileset_id, script_id=script_id)}"
            response = requests.patch(url, headers=headers, json=body, verify=verify, timeout=15)
            action = "updated"
        else:
            body = {"id": None, "name": name, "content": content, "script_type": script_type, "order": order}
            url = f"{base_url}{SCRIPTS_COLLECTION_URL.format(fileset_id=fileset_id)}"
            response = requests.post(url, headers=headers, json=body, verify=verify, timeout=15)
            action = "created"

        if response.status_code not in (200, 201, 204):
            raise ProcessorError(
                f"Error uploading script '{name}' ({script_type}): "
                f"HTTP {response.status_code} - {response.text}"
            )
        return action

    def main(self):
        # Defensive scrub: FW_API_TOKEN is not a declared input variable (see
        # input_variables above) so AutoPkg shouldn't populate it, but if it
        # ends up in env anyway, remove it rather than ever reading it.
        self.env.pop("FW_API_TOKEN", None)
        # A skipped run must not repeat the previous step's summary (AutoPkg
        # reports every output variable that is set after each step).
        self.env.pop("fw_script_import_summary_result", None)

        fileset_id = self.env.get("fw_fileset_id")
        if not fileset_id:
            self.output("fw_fileset_id is not set (no fileset was created/imported this run) - skipping.")
            return
        fileset_id = str(fileset_id)
        if "%" in fileset_id:
            raise ProcessorError(
                f"fw_fileset_id is unresolved ('{fileset_id}'). This usually means it was "
                "passed via an unresolved %VAR% reference in the recipe's Arguments - pass "
                "it through unset instead and let FileWaveScriptImporter read it from env."
            )
        scripts = self.env["fw_scripts"]
        if not scripts:
            self.output("fw_scripts is empty, nothing to do.")
            return

        base_url = self.get_base_url()
        existing_scripts = self.get_existing_scripts(base_url, fileset_id)

        uploaded = []
        for script_def in scripts:
            script_type = script_def.get("script_type")
            if not script_type:
                raise ProcessorError(f"Script definition needs 'script_type': {script_def}")
            if script_type not in VALID_SCRIPT_TYPES:
                raise ProcessorError(
                    f"Invalid script_type '{script_type}'. Valid values: "
                    f"{', '.join(sorted(VALID_SCRIPT_TYPES))}"
                )

            raw_content, default_name = self.resolve_script_source(script_def)
            name = script_def.get("name") or default_name
            order = script_def.get("order")
            content = self.substitute_variables(raw_content, script_def.get("variables"))

            action = self.upload_script(
                base_url, fileset_id, existing_scripts, name, content, script_type, order
            )
            self.output(f"Script '{name}' ({script_type}) {action} on fileset {fileset_id}.")
            uploaded.append(f"{name} ({script_type}, {action})")

        self.env["fw_script_import_summary_result"] = {
            "summary_text": "The following scripts were uploaded to the fileset:",
            "report_fields": ["fw_fileset_id", "fw_scripts_uploaded"],
            "data": {
                "fw_fileset_id": fileset_id,
                "fw_scripts_uploaded": ", ".join(uploaded),
            },
        }


if __name__ == "__main__":
    PROCESSOR = FileWaveScriptImporter()
    PROCESSOR.execute_shell()
