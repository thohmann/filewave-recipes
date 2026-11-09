from __future__ import absolute_import, print_function

import json
import os
import os.path
import platform
import re
import subprocess
from subprocess import CalledProcessError


class Client(object):
    def __init__(self, id, name, type, parent_id, **kwargs):
        self.id = str(id)
        self.name = name
        self.type = type
        self.parent_id = str(parent_id)

    def __str__(self):
        return "%s (%s) '%s', parent=%s" % (self.id, self.name, self.type, self.parent_id)


class Association(object):
    def __init__(self, assoc_id, client_id, fileset_id, kiosk=False, sw_update=False):
        self.id = str(assoc_id)
        self.client_id = str(client_id)
        self.fileset_id = str(fileset_id)
        self.kiosk = kiosk
        self.sw_update = sw_update

    def __str__(self):
        return "%s - Client: %s, Fileset: %s %s" % (
            self.id,
            self.client_id,
            self.fileset_id,
            "(Kiosk)" if self.kiosk else ""
        )


class Fileset(object):
    def __init__(self, id, name, type, size, parent_id, custom_properties=None, **kwargs):
        self.id = str(id)
        self.name = name
        self.type = type
        self.size = size
        # Groups and some fileset types come without custom_properties
        self.custom_properties = custom_properties or {}
        self.parent_id = str(parent_id)
        self.is_critical = kwargs.get('isCritical')


    def __str__(self):
        return "%s - name: %s, type: %s, parent: %s, props: %s" % (
            self.id,
            self.name,
            self.type,
            self.parent_id,
            self.custom_properties
        )

