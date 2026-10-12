# N2.c — exact Android Activity Intent resolution **plan only**

**Status:** internal read-only Kotlin plan model and Android explicit-component
PackageManager adapter. No Android Activity is launched; no app task is
switched, no Intent is sent, no broadcast or service started, and no
permission, background-start exemption or new Manifest declaration is added.

## Exact scope and identity boundaries

The pure NativeIntentPlans normalizer accepts only a valid explicit
current-user package and a fully-qualified Activity class belonging to
that package, with exactly ACTION_MAIN and CATEGORY_LAUNCHER. The
component must appear in a local trusted allowlist and in the current
N2.a Android-filtered visible PackageManager subset, with matching,
enabled and exported ActivityInfo. No implicit Intent, VIEW/SEND,
broadcast, deep link, URI, selector, extras, flags, foreign user,
other-app private component, shell argument or unrestricted class name
is allowed. A non-exported or invisible target is never represented as
launchable. NameNotFoundException cannot distinguish hidden from absent.

The AndroidIntentPlanReader uses only ComponentName and
PackageManager.getActivityInfo with zero query flags. It applies the
syntactic, local allowlist and foreground-user-gesture gate *before*
calling PackageManager, then refreshes Android's visible subset and
resolves only that one exact component. Android exceptions are mapped
to fixed unavailable/not-visible states; no platform exception text
enters the plan. A second read-only probe interface makes the
preflight/denial behavior testable without Android hardware.

The produced version-1 plan describes a component, ACTION_MAIN, a
deterministic SHA-256 plan identity and requires_separate_user_grant=true.
The output always includes executed=false. Identical inputs produce an
identical plan; the plan identifier is a public-content checksum, not
a caller credential, Android IntentSender token or replayable grant.
There is deliberately no execute() or startActivity() capability.
Actual app launches would require a different expressly authorized
work package, Android's user-interaction rules and N6 pairing/lease
security. Neither localhost nor a model-supplied approved flag can
substitute for fresh genuine user action.

## Android versions and restrictions

API30/33/34/36 can create inert plans when all validation gates pass.
A background caller, missing explicit user gesture, unsupported API,
unknown current visibility, disabled or unexported target is denied.
No special background-launch exemption is attempted, and no Android
OS setting is modified.

## Executed tests and truthful claims

The six named T-N2C-01..06 Kotlin tests cover deterministic explicitly
allowlisted plans, implicit/non-exported/wrong-user denial, hostile URI,
extras, flags and selectors, API30/33/34/36 and background launch rules,
duplicate-plan idempotence without execution authorization, and absence
of Android side effects. The initial incomplete model produced five
meaningful RED assertion failures; the fixed pure model passed all six.
Supplemental Kotlin tests assert that mocked resolver calls never occur
for hostile/background requests and that platform exceptions are
redacted. Three independent Native Python source/Manifest tests assert
zero Activity/Intent launch APIs, a non-public adapter and no expanded
Android permissions. Real JVM, SDK36 compiled APK, Android Lint,
Host/Native local gates and the preverified four-API emulator matrix
are required before integration.

The existing emulator matrix validates continued public MCP status,
Activity/FGS, notification Stop, Home and notification revocation;
it does **not** prove an Android Intent was launched, because no
runtime launch functionality exists. No physical Android device or
user package list is changed. Self-review is not independent security
approval. Prior Native PR #39 and parallel Host worktrees remain
untouched.
