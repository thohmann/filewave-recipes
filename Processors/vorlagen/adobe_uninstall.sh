#!/bin/bash
#
# FileWave Uninstall Script für Adobe-Apps (Creative Cloud)
# Deinstalliert eine App mit Adobes eigenem Installer (HyperDrive "Setup"),
# der mit jeder Creative-Cloud-App auf den Client kommt. Anders als ein
# reines Löschen des App-Ordners entfernt das auch Adobes Komponenten und den
# Eintrag in der Creative-Cloud-App. Benutzereinstellungen bleiben erhalten.
#
# Verwendung: als Uninstall-Skript am Platzhalter-Fileset einer Adobe-App.
#
# UNGETESTET auf einem Client (Stand der Vorlage): vor dem ersten Einsatz
# einmal auf einem Testgerät mit installierter App laufen lassen.
#
# Verhalten:
#   - Fehlt Adobes Setup oder ein Parameter, wird nichts gelöscht (nur Log).
#   - Kennt Adobe die App nicht unter der Plattform des Pakets (Paket mit
#     getrennten Intel-/Apple-Silicon-Medien), folgt ein zweiter Versuch mit
#     der Plattform des Geräts.
#   - Das Skript liefert immer exit 0 (wie cleanup_paths_and_receipts).
#
# ---------------------------------------------------------------------------
# Konfiguration (wird von FileWaveScriptImporter per %VAR%-Platzhalter befüllt)
# ---------------------------------------------------------------------------

# Adobes Produktcode, z.B. IDSN (InDesign), PHSP (Photoshop)
SAP_CODE="%ADOBE_SAP_CODE%"
# Basisversion der Ausgabe, z.B. 21.0 für jedes InDesign 2026 (21.x)
BASE_VERSION="%ADOBE_BASE_VERSION%"
# Plattform des Pakets: macuniversal, macarm64 oder osx10-64
PLATFORM="%ADOBE_PLATFORM%"

SETUP="/Library/Application Support/Adobe/Adobe Desktop Common/HDBox/Setup"

# ---------------------------------------------------------------------------
# Hauptlogik
# ---------------------------------------------------------------------------

for value in "$SAP_CODE" "$BASE_VERSION" "$PLATFORM"; do
    # leer oder nicht ersetzter Platzhalter
    if [ -z "$value" ] || [[ "$value" == %*% ]]; then
        echo "Abbruch: SAP-Code, Basisversion oder Plattform fehlt ('$SAP_CODE', '$BASE_VERSION', '$PLATFORM')."
        exit 0
    fi
done

if [ ! -x "$SETUP" ]; then
    echo "Abbruch: Adobes Setup nicht gefunden ($SETUP) - nichts deinstalliert."
    exit 0
fi

run_uninstall() {
    local platform="$1"
    echo "Deinstalliere $SAP_CODE $BASE_VERSION ($platform) ..."
    "$SETUP" --uninstall=1 --sapCode="$SAP_CODE" --baseVersion="$BASE_VERSION" \
        --platform="$platform" --deleteUserPreferences=false
}

if run_uninstall "$PLATFORM"; then
    echo "Fertig: $SAP_CODE $BASE_VERSION deinstalliert."
    exit 0
fi
echo "Adobes Setup meldet einen Fehler für Plattform $PLATFORM."

if [ "$(/usr/bin/uname -m)" = "arm64" ]; then
    DEVICE_PLATFORM="macarm64"
else
    DEVICE_PLATFORM="osx10-64"
fi
if [ "$DEVICE_PLATFORM" != "$PLATFORM" ]; then
    if run_uninstall "$DEVICE_PLATFORM"; then
        echo "Fertig: $SAP_CODE $BASE_VERSION deinstalliert."
        exit 0
    fi
    echo "Adobes Setup meldet auch für Plattform $DEVICE_PLATFORM einen Fehler."
fi

echo "Deinstallation fehlgeschlagen - siehe Ausgabe oben und Adobes Log unter /Library/Logs/Adobe/Installers."
exit 0
