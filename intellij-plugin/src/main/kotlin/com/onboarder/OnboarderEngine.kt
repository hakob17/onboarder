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

    private val home: Path = Paths.get(PathManager.getSystemPath(), "onboarder")
    private val engineDir: Path = home.resolve("engine")
    private val webDir: Path = home.resolve("web")
    private val dataDir: Path = home.resolve("data")

    private val exeName = if (isWindows()) "onboarder-engine.exe" else "onboarder-engine"
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
        // drain output to the log so a crash is diagnosable
        Thread({ proc.inputStream.bufferedReader().forEachLine { log.debug("[engine] $it") } },
            "onboarder-engine-log").apply { isDaemon = true; start() }

        val deadline = System.currentTimeMillis() + 30_000
        while (System.currentTimeMillis() < deadline) {
            if (!proc.isAlive) throw IllegalStateException("Onboarder engine exited (code ${proc.exitValue()})")
            if (health(base)) { baseUrlCache = base; return base }
            Thread.sleep(400)
        }
        proc.destroyForcibly()
        throw IllegalStateException("Onboarder engine did not become healthy within 30s")
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
        // in-place: send the path, not a zip
        postJson("$base/workspaces/$wsId/projects/local", """{"path":${quote(root)}}""")
        waitForAnalysis(base, wsId)
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

    private fun extractAssets() {
        if (!Files.exists(enginePath)) {
            val tar = Files.createTempFile("onboarder-engine", ".tar.gz")
            copyResource("/engine/onboarder-engine.tar.gz", tar)
            Files.createDirectories(engineDir)
            val r = ProcessBuilder("tar", "-xzf", tar.toString(), "-C", engineDir.toString())
                .redirectErrorStream(true).start()
            if (!r.waitFor(120, java.util.concurrent.TimeUnit.SECONDS) || r.exitValue() != 0) {
                throw IllegalStateException("Failed to extract bundled engine")
            }
            Files.deleteIfExists(tar)
            if (!isWindows()) enginePath.toFile().setExecutable(true)
            if (isMac()) runCatching {
                ProcessBuilder("xattr", "-dr", "com.apple.quarantine", engineDir.toString()).start().waitFor()
            }
        }
        if (!Files.exists(webDir.resolve("index.html"))) {
            runCatching { unzipResource("/web/onboarder-web.zip", webDir) }
                .onFailure { log.warn("Onboarder: no bundled web UI; the engine will serve API only", it) }
        }
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

    private fun waitForAnalysis(base: String, wsId: String) {
        val deadline = System.currentTimeMillis() + 180_000
        while (System.currentTimeMillis() < deadline) {
            val body = getBody("$base/workspaces/$wsId/projects") ?: return
            val arr = JsonParser.parseString(body).asJsonArray
            if (arr.size() == 0) { Thread.sleep(800); continue }
            val statuses = arr.map { it.asJsonObject["status"].asString }
            if (statuses.all { it == "ready" || it == "failed" }) return
            Thread.sleep(1000)
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

    private fun postJson(url: String, json: String): String {
        val req = HttpRequest.newBuilder(URI.create(url))
            .timeout(Duration.ofSeconds(30))
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
