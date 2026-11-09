#!/bin/bash
#
# FileWave Preflight Script
# Prüft per Bundle Identifier, ob eine App aktuell läuft, und reagiert
# darauf gemäß der konfigurierten Aktion (siehe ACTION_IF_RUNNING).
#
# Verwendung: als Pre-Install-Skript vor einem Installations- oder
# Update-Fileset einsetzbar.
#
# Ablauf:
#   1. Prüfen, ob die App (Bundle ID) aktuell läuft.
#   2. Läuft sie nicht -> Installation kann fortgesetzt werden (exit 0).
#   3. Läuft sie, wird gemäß ACTION_IF_RUNNING reagiert:
#      - "skip": Installation wird nicht durchgeführt (exit 99).
#      - "quit": App wird höflich beendet (AppleScript "quit"), danach erneut geprüft.
#      - "kill": App wird hart beendet (pkill -9), danach erneut geprüft.
#      Bei "quit"/"kill" gilt: läuft die App danach weiterhin -> Abbruch (exit 99),
#      sonst kann die Installation fortgesetzt werden (exit 0).
#
# Exit Codes:
#   0  = App läuft nicht (mehr) -> Installation/Update kann fortgesetzt werden
#   99 = App läuft (und sollte laut Konfiguration nicht angetastet oder
#        konnte nicht beendet werden) -> Abbruch, später erneut versuchen
#   1  = Unerwarteter Fehler (z.B. Konfigurationsfehler)
#
# ---------------------------------------------------------------------------
# Konfiguration (wird von FileWaveScriptImporter per %VAR%-Platzhalter befüllt)
# ---------------------------------------------------------------------------

# Bundle Identifier der App, z.B. "com.jabra.direct"
APP_BUNDLE_ID="%APP_BUNDLE_ID%"

# Pfad zur App, wird benötigt um den tatsächlichen Prozessnamen zu ermitteln
APP_PATH="/Applications/%APP_NAME%.app"

# Aktion, falls die App beim Preflight-Check läuft. Erlaubte Werte:
#   "skip" = Installation abbrechen (exit 99), App bleibt unangetastet
#   "quit" = App höflich beenden (AppleScript "quit"), dann Installation fortsetzen
#   "kill" = App hart beenden (kill -9), dann Installation fortsetzen
ACTION_IF_RUNNING="%ACTION_IF_RUNNING%"

# ---------------------------------------------------------------------------
# Funktionen
# ---------------------------------------------------------------------------

# Prüft per Bundle Identifier, ob die App aktuell läuft.
app_is_running() {
    local result
    result=$(/usr/bin/osascript -e "application id \"$APP_BUNDLE_ID\" is running" 2>/dev/null)
    [ "$result" = "true" ]
}

# Ermittelt den tatsächlichen Prozessnamen (CFBundleExecutable) aus dem Info.plist der App.
get_process_name() {
    local plist="$APP_PATH/Contents/Info.plist"
    if [ -f "$plist" ]; then
        /usr/bin/defaults read "$plist" CFBundleExecutable 2>/dev/null
    fi
}

# Beendet die App höflich per AppleScript (löst z.B. "Speichern?"-Dialoge aus).
quit_app() {
    /usr/bin/osascript -e "tell application id \"$APP_BUNDLE_ID\" to quit" 2>/dev/null
}

# Beendet alle Prozesse der App hart (SIGKILL).
kill_app() {
    local process_name
    process_name=$(get_process_name)
    if [ -n "$process_name" ]; then
        /usr/bin/pkill -9 -x "$process_name" 2>/dev/null
    fi
    # Fallback: zusätzlich über den App-Pfad beenden (deckt z.B. Helper-Prozesse ab)
    /usr/bin/pkill -9 -f "$APP_PATH" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Hauptlogik
# ---------------------------------------------------------------------------

if [ -z "$APP_BUNDLE_ID" ]; then
    echo "Fehler: APP_BUNDLE_ID ist nicht gesetzt."
    exit 1
fi

echo "Bundle Identifier: $APP_BUNDLE_ID"
echo "Aktion falls App läuft: $ACTION_IF_RUNNING"

if ! app_is_running; then
    echo "App läuft nicht -> Installation kann fortgesetzt werden."
    exit 0
fi

case "$ACTION_IF_RUNNING" in
    skip)
        echo "App läuft -> Installation wird übersprungen (exit 99)."
        exit 99
        ;;
    quit)
        echo "App läuft -> wird höflich beendet (AppleScript quit)."
        quit_app
        ;;
    kill)
        echo "App läuft -> wird hart beendet (kill -9)."
        kill_app
        ;;
    *)
        echo "Fehler: Ungültiger Wert für ACTION_IF_RUNNING ('$ACTION_IF_RUNNING')."
        exit 1
        ;;
esac

# kurze Wartezeit, damit macOS den Prozess aus der Prozessliste entfernen kann
sleep 1

if app_is_running; then
    echo "App läuft weiterhin -> Abbruch (exit 99), später erneut versuchen."
    exit 99
else
    echo "App wurde erfolgreich beendet -> Installation kann fortgesetzt werden."
    exit 0
fi
