"""SDK-free defense-in-depth checks for Android Native N3 declarations."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
ANDROID = "{http://schemas.android.com/apk/res/android}"


def root() -> ET.Element:
    return ET.parse(MANIFEST).getroot()


def test_permission_allowlist_exactly_matches_required_local_service() -> None:
    permissions = [
        item.attrib[ANDROID + "name"] for item in root().findall("uses-permission")
    ]
    assert permissions == [
        "android.permission.INTERNET",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.POST_NOTIFICATIONS",
    ]


def test_foreground_service_is_private_and_explicitly_typed() -> None:
    app = root().find("application")
    assert app is not None
    services = app.findall("service")
    assert len(services) == 1
    service = services[0]
    assert service.attrib[ANDROID + "name"] == ".NativeMcpForegroundService"
    assert service.attrib[ANDROID + "exported"] == "false"
    assert service.attrib[ANDROID + "foregroundServiceType"] == "specialUse"
    assert service.attrib[ANDROID + "stopWithTask"] == "false"
    subtype = service.find("property")
    assert subtype is not None
    assert subtype.attrib[ANDROID + "name"] == (
        "android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
    )
    assert "read-only" in subtype.attrib[ANDROID + "value"].lower()


def test_no_receiver_or_exported_private_activity() -> None:
    app = root().find("application")
    assert app is not None
    assert app.findall("receiver") == []
    assert app.findall("provider") == []
    assert len(app.findall("activity")) == 2
    activity_export = {
        a.attrib[ANDROID + "name"]: a.attrib[ANDROID + "exported"]
        for a in app.findall("activity")
    }
    assert activity_export == {
        ".NativeMcpActivity": "true",
        ".BackgroundMcpActivity": "false",
    }


def test_user_data_backup_and_cleartext_networking_disabled() -> None:
    app = root().find("application")
    assert app is not None
    assert app.attrib[ANDROID + "allowBackup"] == "false"
    assert app.attrib[ANDROID + "usesCleartextTraffic"] == "false"
