package com.onboarder.actions

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.components.service
import com.intellij.openapi.ui.Messages
import com.onboarder.OnboarderView
import com.onboarder.jsonQuote

/** Analyze a Jira/ADO ticket (or pasted text) and stream an evidence-grounded fix suggestion. */
class AnalyzeTicketAction : AnAction() {
    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val options = arrayOf("Paste ticket text", "Jira issue", "Azure DevOps work item")
        val choice = Messages.showChooseDialog(
            project, "Analyze a ticket from:", "Onboarder", null, options, options[0],
        )
        if (choice < 0) return

        val json: String = when (choice) {
            0 -> {
                val body = Messages.showMultilineInputDialog(
                    project, "Paste the ticket description / repro steps:", "Onboarder", "", null, null,
                )?.trim().orEmpty()
                if (body.isEmpty()) return
                """{"command":"analyzeTicket","source":"manual","key":"ticket","title":"","body":${jsonQuote(body)}}"""
            }
            else -> {
                val source = if (choice == 1) "jira" else "ado"
                val prompt = if (source == "jira") "Jira issue key (e.g. PROJ-123):" else "Work item id (e.g. 1234):"
                val key = Messages.showInputDialog(project, prompt, "Onboarder", null)?.trim().orEmpty()
                if (key.isEmpty()) return
                """{"command":"analyzeTicket","source":"$source","key":${jsonQuote(key)},"title":"","body":""}"""
            }
        }
        val view = project.service<OnboarderView>()
        view.open { view.postToWebview(json) }
    }
}
