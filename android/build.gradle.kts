// Kotlin JVM plugins are declared in their modules so that AGP 9.4
// built-in Kotlin does not inherit incompatible Kotlin Android plugin classes.

// Record and enforce resolved versions for each Kotlin/Android module.
// Generated lockfiles are committed and reviewed with dependency updates.
subprojects {
    dependencyLocking {
        lockAllConfigurations()
    }
}
