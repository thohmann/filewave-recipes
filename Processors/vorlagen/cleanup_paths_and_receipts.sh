#!/bin/bash
#
# FileWave Uninstall Script
# Löscht eine konfigurierbare Liste von exakten, absoluten Pfaden
# (Dateien/Ordner). Kein Wildcard-/Glob-Support (bewusst, aus Sicherheitsgründen).
# Optional werden zusätzlich zugehörige Paketquittungen (pkgutil) vergessen.
#
# Verwendung: als Uninstall-Skript für ein Fileset einsetzbar.
#
# Verhalten:
#   - Nicht vorhandene Pfade werden ignoriert (kein Fehler).
#   - Fehler beim Löschen werden geloggt, das Skript läuft aber weiter.
#   - Nicht registrierte Paketquittungen werden ignoriert (kein Fehler).
#   - Das Skript liefert immer exit 0 (FileWave Postinstall-Standard).
#
# ---------------------------------------------------------------------------
# Konfiguration (wird von FileWaveScriptImporter per %VAR%-Platzhalter befüllt)
# ---------------------------------------------------------------------------

# Liste der zu löschenden Pfade. Nur exakte, absolute Pfade - keine Wildcards.
# %PATHS_TO_DELETE% wird vom Prozessor als Liste von Bash-Array-Elementen eingesetzt,
# z.B. fw_script_variables = {"PATHS_TO_DELETE": ["/Applications/Foo.app", "/Library/..."]}
PATHS_TO_DELETE=(
    %PATHS_TO_DELETE%
)

# Kritische Verzeichnisse, die niemals gelöscht werden dürfen
CRITICAL_PATHS=(
    "/" "/System" "/Applications" "/Library" "/Users" "/bin" "/sbin"
    "/usr" "/etc" "/private" "/Volumes" "/opt" "/var" "/tmp" "/dev" "/cores"
)

# Optional: Paketquittungen (Bundle Identifier), die per "pkgutil --forget"
# entfernt werden sollen. Leer lassen, um diesen Schritt zu deaktivieren.
# Ermitteln mit: pkgutil --pkgs | grep <suchbegriff>
PKG_RECEIPTS_TO_FORGET=(
    %PKG_RECEIPTS_TO_FORGET%
)

# Prüft, ob ein Pfad einem kritischen Systemverzeichnis entspricht
is_critical_path() {
    local candidate="$1"
    local critical
    for critical in "${CRITICAL_PATHS[@]}"; do
        if [ "$candidate" = "$critical" ]; then
            return 0
        fi
    done
    return 1
}

# ---------------------------------------------------------------------------
# Hauptlogik
# ---------------------------------------------------------------------------

DELETED_COUNT=0
FAILED_COUNT=0

for target in "${PATHS_TO_DELETE[@]}"; do
    # Sicherheitscheck: nur absolute, nicht-kritische Pfade zulassen
    if [ -z "$target" ] || [[ "$target" != /* ]]; then
        echo "Überspringe ungültigen (nicht-absoluten) Pfad: '$target'"
        continue
    fi
    if is_critical_path "$target"; then
        echo "Sicherheitsabbruch: '$target' ist ein kritisches Systemverzeichnis."
        continue
    fi

    if [ ! -e "$target" ] && [ ! -L "$target" ]; then
        echo "Nicht gefunden (übersprungen): $target"
        continue
    fi

    # "--" verhindert, dass ein Pfad, der mit '-' beginnt, als rm-Option interpretiert wird
    if /bin/rm -rf -- "$target" 2>/dev/null; then
        echo "Gelöscht: $target"
        DELETED_COUNT=$((DELETED_COUNT + 1))
    else
        echo "Fehler beim Löschen: $target"
        FAILED_COUNT=$((FAILED_COUNT + 1))
    fi
done

echo "Fertig. Gelöscht: $DELETED_COUNT, Fehlgeschlagen: $FAILED_COUNT."

# ---------------------------------------------------------------------------
# Paketquittungen entfernen (optional)
# ---------------------------------------------------------------------------

FORGOTTEN_COUNT=0
FORGET_FAILED_COUNT=0

for pkg_id in "${PKG_RECEIPTS_TO_FORGET[@]}"; do
    [ -z "$pkg_id" ] && continue

    if ! /usr/sbin/pkgutil --pkg-info "$pkg_id" >/dev/null 2>&1; then
        echo "Paketquittung nicht registriert (übersprungen): $pkg_id"
        continue
    fi

    if /usr/sbin/pkgutil --forget "$pkg_id" >/dev/null 2>&1; then
        echo "Paketquittung vergessen: $pkg_id"
        FORGOTTEN_COUNT=$((FORGOTTEN_COUNT + 1))
    else
        echo "Fehler beim Vergessen der Paketquittung: $pkg_id"
        FORGET_FAILED_COUNT=$((FORGET_FAILED_COUNT + 1))
    fi
done

echo "Paketquittungen vergessen: $FORGOTTEN_COUNT, Fehlgeschlagen: $FORGET_FAILED_COUNT."

exit 0
