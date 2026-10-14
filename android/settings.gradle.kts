pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "android-mcp-native"
include(":native-protocol")
include(":native-lifecycle")
include(":native-mcp-jvm")

// SDK-free JVM tests stay the default. Android app builds opt in explicitly.
if (providers.gradleProperty("enableAndroidApp").orNull == "true") {
    include(":app")
}

// Disposable E01 fixtures are independent opt-in APKs, never production app deps.
if (providers.gradleProperty("enableV3Fixtures").orNull == "true") {
    include(":native-v3-fixture")
    include(":native-v3-install-fixture")
}
