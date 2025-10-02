#!/usr/local/autopkg/python
# -*- coding: utf-8 -*-

"""
CrowdStrikeFalconDownloader.py

AutoPKG Processor zum Download von CrowdStrike Falcon Sensoren
basierend auf Sensor Update Policies.

Verwendet macOS Keychain für sichere Credential-Speicherung.

WICHTIG: Diese Datei muss als 'CrowdStrikeFalconDownloader.py' gespeichert werden!
"""

import json
import subprocess
import datetime
import hashlib
from pathlib import Path
from autopkglib import Processor, ProcessorError

try:
    import requests
except ImportError:
    raise ProcessorError("Das 'requests' Modul ist erforderlich. Installiere es mit: pip3 install requests")

__all__ = ["CrowdStrikeFalconDownloader"]

CLOUD_BASE_URLS = {
    "us-1": "https://api.crowdstrike.com",
    "us-2": "https://api.us-2.crowdstrike.com",
    "eu-1": "https://api.eu-1.crowdstrike.com",
    "us-gov-1": "https://api.laggar.gcw.crowdstrike.com",
}

KEYCHAIN_SERVICE = "crowdstrike_falcon_api"
KEYCHAIN_ACCOUNT_ID = "api_client_id"
KEYCHAIN_ACCOUNT_SECRET = "api_client_secret"


