#!/bin/bash
#
# FileWave Uninstall Script für Adobe Acrobat (eigenständiger Acrobat-Installer)
# Deinstalliert Acrobat mit Adobes eigenem Werkzeug, das in jeder
# Acrobat-Installation steckt:
#   <App>/Contents/Helpers/Acrobat Uninstaller.app/Contents/Library/
#       LaunchServices/com.adobe.Acrobat.RemoverTool
# Es entfernt App, Distiller, Frameworks, Browser-Erweiterungen, Office-Add-ins,
# die ARM-Registrierung und die Paketquittungen. Benutzereinstellungen bleiben.
#
# Nicht für Creative-Cloud-Apps aus der Adobe Admin Console - dafür gibt es
# adobe_uninstall.
#
# Verwendung: als Uninstall-Skript am Platzhalter-Fileset.
#
# UNGETESTET auf einem Client (Stand der Vorlage): Der Aufruf des RemoverTool
# folgt der in der MacAdmins-Praxis üblichen Form; vor dem ersten Einsatz einmal
# auf einem Testgerät mit installiertem Acrobat laufen lassen.
#
# Verhalten:
#   - Fehlt das RemoverTool, endet es mit Fehler oder liegt die App danach
#     noch da, wird als Rückfall nur der App-Ordner gelöscht. Frameworks,
#     Add-ins usw. bleiben dann liegen (steht im Log).
#   - Ein unplausibler App-Pfad (nicht /Applications/.../*.app) wird nie
#     gelöscht.
#   - Das Skript liefert immer exit 0 (wie cleanup_paths_and_receipts).
#
# ---------------------------------------------------------------------------
# Konfiguration (wird von FileWaveScriptImporter per %VAR%-Platzhalter befüllt)
# ---------------------------------------------------------------------------

# Pfad der App unter /Applications ohne .app, z.B. "Adobe Acrobat DC/Adobe Acrobat"
APP_NAME="%APP_NAME%"

# Für Tests: anderes Wurzelverzeichnis statt /Applications
APPLICATIONS_DIR="${ACROBAT_UNINSTALL_APPLICATIONS_DIR:-/Applications}"

# ---------------------------------------------------------------------------
# Hauptlogik
# ---------------------------------------------------------------------------

if [ -z "$APP_NAME" ] || [[ "$APP_NAME" == %*% ]]; then
    echo "Abbruch: APP_NAME fehlt ('$APP_NAME') - nichts deinstalliert."
    exit 0
fi

APP_PATH="$APPLICATIONS_DIR/$APP_NAME.app"
UNINSTALLER_APP="$APP_PATH/Contents/Helpers/Acrobat Uninstaller.app"
REMOVER_TOOL="$UNINSTALLER_APP/Contents/Library/LaunchServices/com.adobe.Acrobat.RemoverTool"
UNINSTALLER_BIN="$UNINSTALLER_APP/Contents/MacOS/Acrobat Uninstaller"

# Plausibel: direkt unter dem Programme-Ordner, endet auf .app, kein "..".
if [[ "$APP_NAME" == /* ]] || [[ "$APP_NAME" == *..* ]] || [[ "$APP_NAME" == */ ]]; then
    echo "Abbruch: unplausibler App-Name '$APP_NAME' - nichts deinstalliert."
    exit 0
fi

if [ ! -e "$APP_PATH" ]; then
    echo "Nicht installiert: $APP_PATH - nichts zu tun."
    exit 0
fi

if [ -x "$REMOVER_TOOL" ]; then
    echo "Deinstalliere Acrobat mit Adobes RemoverTool ($APP_PATH) ..."
    "$REMOVER_TOOL" Uninstall "$UNINSTALLER_BIN" "$APP_PATH"
    status=$?
    if [ "$status" -eq 0 ] && [ ! -e "$APP_PATH" ]; then
        echo "Fertig: Acrobat deinstalliert."
        exit 0
    fi
    echo "RemoverTool endete mit Status $status, App liegt noch da: $([ -e "$APP_PATH" ] && echo ja || echo nein)."
else
    echo "RemoverTool nicht gefunden: $REMOVER_TOOL"
fi

if [ ! -e "$APP_PATH" ]; then
    echo "App ist nicht mehr vorhanden - kein Rückfall nötig."
    exit 0
fi

# Rückfall: nur den App-Ordner löschen.
echo "Rückfall: lösche nur den App-Ordner $APP_PATH (Frameworks, Add-ins usw. bleiben liegen)."
if /bin/rm -rf -- "$APP_PATH" 2>/dev/null && [ ! -e "$APP_PATH" ]; then
    echo "Gelöscht: $APP_PATH"
else
    echo "Fehler beim Löschen: $APP_PATH"
fi
exit 0
