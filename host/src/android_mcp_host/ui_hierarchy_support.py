"""Bounded and redacted synthetic Android UI hierarchy parser."""

from __future__ import annotations

import json
import re
from typing import Any

from defusedxml import ElementTree  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

MAX_XML_BYTES = 32768
MAX_OUTPUT_BYTES = 30720  # reserve room for the outer MCP receipt
MAX_NODES = 96
MAX_DEPTH = 12
REDACTED = "[REDACTED]"
_NODE = re.compile(r"node_[A-Za-z0-9_-]{1,40}\Z", re.ASCII)
_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,127}\Z", re.ASCII)
_RESOURCE = re.compile(r"[A-Za-z_][A-Za-z0-9_./:-]{0,127}\Z", re.ASCII)
_SECRET = re.compile(
    r"(?:password|passcode|passphrase|pin[\s:=]|otp|one.time|"
    r"bearer|authorization|auth[\s:=]|token|api[_\s-]?key|"
    r"credential|secret|private[_\s-]?key|session[_\s-]?id|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
    re.IGNORECASE,
)
_NOTIFICATION = re.compile(r"(?:notification|sms[_./-]|message[_./-])", re.IGNORECASE)


class InvalidUiTree(ValueError):
    """Untrusted or unsafe UI hierarchy."""


def _boolean(value: object) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise InvalidUiTree("Invalid UI boolean")


def _text(value: object, *, hide: bool = False) -> str:
    if not isinstance(value, str):
        raise InvalidUiTree("Invalid UI text")
    if not value:
        return ""
    if (
        hide
        or len(value) > 96
        or _SECRET.search(value) is not None
        or _NOTIFICATION.search(value) is not None
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
    ):
        return REDACTED
    return value


def _resource(value: object) -> str:
    if not isinstance(value, str):
        raise InvalidUiTree("Invalid resource field")
    if not value:
        return ""
    if _RESOURCE.fullmatch(value) is None or len(value) > 128:
        raise InvalidUiTree("Untrusted resource field")
    return value


def parse_ui_xml(raw: bytes) -> dict[str, Any]:
    """Reject XML tricks and expose only safe, typed, bounded node metadata."""
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_XML_BYTES:
        raise InvalidUiTree("UI size limit")
    if b"\x00" in raw or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise InvalidUiTree("Unsafe XML declaration")
    try:
        raw.decode("utf-8")
        root = ElementTree.fromstring(raw)
    except (UnicodeError, ElementTree.ParseError, DefusedXmlException) as error:
        raise InvalidUiTree("Invalid XML") from error
    if root.tag != "hierarchy" or root.attrib.get("rotation") not in {"0", "1", "2", "3"}:
        raise InvalidUiTree("Invalid hierarchy metadata")
    if root.text and root.text.strip():
        raise InvalidUiTree("Unexpected hierarchy text")
    stack: list[tuple[Any, str | None, int, bool]] = [
        (node, None, 1, False) for node in reversed(root)
    ]
    if not stack:
        raise InvalidUiTree("Empty hierarchy")
    seen: set[str] = set()
    nodes: list[dict[str, Any]] = []
    focused_node_id: str | None = None
    while stack:
        node, parent_id, depth, parent_sensitive = stack.pop()
        if node.tag != "node" or depth > MAX_DEPTH or len(nodes) >= MAX_NODES:
            raise InvalidUiTree("UI node budget exceeded")
        if (node.text and node.text.strip()) or (node.tail and node.tail.strip()):
            raise InvalidUiTree("Unstructured UI content")
        node_id = node.attrib.get("node-id")
        node_class = node.attrib.get("class")
        if (
            not isinstance(node_id, str)
            or _NODE.fullmatch(node_id) is None
            or node_id in seen
            or not isinstance(node_class, str)
            or _CLASS.fullmatch(node_class) is None
        ):
            raise InvalidUiTree("Invalid or repeated node identity")
        seen.add(node_id)
        focused = _boolean(node.attrib.get("focused"))
        password = _boolean(node.attrib.get("password"))
        if focused:
            if focused_node_id is not None:
                raise InvalidUiTree("More than one focused node")
            focused_node_id = node_id
        source_resource = _resource(node.attrib.get("resource-id", ""))
        sensitive = bool(
            parent_sensitive
            or password
            or node_class.endswith("EditText")
            or _NOTIFICATION.search(node_class)
            or _NOTIFICATION.search(source_resource)
        )
        nodes.append(
            {
                "id": node_id,
                "parent_id": parent_id,
                "class_name": node_class,
                "resource_id": _text(source_resource, hide=sensitive),
                "text": _text(node.attrib.get("text", ""), hide=sensitive),
                "content_description": _text(node.attrib.get("content-desc", ""), hide=sensitive),
                "focused": focused,
                "password": password,
            }
        )
        for child in reversed(node):
            stack.append((child, node_id, depth + 1, sensitive))
    result: dict[str, Any] = {
        "rotation": int(root.attrib["rotation"]),
        "focused_node_id": focused_node_id,
        "nodes": nodes,
    }
    if len(json.dumps(result, ensure_ascii=True).encode("ascii")) > MAX_OUTPUT_BYTES:
        raise InvalidUiTree("UI response budget exceeded")
    return result
