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
        self.custom_properties = custom_properties
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
        Führt FileWave Admin CLI-Befehl aus mit Retry-Logik für SIGSEGV-Crashes.
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
        
        # Retry-Schleife
        for attempt in range(max_retries):
            try:
                if print_output:
                    if attempt > 0:
                        print("Retry attempt %d/%d" % (attempt + 1, max_retries))
                    print(process_options)
                    
                self.run_result_ret = subprocess.check_output(process_options, stderr=subprocess.STDOUT).decode().rstrip()
                self.run_result_ret = re.sub(r"QObject::connect.*QNetworkSession::State\)\n", '', self.run_result_ret)
                self.run_result_ret = re.sub(r"qt.network.ssl: Error receiving trust for a CA certificate\n", '', self.run_result_ret)
                
                # Erfolg - breche Retry-Schleife ab
                break
            
            except CalledProcessError as e:
                got_error = True
                
                # SIGSEGV (-11) oder andere Crash-Fehler
                if e.returncode == -11 and attempt < max_retries - 1:
                    if print_output:
                        print("Command crashed with SIGSEGV (returncode: %d)" % e.returncode)
                        print("Retrying in %d seconds..." % retry_delay)
                    time.sleep(retry_delay)
                    continue  # Versuche erneut
                
                # Letzter Versuch oder anderer Fehler
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

    def get_fileset_revisions(self, fileset_name_or_id):
        """
        Holt Revisionen für ein Fileset.
        
        Args:
            fileset_name_or_id: Name oder ID des Filesets
            
        Returns:
            Liste von Revision-Dictionaries oder leere Liste
        """
        try:
            filesets_json = self.run_admin("--listFilesets")
            filesets = json.loads(filesets_json)
            
            # Rekursiv durch Struktur suchen
            def find_fileset(items):
                if not isinstance(items, list):
                    return None
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    # Prüfe auf Name oder ID Match
                    if (item.get("name") == fileset_name_or_id or 
                        str(item.get("id")) == str(fileset_name_or_id)):
                        return item
                    # Rekursiv durch children
                    if "children" in item:
                        result = find_fileset(item["children"])
                        if result:
                            return result
                return None
            
            fileset = find_fileset(filesets)
            return fileset.get("revisions", []) if fileset else []
            
        except Exception as e:
            # Bei Fehler leere Liste zurückgeben
            return []

    def revision_exists(self, fileset_name, revision_name):
        """
        Prüft ob eine Revision mit dem Namen bereits existiert.
        
        Args:
            fileset_name: Name des Filesets
            revision_name: Name der Revision
            
        Returns:
            True wenn Revision existiert, False sonst
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
        search = matcher.search(import_folder_result)
        id = search.group('id')
        if self.create_fs_callback and hasattr(self.create_fs_callback, '__call__'):
            self.create_fs_callback(id)
        return id

    def export_fileset(self, destination, fs_name):
        options = [ '--exportFileset', destination, '--fileset', fs_name, '--name', fs_name]
        export_result = self.run_admin(options)
        matcher = re.compile(r'the fileset with ID (?P<id>.+) was exported to \'(?P<to>.+)\'')
        search = matcher.search(export_result)
        id = search.group('id')
        dest = search.group('to')
        if self.export_fs_callback and hasattr(self.export_fs_callback, '__call__'):
            self.export_fs_callback(id, dest)
        return id

    def import_folder(self, path, name=None, root=None, target=None, activation_script=None, requirements_script=None, preflight_script=None, postflight_script=None, preuninstallation_script=None, postuninstallation_script=None, verification_script=None, create_revision=False, revision_name=None, set_as_default=False):
        """
        Importiert einen Ordner als Fileset mit Revision-Support.
        """
        # DEBUG - Schreibe in temporäre Datei
        import datetime
        debug_file = "/tmp/filewave_debug.log"
        with open(debug_file, "a") as f:
            f.write("=" * 80 + "\n")
            f.write(f"{datetime.datetime.now()}\n")
            f.write(f"import_folder called:\n")
            f.write(f"  name: {name}\n")
            f.write(f"  create_revision: {create_revision}\n")
            f.write(f"  revision_name: {revision_name}\n")
            f.write(f"  set_as_default: {set_as_default}\n")
            
        # Prüfe ob Revision bereits existiert
        if create_revision and revision_name:
            with open(debug_file, "a") as f:
                f.write(f"  Checking if revision exists...\n")
            if self.revision_exists(name, revision_name):
                with open(debug_file, "a") as f:
                    f.write(f"  -> Revision EXISTS, returning None\n")
                return None
            with open(debug_file, "a") as f:
                f.write(f"  -> Revision does NOT exist\n")
                
        # Prüfe ob Fileset existiert
        fileset_exists = False
        if create_revision and name:
            fileset_revisions = self.get_fileset_revisions(name)
            fileset_exists = len(fileset_revisions) > 0
            with open(debug_file, "a") as f:
                f.write(f"  Fileset exists: {fileset_exists}\n")
                f.write(f"  Revisions found: {fileset_revisions}\n")            
            options = ['--importFolder', path]
        
        if create_revision and fileset_exists:
            print("  MODE: Adding revision to existing fileset")
            # Fileset existiert - füge neue Revision hinzu
            options.extend(['--fileset', name])
            options.extend(['--revision', revision_name])
            if set_as_default:
                options.append('--setRevisionAsDefault')
        else:
            print("  MODE: Creating new fileset (or normal import)")            
            # Neues Fileset oder normaler Import
            if name:
                options.extend(["--name", name])
            if root:
                options.extend(["--root", root])
            if target:
                options.extend(["--filesetgroup", str(target)])
            
            # Wenn Revision-Modus und Fileset neu, erstelle mit initialer Revision
            if create_revision and revision_name:
                options.extend(['--revision', revision_name])
                if set_as_default:
                    options.append('--setRevisionAsDefault')
        
        # Scripts nur bei neuem Fileset oder initialer Revision
        if not (create_revision and fileset_exists):
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
        search = matcher.search(import_folder_result)
        if search:
            id = search.group('id')
            if self.create_fs_callback and hasattr(self.create_fs_callback, '__call__'):
                self.create_fs_callback(id)
            return id
        return None

    def import_image(self, path, error_expected=False):
        options = ['--importImage', path]
        import_image_result = self.run_admin( options, error_expected=error_expected )
        matcher = re.compile( r'new imaging fileset with ID (?P<id>.+) was created')
        search = matcher.search(import_image_result)
        id = search.group('id')
        if self.create_fs_callback and hasattr(self.create_fs_callback, '__call__'):
            self.create_fs_callback(id)
        return id

    def import_package(self, path, name=None, root=None, target=None, 
                      create_revision=False, revision_name=None, set_as_default=False):
        """
        Importiert ein Package als Fileset mit Revision-Support.
        """
        # Prüfe ob Revision bereits existiert (nur wenn create_revision=True)
        if create_revision and revision_name:
            if self.revision_exists(name, revision_name):
                return None  # Skip
        
        # Prüfe ob Fileset existiert für Revision-Modus
        fileset_exists = False
        if create_revision and name:
            fileset_revisions = self.get_fileset_revisions(name)
            fileset_exists = len(fileset_revisions) > 0
        
        options = ['--importPackage', path]
        
        if create_revision and fileset_exists:
            # Fileset existiert - füge neue Revision hinzu
            options.extend(['--fileset', name])
            options.extend(['--revision', revision_name])
            if set_as_default:
                options.append('--setRevisionAsDefault')
        else:
            # Neues Fileset oder normaler Import
            if name:
                options.extend(["--name", name])
            if root:
                options.extend(["--root", root])
            if target:
                options.extend(["--filesetgroup", str(target)])
            
            # Wenn Revision-Modus und Fileset neu, erstelle mit initialer Revision
            if create_revision and revision_name:
                options.extend(['--revision', revision_name])
                if set_as_default:
                    options.append('--setRevisionAsDefault')

        import_package_result = self.run_admin(options)
        matcher = re.compile(r'neues Fileset mit der ID (?P<id>.+) wurde mit dem Namen')
        search = matcher.search(import_package_result)
        if search:
            id = search.group('id')
            if self.create_fs_callback and hasattr(self.create_fs_callback, '__call__'):
                self.create_fs_callback(id)
            return id
        return None

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
        search = matcher.search(create_empty_fileset_result)
        id = search.group('id')
        if self.create_fs_callback and hasattr(self.create_fs_callback, '__call__'):
            self.create_fs_callback(id)
        return id