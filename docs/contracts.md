# Shared contracts

The wire-level contract resides in `contracts/device-status.v1.schema.json`. Both Host and eventual Native runtimes must return compatible envelopes, adding runtime-specific information in documented optional fields.

## Status v1

Required:

- `schema_version = 1`
- `runtime = "host" | "android"`
- `capabilities`: feature names with *actual* availability (not a promised feature list)
- `devices`: target descriptors; zero is valid
- `errors`: typed diagnostic entries; a partial failure need not make the whole tool fail

Host adds `host` (OS, arch, Python) and `adb` (executable, availability, reported version, error), and returns zero or more observed devices.

Device descriptor fields: `device_id`, `state`, and `properties`. `device_id` is scoped to a runtime/transport until an explicit host↔native pairing identity is designed.

## Planned command contracts (not implemented)

- Mutations always specify device identifier, expected current state, operation class, idempotency key, timeout and typed arguments.
- Native UI actions include preconditions, per-step stop-on-mismatch and an explicit interaction lease.
- Privileged operations require a separate authorization domain.
- MCP tool catalogs should remain compact and report optional capability IDs in `device_status` instead of exposing every ADB subcommand as one tool.
- Long-running tasks return durable IDs and can be queried or canceled independently of the MCP request connection.

## Compatibility and versioning

Schema versions are explicit integers. Changes that invalidate existing consumers must increment the schema version and ship compatibility tests across Host and Native. The Monorepo may ship separate host wheels and Android APKs under one coordinated repository release without requiring upgrades at exactly the same moment.

## Host typed extensions (candidate)

- `adb-observation.v1.schema.json`: explicit-device observation envelope, allowlisted probes, typed errors and bounded output.
- `adb-development-action.v1.schema.json`: validated action types, fixed fields and allowed limits (not an arbitrary shell).
- `adb-development.v1.schema.json`: result status, dry-run plan, typed errors and truncated-output marker.
- Native joint control is not yet a wire contract; see [Host↔Native coordination](host-native-coordination.md). Do not implement a default permissive bridge.
