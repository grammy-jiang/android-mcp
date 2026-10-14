plugins {
    id("com.android.application") version "9.4.0"
}
android {
    namespace = "org.androidmcp.v3installfixture"
    compileSdk = 36
    defaultConfig {
        applicationId = "org.androidmcp.v3installfixture"
        minSdk = 30
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
