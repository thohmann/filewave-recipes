# Wacom Tablet FileWave Recipe

## Dateien

- `Wacom.filewave.recipe` - FileWave Import-Rezept für Wacom Tablet Treiber

## Funktionen
### Automatische Icon-Extraktion
Das Rezept extrahiert automatisch das echte Wacom-Icon aus dem PKG. Bei jedem Run wird:
1. Das Wacom PKG heruntergeladen
2. Das PKG entpackt (`FlatPkgUnpacker`)
3. Der Payload aus `content.pkg` extrahiert (`PkgPayloadUnpacker`)
4. Die App "Wacom Tablet Utility.app" gefunden (`FileFinder`)
5. Das Icon als 512x512 PNG extrahiert (`AppIconExtractor`)
6. Das Icon für den FileWave Kiosk verwendet

### Cache-Cleanup
Vor und nach dem Import werden temporäre Verzeichnisse bereinigt:
- PathCHOWN ändert Besitzer von `unpack`, `payload`, `Icons` Verzeichnissen
- PathDeleterSafe löscht diese Verzeichnisse sicher

## PKG-Struktur
Das Wacom-Paket hat folgende Struktur:
```
WacomTablet-6.4.11-2.pkg
└── content.pkg/
    └── Payload
        └── Applications/
            └── Wacom Tablet.localized/
                ├── Wacom Tablet Utility.app  ← Icon wird hieraus extrahiert
                ├── Wacom Center.app
                └── Wacom Display Settings.app
```

## Verwendung
```bash
autopkg run Wacom.filewave.recipe
```

## Verwendete Prozessoren
1. **PathCHOWN** (3x) - Ändert Besitzer von Cache-Verzeichnissen
2. **PathDeleterSafe** (2x) - Bereinigt temporäre Verzeichnisse vor und nach Import
3. **FlatPkgUnpacker** - Entpackt das Wacom PKG
4. **PkgPayloadUnpacker** - Extrahiert Payload aus `content.pkg`
5. **FileFinder** - Findet "Wacom Tablet Utility.app" im Payload
6. **PkgRootCreator** - Erstellt Icons-Verzeichnis
7. **AppIconExtractor** - Extrahiert App-Icon als 512x512 PNG
8. **FileWaveImporter** - Importiert PKG in FileWave
9. **FileWaveKioskImporter** - Fügt Kiosk-Informationen mit Icon hinzu

## Abhängigkeiten
- Parent Recipe: `com.github.nstrauss.pkg.WacomTablet`