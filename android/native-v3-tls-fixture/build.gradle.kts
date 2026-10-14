plugins {
    id("com.android.application") version "9.4.0"
}

android {
    namespace = "org.androidmcp.v3tlsfixture"
    compileSdk = 36
    defaultConfig {
        applicationId = "org.androidmcp.v3tlsfixture"
        minSdk = 30
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
}
