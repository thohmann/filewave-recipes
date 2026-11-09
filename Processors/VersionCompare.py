#!/usr/local/autopkg/python
"""Lenient, dependency-optional version comparison.

Replaces distutils.version.LooseVersion (removed from the stdlib in Python
3.12, and only still working here via a setuptools compatibility shim)
without requiring anything external:

- Prefers `packaging.version.Version` for correct PEP 440 semantics when
  `packaging` is importable and both strings parse cleanly. `packaging`
  ships as part of AutoPkg's own pip/setuptools toolchain, but that isn't
  a guarantee for every AutoPkg install, and real-world app version
  strings (CFBundleShortVersionString values from arbitrary vendors, or
  FileWave's own server version) aren't always PEP 440 compliant either.
- Falls back to a simple, dependency-free comparison of '.'-separated
  numeric components (same tolerant spirit as LooseVersion, and consistent
  with the version_compare() logic already used in
  vorlagen/install_update_requirement.sh) whenever packaging isn't
  available or a string doesn't parse as a valid version. This path never
  raises - an unparseable component is just treated as 0.
"""

import re

_LEADING_DIGITS_RE = re.compile(r"\d+")


def _numeric_components(version_string):
    """Split on '.' and coerce each part to an int, using the leading run
    of digits in that part (e.g. '4' -> 4, '4beta' -> 4, 'beta' -> 0)."""
    components = []
    for part in str(version_string).split("."):
        match = _LEADING_DIGITS_RE.match(part)
        components.append(int(match.group()) if match else 0)
    return components


def _compare_numeric(a, b):
    a_parts = _numeric_components(a)
    b_parts = _numeric_components(b)
    length = max(len(a_parts), len(b_parts))
    a_parts += [0] * (length - len(a_parts))
    b_parts += [0] * (length - len(b_parts))
    if a_parts > b_parts:
        return 1
    if a_parts < b_parts:
        return -1
    return 0


def compare(a, b) -> int:
    """Compare two version strings.

    Returns 1 if a > b, -1 if a < b, 0 if equal. Never raises.
    """
    try:
        from packaging.version import InvalidVersion, Version

        try:
            va, vb = Version(str(a)), Version(str(b))
            if va > vb:
                return 1
            if va < vb:
                return -1
            return 0
        except InvalidVersion:
            pass
    except ImportError:
        pass

    return _compare_numeric(a, b)


def gte(a, b) -> bool:
    """True if version a >= version b."""
    return compare(a, b) >= 0


def lt(a, b) -> bool:
    """True if version a < version b."""
    return compare(a, b) < 0
