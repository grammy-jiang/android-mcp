# N1.d — Native Tool profile policy and typed synthetic SDK contracts

N1.d separates the **live** Native MCP public catalog from an internal
synthetic contract-preview registry. No fake approval, client-provided
approved flag, Origin header or loopback address grants live Android
capabilities. The production LocalMcpGateway remains exactly one
device_status Tool using the original Kotlin SDK ToolSchema,
description and public v1 status. Its own resource and sensitive Tool
catalogs remain empty. The default Host MCP three-Tool catalog is
unchanged. N0.b denial still controls the live unpaired path.

## Synthetic-only focused profile

An isolated, non-deployed NativeToolProfiles planner can produce a
focused read-only set of three fixtures: native_build_snapshot,
native_system_snapshot and native_app_health. This is *only* a unit
and Kotlin SDK shape exercise, not a live listener, Android permission
grant, or MCP API. SyntheticPreviewPermit is process-epoch-bound and
must have a strictly localhost test Origin and fake test signature.
Both required fixture permission entries must be true; a missing,
revoked, unexpected Android API, stale process epoch, forged Origin
or requested unapproved capability makes the planner fall back to
the one public status descriptor. Production liveTools always returns
the same single public Tool even with model-supplied approval=true.

Each fake focused Tool is explicitly synthetic and read-only, with
an empty object input schema, no allowed additional input properties,
and a versioned strict object output schema. Output metadata includes
schema_version, a fixed success/partial/denied/unsupported status and
synthetic_only true. Non-preview/unknown tool names always produce a
typed denial. The actual official Kotlin MCP SDK Tool/ToolSchema and
CallToolResult serializer tests cover output schemas, readOnlyHint,
destructiveHint=false, error vs success results, and structuredContent.
They do not register a synthetic handler with the deployed Android
listener.

## Executed test-first and release boundary

T-N1D-01..06 are six named Kotlin policy tests; an initial public-only
scaffold gave three meaningful red failures, then passed after the
conservative fake-catalog implementation. Additional JVM Kotlin SDK
schema serialization/result tests and Python source/privacy/Host
catalog checks provide independent constraints. The actual Kotlin
loopback MCP and verified disposable API30/33/34/36 public
tools/list, tools/call, Activity/FGS, notification Stop and revocation
suites must remain passing. Emulator success proves unchanged public
behavior, not a live authenticated read-only focused profile.

Nothing here enables capture, PackageManager inventory, Accessibility,
screen actions, public network access, MediaProjection, physical
device operations, Android permissions or Host mutation. N6
independent security review, real pairing and explicit caller identity
must precede any production registration of a focused Tool. Tests
with fake approvals are **not** physical-device authorization or
security signoff. GitHub Hosted Actions remain billing-blocked; use
the actual local JDK17/SDK36 quality and disposable-emulator gates.
