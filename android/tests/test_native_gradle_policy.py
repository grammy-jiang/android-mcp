"""Read-only Gradle policy guard tests with synthetic Native Gradle files."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/audit_native_gradle_policy.py"
SPEC = importlib.util.spec_from_file_location("native_gradle_policy", SCRIPT)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def make_fixture(root: Path) -> Path:
    android = root / "android"
    wrapper = android / "gradle/wrapper/gradle-wrapper.properties"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(
        "distributionSha256Sum=" + "a" * 64 + "\n"
        "distributionUrl=https\\://services.gradle.org/distributions/gradle-9.6.0-bin.zip\n"
    )
    (android / "settings.gradle.kts").write_text(
        "repositories { google(); mavenCentral(); gradlePluginPortal() }\n"
        "repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)\n"
    )
    for module in m.MODULES:
        p = android / module / "build.gradle.kts"
        p.parent.mkdir(parents=True)
        p.write_text(
            'plugins { id("org.jetbrains.kotlin.jvm") version "2.3.21" }\n'
            'dependencies { implementation("io.ktor:ktor-server-cio-jvm:3.4.3") }\n'
        )
    app = android / "app/build.gradle.kts"
    app.write_text(
        app.read_text()
        + "\nminSdk = 30\ntargetSdk = 36\n"
        + 'implementation(project(":native-protocol"))\n'
        + 'implementation(project(":native-lifecycle"))\n'
    )
    return root


def test_allow_static_pinned_dependencies_but_report_missing_locks(
    tmp_path: Path,
) -> None:
    repo = make_fixture(tmp_path)
    report = m.policy_for(repo)
    assert report["result"] == "incomplete"
    assert report["explicit_coordinate_count"] == len(m.MODULES)
    assert report["module_count"] == len(m.MODULES)
    assert report["wrapper_sha256_pinned"] is True
    assert len(report["gaps"]) == 2


def test_strict_gate_refuses_unresolved_supply_chain(tmp_path: Path) -> None:
    repo = make_fixture(tmp_path)
    with pytest.raises(m.NativeGradlePolicyError, match="Cannot certify"):
        m.policy_for(repo, strict=True)


@pytest.mark.parametrize(
    "coordinate",
    [
        "io.ktor:ktor-server-cio-jvm:+",
        "io.ktor:ktor-server-cio-jvm:latest.release",
        "io.ktor:ktor-server-cio-jvm:3.4.3-SNAPSHOT",
        "io.ktor:ktor-server-cio-jvm:${ktorVersion}",
    ],
)
def test_dynamic_versions_are_rejected(tmp_path: Path, coordinate: str) -> None:
    repo = make_fixture(tmp_path)
    file = repo / "android/app/build.gradle.kts"
    file.write_text(
        file.read_text().replace("io.ktor:ktor-server-cio-jvm:3.4.3", coordinate)
    )
    with pytest.raises(m.NativeGradlePolicyError):
        m.policy_for(repo)


def test_wrapper_sha_is_required(tmp_path: Path) -> None:
    repo = make_fixture(tmp_path)
    file = repo / "android/gradle/wrapper/gradle-wrapper.properties"
    file.write_text(file.read_text().replace("a" * 64, "bad"))
    with pytest.raises(m.NativeGradlePolicyError, match="SHA-256"):
        m.policy_for(repo)


def test_project_level_repos_must_be_forbidden(tmp_path: Path) -> None:
    repo = make_fixture(tmp_path)
    file = repo / "android/settings.gradle.kts"
    file.write_text("repositories { google(); mavenCentral(); gradlePluginPortal() }\n")
    with pytest.raises(m.NativeGradlePolicyError, match="Project-level"):
        m.policy_for(repo)


def test_min_sdk_and_target_sdk_reviewed_bounds(tmp_path: Path) -> None:
    repo = make_fixture(tmp_path)
    file = repo / "android/app/build.gradle.kts"
    file.write_text(file.read_text().replace("minSdk = 30", "minSdk = 21"))
    with pytest.raises(m.NativeGradlePolicyError, match="minimum API"):
        m.policy_for(repo)


def test_verification_xml_requires_component_checksums_metadata(tmp_path: Path) -> None:
    repo = make_fixture(tmp_path)
    file = repo / "android/gradle/verification-metadata.xml"
    file.write_text("<verification-metadata><components/></verification-metadata>")
    with pytest.raises(m.NativeGradlePolicyError, match="no components"):
        m.policy_for(repo)


def test_module_lockfiles_and_metadata_make_strict_policy_complete(
    tmp_path: Path,
) -> None:
    repo = make_fixture(tmp_path)
    for module in m.MODULES:
        (repo / "android" / module / "gradle.lockfile").write_text(
            "io.ktor:ktor-server-cio-jvm:3.4.3=compileClasspath\n"
        )
    (repo / "android/gradle/verification-metadata.xml").write_text(
        "<verification-metadata><components>"
        '<component group="a" name="b" version="1">'
        '<artifact name="b-1.jar"><sha256 value="'
        + "a" * 64
        + '"/></artifact></component></components></verification-metadata>'
    )
    report = m.policy_for(repo, strict=True)
    assert report["result"] == "passed"
    assert report["lockfile_count"] == len(m.MODULES)


def test_dynamic_android_test_fixture_dependency_is_rejected(tmp_path: Path) -> None:
    repo = make_fixture(tmp_path)
    fixture = repo / "android/native-v3-fixture/build.gradle.kts"
    fixture.write_text(
        fixture.read_text()
        + '\nandroidTestImplementation("androidx.test:runner:latest.release")\n'
    )
    with pytest.raises(m.NativeGradlePolicyError):
        m.policy_for(repo)
