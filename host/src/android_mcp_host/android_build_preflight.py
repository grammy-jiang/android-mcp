"""Fail-closed, read-only Android Gradle project preflight.

No Gradle wrapper or task is ever executed, even --version. Only fixed
source metadata and bounded Git HEAD/status requests are observed.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import subprocess
import zipfile
from collections.abc import Callable, Mapping, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

from android_mcp_host.command_runner import OutputLimitExceeded, RunResult, bounded_run
from android_mcp_host.sdk_ndk_inventory import _SAFE_PROBE_ENV, SdkNdkInventory

OUTPUT_BYTES = 65536
MAX_FILE_BYTES = 65536
MAX_WRAPPER_BYTES = 1048576
SHA = re.compile(r"[0-9a-f]{40,64}\Z", re.ASCII)
SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
DIST = re.compile(r"^https\\?://services\.gradle\.org/distributions/gradle-9\.6\.0-bin\.zip$")
AGP = re.compile(r'id\("com\.android\.application"\) version "9\.4\.0"')
COMPILE = re.compile(r"\bcompileSdk\s*=\s*36\b")
JAVA = re.compile(r"\bsourceCompatibility\s*=\s*JavaVersion\.VERSION_17\b")
BUILD_VARIANT = "debug"
TASKS = {
    "assemble_debug": (":app:assembleDebug",),
    "lint_debug": (":app:lintDebug",),
    "test_jvm": (":native-protocol:test", ":native-lifecycle:test", ":native-mcp-jvm:test"),
}
Runner = Callable[[Sequence[str], float, int], RunResult]
# Git status should not write an index lock, run fsmonitor hooks or consult
# caller-supplied global/system Git configs, credentials and environment.
_GIT_ENV = {
    **_SAFE_PROBE_ENV,
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
}


def _safe_git_run(argv: Sequence[str], timeout: float, limit: int) -> RunResult:
    return bounded_run(argv, timeout, limit, env=_GIT_ENV)


def get_build_preflight_output_schema() -> dict[str, Any]:
    data: Any = json.loads(
        files("android_mcp_host.wire_schemas")
        .joinpath("host-android-build-preflight.v1.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(data, dict):
        raise ValueError("Invalid packaged build preflight schema")
    return data


def _error(code: str) -> dict[str, str]:
    return {"code": code, "message": "Approved Android build preflight could not be confirmed"}


def _static_file(root: Path, name: str, *, limit: int = MAX_FILE_BYTES) -> bytes | None:
    """Read only regular files below the trusted root; reject symlink ancestry."""
    relative = Path(name)
    # Path.is_relative_to is lexical: "/trusted/../secret" still tests True.
    # Explicitly reject dotdot components before constructing a candidate.
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        return None
    path = root / relative
    try:
        if path == root or not path.is_relative_to(root):
            return None
        for index in range(1, len(relative.parts) + 1):
            if (root / Path(*relative.parts[:index])).is_symlink():
                return None
        if not path.is_file():
            return None
        size = path.stat().st_size
        if not 0 < size <= limit:
            return None
        data = path.read_bytes()
        return data if len(data) == size else None
    except (OSError, ValueError):
        return None


def _wrapper_metadata(data: bytes) -> tuple[str, str] | None:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError:
        return None
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue
        key, sep, value = line.partition("=")
        if not sep or key in values:
            return None
        values[key.strip()] = value.strip()
    url = values.get("distributionUrl", "")
    checksum = values.get("distributionSha256Sum", "")
    if (
        DIST.fullmatch(url) is None
        or SHA256.fullmatch(checksum) is None
        or values.get("validateDistributionUrl") != "true"
        or values.get("retries") != "0"
    ):
        return None
    return "9.6.0", checksum


def _build_metadata(source: bytes, settings: bytes) -> bool:
    try:
        build = source.decode("utf-8")
        projects = settings.decode("utf-8")
    except UnicodeError:
        return False
    return (
        AGP.search(build) is not None
        and COMPILE.search(build) is not None
        and JAVA.search(build) is not None
        and 'include(":app")' in projects
        and "enableAndroidApp" in projects
    )


class AndroidBuildPreflight:
    """Trusted constructor pins; a remote MCP client chooses only a closed action."""

    def __init__(
        self,
        root: Path,
        *,
        expected_revision: str | None = None,
        expected_wrapper_sha256: str | None = None,
        inventory: SdkNdkInventory | None = None,
        runner: Runner = _safe_git_run,
        git_binary: Path = Path("/usr/bin/git"),
        timeout_s: float = 3.0,
    ) -> None:
        if (
            not root.is_absolute()
            or ".." in root.parts
            or len(str(root)) > 1024
            or git_binary != Path("/usr/bin/git")
        ):
            raise ValueError("Only trusted absolute project and fixed Git executable")
        if not 0 < timeout_s <= 5:
            raise ValueError("Git metadata deadline must be within 0-5 seconds")
        self._root = root
        self._expected_revision = expected_revision
        self._expected_wrapper = expected_wrapper_sha256
        self._inventory = inventory if inventory is not None else SdkNdkInventory()
        self._runner = runner
        self._git = git_binary
        self._timeout = timeout_s

    def _git_read(self, *arguments: str) -> RunResult | str:
        argv = [
            str(self._git),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(self._root),
            *arguments,
        ]
        try:
            result = self._runner(argv, self._timeout, OUTPUT_BYTES)
        except subprocess.TimeoutExpired:
            return "METADATA_TIMEOUT"
        except OutputLimitExceeded:
            return "OUTPUT_LIMIT"
        except PermissionError:
            return "PERMISSION_DENIED"
        except (OSError, ValueError, RuntimeError):
            return "GIT_EXEC_FAILED"
        if (
            not isinstance(result.stdout, str)
            or not isinstance(result.stderr, str)
            or result.truncated
            or len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))
            > OUTPUT_BYTES
        ):
            return "OUTPUT_LIMIT"
        if result.returncode != 0 or result.stderr:
            return "METADATA_UNAVAILABLE"
        return result

    def plan(self, action: str = "assemble_debug", variant: str = "debug") -> dict[str, Any]:
        """Return a checked inert command preview. Never run Gradle or mutate Git."""
        response: dict[str, Any] = {
            "schema_version": 1,
            "runtime": "host",
            "status": "blocked",
            "project_root": str(self._root),
            "expected_revision": self._expected_revision
            if isinstance(self._expected_revision, str) and SHA.fullmatch(self._expected_revision)
            else None,
            "observed_revision": None,
            "wrapper_sha256": None,
            "gradle_distribution_sha256": None,
            "gradle_version": None,
            "agp_version": None,
            "jdk_version": None,
            "sdk_api": None,
            "variant": "debug",
            "action": action if isinstance(action, str) and action in TASKS else None,
            "tasks": [],
            "argv_preview": [],
            "dirty": None,
            "execution_enabled": False,
            "sdk_licenses_verified": False,
            "errors": [],
        }

        def fail(code: str, status: str = "blocked") -> dict[str, Any]:
            response["status"] = status
            response["errors"].append(_error(code))
            return response

        if type(action) is not str or action not in TASKS or variant != BUILD_VARIANT:
            return fail("INVALID_ACTION")
        if (
            not isinstance(self._expected_revision, str)
            or SHA.fullmatch(self._expected_revision) is None
            or not isinstance(self._expected_wrapper, str)
            or SHA256.fullmatch(self._expected_wrapper) is None
        ):
            return fail("UNAPPROVED_PIN")
        try:
            if self._root.is_symlink() or not self._root.is_dir():
                return fail("PROJECT_ROOT_UNTRUSTED")
        except OSError:
            return fail("PROJECT_ROOT_UNTRUSTED")
        # Source / wrapper bytes are never interpreted as executable code.
        gradlew = _static_file(self._root, "android/gradlew")
        wrapper = _static_file(
            self._root, "android/gradle/wrapper/gradle-wrapper.jar", limit=MAX_WRAPPER_BYTES
        )
        properties = _static_file(self._root, "android/gradle/wrapper/gradle-wrapper.properties")
        app = _static_file(self._root, "android/app/build.gradle.kts")
        settings = _static_file(self._root, "android/settings.gradle.kts")
        if any(item is None for item in (gradlew, wrapper, properties, app, settings)):
            return fail("PROJECT_FILES_UNVERIFIED")
        assert gradlew is not None and wrapper is not None and properties is not None
        assert app is not None and settings is not None
        if not gradlew.startswith(b"#!/") or not zipfile.is_zipfile(io.BytesIO(wrapper)):
            return fail("WRAPPER_UNVERIFIED")
        try:
            gradlew_mode = (self._root / "android/gradlew").stat().st_mode
            if not stat.S_ISREG(gradlew_mode) or gradlew_mode & 0o111 == 0:
                return fail("WRAPPER_UNVERIFIED")
            with zipfile.ZipFile(io.BytesIO(wrapper)) as jar:
                # Verify that this actually contains Gradle's entrypoint,
                # not an arbitrary ZIP or two bytes resembling a JAR magic.
                if (
                    len(jar.infolist()) > 512
                    or "org/gradle/wrapper/GradleWrapperMain.class" not in jar.namelist()
                ):
                    return fail("WRAPPER_UNVERIFIED")
        except (OSError, zipfile.BadZipFile, ValueError):
            return fail("WRAPPER_UNVERIFIED")
        sha = hashlib.sha256(wrapper).hexdigest()
        response["wrapper_sha256"] = sha
        if sha != self._expected_wrapper:
            return fail("WRAPPER_SHA_MISMATCH")
        metadata = _wrapper_metadata(properties)
        if metadata is None or not _build_metadata(app, settings):
            return fail("BUILD_METADATA_UNVERIFIED")
        response["gradle_version"], response["gradle_distribution_sha256"] = metadata
        response["agp_version"] = "9.4.0"
        response["sdk_api"] = 36
        status = self._git_read("rev-parse", "--verify", "HEAD")
        if isinstance(status, str):
            return fail(status, "unavailable")
        revision = status.stdout.strip()
        if not SHA.fullmatch(revision):
            return fail("REVISION_UNVERIFIED")
        response["observed_revision"] = revision
        if revision != self._expected_revision:
            return fail("REVISION_MISMATCH")
        dirty = self._git_read("status", "--porcelain=v1", "--untracked-files=all")
        if isinstance(dirty, str):
            return fail(dirty, "unavailable")
        response["dirty"] = bool(dirty.stdout)
        if response["dirty"]:
            return fail("DIRTY_WORKTREE")
        try:
            toolchain = self._inventory.inspect()
        except Exception:
            # Boundary to an injected local provider: unexpected filesystem,
            # parser or CLI failures must never leak a private exception.
            return fail("TOOLCHAIN_UNAVAILABLE", "unavailable")
        if not isinstance(toolchain, Mapping) or not isinstance(toolchain.get("tools"), Mapping):
            return fail("TOOLCHAIN_UNAVAILABLE", "unavailable")
        state: Mapping[str, Any] = toolchain["tools"]
        jdk = state.get("jdk17")
        sdk = state.get("sdk_platform")
        gradle = state.get("gradle")
        build_tools = state.get("build_tools")
        if not all(
            isinstance(entry, dict) and entry.get("runnable") is True
            for entry in (jdk, sdk, gradle, build_tools)
        ):
            return fail("TOOLCHAIN_UNAVAILABLE", "unavailable")
        assert isinstance(jdk, dict) and isinstance(sdk, dict)
        assert isinstance(gradle, dict) and isinstance(build_tools, dict)
        version = jdk.get("version")
        if not isinstance(version, str) or len(version) > 64 or not version.isascii():
            return fail("TOOLCHAIN_UNAVAILABLE", "unavailable")
        response["jdk_version"] = version
        if (
            not str(jdk["version"]).startswith("17.")
            or sdk.get("version") != "36"
            or build_tools.get("version") != "36.0.0"
            or gradle.get("version") not in {"9.6", "9.6.0"}
        ):
            return fail("TOOLCHAIN_INCOMPATIBLE", "unavailable")
        tasks = list(TASKS[action])
        response["tasks"] = tasks
        response["argv_preview"] = [
            "./gradlew",
            "--offline",
            "--no-daemon",
            *(["-PenableAndroidApp=true"] if action != "test_jvm" else []),
            *tasks,
        ]
        response["status"] = "planned"
        return response
