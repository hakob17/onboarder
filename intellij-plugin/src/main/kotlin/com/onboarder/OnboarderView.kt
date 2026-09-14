package com.onboarder

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.Service
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindowManager
import com.intellij.ui.jcef.JBCefBrowser

/** Project-level holder for the Onboarder tool-window browser, so actions can drive it. */
@Service(Service.Level.PROJECT)
class OnboarderView(private val project: Project) {
    @Volatile var browser: JBCefBrowser? = null

    /** Open the Onboarder tool window, then run [after] on the EDT once it's shown. */
    fun open(after: () -> Unit = {}) {
        val tw = ToolWindowManager.getInstance(project).getToolWindow("Onboarder") ?: return
        tw.activate({ ApplicationManager.getApplication().invokeLater(after) }, true)
    }

    /** Deliver a message to the SPA exactly like a VS Code webview postMessage. [json] must be a JSON object. */
    fun postToWebview(json: String) {
        val b = browser ?: return
        val cef = b.cefBrowser
        cef.executeJavaScript(
            "window.dispatchEvent(new MessageEvent('message',{data:$json}));",
            cef.url, 0,
        )
    }
}
