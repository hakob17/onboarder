package com.onboarder.actions

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.components.service
import com.onboarder.OnboarderView

/** Open the Onboarder tool window, which analyzes the project in place and renders the map. */
class MapAction : AnAction() {
    override fun actionPerformed(e: AnActionEvent) {
        e.project?.service<OnboarderView>()?.open()
    }
}
