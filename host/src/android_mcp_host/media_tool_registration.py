"""Registered sensitive Host media tool families, preserving legacy ordering."""

from __future__ import annotations

from fastmcp import FastMCP

from android_mcp_host.synthetic_file_pull import FilePullService
from android_mcp_host.synthetic_file_pull_tool import register_file_pull_tool
from android_mcp_host.synthetic_file_push import FilePushService
from android_mcp_host.synthetic_file_push_tool import register_file_push_tool
from android_mcp_host.synthetic_screenrecord import ScreenRecordService
from android_mcp_host.synthetic_screenrecord_tool import register_screenrecord_tool
from android_mcp_host.synthetic_screenshot import ScreenshotArtifacts
from android_mcp_host.synthetic_screenshot_tool import register_screenshot_tool
from android_mcp_host.synthetic_ui_action_tool import register_ui_action_tool
from android_mcp_host.synthetic_ui_actions import UiActionService
from android_mcp_host.synthetic_ui_hierarchy import UiHierarchyService
from android_mcp_host.synthetic_ui_tool import register_ui_hierarchy_tool


def register_media_tools(
    server: FastMCP,
    screenshot: ScreenshotArtifacts | None,
    hierarchy: UiHierarchyService | None,
    screenrecord: ScreenRecordService | None,
    file_pull: FilePullService | None = None,
    file_push: FilePushService | None = None,
    ui_action: UiActionService | None = None,
) -> None:
    if screenshot is not None:
        register_screenshot_tool(server, screenshot)
    if hierarchy is not None:
        register_ui_hierarchy_tool(server, hierarchy)
    if screenrecord is not None:
        register_screenrecord_tool(server, screenrecord)
    if file_pull is not None:
        register_file_pull_tool(server, file_pull)
    if file_push is not None:
        register_file_push_tool(server, file_push)
    if ui_action is not None:
        register_ui_action_tool(server, ui_action)
