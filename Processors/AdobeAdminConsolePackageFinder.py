#!/usr/local/autopkg/python
"""See docstring for AdobeAdminConsolePackageFinder class"""

import gzip
import json
import os
import re
import struct
import zlib
import xml.etree.ElementTree as ET

from autopkglib import Processor, ProcessorError

__version__ = "1.2.0"

DEFAULT_PACKAGES_DIR = "/Users/Shared/AdobePackages"
# ADOBE_PACKAGES_DIR is a work folder: a package in it is "not done yet".
# AdobePackageArchiver, the last step of every Adobe recipe, moves a finished
# package into the archive folder, which is never searched.
ARCHIVE_FOLDER_NAME = "_Archiv"

# Layout of an Adobe Admin Console package (verified on a flat "Managed
# Package", InDesign 2026 21.6, built 2026-09):
#   <name>.pkg (xar)
#     Distribution
#     Install.pkg/PackageInfo     - empty payload, only a preinstall script
#     Install.pkg/Scripts         - an UNCOMPRESSED odc cpio archive, stored
#                                   uncompressed in the xar heap, holding
#                                   everything (several GB):
#       optionXML.xml             - package description; one <HDMedia> per
#                                   contained component, the app itself has
#                                   <MediaType>Product</MediaType>
#       HD/<TargetFolderName>/Application.json
#                                 - per component: AppLaunch, InstallDir,
#                                   SystemRequirement, ...
#       HD/<TargetFolderName>/appIcon2x.png, appIcon.png
#                                 - the component's icon, 168 and 84 pixels
# Because nothing is compressed, both files can be read by seeking - no need
# to unpack gigabytes. A gzip-compressed Scripts archive (what pkgbuild
# normally writes) is read as a stream instead.
#
# The older, non-flat layout (<name>_Install.pkg is a folder) keeps the same
# files under Contents/Resources/. That path is implemented from Adobe's
# documented layout and NOT verified against a real package.
XAR_MAGIC = b"xar!"
CPIO_ODC_MAGIC = b"070707"
CPIO_TRAILER = "TRAILER!!!"
OPTION_XML = "optionXML.xml"
APPLICATION_JSON = re.compile(r"^HD/([^/]+)/Application\.json$")
# best first
ICON_NAMES = ("appIcon2x.png", "appIcon.png")
ICON_PNG = re.compile(r"^HD/([^/]+/(?:%s))$" % "|".join(re.escape(name) for name in ICON_NAMES))
BUNDLE_RESOURCES = os.path.join("Contents", "Resources")

# optionXML.xml also carries the Adobe ID and organisation of whoever built
# the package. Deliberately not read into the AutoPkg env (it ends up in
# receipts and logs).


class PackageFormatError(Exception):
    """The file is not an Adobe Admin Console package we can read."""


def version_key(version: str) -> tuple:
    """Sort key for Adobe product versions such as '21.6.0.057'."""
    return tuple(int(part) for part in re.findall(r"\d+", version or ""))


def _find_scripts_offset(handle) -> int:
    """Absolute file offset of Install.pkg/Scripts inside a flat package."""
    header = handle.read(28)
    if len(header) < 28 or header[:4] != XAR_MAGIC:
        raise PackageFormatError("not a flat package (no xar header)")
    header_size, _version, toc_compressed, _toc_size, _cksum = struct.unpack(">HHQQI", header[4:])
    handle.seek(header_size)
    try:
        toc = ET.fromstring(zlib.decompress(handle.read(toc_compressed)))
    except (zlib.error, ET.ParseError) as e:
        raise PackageFormatError(f"unreadable xar table of contents ({e})")
    for entry in toc.iter("file"):
        if entry.findtext("name") != "Scripts":
            continue
        data = entry.find("data")
        if data is None:
            continue
        encoding = data.find("encoding")
        style = encoding.get("style") if encoding is not None else ""
        if style != "application/octet-stream":
            raise PackageFormatError(f"Scripts archive is stored with xar encoding '{style}', expected none")
        return header_size + toc_compressed + int(data.findtext("offset"))
    raise PackageFormatError("no Scripts archive in the package")


def _skip(stream, count: int) -> None:
    """Move forward in a cpio stream; seek when the stream can (plain file),
    read and drop otherwise (gzip)."""
    if isinstance(stream, gzip.GzipFile):
        while count > 0:
            chunk = stream.read(min(count, 1 << 20))
            if not chunk:
                raise PackageFormatError("Scripts archive ends unexpectedly")
            count -= len(chunk)
    else:
        stream.seek(count, os.SEEK_CUR)