class FWAdminClient(object):

    ExitStatusDescription = {
        0: ("kExitOK", "No Error"),
        100: ("kExitUnknownError", "Unknown Error"),
        101: ("kExitFilesetNotExists", "The given fileset does not exist"),
        102: ("kExitClientNotExists", "The given client does not exist"),
        103: ("kExitGroupNotExists", "The given group does not exist"),
        104: ("kExitTargetIsNotGroup", "The given target does not exist"),
        105: ("kExitDBError", "Database internal error"),
        106: ("kExitFilesetUploadError", "Error while uploading fileset"),
        107: ("kExitModelUpdateError", "Error while updating the model"),
        108: ("kExitLoginError", "Login Error or Version Mismatch"),
        109: ("kExitImportFilesetError", "Error while importing a fileset"),
        110: ("kExitUnknownImportType", "Package type not supported for import"),
        111: ("kExitParseError", "Command line parse failed"),
        112: ("kExitAssociationToImagingFilesetError", "Can't create association with an imaging fileset"),
        113: ("kExitGroupCreationError", "Can't create a new fileset group"),
        114: ("kExitFilesetMergeError", "Cannot merge files in the fileset"),
        115: ("kExitExportFilesetError", "Error while exporting a fileset"),
    }

    def __init__(self,
                 admin_name = 'fwadmin',
                 admin_pwd = 'filewave',
                 server_host = 'localhost',
                 server_port = "20016",
                 create_fs_callback=None,
                 remove_fs_callback=None,
                 export_fs_callback=None,
                 print_output=False):

        self.fwadmin_executable = self.get_admin_tool_path()
        self.connection_options = ['-u', admin_name,
                                   '-p', admin_pwd,
                                   '-H', server_host,
                                   '-P', server_port ]

        self.print_output = print_output
        self.create_fs_callback = create_fs_callback
        self.remove_fs_callback = remove_fs_callback
        self.export_fs_callback = export_fs_callback
        self.last_fileset_name = None  # name actually used by the last import

    @classmethod
    def get_admin_tool_path(cls):
        systemName = platform.system()
        appPath = ''
        if 'Darwin' == systemName:
            appPath = "%s/FileWave Admin.app/Contents/MacOS/FileWave Admin"
        elif 'Windows' == systemName:
            appPath = '%s/RelWithDebInfo/FileWaveAdmin.exe'
        elif 'Linux' == systemName:
            appPath = '%s/FileWaveAdmin'
        else:
            raise Exception( 'Unsupported platform' )

        return appPath % cls.get_executable_path()

    @classmethod
    def get_executable_path(cls):
        return os.environ.get("FILEWAVE_ADMIN_PATH", '/Applications/FileWave')

    def run_admin(self, options, include_connection_options=True, error_expected=False, print_output=None, max_retries=3, retry_delay=5):
        """
        Runs a FileWave Admin CLI command, with retry logic for SIGSEGV crashes.
        """
        import time

        print_output = print_output or self.print_output
        process_options = [self.fwadmin_executable]
        if include_connection_options:
            process_options.extend(self.connection_options)

        # Map string type for both Python 2 and Python 3.
        try:
            _ = basestring
        except NameError:
            basestring = str  # pylint: disable=W0622

        if isinstance(options, basestring):
            process_options.append(options)
        else:
            process_options.extend(options)

        got_error = False
        self.run_result_ret = None

        # Retry loop
        for attempt in range(max_retries):
            try:
                if print_output:
                    if attempt > 0:
                        print("Retry attempt %d/%d" % (attempt + 1, max_retries))
                    print(self._redact_command(process_options))

                self.run_result_ret = subprocess.check_output(process_options, stderr=subprocess.STDOUT).decode().rstrip()
                self.run_result_ret = re.sub(r"QObject::connect.*QNetworkSession::State\)\n", '', self.run_result_ret)
                self.run_result_ret = re.sub(r"qt.network.ssl: Error receiving trust for a CA certificate\n", '', self.run_result_ret)

                # Success - stop the retry loop
                break

            except CalledProcessError as e:
                got_error = True

                # str(CalledProcessError) embeds e.cmd verbatim (see the
                # stdlib's __str__), and this exception tends to travel far -
                # re-raised here, then often wrapped into a ProcessorError
                # several call frames up (e.g. FileWaveImporter's "... Reason:
                # %s" % e) or printed directly (FWTool.main()). Redact the
                # password at the source so every one of those call sites is
                # safe without having to remember to sanitize individually.
                e.cmd = self._redact_command(e.cmd)

                # SIGSEGV (-11) or another crash-type error
                if e.returncode == -11 and attempt < max_retries - 1:
                    if print_output:
                        print("Command crashed with SIGSEGV (returncode: %d)" % e.returncode)
                        print("Retrying in %d seconds..." % retry_delay)
                    time.sleep(retry_delay)
                    continue  # try again

                # Last attempt, or a different kind of error
                if print_output:
                    print("Command failed, error code: ", e.returncode)
                    print("Output: ", e.output)

                if not error_expected:
                    raise e
                else:
                    self.run_result_ret = e.output, e.returncode
                    break

        if error_expected and not got_error:
            raise Exception("Expected an error, but command was successful")

        return self.run_result_ret

    @staticmethod
    def _redact_command(cmd):
        """Return a copy of an admin-tool argv list with the -p <password>
        value masked - safe to print or fold into an exception/error message."""
        redacted = list(cmd)
        for i, arg in enumerate(redacted):
            if arg == '-p' and i + 1 < len(redacted):
                redacted[i + 1] = '***REDACTED***'
        return redacted

    @staticmethod
    def _require_match(matcher, text, what):
        """Search `text` with `matcher` and return the match, or raise a
        clear RuntimeError instead of leaving callers to hit
        AttributeError: 'NoneType' object has no attribute 'group' if the
        FileWave Admin CLI's output doesn't match the expected pattern
        (unexpected message, locale, or version)."""
        search = matcher.search(text)
        if search is None:
            raise RuntimeError(
                "Could not find %s in FileWave Admin output: %r" % (what, text)
            )
        return search

    # FileWave Admin's output after --importFolder/--importPackage
    IMPORT_RESULT_PATTERNS = (
        re.compile(r'RESULT: a new fileset with ID (?P<id>\d+)', re.IGNORECASE),
        re.compile(r'RESULT: a new revision with ID (?P<id>\d+)', re.IGNORECASE),
    )

    def _parse_import_result(self, result):
        """The new fileset/revision ID from an import's output. Raises instead
        of returning None, so None from import_folder/import_package always
        means "revision already exists" and never "import ran but its output
        wasn't understood"."""
        for matcher in self.IMPORT_RESULT_PATTERNS:
            search = matcher.search(result)
            if search:
                id = search.group('id')
                if self.create_fs_callback and hasattr(self.create_fs_callback, '__call__'):
                    self.create_fs_callback(id)
                return id
        raise RuntimeError("Could not find the new fileset/revision ID in FileWave Admin output: %r" % (result,))

    def _prepare_revision(self, name, target, revision_name, set_as_default):
        """Revision mode: (skip, fileset_exists, set_as_default). Creates the
        empty fileset first if it doesn't exist yet."""
        revisions = self.get_fileset_revisions(name)
        if revision_name and any(rev.get("name") == revision_name for rev in revisions):
            return True, True, set_as_default
        if revisions:
            return False, True, set_as_default
        print("Creating empty fileset '%s' for revision management..." % name)
        self.create_empty_fileset(name, target)
        print("  -> Created empty fileset with 'Initial Revision'")
        print("  -> First revision '%s' will automatically be set as default" % revision_name)
        return False, True, True  # The first real revision becomes the default

    @staticmethod
    def _find_fileset_in_tree(items, name_or_id):
        """Recursively search a --listFilesets tree for an exact name or ID match."""
        if not isinstance(items, list):
            return None
        for item in items:
            if not isinstance(item, dict):
                continue
            if (item.get("name") == name_or_id or
                str(item.get("id")) == str(name_or_id)):
                return item
            if "children" in item:
                result = FWAdminClient._find_fileset_in_tree(item["children"], name_or_id)
                if result:
                    return result
        return None

    def get_fileset(self, name_or_id):
        """
        Fetches the raw fileset dict (id, name, revisions, ...) for an exact
        name or ID match.

        Args:
            name_or_id: Name or ID of the fileset

        Returns:
            The fileset dict, or None if not found. Errors listing the
            filesets propagate: treating them as "not found" would make
            revision mode create a duplicate fileset or re-import a revision.
        """
        filesets = json.loads(self.run_admin("--listFilesets"))
        return self._find_fileset_in_tree(filesets, name_or_id)

    def get_fileset_revisions(self, fileset_name_or_id):
        """
        Fetches the revisions for a fileset.

        Args:
            fileset_name_or_id: Name or ID of the fileset

        Returns:
            List of revision dicts, or an empty list
        """
        fileset = self.get_fileset(fileset_name_or_id)
        return fileset.get("revisions", []) if fileset else []

    def revision_exists(self, fileset_name, revision_name):
        """
        Checks whether a revision with the given name already exists.

        Args:
            fileset_name: Name of the fileset
            revision_name: Name of the revision

        Returns:
            True if the revision exists, False otherwise
        """
        revisions = self.get_fileset_revisions(fileset_name)
        return any(rev.get("name") == revision_name for rev in revisions)

    def get_version(self):
        version = self.run_admin("-v")
        return version

    def get_clients(self):
        clients = json.loads(self.run_admin("--listClients"))

        def recursive_generator(client):
            children = client.pop('children', [])
            yield Client(**client)
            for child in children:
                for child_client in recursive_generator(child):
                    yield child_client

        for c in clients:
            for gg in recursive_generator(c):
                yield gg

    def get_filesets(self):
        filesets = json.loads(self.run_admin("--listFilesets"))

        def recursive_generator(fileset):
            children = fileset.pop('children', [])
            yield Fileset(**fileset)
            for child in children:
                for child_fileset in recursive_generator(child):
                    yield child_fileset

        for fs in filesets:
            for gg in recursive_generator(fs):
                yield gg

    def get_associations(self):
        associations = json.loads(self.run_admin(['--listAssociations']))

        for assoc in associations:
            yield Association(**assoc)

    def create_association(self, client_id, fileset_id, kiosk=False, sw_update=False, error_expected=False ):
        args = ['--createAssociation', '--clientgroup', client_id, '--fileset', fileset_id]
        if kiosk:
            args.append('--kiosk')

        if sw_update:
            args.append('--software_update')

        self.run_admin(args, error_expected=error_expected)

    def remove_association(self, assoc_id):
        self.run_admin(['--deleteAssociation', str(assoc_id)])

    def get_help(self):
        return self.run_admin("-h")

    def import_fileset(self, path, name=None, root=None, target=None, activation_script=None, requirements_script=None, preflight_script=None, postflight_script=None, preuninstallation_script=None, postuninstallation_script=None, verification_script=None):
        options = ['--importFileset', path]
        if name:
            options.extend(["--name", name])
        if root:
            options.extend(["--root", root])
        if target:
            options.extend(["--filesetgroup", str(target)])
        if activation_script:
            options.extend(["--addActivationScript", str(activation_script)])
        if requirements_script:
            options.extend(["--addRequirementsScript", str(requirements_script)])
        if preflight_script:
            options.extend(["--addPreflightScript", str(preflight_script)])
        if postflight_script:
            options.extend(["--addPostflightScript", str(postflight_script)])
        if preuninstallation_script:
            options.extend(["--addPreuninstallationScript", str(preuninstallation_script)])
        if postuninstallation_script:
            options.extend(["--addPostuninstallationScript", str(postuninstallation_script)])
        if verification_script:
            options.extend(["--addVerificationScript", str(verification_script)])

        import_folder_result = self.run_admin(options)
        matcher = re.compile(r'new fileset with ID (?P<id>.+) was created')
        search = self._require_match(matcher, import_folder_result, "the new fileset ID")
        id = search.group('id')
        if self.create_fs_callback and hasattr(self.create_fs_callback, '__call__'):
            self.create_fs_callback(id)
        return id

    def export_fileset(self, destination, fs_name):
        options = [ '--exportFileset', destination, '--fileset', fs_name, '--name', fs_name]
        export_result = self.run_admin(options)
        matcher = re.compile(r'the fileset with ID (?P<id>.+) was exported to \'(?P<to>.+)\'')
        search = self._require_match(matcher, export_result, "the exported fileset ID")
        id = search.group('id')
        dest = search.group('to')
        if self.export_fs_callback and hasattr(self.export_fs_callback, '__call__'):
            self.export_fs_callback(id, dest)
        return id

    def import_folder(self, path, name=None, root=None, target=None, activation_script=None, requirements_script=None, preflight_script=None, postflight_script=None, preuninstallation_script=None, postuninstallation_script=None, verification_script=None, create_revision=False, revision_name=None, set_as_default=False):
        """
        Imports a folder as a fileset, with revision support. Returns the new
        fileset/revision ID, or None if the revision already exists.
        """
        self.last_fileset_name = name
        fileset_exists = False
        if create_revision and name:
            skip, fileset_exists, set_as_default = self._prepare_revision(name, target, revision_name, set_as_default)
            if skip:
                return None

        options = ['--importFolder', path]

        # Fileset reference: either an existing fileset, or a new name
        if create_revision and fileset_exists:
            options.extend(['--fileset', name])
        elif name:
            options.extend(['--name', name])

        # Root path (whenever given)
        if root:
            options.extend(['--root', root])

        # Fileset group (only for a brand-new fileset)
        if target and not (create_revision and fileset_exists):
            options.extend(['--filesetgroup', str(target)])

        # Revision parameters (only in revision mode)
        if create_revision and revision_name:
            options.extend(['--revision', revision_name])
            if set_as_default:
                options.append('--setRevisionAsDefault')

        # Scripts (whenever given)
        if activation_script:
            options.extend(['--addActivationScript', str(activation_script)])
        if requirements_script:
            options.extend(['--addRequirementsScript', str(requirements_script)])
        if preflight_script:
            options.extend(['--addPreflightScript', str(preflight_script)])
        if postflight_script:
            options.extend(['--addPostflightScript', str(postflight_script)])
        if preuninstallation_script:
            options.extend(['--addPreuninstallationScript', str(preuninstallation_script)])
        if postuninstallation_script:
            options.extend(['--addPostuninstallationScript', str(postuninstallation_script)])
        if verification_script:
            options.extend(['--addVerificationScript', str(verification_script)])

        return self._parse_import_result(self.run_admin(options))

    def import_image(self, path, error_expected=False):
        options = ['--importImage', path]
        import_image_result = self.run_admin( options, error_expected=error_expected )
        matcher = re.compile( r'new imaging fileset with ID (?P<id>.+) was created')
        search = self._require_match(matcher, import_image_result, "the new imaging fileset ID")
        id = search.group('id')
        if self.create_fs_callback and hasattr(self.create_fs_callback, '__call__'):
            self.create_fs_callback(id)
        return id

    def import_package(self, path, name=None, root=None, target=None,
                      create_revision=False, revision_name=None, set_as_default=False,
                      existing_names=None):
        """
        Imports a package as a fileset, with revision support. Returns the new
        fileset/revision ID, or None if the revision already exists. Outside
        revision mode a taken name gets a number appended; the name actually
        used is in self.last_fileset_name. `existing_names` saves a
        --listFilesets call when the caller already listed the filesets.
        """
        fileset_exists = False
        if create_revision and name:
            skip, fileset_exists, set_as_default = self._prepare_revision(name, target, revision_name, set_as_default)
            if skip:
                self.last_fileset_name = name
                return None

        # Check for a name collision (only outside revision mode)
        if not create_revision and name:
            original_name = name
            counter = 1

            if existing_names is None:
                existing_names = [fs.name for fs in self.get_filesets()]
            existing_names = set(existing_names)

            # Append a number if the name already exists
            while name in existing_names:
                name = "%s %d" % (original_name, counter)
                counter += 1

            if name != original_name:
                print("Fileset '%s' already exists. Using name: '%s'" % (original_name, name))

        options = ['--importPackage', path]

        # Fileset reference: either an existing fileset, or a new name
        if create_revision and fileset_exists:
            options.extend(['--fileset', name])
        elif name:
            options.extend(['--name', name])

        # Root path (whenever given)
        if root:
            options.extend(['--root', root])

        # Fileset group (only for a brand-new fileset)
        if target and not (create_revision and fileset_exists):
            options.extend(['--filesetgroup', str(target)])

        # Revision parameters (only in revision mode)
        if create_revision and revision_name:
            options.extend(['--revision', revision_name])
            if set_as_default:
                options.append('--setRevisionAsDefault')

        self.last_fileset_name = name
        return self._parse_import_result(self.run_admin(options))

    def set_property(self, fileset_id, prop_name, prop_value):
        options = ['--fileset', fileset_id, '--setProperty', '--key', prop_name, '--value', prop_value]
        self.run_admin(options)

    def remove_fileset(self, fileset_id):
        self.run_admin(['--deleteFileset', str(fileset_id)])
        if self.remove_fs_callback and hasattr(self.remove_fs_callback, '__call__'):
            self.remove_fs_callback(fileset_id)
        return fileset_id

    def set_fileset_critical(self, fileset_id, is_critical):
        options = ['--fileset', fileset_id, '--setCriticalFlag',  '--value', "1" if is_critical else "0"]
        self.run_admin(options)

    def model_update(self):
        self.run_admin(['--updateModel'])

    def create_empty_fileset(self, name, target=None):
        options = ['--createFileset', str(name)]
        if target:
            options.extend(["--filesetgroup", str(target)])
        create_empty_fileset_result = self.run_admin(options)
        print(create_empty_fileset_result)
        matcher = re.compile(r'new fileset (?P<id>.+) created with name (?P<name>.+)')
        search = self._require_match(matcher, create_empty_fileset_result, "the new fileset ID")
        id = search.group('id')
        if self.create_fs_callback and hasattr(self.create_fs_callback, '__call__'):
            self.create_fs_callback(id)
        return id
