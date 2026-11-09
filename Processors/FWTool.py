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

"""See docstring for FWTool class"""
from __future__ import absolute_import, print_function

import os
import os.path
import sys
from subprocess import CalledProcessError

from autopkglib import DmgMounter, Processor, ProcessorError

# Ensure that the FWAdminClient can be imported from CommandLine module, since
# this Processor was imported via autopkg explicitly, the directory is not in
# the search path.
sys.path.append(os.path.dirname(__file__))
import Keychain
import VersionCompare
from CommandLine import FWAdminClient

FWTOOL_SUMMARY_RESULT = 'fwtool_summary_result'
DEFAULT_FW_SERVER_HOST = "localhost"
DEFAULT_FW_SERVER_PORT = "20016"
DEFAULT_FW_ADMIN_USERNAME = "fwadmin"
MINIMUM_FW_VERSION = "10.0.0"

COMMON_FILEWAVE_VARIABLES = {
        "FW_SERVER_HOST": {
            "default": DEFAULT_FW_SERVER_HOST,
            "description": ("The hostname/ip of the FileWave server.  Defaults to %s"
                           % DEFAULT_FW_SERVER_HOST),
            "required": False,
        },
        "FW_SERVER_PORT": {
            "default": DEFAULT_FW_SERVER_PORT,
            "description": ("The port number of the FileWave server.  Defaults to %s"
                            % DEFAULT_FW_SERVER_PORT),
            "required": False,
        },
        "FW_ADMIN_USER": {
            "default": DEFAULT_FW_ADMIN_USERNAME,
            "description": ("The username to use when connecting to the FileWave server.  Defaults to %s"
                            % DEFAULT_FW_ADMIN_USERNAME),
            "required": False,
        },
        # No FW_ADMIN_PASSWORD entry here on purpose: the password is never
        # read from the AutoPkg environment (recipe/override/global
        # preferences) - it's looked up fresh from the macOS Keychain in
        # validate_tools() below. See Keychain.py.
        "FW_RELAX_VERSION": {
            "default": False,
            "description": "Relax the version check and continue on regardless",
            "required": False
        }
}

class FWTool(DmgMounter):
    """Validates that the FileWave Admin Command Line tools are available on this machine."""

    description = __doc__

    input_variables = COMMON_FILEWAVE_VARIABLES

    output_variables = {
        FWTOOL_SUMMARY_RESULT: {
            "description": "The results of the installation/validation check."
        },
    }

    client = None

    def validate_tools(self, print_path=False, list_filesets=True):

        self.relaxed_version_check = self.env.get('FW_RELAX_VERSION', False)

        # Defensive scrub: FW_ADMIN_PASSWORD is not a declared input variable
        # (see COMMON_FILEWAVE_VARIABLES above) so AutoPkg shouldn't populate
        # it, but if it ends up in env anyway (e.g. a recipe/override still
        # setting it from before this change), remove it rather than ever
        # reading or re-exposing it.
        self.env.pop('FW_ADMIN_PASSWORD', None)

        admin_user = self.env['FW_ADMIN_USER']
        server_host = self.env['FW_SERVER_HOST']
        try:
            admin_password = Keychain.get_admin_password(server_host, admin_user)
        except Keychain.KeychainError as e:
            raise ProcessorError(str(e))

        self.client = FWAdminClient(
            admin_name=admin_user,
            admin_pwd=admin_password,
            server_host=server_host,
            server_port=self.env['FW_SERVER_PORT'],
            print_output=False
        )

        if print_path:
            print("Path to Admin Tool:", FWAdminClient.get_admin_tool_path())

        self.version = self.client.get_version()
        if VersionCompare.lt(self.version, MINIMUM_FW_VERSION):
            if self.relaxed_version_check:
                self.output("FileWave Version 10.0 must be installed - you have version %s" % (self.version))
            else:
                raise ProcessorError("FileWave Version 10.0 must be installed - you have version %s" % (self.version))

        self.can_list_filesets = "No"
        self.exit_status_message = "VALIDATION OK"
        self.exception = None

        if self.env['FW_ADMIN_USER'] == 'fwadmin':
            self.output("WARNING: You are using the FileWave super-user account (fwadmin)")

        # Only FWTool's own validation run lists filesets here; importers call
        # validate_tools(list_filesets=False) and list them once themselves.
        if not list_filesets:
            return
        try:
            the_filesets = self.client.get_filesets()
            count_filesets = sum(1 for i in the_filesets)
            self.can_list_filesets = "Yes" if count_filesets >= 0 else "No"
        except CalledProcessError as e:
            self.exception = e
            self.exit_status_message = FWAdminClient.ExitStatusDescription.get(
                e.returncode, (None, "Unknown exit code %s" % e.returncode))[1]
        except Exception as e:
            self.exception = e

    def main(self):
        self.validate_tools(print_path=True)

        if FWTOOL_SUMMARY_RESULT in self.env:
            del self.env[FWTOOL_SUMMARY_RESULT]

        self.env[FWTOOL_SUMMARY_RESULT] = {
            'summary_text': 'Here are the results of installation validation:',
            'report_fields': ['fw_admin_console_version',
                              'fw_admin_user',
                              'fw_server_host',
                              'fw_server_port',
                              'fw_can_list_filesets',
                              'fw_message'
                              ],
            'data': {
                'fw_admin_console_version': self.version,
                'fw_admin_user': self.env['FW_ADMIN_USER'],
                'fw_server_host': self.env['FW_SERVER_HOST'],
                'fw_server_port': self.env['FW_SERVER_PORT'],
                'fw_can_list_filesets': self.can_list_filesets,
                'fw_message': self.exit_status_message
            }}

        if self.exception is not None:
            print(self.exception)

if __name__ == '__main__':
    PROCESSOR = FWTool()
    PROCESSOR.execute_shell()
