// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

plugins {
    // lets Gradle auto-download the JDK the IntelliJ Platform plugin pins
    // (platform 2024.2 -> Java 21) when it is not installed locally
    id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0"
}

rootProject.name = "ord-jetbrains"
