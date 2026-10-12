plugins {
    // AGP 9.4 provides built-in Kotlin support.
    id("com.android.application") version "9.4.0"
}

android {
    namespace = "org.androidmcp.nativeapp"
    compileSdk = 36

    defaultConfig {
        applicationId = "org.androidmcp.nativeapp"
        minSdk = 30
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation(project(":native-protocol"))
    implementation(project(":native-lifecycle"))
    implementation("io.modelcontextprotocol:kotlin-sdk-server:0.14.0")
    implementation("io.ktor:ktor-server-cio-jvm:3.4.3")
}
