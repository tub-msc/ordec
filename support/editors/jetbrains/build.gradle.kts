// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import org.jetbrains.intellij.platform.gradle.TestFrameworkType

plugins {
    id("java")
    id("org.jetbrains.intellij.platform") version "2.18.1"
}

group = "org.ordec"
version = "0.1.0"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        // PyCharm Community as build target: the ORD dialect builds on its
        // bundled Python support (PythonCore). useInstaller = false
        // resolves the IDE from the IntelliJ Maven repository, since the
        // installer endpoint no longer serves pre-unification PyCharm
        // Community versions.
        pycharmCommunity("2024.2.4") {
            useInstaller = false
        }
        bundledPlugin("PythonCore")
        testFramework(TestFrameworkType.Platform)
    }
    testImplementation("junit:junit:4.13.2")
    // the platform test framework references opentest4j but does not carry
    // it, a documented IntelliJ Platform Gradle Plugin gotcha
    testImplementation("org.opentest4j:opentest4j:1.3.0")
}

intellijPlatform {
    // no settings UI in this plugin, skip the headless-IDE indexing phase
    buildSearchableOptions = false

    pluginConfiguration {
        ideaVersion {
            sinceBuild = "242"
            untilBuild = provider { null }
        }
    }
}
