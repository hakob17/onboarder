plugins {
    kotlin("jvm") version "2.0.21"
    id("org.jetbrains.intellij.platform") version "2.1.0"
}

group = "com.onboarder"
version = "0.1.0"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        // Build against 2024.2 (JCEF APIs are identical/stable); the plugin declares
        // <depends>com.intellij.modules.jcef</depends> so its classloader resolves JCEF
        // on 2024.2 (core) and on 2024.3+/2026.2 (bundled jcef plugin) alike.
        intellijIdeaCommunity("2024.2.5")
        instrumentationTools()
    }
}

intellijPlatform {
    pluginConfiguration {
        id = "com.onboarder.intellij"
        name = "Onboarder"
        version = project.version.toString()
        ideaVersion {
            sinceBuild = "242"
            untilBuild = provider { null }  // no upper bound — load on 2024.2 and every newer build
        }
    }
}

kotlin {
    jvmToolchain(21)
}

// Skip the headless-IDE step that indexes searchable options — not needed and flaky.
tasks.named("buildSearchableOptions") { enabled = false }

// ---------------------------------------------------------------------------
// Bundle the self-contained analysis engine and the built web UI into the
// plugin as single archives, extracted at runtime (see OnboarderEngine.kt).
// Build them first:  backend/build_engine.sh  and  (cd frontend && npm run build)
// ---------------------------------------------------------------------------
val engineDist = layout.projectDirectory.dir("../backend/dist/onboarder-engine")
val webDist = layout.projectDirectory.dir("../frontend/dist")
val resGen = layout.buildDirectory.dir("generated-resources")

val bundleEngine by tasks.registering(Tar::class) {
    from(engineDist)
    into("onboarder-engine")
    compression = Compression.GZIP
    archiveFileName.set("onboarder-engine.tar.gz")
    destinationDirectory.set(resGen.map { it.dir("engine") })
    onlyIf { engineDist.asFile.exists() }
}

val bundleWeb by tasks.registering(Zip::class) {
    from(webDist)
    archiveFileName.set("onboarder-web.zip")
    destinationDirectory.set(resGen.map { it.dir("web") })
    onlyIf { webDist.asFile.exists() }
}

sourceSets {
    main {
        resources {
            srcDir(resGen)
        }
    }
}

tasks.processResources {
    dependsOn(bundleEngine, bundleWeb)
    doFirst {
        if (!engineDist.asFile.exists()) {
            logger.warn("Onboarder: engine build missing at $engineDist — run backend/build_engine.sh. " +
                "The plugin will build but can't start the local engine until it's bundled.")
        }
        if (!webDist.asFile.exists()) {
            logger.warn("Onboarder: web build missing at $webDist — run `npm run build` in frontend/.")
        }
    }
}