def _read_flat_package(path: str) -> dict:
    """{'optionXML.xml': bytes, '<TargetFolderName>': Application.json bytes,
    '<TargetFolderName>/appIcon2x.png': bytes, ...}"""
    found = {}
    with open(path, "rb") as handle:
        start = _find_scripts_offset(handle)
        handle.seek(start)
        compressed = handle.read(2) == b"\x1f\x8b"
        handle.seek(start)
        stream = gzip.GzipFile(fileobj=handle) if compressed else handle
        while True:
            header = stream.read(76)
            if len(header) < 76 or header[:6] != CPIO_ODC_MAGIC:
                raise PackageFormatError("Scripts archive is not an odc cpio archive")
            name_size = int(header[59:65], 8)
            file_size = int(header[65:76], 8)
            name = stream.read(name_size)[:-1].decode("utf-8", "replace")
            if name == CPIO_TRAILER:
                break
            if name.startswith("./"):
                name = name[2:]
            match = APPLICATION_JSON.match(name) or ICON_PNG.match(name)
            if name == OPTION_XML:
                found[OPTION_XML] = stream.read(file_size)
            elif match:
                found[match.group(1)] = stream.read(file_size)
            else:
                _skip(stream, file_size)
    return found


def _read_bundle_package(path: str) -> dict:
    """Same result as _read_flat_package() for the non-flat layout."""
    resources = os.path.join(path, BUNDLE_RESOURCES)
    found = {}
    option_xml = os.path.join(resources, OPTION_XML)
    if os.path.isfile(option_xml):
        with open(option_xml, "rb") as handle:
            found[OPTION_XML] = handle.read()
    hd_dir = os.path.join(resources, "HD")
    if os.path.isdir(hd_dir):
        for folder in os.listdir(hd_dir):
            application_json = os.path.join(hd_dir, folder, "Application.json")
            if os.path.isfile(application_json):
                with open(application_json, "rb") as handle:
                    found[folder] = handle.read()
            for icon_name in ICON_NAMES:
                icon = os.path.join(hd_dir, folder, icon_name)
                if os.path.isfile(icon):
                    with open(icon, "rb") as handle:
                        found[f"{folder}/{icon_name}"] = handle.read()
    return found


def read_products(path: str) -> list:
    """The apps (not their helper components) an Admin Console package
    installs, as dicts: sap_code, version, base_version, platform (of the package),
    app_name, app_path, min_os, package_name, pkg_path, icon (PNG bytes,
    may be empty). An app can appear
    twice (one media per CPU architecture). Raises PackageFormatError."""
    files = _read_bundle_package(path) if os.path.isdir(path) else _read_flat_package(path)
    if OPTION_XML not in files:
        raise PackageFormatError(f"no {OPTION_XML} - not an Adobe Admin Console package")
    try:
        option_xml = ET.fromstring(files[OPTION_XML])
    except ET.ParseError as e:
        raise PackageFormatError(f"unreadable {OPTION_XML} ({e})")

    # Platform the package was built for in the Admin Console. A universal
    # package may carry an app as two media (Intel + Apple silicon); what a
    # recipe selects is the package, so this wins over the media's platform.
    package_platform = (option_xml.findtext("ProcessorArchitecture") or "").strip().lower()

    products = []
    for media in option_xml.iter("HDMedia"):
        if (media.findtext("MediaType") or "").lower() != "product":
            continue
        folder = media.findtext("TargetFolderName") or ""
        try:
            application = json.loads(files.get(folder) or b"{}")
        except ValueError as e:
            raise PackageFormatError(f"unreadable HD/{folder}/Application.json ({e})")
        launch = re.search(r"([^/]+)\.app/", application.get("AppLaunch") or "")
        app_name = launch.group(1) if launch else ""
        install_dir = ((application.get("InstallDir") or {}).get("value") or "").replace(
            "[AdobeProgramFiles]", "/Applications")
        os_range = (application.get("SystemRequirement") or {}).get("SupportedOsVersionRange") or [{}]
        products.append({
            "sap_code": media.findtext("SAPCode") or "",
            "version": media.findtext("productVersion") or application.get("ProductVersion") or "",
            # what Adobe's uninstaller wants as --baseVersion (21.0 for every 21.x)
            "base_version": media.findtext("baseVersion") or application.get("BaseVersion") or "",
            "platform": package_platform or media.findtext("productPlatform") or application.get("Platform") or "",
            "app_name": app_name,
            "app_path": f"{install_dir}/{app_name}.app" if install_dir and app_name else "",
            "min_os": os_range[0].get("min") or "",
            "package_name": option_xml.findtext("PackageName") or "",
            "pkg_path": path,
            "icon": next((files[f"{folder}/{name}"] for name in ICON_NAMES if f"{folder}/{name}" in files), b""),
        })
    return products


