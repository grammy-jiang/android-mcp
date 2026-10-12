"""Platform-real subprocess integration with a fake ADB executable (no tablet)."""

from pathlib import Path

from android_mcp_host.adb import AdbReport, Device
from android_mcp_host.probes import ProbeService


class FixedDevice:
    def inspect(self):
        return AdbReport(True, "/unused/adb", "37.0", None, (Device("EMULATOR-001", "device", {}),))


def test_actual_subprocess_uses_explicit_serial_and_safe_fixed_arguments(tmp_path: Path):
    fake_dir = tmp_path / "ADB executable with spaces"
    fake_dir.mkdir()
    executable = fake_dir / "adb"
    executable.write_text(
        "#!/bin/sh\n"
        "test \"$1\" = '-s' || exit 71\n"
        "test \"$2\" = 'EMULATOR-001' || exit 72\n"
        "test \"$3\" = 'shell' || exit 73\n"
        "test \"$4\" = 'getenforce' || exit 74\n"
        "printf 'Enforcing\\n'\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    service = ProbeService(FixedDevice(), adb_executable=str(executable), timeout_s=2)
    observed = service.observe("EMULATOR-001", ["selinux"])
    assert observed["status"] == "ok"
    assert observed["results"][0]["fields"]["enforcement"] == "Enforcing"
    assert observed["errors"] == []
