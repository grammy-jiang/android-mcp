"""SDK-free guards and UI fixture tests for Android 11–13 Native support."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/smoke-native-legacy-emulator.py"
spec = importlib.util.spec_from_file_location("native_legacy_emulator_smoke", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("api", [30, 33])
def test_legacy_api_support_is_exact(api: int) -> None:
    module.require_old_api(api)


@pytest.mark.parametrize("api", [-1, 0, 29, 31, 32, 34, 36])
def test_legacy_probe_rejects_other_api_levels(api: int) -> None:
    with pytest.raises(ValueError, match="30 or 33"):
        module.require_old_api(api)


def ui(n2: str = "true", n3: str = "false", warning: str = "") -> str:
    message = warning or module.N3_UNSUPPORTED_MESSAGE
    return (
        '<hierarchy><node text="START LOCAL READ-ONLY MCP" '
        f'class="android.widget.Button" enabled="{n2}"/>'
        '<node text="OPEN PERSISTENT SERVICE PREVIEW" '
        f'class="android.widget.Button" enabled="{n3}"/>'
        f'<node text="{message}" class="android.widget.TextView"/></hierarchy>'
    )


def test_old_android_must_have_n2_and_show_n3_disabled() -> None:
    module.inspect_old_api_ui(ui())


def test_rejects_old_android_that_accidentally_enables_n3() -> None:
    with pytest.raises(AssertionError, match="entry is enabled"):
        module.inspect_old_api_ui(ui(n3="true"))


def test_rejects_old_android_that_breaks_n2() -> None:
    with pytest.raises(AssertionError, match="N2 MCP start"):
        module.inspect_old_api_ui(ui(n2="false"))


def test_rejects_old_android_missing_version_explanation() -> None:
    with pytest.raises(AssertionError, match="warning is missing"):
        module.inspect_old_api_ui(ui(warning="Not supported"))


def test_rejects_missing_or_duplicate_buttons() -> None:
    with pytest.raises(AssertionError):
        module.inspect_old_api_ui("<hierarchy/>")
    with pytest.raises(AssertionError):
        module.inspect_old_api_ui(
            ui().replace(
                "</hierarchy>",
                (
                    '<node text="OPEN PERSISTENT SERVICE PREVIEW" '
                    'class="android.widget.Button" enabled="false"/></hierarchy>'
                ),
            )
        )
