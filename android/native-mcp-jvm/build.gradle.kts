plugins {
    id("org.jetbrains.kotlin.jvm") version "2.3.21"
    application
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation(project(":native-protocol"))
    implementation("io.modelcontextprotocol:kotlin-sdk-server:0.14.0")
    implementation("io.ktor:ktor-server-cio-jvm:3.4.3")
    testImplementation(kotlin("test"))
    testImplementation("org.junit.jupiter:junit-jupiter:5.13.4")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher:1.13.4")
}

application {
    mainClass.set("org.androidmcp.prototype.MainKt")
}

tasks.test {
    useJUnitPlatform()
}
