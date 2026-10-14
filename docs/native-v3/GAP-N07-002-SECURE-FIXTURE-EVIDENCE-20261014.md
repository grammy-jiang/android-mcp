# GAP-N07-002 — Secure-window and synthetic password fixture coverage

**Date:** 2026-10-14. **Engineering result:** signed fixture enhancement
tested on Android API 30, 33, 34 and 36. **Product result:** NOT_DONE.

The fixture now exposes a non-exported `SecureFixtureActivity` reachable
only through its own visible user-interface button. The Activity sets
Android `WindowManager.LayoutParams.FLAG_SECURE` before showing any content,
uses a true Android password-variant `EditText`, and paints an unmistakable
fixed magenta surface as a synthetic protected-pixel oracle. The marker
is not user data and is generated inside the separate signed fixture APK.

## Behavior-first evidence

On an exclusively owned disposable API36 AVD, new real AndroidJUnitRunner
tests first **failed behaviorally** after successful compilation because
the absent FLAG_SECURE exposed the protected marker in an actual OS
UiAutomation screenshot. After adding the OS window flag and a
password-type EditText, AndroidJUnitRunner passed all 12 tests. The
three new tests independently assert non-exported Activity metadata,
password node classification/window flags, and protected pixels
appearing in the fixture's own Canvas but not in Android OS capture.

The existing `scripts/check-native-v3-fixtures.sh --matrix` then
installed the new signed APK and instrumentation APK, executed
**12/12 tests on each of API30/33/34/36** (48 actual on-device
fixture tests), and confirmed the existing external UI touch counter,
process restart persistence, SAF direct-read refusal, normal known
pixel screenshot, APK identity and debug signer.

## Independently inspected OS state and limitations

On API36 the exclusively owned AVD `emulator-5562` showed:
a true resumed private SecureFixtureActivity after tapping the
fixture's visible navigation control; an external Android system
screenshot returned black rather than the fixture's magenta pixels;
external UI inspection did not reveal the fixed synthetic marker
string; backing out returned to the normal fixture Activity.
This is independent **fixture** evidence, not a Native MCP-mediated
MediaProjection screenshot or Accessibility gesture.

The external secure-window oracle is not yet a repeatable automated
independent four-version gate; the AndroidJUnitRunner OS screenshot
and Android framework metadata checks do run on all four versions.
The OS may withhold a secure-window root entirely from UiAutomation,
so a null root cannot be treated as positive independent semantic
Accessibility-tree proof. Do not claim screenshot masking alone
means a production Native AccessibilityService safely refuses a
password-bearing third-party window.

## Exact artifacts of this incremental source

- Signed synthetic fixture APK SHA-256:
  `7d7ece841b17e9acae43251baae0bfb811dbcf1e7f7913fdb99e9173a3522e6d`
- AndroidJUnitRunner fixture APK SHA-256:
  `2ac48454bfcc9afc47d42169bfd5e544f013c54cb65b72ec10cc2cf1b63631a9`
- All four API levels: 12 actual instrumentation tests per version passed.
- The real Native MCP product can still expose only its existing
  `device_status` endpoint; 0 N07/N08/N09 production positive cases
  are credited from test-fixture work.

**GAP-N07-002 remains OPEN** until the independent secure/password UI
accessibility tree privacy oracle and actual Native Accessibility
inspection/gesture refusal can be observed through authenticated
Native MCP on API30/33/34/36, alongside real Stop, process-death,
permission revocation and cross-app fixture tests. Corresponding
N09 MediaProjection secure pixel tests are also not certified.

Do not convert this technical infrastructure improvement into a
review sign-off, OS permission bypass or product completion tick.
