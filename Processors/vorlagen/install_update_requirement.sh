#!/bin/bash
#
# FileWave Requirement Script
# Prüft, ob eine App unter einem bestimmten Pfad installiert ist und optional,
# ob die installierte Version >= einer geforderten Mindestversion ist.
#
# Verwendung: als Requirement-Script sowohl für ein "Installations-Fileset"
# als auch für ein "Update-Fileset" einsetzbar (siehe MODE unten).
#
# Exit Codes:
#   0   = Aktion (Installation/Update) ist erforderlich
#   210 = Aktion ist NICHT erforderlich (App bereits in gewünschtem Zustand)
#
# ---------------------------------------------------------------------------
# Konfiguration (wird von FileWaveScriptImporter per %VAR%-Platzhalter befüllt)
# ---------------------------------------------------------------------------

# Pfad zur App (z.B. /Applications/Beispiel.app)
APP_PATH="/Applications/%APP_NAME%.app"

# Mindestversion, z.B. "1.2.3". Leer lassen ("") um Versionsprüfung zu deaktivieren.
REQUIRED_VERSION="%REQUIRED_VERSION%"

# Modus: "Installation" oder "Update"
MODE="%MODE%"

# ---------------------------------------------------------------------------
# Funktionen
# ---------------------------------------------------------------------------

# Liest CFBundleShortVersionString aus dem Info.plist der App.
# Gibt die Version aus oder nichts, falls nicht lesbar.
get_installed_version() {
    local plist="$APP_PATH/Contents/Info.plist"
    if [ -f "$plist" ]; then
        /usr/bin/defaults read "$plist" CFBundleShortVersionString 2>/dev/null
    fi
}

# Vergleicht zwei Versionsnummern (Punkt-getrennt).
# Ausgabe: 1 = v1 > v2, 0 = v1 == v2, -1 = v1 < v2
version_compare() {
    local v1="$1" v2="$2"
    if [ "$v1" = "$v2" ]; then
        echo 0
        return
    fi
    local IFS=.
    local -a ver1=($v1) ver2=($v2)
    local i max=${#ver1[@]}
    if [ ${#ver2[@]} -gt $max ]; then
        max=${#ver2[@]}
    fi
    for ((i = 0; i < max; i++)); do
        local n1=${ver1[i]:-0}
        local n2=${ver2[i]:-0}
        # nicht-numerische Anteile entfernen, um Vergleichsfehler zu vermeiden
        n1=${n1//[^0-9]/}
        n2=${n2//[^0-9]/}
        n1=${n1:-0}
        n2=${n2:-0}
        if ((10#$n1 > 10#$n2)); then
            echo 1
            return
        elif ((10#$n1 < 10#$n2)); then
            echo -1
            return
        fi
    done
    echo 0
}

# Prüft, ob installierte Version >= geforderter Version ist.
version_meets_requirement() {
    local installed="$1"
    if [ -z "$REQUIRED_VERSION" ]; then
        return 0
    fi
    if [ -z "$installed" ]; then
        return 1
    fi
    local cmp
    cmp=$(version_compare "$installed" "$REQUIRED_VERSION")
    [ "$cmp" -ge 0 ]
}

# ---------------------------------------------------------------------------
# Hauptlogik
# ---------------------------------------------------------------------------

if [ -e "$APP_PATH" ]; then
    APP_INSTALLED=true
else
    APP_INSTALLED=false
fi

INSTALLED_VERSION=""
if [ "$APP_INSTALLED" = true ]; then
    INSTALLED_VERSION=$(get_installed_version)
fi

echo "App-Pfad: $APP_PATH"
echo "App installiert: $APP_INSTALLED"
if [ -n "$INSTALLED_VERSION" ]; then
    echo "Installierte Version: $INSTALLED_VERSION"
fi
if [ -n "$REQUIRED_VERSION" ]; then
    echo "Geforderte Mindestversion: $REQUIRED_VERSION"
fi
echo "Modus: $MODE"

case "$MODE" in
    Installation)
        if [ "$APP_INSTALLED" = false ]; then
            echo "App ist nicht installiert -> Installation erforderlich."
            exit 0
        else
            echo "App ist bereits installiert -> keine Installation erforderlich."
            exit 210
        fi
        ;;

    Update)
        if [ "$APP_INSTALLED" = false ]; then
            echo "App ist nicht installiert -> Update nicht anwendbar."
            exit 210
        fi

        if version_meets_requirement "$INSTALLED_VERSION"; then
            echo "Installierte Version erfüllt die Anforderung -> kein Update erforderlich."
            exit 210
        else
            echo "Installierte Version erfüllt die Anforderung nicht -> Update erforderlich."
            exit 0
        fi
        ;;

    *)
        echo "Ungültiger MODE '$MODE'. Erlaubt sind 'Installation' oder 'Update'."
        exit 210
        ;;
esac
