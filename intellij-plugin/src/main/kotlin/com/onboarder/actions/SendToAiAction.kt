package com.onboarder.actions

import com.intellij.notification.NotificationType
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.wm.ToolWindowManager
import com.onboarder.copyToClipboard
import com.onboarder.notify

/**
 * Hand off Onboarder's architecture context to the IDE's AI. There is no public API to
 * inject a prompt into JetBrains AI Assistant / Copilot, so this copies a ready prompt to
 * the clipboard and opens the AI tool window for you to paste — and nudges the assistant to
 * use the Onboarder MCP tools for live, grounded answers.
 */
class SendToAiAction : AnAction() {
    private val aiToolWindowIds = listOf("AIAssistant", "AI Assistant", "Copilot Chat", "GitHub Copilot Chat")

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val prompt = """
            Use the Onboarder MCP server (tools prefixed `onboarder_`) to answer questions about THIS
            project's architecture, grounded in the real code:
            - onboarder_overview — projects, endpoints, and layer counts (start here)
            - onboarder_find_nodes / onboarder_search_code — locate endpoints, services, tables
            - onboarder_trace_flow — follow a request endpoint → service → repository → table
            - onboarder_get_node — a node's edges and file:line evidence
            - onboarder_read_source — read the exact lines behind a node

            Always cite the file:line evidence the tools return, and prefer them over guessing.
            My question:
        """.trimIndent()
        copyToClipboard(prompt)

        val tw = aiToolWindowIds.firstNotNullOfOrNull { ToolWindowManager.getInstance(project).getToolWindow(it) }
        if (tw != null) {
            tw.activate(null, true)
            notify(project, "Onboarder context copied — paste it into the AI chat, then ask your question.")
        } else {
            notify(
                project,
                "Onboarder context copied to the clipboard. Open your AI assistant's chat and paste it. " +
                    "Tip: run “Configure MCP Server for AI Assistant” so the assistant can call Onboarder directly.",
                NotificationType.INFORMATION,
            )
        }
    }
}
