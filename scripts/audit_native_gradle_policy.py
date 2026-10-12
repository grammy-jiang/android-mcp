#!/usr/bin/env python3
"""Read-only Android Native dependency-reproducibility and plugin policy check.

This is a *static preflight*, not a substitute for resolving dependencies,
running Gradle dependency verification, or checking actual artifacts.
Use --strict only after real Gradle lockfiles and checksum metadata exist.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
MODULES = ("app", "native-protocol", "native-lifecycle", "native-mcp-jvm")
COORDINATE = re.compile(
    r'\b(?:implementation|api|testImplementation|testRuntimeOnly|runtimeOnly)\("([^"()]+)"\)'
)
PLUGIN = re.compile(r'\bid\("([^"()]+)"\)\s+version\s+"([^"()]+)"')
PINNED = re.compile(r"\A\d+\.\d+(?:\.\d+)*(?:[-.][A-Za-z0-9.]+)?\Z")
SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
ALLOWED_REPOS = ("google()", "mavenCentral()", "gradlePluginPortal()")


class NativeGradlePolicyError(ValueError):
    """Build policy could not be checked or was violated."""


def read_bounded(path: Path) -> str:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 200_000:
        raise NativeGradlePolicyError(
            f"Missing, symlinked or oversized policy input: {path.name}"
        )
    return path.read_text(encoding="utf-8")


def policy_for(repo_root: Path, strict: bool = False) -> dict[str, object]:
    android = repo_root / "android"
    wrapper = read_bounded(android / "gradle/wrapper/gradle-wrapper.properties")
    sha_matches = re.findall(
        r"^distributionSha256Sum=([a-f0-9]{64})\s*$", wrapper, re.MULTILINE
    )
    if len(sha_matches) != 1 or not SHA256.fullmatch(sha_matches[0]):
        raise NativeGradlePolicyError(
            "Gradle wrapper must pin exactly one full SHA-256"
        )
    urls = re.findall(r"^distributionUrl=(.+)$", wrapper, re.MULTILINE)
    if len(urls) != 1 or not urls[0].startswith(
        "https\\://services.gradle.org/distributions/gradle-"
    ):
        raise NativeGradlePolicyError("Gradle distribution must use official HTTPS URL")
    if not urls[0].endswith("-bin.zip"):
        raise NativeGradlePolicyError("Unexpected Gradle distribution artifact type")

    settings = read_bounded(android / "settings.gradle.kts")
    if "RepositoriesMode.FAIL_ON_PROJECT_REPOS" not in settings:
        raise NativeGradlePolicyError(
            "Project-level dependency repositories must be forbidden"
        )
    if any(settings.count(repo) < 1 for repo in ALLOWED_REPOS):
        raise NativeGradlePolicyError(
            "Missing approved Gradle repository configuration"
        )

    coordinates: list[str] = []
    plugin_versions: list[str] = []
    for name in MODULES:
        script = read_bounded(android / name / "build.gradle.kts")
        for candidate in COORDINATE.findall(script):
            pieces = candidate.split(":")
            if (
                len(pieces) != 3
                or not PINNED.fullmatch(pieces[2])
                or "snapshot" in pieces[2].lower()
                or "latest" in pieces[2].lower()
            ):
                raise NativeGradlePolicyError(
                    f"Dynamic or ambiguous dependency in module {name}"
                )
            coordinates.append(candidate)
        for _, version in PLUGIN.findall(script):
            if not PINNED.fullmatch(version):
                raise NativeGradlePolicyError(
                    f"Gradle plugin version is not static in module {name}"
                )
            plugin_versions.append(version)
        # Fail closed for versions injected dynamically in dependency strings.
        if re.search(
            r'(?:implementation|api|runtimeOnly|testImplementation|testRuntimeOnly)\("[^"\n]*\$',
            script,
        ):
            raise NativeGradlePolicyError(
                f"Unreviewed interpolated dependency in module {name}"
            )

    app = read_bounded(android / "app/build.gradle.kts")
    if not re.search(r"\bminSdk\s*=\s*30\b", app):
        raise NativeGradlePolicyError(
            "App minimum API must remain 30 until reviewed change"
        )
    if not re.search(r"\btargetSdk\s*=\s*36\b", app):
        raise NativeGradlePolicyError(
            "Target API baseline must remain 36 until reviewed change"
        )
    for p in (":native-protocol", ":native-lifecycle"):
        if f'project("{p}")' not in app:
            raise NativeGradlePolicyError(f"Native APK missing {p} module dependency")

    lock_paths = [android / "gradle.lockfile"] + [
        android / module / "gradle.lockfile" for module in MODULES
    ]
    locks = [path for path in lock_paths if path.is_file()]
    lock_nontrivial = 0
    for p in locks:
        content = read_bounded(p)
        if any(
            line and not line.startswith("#") and ":" in line and "=" in line
            for line in content.splitlines()
        ):
            lock_nontrivial += 1
    verification = android / "gradle/verification-metadata.xml"
    verified_components = 0
    verified_sha256 = 0
    if verification.is_file():
        try:
            tree = ET.fromstring(read_bounded(verification))
        except ET.ParseError as error:
            raise NativeGradlePolicyError(
                "Malformed Gradle dependency verification XML"
            ) from error
        verified_components = sum(
            1 for entry in tree.iter() if entry.tag.endswith("component")
        )
        verified_sha256 = sum(
            1
            for entry in tree.iter()
            if entry.tag.endswith("sha256")
            and SHA256.fullmatch(entry.attrib.get("value", ""))
        )
        if verified_components == 0:
            raise NativeGradlePolicyError(
                "Gradle verification metadata has no components"
            )

    gaps = []
    if len(locks) < len(MODULES) or lock_nontrivial < len(MODULES):
        gaps.append("Gradle dependency locking is not complete for every module")
    if verified_components == 0 or verified_sha256 == 0:
        gaps.append("Gradle dependency verification SHA-256 metadata is not populated")
    if strict and gaps:
        raise NativeGradlePolicyError(
            "Cannot certify reproducible build: " + "; ".join(gaps)
        )

    return {
        "result": "passed" if not gaps else "incomplete",
        "kind": "static_preflight_only",
        "module_count": len(MODULES),
        "explicit_coordinate_count": len(coordinates),
        "plugin_version_count": len(plugin_versions),
        "wrapper_sha256_pinned": True,
        "lockfile_count": len(locks),
        "verification_component_count": verified_components,
        "verification_sha256_count": verified_sha256,
        "gaps": gaps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=HERE)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require nonempty module locks and verification SHA-256 hashes",
    )
    args = parser.parse_args()
    try:
        report = policy_for(args.repo, args.strict)
    except (NativeGradlePolicyError, OSError, UnicodeError) as error:
        print(f"NATIVE_GRADLE_POLICY_FAILED: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
