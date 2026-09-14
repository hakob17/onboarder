package com.onboarder.actions

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.components.service
import com.intellij.openapi.ui.Messages
import com.onboarder.OnboarderView
import com.onboarder.jsonQuote

/** Ask Onboarder to explain a flow or investigate an issue, in the chat panel. */
class AskAction : AnAction() {
    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val q = Messages.showInputDialog(
            project,
            "Ask Onboarder about this codebase — explain a flow, or report an issue to investigate:",
            "Ask Onboarder",
            null,
        )?.trim()
        if (q.isNullOrEmpty()) return
        val view = project.service<OnboarderView>()
        view.open { view.postToWebview("""{"command":"chat","question":${jsonQuote(q)}}""") }
    }
}
