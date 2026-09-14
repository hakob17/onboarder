package com.onboarder

import com.google.gson.JsonParser
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.service
import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.vfs.LocalFileSystem
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.jcef.JBCefApp
import com.intellij.ui.jcef.JBCefBrowser
import com.intellij.ui.jcef.JBCefJSQuery
import org.cef.browser.CefBrowser
import org.cef.browser.CefFrame
import org.cef.handler.CefLoadHandlerAdapter
import java.nio.file.Files
import java.nio.file.Paths
import java.util.Base64
import javax.swing.JLabel
import javax.swing.JPanel
import java.awt.BorderLayout

class OnboarderToolWindowFactory : ToolWindowFactory {
    private val log = thisLogger()

    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val contentFactory = com.intellij.ui.content.ContentFactory.getInstance()
        if (!JBCefApp.isSupported()) {
            val panel = JPanel(BorderLayout()).apply {
                add(JLabel("<html>Onboarder needs the embedded browser (JCEF), which isn't available " +
                    "in this IDE. Use the web app instead.</html>"), BorderLayout.CENTER)
            }
            toolWindow.contentManager.addContent(contentFactory.createContent(panel, "", false))
            return
        }

        val browser = JBCefBrowser()
        project.service<OnboarderView>().browser = browser
        com.intellij.openapi.util.Disposer.register(toolWindow.disposable, browser)

        installBridge(project, browser)

        toolWindow.contentManager.addContent(
            contentFactory.createContent(browser.component, "", false),
        )

        // Analysis can take a while — do it off the EDT, then load the map.
        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Onboarder: analyzing project…", true) {
            override fun run(indicator: ProgressIndicator) {
                try {
                    val url = project.service<OnboarderEngine>().mapUrl()
                    ApplicationManager.getApplication().invokeLater { browser.loadURL(url) }
                } catch (e: Exception) {
                    log.warn("Onboarder: failed to start", e)
                    ApplicationManager.getApplication().invokeLater {
                        browser.loadHTML("<html><body style='font-family:sans-serif;padding:24px'>" +
                            "<h3>Onboarder couldn't start the local engine</h3><pre>" +
                            (e.message ?: "unknown error").take(400) + "</pre></body></html>")
                    }
                }
            }
        })
    }

    /**
     * Make the JCEF frame look like a VS Code webview so the existing SPA bridge works
     * unchanged: define window.acquireVsCodeApi so host.postMessage(...) routes here.
     */
    private fun installBridge(project: Project, browser: JBCefBrowser) {
        val query = JBCefJSQuery.create(browser as com.intellij.ui.jcef.JBCefBrowserBase)
        query.addHandler { raw ->
            handleHostMessage(project, raw)
            null
        }
        val shim = """
            (function(){
              if (window.acquireVsCodeApi) return;
              var post = function(msg){ ${query.inject("JSON.stringify(msg)")} };
              window.acquireVsCodeApi = function(){ return { postMessage: post, getState:function(){}, setState:function(){} }; };
            })();
        """.trimIndent()
        browser.jbCefClient.addLoadHandler(object : CefLoadHandlerAdapter() {
            override fun onLoadStart(b: CefBrowser?, frame: CefFrame?, transitionType: org.cef.network.CefRequest.TransitionType?) {
                b?.executeJavaScript(shim, b.url, 0)
            }
        }, browser.cefBrowser)
    }

    private fun handleHostMessage(project: Project, raw: String) {
        val msg = runCatching { JsonParser.parseString(raw).asJsonObject }.getOrNull() ?: return
        when (msg.get("command")?.asString) {
            "openFile" -> {
                val file = msg.get("file")?.asString ?: return
                val line = msg.get("line")?.asInt ?: 1
                openInEditor(project, file, line)
            }
            "saveFile" -> {
                val name = msg.get("name")?.asString ?: "onboarder-export"
                val data = msg.get("data")?.asString ?: return
                val kind = msg.get("kind")?.asString ?: "text"
                saveArtifact(project, name, data, kind)
            }
            // select/chat/diff/refresh are host->webview; nothing to do here.
        }
    }

    private fun openInEditor(project: Project, relPath: String, line: Int) {
        val base = project.basePath ?: return
        val abs = Paths.get(base).resolve(relPath).normalize()
        ApplicationManager.getApplication().invokeLater {
            val vf = LocalFileSystem.getInstance().refreshAndFindFileByNioFile(abs) ?: run {
                Messages.showWarningDialog(project, "File not found: $abs", "Onboarder")
                return@invokeLater
            }
            FileEditorManager.getInstance(project)
                .openTextEditor(OpenFileDescriptor(project, vf, (line - 1).coerceAtLeast(0), 0), true)
        }
    }

    private fun saveArtifact(project: Project, name: String, data: String, kind: String) {
        ApplicationManager.getApplication().invokeLater {
            val descriptor = com.intellij.openapi.fileChooser.FileSaverDescriptor("Save Onboarder Export", "")
            val dialog = com.intellij.openapi.fileChooser.FileChooserFactory.getInstance()
                .createSaveFileDialog(descriptor, project)
            val wrapper = dialog.save(null as com.intellij.openapi.vfs.VirtualFile?, name) ?: return@invokeLater
            val bytes = if (kind == "dataurl") {
                Base64.getDecoder().decode(data.substringAfter(","))
            } else data.toByteArray(Charsets.UTF_8)
            Files.write(wrapper.file.toPath(), bytes)
        }
    }
}
