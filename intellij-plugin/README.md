# Onboarder — IntelliJ / JetBrains plugin

An IntelliJ Platform plugin that brings Onboarder into JetBrains IDEs (IntelliJ IDEA,
PyCharm, GoLand, WebStorm, …): an interactive architecture map of the open project, AI
summaries, investigation chat, and Jira/ADO ticket → fix suggestions — plus a connection
to the IDE's own AI tools.

## How it works

- **Local, in place, zero-setup.** The plugin ships the same self-contained analysis
  engine as the VS Code extension. On first use it extracts and starts it as a background
  process and points an embedded browser (JCEF) at it. Your code is read directly off disk —
  no upload, no Python, no server to run.
- **Same UI.** The tool window hosts the built Onboarder web app; a small shim makes the
  JCEF frame present the same message bridge as the VS Code webview, so `Open in editor`,
  save/export, chat, and ticket analysis all work through the IDE.
- **Connected to the IDE's AI — two ways:**
  1. **MCP server** (*Tools → Onboarder → Configure MCP Server for AI Assistant*). Onboarder
     runs as an MCP server (`onboarder-engine --mcp`) exposing `onboarder_overview`,
     `onboarder_find_nodes`, `onboarder_trace_flow`, `onboarder_get_node`,
     `onboarder_read_source`, `onboarder_search_code`. Add the generated config in
     **Settings | Tools | AI Assistant | Model Context Protocol (MCP)** and the assistant can
     query the real architecture and cite `file:line` evidence. The same server works with
     Claude Code, Cursor, and any MCP client.
  2. **Prompt hand-off** (*Tools → Onboarder → Send Architecture Context to AI*). Copies a
     ready, tool-aware prompt and opens the AI tool window (there is no public API to inject a
     prompt directly, so you paste it).

## Actions (Tools → Onboarder)

| Action | What it does |
|---|---|
| **Map This Project** | Analyze the open project and open the map tool window |
| **Ask About This Codebase** | Explain a flow / investigate an issue in the chat |
| **Analyze a Ticket (Jira / ADO)** | Evidence-grounded fix suggestion for a ticket |
| **Send Architecture Context to AI** | Copy a grounded prompt + open the AI chat |
| **Configure MCP Server for AI Assistant** | Generate the MCP config for AI Assistant |

## Build

The plugin bundles the engine and web UI as archives, so build those first:

```sh
# 1. the self-contained engine for your OS/arch  (→ backend/dist/onboarder-engine)
cd backend && ./build_engine.sh

# 2. the web UI  (→ frontend/dist)
cd ../frontend && npm install && npm run build

# 3. the plugin  (bundles both, → build/distributions/onboarder-intellij-<ver>.zip)
cd ../intellij-plugin
#    Open this folder in IntelliJ IDEA (it provisions Gradle 8.10 from
#    gradle/wrapper/gradle-wrapper.properties), or use a local Gradle 8.10+:
gradle buildPlugin        # or ./gradlew buildPlugin once the wrapper jar exists
```

Run it in a sandbox IDE with `gradle runIde`. Install the built ZIP via
**Settings | Plugins | ⚙ | Install Plugin from Disk…**

> No `gradlew` jar is committed. Opening the project in IntelliJ generates the wrapper
> automatically; from the CLI, run `gradle wrapper` once (needs a local Gradle) or use your
> system Gradle directly.

> The bundled engine is platform-specific (built by `build_engine.sh` on your machine).
> Ship a plugin built on the same OS/arch you install on, or set `onboarder.backendUrl`-style
> configuration to point at a hosted engine (roadmap).

## Requirements

- IntelliJ Platform 2024.2+ (JCEF-enabled; standard on IntelliJ IDEA and most JetBrains IDEs)
- JBR with JCEF (the default runtime)
