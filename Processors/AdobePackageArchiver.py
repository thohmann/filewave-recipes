#!/usr/local/autopkg/python
"""See docstring for AdobePackageArchiver class"""

import errno
import os
import shutil
import sys

from autopkglib import Processor, ProcessorError

# This processor's own directory isn't on sys.path when autopkg imports it.
sys.path.append(os.path.dirname(__file__))
from AdobeAdminConsolePackageFinder import archive_dir, packages_dir

__version__ = "1.0.0"


def is_below(path: str, folder: str) -> bool:
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path != folder and os.path.commonpath([path, folder]) == folder


def free_name(folder: str, name: str) -> str:
    """`name`, or 'stem (2).ext', 'stem (3).ext', ... if it is taken in folder."""
    stem, extension = os.path.splitext(name)
    candidate, number = name, 1
    while os.path.lexists(os.path.join(folder, candidate)):
        number += 1
        candidate = f"{stem} ({number}){extension}"
    return candidate


def move(source: str, target: str) -> None:
    """Move a package (file or bundle folder). On another volume: copy under a
    temporary name, compare the size, then rename and delete the source - a
    half-copied package never appears under its final name."""
    try:
        os.rename(source, target)
        return
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
    partial = target + ".partial"
    if os.path.isdir(source):
        shutil.copytree(source, partial, symlinks=True)
        shutil.rmtree(source) if _tree_size(partial) == _tree_size(source) else _fail(partial, source)
    else:
        shutil.copy2(source, partial)
        os.remove(source) if os.path.getsize(partial) == os.path.getsize(source) else _fail(partial, source)
    os.rename(partial, target)


def _tree_size(folder: str) -> int:
    return sum(os.path.getsize(os.path.join(current, name))
               for current, _folders, files in os.walk(folder) for name in files)


def _fail(partial: str, source: str):
    shutil.rmtree(partial) if os.path.isdir(partial) else os.remove(partial)
    raise OSError(f"copy of {source} is incomplete")


def remove_empty_folders(folder: str, root: str) -> None:
    """Remove folder and its parents while they are empty (a lone .DS_Store
    doesn't count), up to but never including root."""
    while is_below(folder, root):
        if set(os.listdir(folder)) - {".DS_Store"}:
            return
        shutil.rmtree(folder)
        folder = os.path.dirname(folder)


class AdobePackageArchiver(Processor):
    """Moves the Adobe Admin Console packages a recipe is done with from the
    work folder (ADOBE_PACKAGES_DIR) into the archive folder.

    Must be the LAST step of an Adobe recipe: reaching it means every step
    before worked (filesets imported, or their version already on the
    server). After a failed run the package stays in the work folder and the
    next run tries again. The archive is flat and never emptied by this
    processor - tidy it by hand or by cron.
    """

    description = __doc__

    input_variables = {
        "adobe_packages_to_archive": {
            "required": False,
            "default": None,
            "description": (
                "List of package paths, the output of "
                "AdobeAdminConsolePackageFinder (read from the env; a list can't "
                "go through a %VAR% argument). Absent/empty = nothing to do."
            ),
        },
        "ADOBE_PACKAGES_DIR": {
            "required": False,
            "default": "",
            "description": "The work folder; only packages below it are moved.",
        },
        "ADOBE_ARCHIVE_DIR": {
            "required": False,
            "default": "",
            "description": "Archive folder, created if missing. Empty = <ADOBE_PACKAGES_DIR>/_Archiv.",
        },
    }
    output_variables = {
        "adobe_archived_packages": {"description": "Where the packages are now, comma-separated (may be empty)."},
        "adobe_archive_summary_result": {"description": "Summary of the archived packages."},
    }

    def main(self):
        self.env["adobe_archived_packages"] = ""
        self.env.pop("adobe_archive_summary_result", None)
        packages = self.env.get("adobe_packages_to_archive") or []
        if isinstance(packages, str):
            packages = [packages]
        root, archive = packages_dir(self.env), archive_dir(self.env)

        archived = []
        for source in packages:
            if not os.path.lexists(source):
                continue  # e.g. moved by hand since the finder ran
            if not is_below(source, root) or is_below(source, archive):
                self.output(f"WARNING: not archiving {source} - not in the work folder {root}.")
                continue
            try:
                os.makedirs(archive, exist_ok=True)
                target = os.path.join(archive, free_name(archive, os.path.basename(source)))
                move(source, target)
                remove_empty_folders(os.path.dirname(source), root)
            except OSError as e:
                # The filesets are imported; a package that stays where it is
                # only gets looked at again. Not worth failing the recipe.
                self.output(f"WARNING: could not archive {source}: {e}")
                continue
            archived.append(target)
            self.output(f"Archived {source} -> {target}")

        if archived:
            self.env["adobe_archived_packages"] = ", ".join(archived)
            self.env["adobe_archive_summary_result"] = {
                "summary_text": "The following Adobe packages were moved to the archive:",
                "report_fields": ["archived_package"],
                "data": {"archived_package": ", ".join(os.path.basename(path) for path in archived)},
            }


if __name__ == "__main__":
    PROCESSOR = AdobePackageArchiver()
    PROCESSOR.execute_shell()
