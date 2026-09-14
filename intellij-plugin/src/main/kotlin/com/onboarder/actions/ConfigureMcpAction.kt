package com.onboarder.actions

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.service
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.Task
import com.intellij.openapi.ui.Messages
import com.onboarder.OnboarderEngine
import com.onboarder.copyToClipboard
import com.onboarder.jsonQuote
import com.onboarder.notify

/**
 * Produce the MCP server configuration that connects the IDE's AI Assistant to Onboarder,
 * so it can query the code graph live. Ensures the project is analyzed first (so the config
 * can pin the workspace), then shows the JSON snippet and copies it to the clipboard.
 *
 * There's no stable public API to register an MCP server into AI Assistant programmatically,
 * so the user pastes this in Settings | Tools | AI Assistant | Model Context Protocol (MCP).
 */
class ConfigureMcpAction : AnAction() {
    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val engine = project.service<OnboarderEngine>()
        object : Task.Backgroundable(project, "Onboarder: preparing MCP configuration…", true) {
            override fun run(indicator: ProgressIndicator) {
                // Analyze first so the config pins this workspace (and the binary is extracted).
                runCatching { engine.ensureWorkspace() }
                val cmd = engine.mcpCommand()
                val env = engine.mcpEnv()
                val envJson = env.entries.joinToString(",\n      ") { "${jsonQuote(it.key)}: ${jsonQuote(it.value)}" }
                val argsJson = cmd.drop(1).joinToString(", ") { jsonQuote(it) }
                val snippet = """
                    {
                      "command": ${jsonQuote(cmd.first())},
                      "args": [$argsJson],
                      "env": {
                      $envJson
                      }
                    }
                """.trimIndent()
                ApplicationManager.getApplication().invokeLater {
                    copyToClipboard(snippet)
                    Messages.showMultilineInputDialog(
                        project,
                        "Add this Onboarder MCP server in:\n" +
                            "Settings | Tools | AI Assistant | Model Context Protocol (MCP) → Add.\n" +
                            "(Copied to your clipboard.)",
                        "Onboarder MCP Configuration",
                        snippet, null, null,
                    )
                    notify(project, "Onboarder MCP config copied. Add it in AI Assistant's MCP settings.")
                }
            }
        }.queue()
    }
}
