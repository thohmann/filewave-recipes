#!/usr/local/autopkg/python
#
# Copyright 2015 FileWave (Europe) GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""See docstring for FileWaveImporter class"""
from __future__ import absolute_import, print_function

import glob
import os
import os.path
import sys

from autopkglib import Processor, ProcessorError

# Ensure that the FWAdminClient can be imported from CommandLine module, since
# this Processor was imported via autopkg explicitly, the directory is not in
# the search path.
sys.path.append(os.path.dirname(__file__))
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
  sys.path.insert(0, _current_dir)
import VersionCompare
from CommandLine import FWAdminClient
from FWTool import COMMON_FILEWAVE_VARIABLES, FWTool


__version__ = "0.0.2"
FW_FILESET_DESTINATION = "/Applications"
FILEWAVE_SUMMARY_RESULT = 'filewave_summary_result'

class FileWaveImporter(FWTool):
    """Imports a path as a fileset into FileWave.  The path points to either a Mac Package or a folder."""

    description = __doc__

    importer_variables = {
        "fw_import_source": {
            "required": True,
            "description": "The file/folder that will be imported into the FileWave fileset, can be dmg, pkg or folder.",
        },
        "fw_fileset_name": {
            "required": True,
            "description": "The name of the fileset to be created (will be made unique if it isnt already).",
        },
        "fw_fileset_group": {
            "required": False,
            "description": "The name of the fileset group to import into - can be left blank, will be created if it does not exist.",
        },
        "fw_destination_root": {
            "default": FW_FILESET_DESTINATION,
            "required": False,
            "description": ("The location at which to place all the imported data.  Defaults to %s"
                             % FW_FILESET_DESTINATION )
        },
        "fw_export_fileset": {
            "required": False,
            "description": "Should the fileset be exported to specified path",
        },
        "fw_app_bundle_id": {
            "default": None,
            "required": False,
            "description": "If specified the importer will use this value to \
            locate other filesets representing the same application in order to \
            perform a version check - i.e. only newer app versions will be \
            imported.  This should be the CFBundleIdentifier from the apps Info.plist"
        },
        "fw_app_version": {
            "default": None,
            "required": False,
            "description": "This should be the CFBundleShortVersionString value \
                           from the apps Info.plist."
        },
        "fw_fileset_activation_script": {
            "default": None,
            "required": False,
            "description": "The location of an activation script. Needs to be in the imported folder and executable.",
        },
        "fw_fileset_requirements_script": {
            "default": None,
            "required": False,
            "description": "The location of a requirements script. Needs to be in the imported folder and executable.",
        },
        "fw_fileset_preflight_script": {
            "default": None,
            "required": False,
            "description": "The location of a preflight script. Needs to be in the imported folder and executable.",
        },
        "fw_fileset_postflight_script": {
            "default": None,
            "required": False,
            "description": "The location of a postflight script. Needs to be in the imported folder and executable.",
        },
        "fw_fileset_preuninstallation_script": {
            "default": None,
            "required": False,
            "description": "The location of a preuninstallation script. Needs to be in the imported folder and executable.",
        },
        "fw_fileset_postuninstallation_script": {
            "default": None,
            "required": False,
            "description": "The location of a postuninstallation script. Needs to be in the imported folder and executable.",
        },
        "fw_fileset_verification_script": {
            "default": None,
            "required": False,
            "description": "The location of a verification script. Needs to be in the imported folder and executable.",
        },
        # Revision support
        "fw_create_revision": {
            "default": False,
            "required": False,
            "description": "If True, creates a new revision instead of updating the fileset. Requires fw_revision_name or fw_app_version.",
        },
        "fw_revision_name": {
            "default": None,
            "required": False,
            "description": "Name of the revision to create. If not specified, fw_app_version will be used.",
        },
        "fw_set_revision_as_default": {
            "default": False,
            "required": False,
            "description": "If True, sets the newly created revision as the default revision. Only used when fw_create_revision is True.",
        },
    }

    input_variables = dict(COMMON_FILEWAVE_VARIABLES, **importer_variables)

    output_variables = {
        "fw_fileset_id": {
            "description": "The resulting FileWave fileset ID for the newly created fileset."
        },
        FILEWAVE_SUMMARY_RESULT: {
            "description": "Summary of what was imported into FileWave."
        }}


    def find_first_in_path(self, path, ext="app"):
        """Find app bundle at path."""
        #pylint: disable=no-self-use
        apps = glob.glob(os.path.join(path, "*.%s" % (ext)))
        if len(apps) == 0:
            raise ProcessorError("No %s found in dmg" % (ext))
        return apps[0]


    def main(self):
        self.validate_tools(print_path=False, list_filesets=False)

        # Always reset first: if this run skips (version/revision already
        # satisfied), fw_fileset_id must not leak a stale value from an
        # earlier FileWaveImporter step in the same recipe run.
        self.env['fw_fileset_id'] = None
        # Same for the summary: AutoPkg reports every step's output variables
        # that are set, so a skipped step would repeat the previous import.
        self.env.pop(FILEWAVE_SUMMARY_RESULT, None)

        fw_app_bundle_id = self.env.get('fw_app_bundle_id', None)
        fw_app_version = self.env.get('fw_app_version', None)
        
        # Get revision parameters
        create_revision = self.env.get('fw_create_revision', False)
        revision_name = self.env.get('fw_revision_name', None)
        set_as_default = self.env.get('fw_set_revision_as_default', False)

        # If no revision_name was given, fall back to fw_app_version
        if create_revision and not revision_name:
            revision_name = fw_app_version
            if not revision_name:
                raise ProcessorError(
                    "fw_create_revision is True but neither fw_revision_name "
                    "nor fw_app_version is specified."
                )

        # Log revision mode
        if create_revision:
            self.output("Revision mode active: creating revision '%s'" % revision_name)
            if set_as_default:
                self.output("  -> Will be set as the default revision")

        check_version = fw_app_bundle_id is not None and fw_app_version is not None

        # perform version check by scanning existing filesets?
        # Only when NOT in revision mode
        existing_names = None
        if check_version and not create_revision:
            filesets = list(self.client.get_filesets())
            # reused by import_package's name-collision check (one listing per step)
            existing_names = [fileset.name for fileset in filesets]
            for fileset in filesets:
                app_bundle_id = fileset.custom_properties.get("autopkg_app_bundle_id", None)
                app_version = fileset.custom_properties.get("autopkg_app_version", None)

                if app_bundle_id is not None and app_version is not None and \
                                app_bundle_id == fw_app_bundle_id and \
                                VersionCompare.gte(app_version, fw_app_version):
                    self.output("This app version is already satisfied by the fileset %s called '%s' (%s, %s)" %
                          (fileset.id, fileset.name, fw_app_bundle_id, fw_app_version))
                    # Deliberately NOT setting fw_fileset_id here: this fileset was
                    # merely found via a server-wide bundle-id/version match, it
                    # wasn't created/managed by this recipe run. Downstream steps
                    # (e.g. script importers) should skip rather than modify an
                    # unrelated (possibly production) fileset.
                    return

        import_source = self.env['fw_import_source']
        if not os.path.exists(import_source):
            raise ProcessorError("Import source %s does not exist" %
                                 (import_source))

        fileset_name = self.env['fw_fileset_name']
        fileset_group = self.env.get('fw_fileset_group', None)
        destination_root = self.env.get('fw_destination_root',
                                        FW_FILESET_DESTINATION)
        find_type_in_dmg = self.env.get('fw_dmg_content_type', None)
        fileset_activation_script = self.env.get('fw_fileset_activation_script', None)
        fileset_requirements_script = self.env.get('fw_fileset_requirements_script', None)
        fileset_preflight_script = self.env.get('fw_fileset_preflight_script', None)
        fileset_postflight_script = self.env.get('fw_fileset_postflight_script', None)
        fileset_preuninstallation_script = self.env.get('fw_fileset_preuninstallation_script', None)
        fileset_postuninstallation_script = self.env.get('fw_fileset_postuninstallation_script', None)
        fileset_verification_script = self.env.get('fw_fileset_verification_script', None)

        fileset_id = None
        dmg_path = None  # DmgMounter.unmount() takes the dmg's path, not the mountpoint
        filename, file_extension = os.path.splitext(import_source)

        try:
            if file_extension in [ ".dmg" ] and find_type_in_dmg is not None:
                dmg_mountpoint = self.mount(import_source)
                dmg_path = import_source
                import_source = self.find_first_in_path(dmg_mountpoint, find_type_in_dmg)
                # with the dot, like the checks below ("pkg" -> ".pkg")
                file_extension = os.path.splitext(import_source)[1]

            try:
                if file_extension in [ ".pkg", ".mpkg", ".msi" ]:
                    # Extended parameters for revision support
                    fileset_id = self.client.import_package(
                        path=import_source,
                        name=fileset_name,
                        target=fileset_group,
                        create_revision=create_revision,
                        revision_name=revision_name if create_revision else None,
                        set_as_default=set_as_default if create_revision else False,
                        existing_names=existing_names
                    )

                    # Check for skip (when the revision already exists)
                    if fileset_id is None and create_revision:
                        self.output("Revision '%s' already exists in fileset '%s'" % (revision_name, fileset_name))
                        self.output("Skipping import (no update necessary)")
                        return

                elif os.path.isdir(import_source):
                    # Extended parameters for revision support
                    fileset_id = self.client.import_folder(
                        path=import_source,
                        name=fileset_name,
                        root=destination_root,
                        target=fileset_group,
                        activation_script=fileset_activation_script,
                        requirements_script=fileset_requirements_script,
                        preflight_script=fileset_preflight_script,
                        postflight_script=fileset_postflight_script,
                        preuninstallation_script=fileset_preuninstallation_script,
                        postuninstallation_script=fileset_postuninstallation_script,
                        verification_script=fileset_verification_script,
                        create_revision=create_revision,
                        revision_name=revision_name if create_revision else None,
                        set_as_default=set_as_default if create_revision else False
                    )
                    
                    # Check for skip (when the revision already exists)
                    if fileset_id is None and create_revision:
                        self.output("Revision '%s' already exists in fileset '%s'" % (revision_name, fileset_name))
                        self.output("Skipping import (no update necessary)")
                        return

                if fileset_id is None:
                    raise Exception("Import source is neither a .pkg/.mpkg/.msi nor a folder")
                # import_package appends a number when the name is taken
                fileset_name = self.client.last_fileset_name or fileset_name

                self.env[FILEWAVE_SUMMARY_RESULT] = {
                    'summary_text': 'The following fileset was imported:',
                    'report_fields': ['fw_fileset_id', 'fw_fileset_group', 'fw_fileset_name'],
                    'data': {
                        'fw_fileset_id': fileset_id,
                        'fw_fileset_group': fileset_group if fileset_group is not None else "Root",
                        'fw_fileset_name': fileset_name
                    }}

                self.env['fw_fileset_id'] = fileset_id

                # Only set properties when NOT in revision mode
                if check_version and not create_revision:
                    # re-write the props back into the fileset
                    self.client.set_property(fileset_id, "autopkg_app_bundle_id", fw_app_bundle_id)
                    self.client.set_property(fileset_id, "autopkg_app_version", fw_app_version)

            except Exception as e:
                raise ProcessorError("Error importing the folder '%s' into FileWave as a fileset called '%s'.  Reason: %s" %
                                     (import_source, fileset_name, e))

        finally:
            if dmg_path is not None:
                self.unmount(dmg_path)

            # only after a successful import - otherwise an export error would
            # replace the real import error
            export_fileset = self.env.get('fw_export_fileset', None)
            if export_fileset and fileset_id is not None:
                self.client.export_fileset(export_fileset, fileset_name)

if __name__ == '__main__':
    PROCESSOR = FileWaveImporter()
    PROCESSOR.execute_shell()