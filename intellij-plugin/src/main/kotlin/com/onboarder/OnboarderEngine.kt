package com.onboarder

import com.google.gson.JsonParser
import com.intellij.openapi.Disposable
import com.intellij.openapi.application.PathManager
import com.intellij.openapi.components.Service
import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.project.Project
import java.io.BufferedInputStream
import java.net.ServerSocket
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths
import java.time.Duration
import java.util.zip.ZipInputStream

/**
 * Owns the local Onboarder engine: extracts the bundled self-contained binary and
 * web UI, starts the engine as a background process (analyzing the project in place —
 * no upload), and exposes the base URL, the mapped workspace id, and the MCP command.
 */
@Service(Service.Level.PROJECT)
class OnboarderEngine(private val project: Project) : Disposable {
    private val log = thisLogger()
    private val http: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(3)).build()

    @Volatile private var process: Process? = null
    @Volatile private var baseUrlCache: String? = null
    @Volatile private var wsIdCache: String? = null
    private val engineOut = java.util.concurrent.ConcurrentLinkedDeque<String>()

    private val home: Path = Paths.get(PathManager.getSystemPath(), "onboarder")
    private val engineRoot: Path = home.resolve("engine")
    private val webRoot: Path = home.resolve("web")
    private val dataDir: Path = home.resolve("data")

    private val exeName = if (isWindows()) "onboarder-engine.exe" else "onboarder-engine"
    // Per-build engine + web dirs: a new plugin build hashes to a new folder, so a fresh
    // engine can never be shadowed by a stale copy, and two projects opening at once never
    // wipe/overwrite the files another is already serving.
    private val engineStamp: String by lazy { bundledEngineStamp() }
    private val engineDir: Path get() = engineRoot.resolve(engineStamp)
    private val webDir: Path get() = webRoot.resolve(engineStamp)
    private val enginePath: Path get() = engineDir.resolve("onboarder-engine").resolve(exeName)

    /** Ensure the engine process is up; returns its base URL. */
    @Synchronized
    fun ensureEngine(): String {
        baseUrlCache?.let { if (health(it)) return it }
        extractAssets()
        val port = freePort()
        val base = "http://127.0.0.1:$port"
        val pb = ProcessBuilder(enginePath.toString())
            .redirectErrorStream(true)
        pb.environment().apply {
            put("PORT", port.toString())
            put("HOST", "127.0.0.1")
            put("ONBOARDER_DATA_DIR", dataDir.toString())
            if (Files.exists(webDir)) put("ONBOARDER_STATIC_DIR", webDir.toString())
        }
        Files.createDirectories(dataDir)
        log.info("Onboarder: starting engine $enginePath on $base")
        val proc = pb.start()
        process = proc
        engineOut.clear()
        // drain output to the log AND a ring buffer, so a crash shows its cause
        Thread({
            proc.inputStream.bufferedReader().forEachLine {
                log.info("[engine] $it")
                engineOut.addLast(it)
                while (engineOut.size > 80) engineOut.pollFirst()
            }
        }, "onboarder-engine-log").apply { isDaemon = true; start() }

        val deadline = System.currentTimeMillis() + 90_000  // first run extracts + cold-boots
        while (System.currentTimeMillis() < deadline) {
            if (!proc.isAlive) {
                Thread.sleep(200)  // let the drain thread catch the crash output
                val tail = engineOut.toList().takeLast(25).joinToString("\n").ifBlank { "(engine produced no output)" }
                val code = proc.exitValue()
                // A crash with no output is almost always a bad/corrupt extraction — wipe this
                // build's engine dir so the next open re-extracts a clean copy (self-heal).
                if (code != 0 && engineOut.isEmpty()) {
                    log.warn("Onboarder: engine exited $code with no output — wiping $engineDir to re-extract")
                    runCatching { engineDir.toFile().deleteRecursively() }
                }
                throw IllegalStateException(
                    "Onboarder engine exited (code $code) at $enginePath\n--- engine output ---\n$tail")
            }
            if (health(base)) { baseUrlCache = base; return base }
            Thread.sleep(400)
        }
        proc.destroyForcibly()
        throw IllegalStateException("Onboarder engine did not become healthy within 90s")
    }

    /** Ensure the open project is analyzed in place; returns the workspace id. */
    @Synchronized
    fun ensureWorkspace(): String {
        val base = ensureEngine()
        val root = project.basePath ?: throw IllegalStateException("No project directory to analyze")
        wsIdCache?.let { return it }

        val name = project.name.ifBlank { Path.of(root).fileName.toString() }
        val created = postJson("$base/workspaces", """{"name":${quote(name)}}""")
        val wsId = JsonParser.parseString(created).asJsonObject["id"].asString
        // in-place: send the path, not a zip. Scanning a big folder for project roots
        // can take a little while, so give this call plenty of headroom.
        postJson("$base/workspaces/$wsId/projects/local", """{"path":${quote(root)}}""", timeoutSec = 120)
        waitForProjects(base, wsId)
        wsIdCache = wsId
        return wsId
    }

    /** URL to load in the JCEF browser: engine-served SPA, same-origin API, scoped to the workspace. */
    fun mapUrl(): String {
        val base = ensureEngine()
        val ws = ensureWorkspace()
        return "$base/?api=&ws=$ws"
    }

    /** The command + env an MCP client (JetBrains AI Assistant) should run to reach Onboarder. */
    fun mcpCommand(): List<String> = listOf(enginePath.toString(), "--mcp")

    fun mcpEnv(): Map<String, String> {
        val env = linkedMapOf("ONBOARDER_DATA_DIR" to dataDir.toString())
        wsIdCache?.let { env["ONBOARDER_WORKSPACE_ID"] = it }
        return env
    }

    fun enginePathString(): String = enginePath.toString()

    // ---- internals ----

    /** Move src into dst atomically; if dst already exists (another project won the race)
     *  that's fine, drop src. Falls back to a plain move if ATOMIC_MOVE is unsupported. */
    private fun publishDir(src: Path, dst: Path, exists: () -> Boolean) {
        try {
            Files.move(src, dst, java.nio.file.StandardCopyOption.ATOMIC_MOVE)
        } catch (e: Exception) {
            if (!exists()) runCatching { Files.move(src, dst) }
            if (!exists()) throw IllegalStateException("could not place $dst", e)
        } finally {
            runCatching { if (Files.exists(src)) src.toFile().deleteRecursively() }
        }
    }

    private fun extractAssets() {
        // Engine: per-build dir, extracted ATOMICALLY — unpack into a temp dir, then rename
        // it into place. Two projects opening at once can't see a half-written binary (which
        // is what made the engine exit 255), and a new build can't be shadowed by a stale one.
        if (!Files.exists(enginePath)) {
            Files.createDirectories(engineRoot)
            val tmp = Files.createTempDirectory(engineRoot, ".extract-")
            try {
                val tar = Files.createTempFile("onboarder-engine", ".tar.gz")
                copyResource("/engine/onboarder-engine.tar.gz", tar)
                val r = ProcessBuilder("tar", "-xzf", tar.toString(), "-C", tmp.toString())
                    .redirectErrorStream(true).start()
                if (!r.waitFor(180, java.util.concurrent.TimeUnit.SECONDS) || r.exitValue() != 0) {
                    throw IllegalStateException("Failed to extract bundled engine")
                }
                Files.deleteIfExists(tar)
                val tmpExe = tmp.resolve("onboarder-engine").resolve(exeName)
                if (!isWindows()) tmpExe.toFile().setExecutable(true)
                if (isMac()) runCatching {
                    ProcessBuilder("xattr", "-dr", "com.apple.quarantine", tmp.toString()).start().waitFor()
                }
                publishDir(tmp, engineDir) { Files.exists(enginePath) }
            } finally {
                runCatching { if (Files.exists(tmp)) tmp.toFile().deleteRecursively() }
            }
        }
        // Web UI: per-build dir, also published atomically (so a concurrent project never
        // wipes the copy another is serving).
        if (!Files.exists(webDir.resolve("index.html"))) {
            Files.createDirectories(webRoot)
            val tmp = Files.createTempDirectory(webRoot, ".web-")
            try {
                unzipResource("/web/onboarder-web.zip", tmp)
                publishDir(tmp, webDir) { Files.exists(webDir.resolve("index.html")) }
            } catch (e: Exception) {
                log.warn("Onboarder: no bundled web UI; the engine will serve API only", e)
            } finally {
                runCatching { if (Files.exists(tmp)) tmp.toFile().deleteRecursively() }
            }
        }
        // Prune dirs from older builds (best-effort).
        for (rootDir in listOf(engineRoot, webRoot)) runCatching {
            if (Files.isDirectory(rootDir)) Files.list(rootDir).use { s ->
                s.filter { it.fileName.toString() != engineStamp && !it.fileName.toString().startsWith(".") }
                    .forEach { old -> runCatching { old.toFile().deleteRecursively() } }
            }
        }
    }

    /** Short hash of the bundled engine archive, so a new build forces a fresh extract. */
    private fun bundledEngineStamp(): String {
        val md = java.security.MessageDigest.getInstance("SHA-256")
        javaClass.getResourceAsStream("/engine/onboarder-engine.tar.gz")?.use { s ->
            val buf = ByteArray(1 shl 16)
            while (true) { val n = s.read(buf); if (n < 0) break; md.update(buf, 0, n) }
        } ?: return "none"
        return md.digest().joinToString("") { "%02x".format(it) }.take(16)
    }

    private fun copyResource(name: String, dest: Path) {
        val stream = javaClass.getResourceAsStream(name)
            ?: throw IllegalStateException("bundled resource missing: $name (build the engine before packaging)")
        stream.use { Files.copy(it, dest, java.nio.file.StandardCopyOption.REPLACE_EXISTING) }
    }

    private fun unzipResource(name: String, destDir: Path) {
        val stream = javaClass.getResourceAsStream(name) ?: throw IllegalStateException("resource missing: $name")
        Files.createDirectories(destDir)
        ZipInputStream(BufferedInputStream(stream)).use { zip ->
            var entry = zip.nextEntry
            while (entry != null) {
                val target = destDir.resolve(entry.name).normalize()
                require(target.startsWith(destDir)) { "zip slip: ${entry.name}" }
                if (entry.isDirectory) {
                    Files.createDirectories(target)
                } else {
                    Files.createDirectories(target.parent)
                    Files.newOutputStream(target).use { zip.copyTo(it) }
                }
                entry = zip.nextEntry
            }
        }
    }

    /**
     * Open the UI as soon as the projects are registered, not when analysis finishes.
     * The web overview lists every repo and streams each one's progress live (SSE), so a
     * folder of large repos no longer sits on a blank tool window up to the old 180s limit.
     */
    private fun waitForProjects(base: String, wsId: String) {
        val deadline = System.currentTimeMillis() + 60_000
        while (System.currentTimeMillis() < deadline) {
            val body = getBody("$base/workspaces/$wsId/projects") ?: return
            val arr = JsonParser.parseString(body).asJsonArray
            if (arr.size() > 0) return
            Thread.sleep(300)
        }
    }

    private fun health(base: String): Boolean = runCatching {
        val req = HttpRequest.newBuilder(URI.create("$base/health"))
            .timeout(Duration.ofSeconds(2)).GET().build()
        http.send(req, HttpResponse.BodyHandlers.discarding()).statusCode() == 200
    }.getOrDefault(false)

    private fun getBody(url: String): String? = runCatching {
        val req = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(10)).GET().build()
        val res = http.send(req, HttpResponse.BodyHandlers.ofString())
        if (res.statusCode() in 200..299) res.body() else null
    }.getOrNull()

    private fun postJson(url: String, json: String, timeoutSec: Long = 30): String {
        val req = HttpRequest.newBuilder(URI.create(url))
            .timeout(Duration.ofSeconds(timeoutSec))
            .header("content-type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(json)).build()
        val res = http.send(req, HttpResponse.BodyHandlers.ofString())
        check(res.statusCode() in 200..299) { "POST $url -> ${res.statusCode()}: ${res.body()}" }
        return res.body()
    }

    override fun dispose() {
        process?.destroyForcibly()
        process = null
    }

    private companion object {
        fun freePort(): Int = ServerSocket(0).use { it.localPort }
        fun quote(s: String): String = "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
        fun isWindows() = System.getProperty("os.name").lowercase().contains("win")
        fun isMac() = System.getProperty("os.name").lowercase().contains("mac")
    }
}
