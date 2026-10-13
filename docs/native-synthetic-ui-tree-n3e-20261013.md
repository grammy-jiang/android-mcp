# N3.e — bounded synthetic Accessibility hierarchy, real UI reads disabled

**Status:** completed **internal, synthetic-only** Kotlin UI-tree model and
default-denying Android adapter. No AccessibilityService is declared,
user-enabled or connected in the production APK. No real Android UI
hierarchy, other-app window, password, device credential or gesture is read,
and no public Native MCP UI-tree Tool is registered.

## Synthetic scope and privacy boundary

NativeSyntheticUiTree accepts only explicitly injected fake node graphs
from a Kotlin unit test, with fake caller authentication and fake user
consent. Context contains a new random per-process epoch, a current
window/node epoch, Android API 30+, declared/enabled/connected *fake*
service, current foreground and unlocked/nonsecure/visible window, and
a single expected current-app package. Mismatched epoch, missing fake
service/caller consent, background, locked/secure/hidden window, or a
root in another package produces a fixed denial and **zero nodes**.
Revocation permanently disables the entire instance. A synthetic
window change rotates the node epoch; all previously returned handles
become stale even if the Android process itself remains alive.

The approved fake tree emits **only** safe node role, focus flag, depth,
opaque ephemeral 128-bit handle and a parent-handle link. Raw source
IDs, node text, content descriptions, coordinates, resource IDs, custom
view labels and package names never enter the output. INPUT and
password nodes are redacted, marked unfocused and their descendants
are not traversed. Invisible/other-package children are not returned.
Handles use a per-instance random salt, the current synthetic window
epoch and the internal fake source ID; they are stable for equivalent
fake trees within an unchanged window but not reusable across windows,
restarts or a different process-scoped model.

The traversal is nonrecursive and bounded: at most 64 returned nodes,
maximum depth 8, bounded children visited per node, and a serialized
JSON result below 16 KiB. An identity-based visited set rejects cyclic
node references and duplicates; duplicate raw IDs cannot alias handles.
Oversized, cyclic, hidden or malformed trees return partial metadata,
not unbounded recursion or a fabricated complete hierarchy. No
private raw data is placed in generated diagnostics or a public Tool.

The private AndroidUiTreeReadiness adapter only checks the existing
N3.d Accessibility eligibility reader. With the APK's absent service,
it reports SERVICE_UNAVAILABLE with an empty list; otherwise it still
returns an empty DENIED result. It never constructs AccessibilityNodeInfo,
calls getRootInActiveWindow, dispatches a gesture, writes Settings,
starts an AccessibilityService, grants permission or requests an
Android Accessibility system dialog.

## Test-first evidence and activation status

Six specified T-N3E-01..06 Kotlin/JUnit tests were written first:
all six produced meaningful failures against a deliberately incomplete
scaffold. After implementation all six pass. Additional tests cover
ephemeral handle stability and cross-instance inequality, duplicate
source IDs, cyclic references, 1,500+-node structures, enormous
password/private text, redaction of descendants, fake window rotation
and stale-handle denial. Five Native Python source/Manifest tests pin
exact bounds, absence of raw text fields in serialized safe-node
objects, production Android denial, no gesture APIs and the unchanged
one-Tool public MCP registry.

The full macOS JDK17/SDK36 Kotlin/JVM, official Python/Kotlin MCP
interoperability, Host/Native security and signed APK/Lint/permission
gates are required. Verified disposable API30/33/34/36 emulator
acceptance verifies only the **existing** public status, foreground
service and notification lifecycle. The real Accessibility consent
portion of T-N3E-05 is explicitly deferred: there is no approved
capture-capable/user-activated AccessibilityService on any emulator.
Synthetic API30/33/34/36 tests are not evidence that Android actually
allowed UI hierarchy inspection.

The feature remains inert until separately reviewed purpose-specific
AccessibilityService declaration and genuine user activation, N6
caller identity/fencing and independent security approval. No
physical Android device, user setting, other-app data or
privileged capability is modified. Earlier Native Draft PR #39 and
concurrent Host worktrees are untouched.