def packages_dir(env) -> str:
    return env.get("ADOBE_PACKAGES_DIR") or DEFAULT_PACKAGES_DIR


def archive_dir(env) -> str:
    """ADOBE_ARCHIVE_DIR, or the _Archiv folder inside the work folder."""
    return env.get("ADOBE_ARCHIVE_DIR") or os.path.join(packages_dir(env), ARCHIVE_FOLDER_NAME)


def find_packages(root: str, exclude: str = "") -> list:
    """Every *.pkg below root (files and bundle packages; doesn't descend
    into a bundle package), except Adobe's *_Uninstall.pkg and everything in
    the folder `exclude` (the archive)."""
    excluded = os.path.realpath(exclude) if exclude else None
    result = []
    for current, folders, files in os.walk(root):
        folders[:] = sorted(f for f in folders if os.path.realpath(os.path.join(current, f)) != excluded)
        for name in sorted(folders + files):
            if name.lower().endswith(".pkg") and not name.lower().endswith("_uninstall.pkg"):
                result.append(os.path.join(current, name))
        folders[:] = [f for f in folders if not f.lower().endswith(".pkg")]
    return result


class AdobeAdminConsolePackageFinder(Processor):
    """Finds the newest Adobe Admin Console package for one app in a local
    folder and reports its path and version.

    Adobe apps can't be downloaded by URL: a package has to be built and
    downloaded by hand in the Adobe Admin Console. This processor replaces
    the download step - drop the packages anywhere below ADOBE_PACKAGES_DIR
    (file and folder names don't matter), the app and version are read from
    the package itself.

    ADOBE_PACKAGES_DIR is a work folder: AdobePackageArchiver, the recipe's
    last step, moves the package into the archive once everything worked. So
    "no package for this app" is the normal state between two versions - the
    recipe then stops without an error (stop_processing_recipe) instead of
    failing. A package left behind by a failed run is simply tried again.
    """

    description = __doc__

    input_variables = {
        "adobe_app_name": {
            "required": True,
            "description": (
                "The app the package must install, without .app. Either its "
                "path below /Applications, 'Adobe Illustrator 2027/Adobe "
                "Illustrator' (the APP_NAME the script templates need; use this "
                "form when the app's own name carries no year), or just its "
                "name, 'Adobe InDesign 2026'. Compared case-insensitively."
            ),
        },
        "adobe_platform": {
            "required": False,
            "default": "",
            "description": (
                "Platform of the package as Adobe names it: macuniversal, "
                "macarm64 or osx10-64. Empty = any; then packages of several "
                "platforms for the same app are an error."
            ),
        },
        "ADOBE_PACKAGES_DIR": {
            "required": False,
            "default": DEFAULT_PACKAGES_DIR,
            "description": (
                "Folder searched (recursively) for packages. Set it globally in "
                f"the AutoPkg plist; defaults to {DEFAULT_PACKAGES_DIR}."
            ),
        },
        "ADOBE_ARCHIVE_DIR": {
            "required": False,
            "default": "",
            "description": (
                "Archive folder, never searched for packages. Empty = "
                f"<ADOBE_PACKAGES_DIR>/{ARCHIVE_FOLDER_NAME}."
            ),
        },
    }
    output_variables = {
        "stop_processing_recipe": {"description": "True if there is no package for this app (nothing to do)."},
        "adobe_packages_to_archive": {"description": (
            "List of the packages AdobePackageArchiver moves away when the recipe "
            "got through: every package of this app and platform in the work "
            "folder (the chosen one and older ones) that holds no other app.")},
        "pkg_path": {"description": "Path of the newest matching package."},
        "version": {"description": "Product version of the app in that package, e.g. 21.6.0.057."},
        "adobe_sap_code": {"description": "Adobe's product code, e.g. IDSN."},
        "adobe_platform": {"description": "Platform of the package (macuniversal, macarm64, osx10-64)."},
        "adobe_base_version": {"description": "Base version of the app, e.g. 21.0 for 21.6.0.057 (may be empty)."},
        "adobe_app_path": {"description": "Where the app gets installed, e.g. /Applications/Adobe InDesign 2026/Adobe InDesign 2026.app."},
        "adobe_min_os": {"description": "Minimum macOS version the app supports, e.g. 13.0.0 (may be empty)."},
        "adobe_package_name": {"description": "Package name given in the Admin Console."},
        "adobe_icon_path": {"description": (
            "The app's icon from the package, written as PNG (168 pixels) into "
            "RECIPE_CACHE_DIR; empty if the package has none.")},
    }

    def main(self):
        root = packages_dir(self.env)
        wanted_app = str(self.env["adobe_app_name"]).strip().strip("/").lower()
        if wanted_app.endswith(".app"):
            wanted_app = wanted_app[:-4]
        by_path = "/" in wanted_app
        wanted_platform = str(self.env.get("adobe_platform") or "").strip().lower()
        if not wanted_app:
            raise ProcessorError("adobe_app_name is empty.")
        if not os.path.isdir(root):
            # A missing work folder is an empty one (user decision): create
            # it, so the place to drop packages exists after the first run.
            try:
                os.makedirs(root, exist_ok=True)
            except OSError as e:
                raise ProcessorError(f"ADOBE_PACKAGES_DIR '{root}' does not exist and can't be created: {e}")
            self.output(f"Created the work folder {root}.")

        candidates, seen, single_app_packages = [], [], []
        for path in find_packages(root, exclude=archive_dir(self.env)):
            try:
                products = read_products(path)
            except PackageFormatError as e:
                self.output(f"Ignoring {path}: {e}", verbose_level=2)
                continue
            except OSError as e:
                # e.g. a download still in progress or missing read permission
                self.output(f"WARNING: could not read {path}: {e}")
                continue
            matching = []
            for product in products:
                # shown as the APP_NAME a recipe would need
                shown = product["app_path"][len("/Applications/"):-len(".app")] if product["app_path"].startswith(
                    "/Applications/") else product["app_name"]
                seen.append(f"{shown} {product['version']} ({product['platform']})")
                found_app = shown if by_path else product["app_name"]
                if found_app.lower() != wanted_app:
                    continue
                if wanted_platform and product["platform"].lower() != wanted_platform:
                    continue
                matching.append(product)
            candidates.extend(matching)
            if matching and len(matching) == len(products):
                single_app_packages.append(path)

        if not candidates:
            # The normal state between two versions - not an error. The list
            # of what IS there shows a wrong APP_NAME at a glance.
            wanted = self.env["adobe_app_name"] + (f" ({wanted_platform})" if wanted_platform else "")
            self.output(
                f"No package for '{wanted}' below {root} - nothing to do. "
                f"Waiting there: {', '.join(sorted(set(seen))) or 'no Adobe packages'}."
            )
            self.env["stop_processing_recipe"] = True
            return
        platforms = sorted({product["platform"] for product in candidates})
        if len(platforms) > 1:
            raise ProcessorError(
                f"Packages for several platforms found ({', '.join(platforms)}) - "
                "set adobe_platform to choose one."
            )

        newest = max(candidates, key=lambda product: version_key(product["version"]))
        if not newest["version"]:
            raise ProcessorError(f"No product version in {newest['pkg_path']}.")
        self.env["pkg_path"] = newest["pkg_path"]
        self.env["version"] = newest["version"]
        self.env["adobe_sap_code"] = newest["sap_code"]
        self.env["adobe_platform"] = newest["platform"]
        self.env["adobe_base_version"] = newest["base_version"]
        self.env["adobe_app_path"] = newest["app_path"]
        self.env["adobe_min_os"] = newest["min_os"]
        self.env["adobe_package_name"] = newest["package_name"]
        self.env["adobe_icon_path"] = self.write_icon(newest)
        # newest first; a package that also holds another app stays in the
        # work folder, or that app's recipe would never see it
        self.env["adobe_packages_to_archive"] = sorted(
            single_app_packages, key=lambda path: path != newest["pkg_path"])
        if newest["pkg_path"] not in single_app_packages:
            self.output(f"Note: {newest['pkg_path']} holds several apps and will not be archived.")
        self.output(
            f"Found {newest['app_name']} {newest['version']} ({newest['platform']}): {newest['pkg_path']}"
        )

    def write_icon(self, product: dict) -> str:
        """Path of the product's icon written into the recipe cache, or ''."""
        cache_dir = self.env.get("RECIPE_CACHE_DIR")
        if not product["icon"] or not cache_dir:
            return ""
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, f"{product['app_name']} Icon.png")
        with open(path, "wb") as handle:
            handle.write(product["icon"])
        return path


if __name__ == "__main__":
    PROCESSOR = AdobeAdminConsolePackageFinder()
    PROCESSOR.execute_shell()
