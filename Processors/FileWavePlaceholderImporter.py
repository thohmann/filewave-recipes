#!/usr/local/autopkg/python
"""See docstring for FileWavePlaceholderImporter class"""

import os
import shutil
import subprocess
import sys
import tempfile

from autopkglib import ProcessorError

# This processor is imported by AutoPkg explicitly, so its directory is not in
# the search path.
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)
from AppIconExtractor import AppIconExtractor
from FWTool import COMMON_FILEWAVE_VARIABLES, FWTool

__all__ = ["FileWavePlaceholderImporter"]

# Same key release/FWRelease.py looks the placeholder up by. Deliberately not
# autopkg_app_bundle_id: FileWaveImporter's version check must never see it.
DEPENDENCY_BUNDLE_ID_PROPERTY = "autopkg_dependency_bundle_id"
FILEWAVE_SUMMARY_RESULT = "filewave_summary_result"


class FileWavePlaceholderImporter(FWTool):
    """Creates an app's placeholder fileset once: an empty fileset tagged with
    the custom property autopkg_dependency_bundle_id. The release tooling
    finds it by that property and re-points its dependency to the approved
    Installation fileset; the following FileWaveScriptImporter and
    FileWaveKioskImporter steps give it the uninstall script and Kiosk data.

    If a fileset with that property already exists, nothing happens and
    fw_fileset_id stays unset, so the following steps skip: an existing
    placeholder (possibly in use) is never modified.
    """

    description = __doc__

    placeholder_variables = {
        "fw_placeholder_name": {
            "required": True,
            "description": "Name of the placeholder fileset, e.g. 'Google Chrome (App)'.",
        },
        "fw_dependency_bundle_id": {
            "required": True,
            "description": (
                "Value of the custom property autopkg_dependency_bundle_id: the "
                "fw_app_bundle_id of the Installation fileset this placeholder stands for."
            ),
        },
        "fw_fileset_group": {
            "required": False,
            "description": "Fileset group to create the placeholder in; created if missing.",
        },
        "fw_icon_path": {
            "required": False,
            "description": (
                "A ready-made Kiosk icon (png/jpg), e.g. adobe_icon_path of "
                "AdobeAdminConsolePackageFinder. Wins over fw_icon_source."
            ),
        },
        "fw_icon_source": {
            "required": False,
            "description": (
                "Package (.pkg) the Kiosk icon is taken from. Only read when the "
                "placeholder is created; without it, or if no icon is found, the "
                "placeholder gets no icon."
            ),
        },
        "fw_icon_app_name": {
            "required": False,
            "description": (
                "App whose icon is used, without .app (a path like 'Folder/App' "
                "is reduced to its last component). Defaults to APP_NAME."
            ),
        },
    }

    input_variables = dict(COMMON_FILEWAVE_VARIABLES, **placeholder_variables)

    output_variables = {
        "fw_fileset_id": {
            "description": "ID of the placeholder if it was created in this run, otherwise unset."
        },
        "kiosk_icon_path": {
            "description": "PNG of the app icon if one was extracted, otherwise unset."
        },
        FILEWAVE_SUMMARY_RESULT: {
            "description": "Summary of the created placeholder."
        },
    }

    def main(self):
        self.validate_tools(print_path=False, list_filesets=False)

        # Always reset first (as FileWaveImporter does): the steps after this
        # one must never act on the Update fileset of the step before.
        self.env["fw_fileset_id"] = None
        self.env["kiosk_icon_path"] = None
        self.env.pop(FILEWAVE_SUMMARY_RESULT, None)

        name = str(self.env.get("fw_placeholder_name") or "").strip()
        bundle_id = str(self.env.get("fw_dependency_bundle_id") or "").strip()
        if not name or not bundle_id:
            raise ProcessorError("fw_placeholder_name and fw_dependency_bundle_id are required.")
        for value in (name, bundle_id):
            if "%" in value:
                raise ProcessorError(f"Unresolved variable in '{value}'.")
        group = self.env.get("fw_fileset_group") or None

        same_name = None
        for fileset in self.client.get_filesets():
            if fileset.custom_properties.get(DEPENDENCY_BUNDLE_ID_PROPERTY) == bundle_id:
                self.output(
                    f"Placeholder for {bundle_id} already exists: fileset {fileset.id} "
                    f"'{fileset.name}' - left untouched."
                )
                return
            if fileset.name == name:
                same_name = fileset
        if same_name is not None:
            # e.g. a placeholder made by hand before this processor existed
            raise ProcessorError(
                f"A fileset called '{name}' (ID {same_name.id}) exists, but without "
                f"{DEPENDENCY_BUNDLE_ID_PROPERTY}={bundle_id}. If it is this app's placeholder, "
                "set that custom property on it; otherwise rename it."
            )

        try:
            fileset_id = self.client.create_empty_fileset(name, group)
            self.client.set_property(fileset_id, DEPENDENCY_BUNDLE_ID_PROPERTY, bundle_id)
        except Exception as e:
            raise ProcessorError(f"Error creating the placeholder fileset '{name}'. Reason: {e}")
        self.output(f"Created placeholder fileset {fileset_id} '{name}' for {bundle_id}.")

        self.env["fw_fileset_id"] = fileset_id
        self.env[FILEWAVE_SUMMARY_RESULT] = {
            "summary_text": "The following placeholder fileset was created:",
            "report_fields": ["fw_fileset_id", "fw_fileset_group", "fw_fileset_name"],
            "data": {
                "fw_fileset_id": fileset_id,
                "fw_fileset_group": group if group is not None else "Root",
                "fw_fileset_name": name,
            },
        }

        try:
            self.env["kiosk_icon_path"] = self.extract_icon()
        except Exception as e:
            # the icon is a nicety - never fail the run over it
            self.output(f"WARNING: no Kiosk icon for '{name}': {e}")

    def extract_icon(self):
        """Path of the Kiosk icon: fw_icon_path, else the app icon taken from
        fw_icon_source, else None."""
        ready_made = self.env.get("fw_icon_path")
        if ready_made:
            if not os.path.isfile(ready_made):
                raise ProcessorError(f"fw_icon_path '{ready_made}' does not exist")
            return str(ready_made)
        source = self.env.get("fw_icon_source")
        app_name = os.path.basename(str(self.env.get("fw_icon_app_name") or self.env.get("APP_NAME") or ""))
        if not source or not app_name:
            self.output("No fw_icon_path, fw_icon_source or app name - placeholder gets no Kiosk icon.")
            return None
        if not str(source).lower().endswith(".pkg") or not os.path.isfile(source):
            raise ProcessorError(f"'{source}' is not a flat package")

        cache_dir = self.env.get("RECIPE_CACHE_DIR") or tempfile.gettempdir()
        os.makedirs(cache_dir, exist_ok=True)
        work_dir = tempfile.mkdtemp(prefix="placeholder_icon_", dir=cache_dir)
        try:
            expanded = os.path.join(work_dir, "pkg")   # pkgutil wants a new folder
            result = subprocess.run(["/usr/sbin/pkgutil", "--expand-full", source, expanded],
                                    capture_output=True, text=True)
            if result.returncode != 0:
                raise ProcessorError(f"pkgutil --expand-full failed: {result.stderr.strip()}")
            app_path = self.find_app(expanded, app_name + ".app")
            if app_path is None:
                raise ProcessorError(f"no {app_name}.app in {source}")
            extractor = AppIconExtractor()
            extractor.env = {"app_path": app_path, "output_dir": cache_dir, "icon_size": "256",
                             "output_filename": app_name + " Kiosk-Icon"}
            extractor.main()
            return extractor.env.get("icon_path") or os.path.join(cache_dir, app_name + " Kiosk-Icon.png")
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    @staticmethod
    def find_app(root, bundle_name):
        """Topmost folder called bundle_name below root, or None."""
        for current, folders, _files in os.walk(root):
            if bundle_name in folders:
                return os.path.join(current, bundle_name)
            # never look inside other app bundles
            folders[:] = sorted(f for f in folders if not f.endswith(".app"))
        return None


if __name__ == "__main__":
    PROCESSOR = FileWavePlaceholderImporter()
    PROCESSOR.execute_shell()