class CrowdStrikeFalconDownloader(Processor):
    """Downloads CrowdStrike Falcon sensor based on policy configuration."""
    
    description = __doc__
    
    input_variables = {
        "cloud": {
            "required": False,
            "default": "eu-1",
            "description": "CrowdStrike Cloud Region (us-1, us-2, eu-1, us-gov-1)",
        },
        "platform": {
            "required": False,
            "default": "Mac",
            "description": "Platform name (Mac, macOS)",
        },
        "policy_name": {
            "required": False,
            "default": "platform_default",
            "description": "Sensor Update Policy Name",
        },
        "client_id": {
            "required": False,
            "description": "API Client ID (optional, falls nicht in Keychain)",
        },
        "client_secret": {
            "required": False,
            "description": "API Client Secret (optional, falls nicht in Keychain)",
        },
    }
    
    output_variables = {
        "pathname": {
            "description": "Path to downloaded installer",
        },
        "version": {
            "description": "Sensor version",
        },
        "sha256": {
            "description": "SHA256 hash of installer",
        },
        "policy_info": {
            "description": "Policy information dictionary",
        },
    }
    
    def read_from_keychain(self, account):
        """Liest Credentials aus macOS Keychain."""
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-a", account, "-s", KEYCHAIN_SERVICE, "-w"],
                check=True, capture_output=True, text=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None
    
    def get_credentials(self):
        """Holt Credentials aus Input-Variablen oder Keychain."""
        client_id = self.env.get("client_id")
        client_secret = self.env.get("client_secret")
        
        # Falls nicht in Input-Variablen, versuche Keychain
        if not client_id:
            client_id = self.read_from_keychain(KEYCHAIN_ACCOUNT_ID)
        if not client_secret:
            client_secret = self.read_from_keychain(KEYCHAIN_ACCOUNT_SECRET)
        
        if not client_id or not client_secret:
            raise ProcessorError(
                "API Credentials nicht gefunden. "
                "Entweder in Recipe angeben oder vorher speichern mit: "
                "python crowdstrike_downloader.py --setup-credentials"
            )
        
        return client_id, client_secret
    
    def authenticate(self, base_url, client_id, client_secret):
        """Authentifizierung gegen CrowdStrike API."""
        session = requests.Session()
        session.headers.update({'Content-Type': 'application/x-www-form-urlencoded'})
        
        auth_url = f"{base_url}/oauth2/token"
        payload = {'client_id': client_id, 'client_secret': client_secret}
        
        try:
            resp = session.post(auth_url, data=payload, timeout=30)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise ProcessorError(f"Authentifizierung fehlgeschlagen: {e}")
        
        token_data = resp.json()
        access_token = token_data.get('access_token')
        if not access_token:
            raise ProcessorError("Kein access_token in der API-Antwort erhalten.")
        
        session.headers.update({
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        })
        
        return session
    
    def api_get(self, session, base_url, endpoint, params=None):
        """GET-Request an die API mit Filter-Handling."""
        url = f"{base_url}{endpoint}"
        
        if params and 'filter' in params:
            filter_str = params.pop('filter')
            encoded_filter = filter_str.replace("'", "%27")
            query_parts = [f"filter={encoded_filter}"]
            for key, value in params.items():
                query_parts.append(f"{key}={value}")
            url = f"{url}?{'&'.join(query_parts)}"
            resp = session.get(url, timeout=60)
        else:
            resp = session.get(url, params=params, timeout=60)
        
        try:
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise ProcessorError(f"API Request fehlgeschlagen: {e}")
        
        return resp.json()
    
    def get_sensor_update_policy(self, session, base_url, platform, policy_name):
        """Holt Sensor Update Policy und extrahiert Version/Build."""
        fql = f"platform_name:'{platform}'"
        params = {'filter': fql, 'limit': 500}
        
        self.output(f"Suche Policy '{policy_name}' für Platform '{platform}'...")
        resp = self.api_get(session, base_url, "/policy/combined/sensor-update/v2", params)
        
        resources = resp.get("resources", [])
        if not resources:
            raise ProcessorError(f"Keine Policies gefunden für platform={platform}")
        
        # Suche nach exaktem Namen
        pol = None
        for p in resources:
            if p.get("name") == policy_name:
                pol = p
                break
        
        # Fallback: erste enabled Policy mit Version
        if not pol:
            self.output(f"Policy '{policy_name}' nicht gefunden, suche Fallback...")
            for p in resources:
                settings = p.get("settings") or {}
                if p.get("enabled") and settings.get("sensor_version"):
                    pol = p
                    self.output(f"Verwende Policy: {p.get('name')}")
                    break
        
        if not pol:
            raise ProcessorError(f"Keine verwendbare Policy gefunden für platform={platform}")
        
        settings = pol.get("settings") or {}
        sensor_version = settings.get("sensor_version")
        
        self.output(f"Policy: {pol.get('name')}, Version: {sensor_version}")
        
        return sensor_version, pol
    
    def find_installer(self, session, base_url, platform, version_prefix):
        """Sucht Installer für Platform und Version."""
        plat_key = platform.lower()
        if plat_key in ("mac", "macos"):
            plat_key = "mac"
        
        fql = f'platform:"{plat_key}"'
        params = {'filter': fql, 'sort': 'version|desc', 'limit': 200}
        
        self.output(f"Suche Installer für {platform}, Version {version_prefix}...")
        resp = self.api_get(session, base_url, "/sensors/combined/installers/v1", params)
        
        resources = resp.get("resources", [])
        if not resources:
            raise ProcessorError(f"Keine Installer gefunden für platform={platform}")
        
        # Filtere nach Version
        if version_prefix:
            matching = [r for r in resources if r.get("version", "").startswith(version_prefix)]
            if matching:
                installer = matching[0]
                self.output(f"Installer gefunden: {installer.get('version')}")
                return installer
        
        # Fallback: neuester Installer
        installer = resources[0]
        self.output(f"Verwende neuesten Installer: {installer.get('version')}")
        return installer
    
    def download_installer(self, session, base_url, sha256, out_file):
        """Lädt Installer herunter."""
        self.output(f"Starte Download: {out_file.name}")
        
        url = f"{base_url}/sensors/entities/download-installer/v1"
        params = {'id': sha256}
        
        try:
            resp = session.get(url, params=params, timeout=300, stream=True)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise ProcessorError(f"Download fehlgeschlagen: {e}")
        
        payload = resp.content
        if not payload:
            raise ProcessorError("Download lieferte keinen Inhalt")
        
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "wb") as f:
            f.write(payload)
        
        self.output(f"Download abgeschlossen: {len(payload)} bytes")
        return out_file
    
    def cleanup_old_versions(self, download_dir, current_file, max_versions=3):
        """Löscht alte Versionen, behält nur die neuesten max_versions."""
        # Finde alle FalconSensor .pkg Dateien
        all_pkgs = sorted(
            download_dir.glob("FalconSensorMacOS_*_Install.pkg"),
            key=lambda p: p.stat().st_mtime,
            reverse=True  # Neueste zuerst
        )
        
        # Entferne die aktuelle Datei aus der Liste falls vorhanden
        all_pkgs = [p for p in all_pkgs if p != current_file]
        
        # Füge aktuelle Datei an den Anfang hinzu
        all_pkgs.insert(0, current_file)
        
        # Behalte nur max_versions, lösche den Rest
        if len(all_pkgs) > max_versions:
            to_delete = all_pkgs[max_versions:]
            self.output(f"Cleanup: Behalte {max_versions} neueste Versionen, lösche {len(to_delete)} alte")
            for old_pkg in to_delete:
                try:
                    old_pkg.unlink()
                    self.output(f"  Gelöscht: {old_pkg.name}")
                except Exception as e:
                    self.output(f"  Warnung: Konnte {old_pkg.name} nicht löschen: {e}")
        else:
            self.output(f"Cleanup: {len(all_pkgs)} Version(en) im Cache, kein Cleanup nötig")
    
    def verify_sha256(self, file_path, expected_sha):
        """Verifiziert SHA256 Hash."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        
        actual_sha = h.hexdigest()
        if actual_sha.lower() != expected_sha.lower():
            raise ProcessorError(
                f"SHA256 Hash stimmt nicht überein!\n"
                f"Erwartet: {expected_sha}\n"
                f"Aktuell:  {actual_sha}"
            )
        
        self.output("SHA256 Verifikation erfolgreich")
    
    def main(self):
        """Main processor logic."""
        cloud = self.env.get("cloud", "eu-1").lower()
        platform = self.env.get("platform", "Mac")
        policy_name = self.env.get("policy_name", "platform_default")
        
        # Validate cloud
        if cloud not in CLOUD_BASE_URLS:
            raise ProcessorError(f"Unbekannte Cloud: {cloud}")
        
        base_url = CLOUD_BASE_URLS[cloud]
        self.output(f"CrowdStrike Cloud: {cloud} → {base_url}")
        
        # Get credentials
        client_id, client_secret = self.get_credentials()
        
        # Authenticate
        self.output("Authentifizierung...")
        session = self.authenticate(base_url, client_id, client_secret)
        
        # Get policy
        sensor_version, policy_info = self.get_sensor_update_policy(
            session, base_url, platform, policy_name
        )
        
        if not sensor_version:
            raise ProcessorError("Keine sensor_version in Policy gefunden")
        
        # Find installer
        installer = self.find_installer(session, base_url, platform, sensor_version)
        
        sha256 = installer.get("sha256")
        full_version = installer.get("version")
        
        if not sha256 or not full_version:
            raise ProcessorError("Installer-Informationen unvollständig")
        
        # Prepare download path
        download_dir = Path(self.env.get("RECIPE_CACHE_DIR")) / "downloads"
        filename = f"FalconSensorMacOS_{full_version}_Install.pkg"
        out_file = download_dir / filename
        
        # Check if already downloaded
        if out_file.exists() and out_file.stat().st_size > 0:
            self.output(f"Datei existiert bereits: {out_file}")
            # Verify hash
            try:
                self.verify_sha256(out_file, sha256)
                self.output("Existierende Datei ist gültig, überspringe Download")
            except ProcessorError:
                self.output("Existierende Datei ist ungültig, lade neu herunter")
                out_file.unlink()
                self.download_installer(session, base_url, sha256, out_file)
                self.verify_sha256(out_file, sha256)
                # Cleanup nach neuem Download
                self.cleanup_old_versions(download_dir, out_file, max_versions=3)
        else:
            # Download
            self.download_installer(session, base_url, sha256, out_file)
            self.verify_sha256(out_file, sha256)
            # Cleanup nach neuem Download
            self.cleanup_old_versions(download_dir, out_file, max_versions=3)
        
        # Set output variables
        self.env["pathname"] = str(out_file)
        self.env["version"] = full_version
        self.env["sha256"] = sha256
        self.env["policy_info"] = policy_info
        
        self.output(f"Download erfolgreich: {filename}")
        self.output(f"Version: {full_version}")


if __name__ == "__main__":
    processor = CrowdStrikeFalconDownloader()
    processor.execute_shell()