import * as cp from "child_process";
import * as crypto from "crypto";
import * as fs from "fs";
import * as net from "net";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

interface Backend {
  baseUrl: string;
  proc?: cp.ChildProcess;
  mode: "local" | "remote";
}

const ZIP_SKIP_DIRS = [
  "node_modules", ".git", "dist", "build", ".venv", "venv", "target", "out",
  ".next", ".nuxt", "coverage", "__pycache__", ".gradle", "Pods", ".dart_tool",
  ".idea", ".vscode",
];

interface ProjectInfo {
  id: string;
  name: string;
  status: string;
  root_path: string;
}

interface GraphNode {
  id: string;
  project_id: string;
  kind: string;
  name: string;
  file?: string;
  line_start?: number;
}

interface GraphEdge {
  src: string;
  dst: string;
  kind: string;
}

// Hosted fallback (zero-config) backend: the Railway deploy. Used only when the
// bundled local engine can't run; it uploads the open folder for analysis (a
// remote backend can't read the dev's disk). Files still open locally.
const DEFAULT_BACKEND_URL = "https://onboarder-production.up.railway.app";

// Bundled, self-contained analysis engine: a PyInstaller binary downloaded once
// from the GitHub release and launched locally, so analysis runs in place against
// the open folder with no upload and no Python on the user's machine.
const ENGINE_VERSION = "0.11.0";
const ENGINE_REPO = "hakob17/onboarder";
const ENGINE_TAG = `engine-v${ENGINE_VERSION}`;

let backend: Backend | null = null;
let panel: vscode.WebviewPanel | null = null;
let output: vscode.OutputChannel;
let currentWsId: string | null = null;
const projectRoots = new Map<string, string>();

function cfg() {
  return vscode.workspace.getConfiguration("onboarder");
}

function repoDefault(context: vscode.ExtensionContext, segment: string): string {
  return path.resolve(context.extensionPath, "..", segment);
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.listen(0, "127.0.0.1", () => {
      const port = (srv.address() as net.AddressInfo).port;
      srv.close(() => resolve(port));
    });
    srv.on("error", reject);
  });
}

async function healthy(baseUrl: string): Promise<boolean> {
  try {
    const r = await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(1500) });
    return r.ok;
  } catch {
    return false;
  }
}

async function api<T>(base: string, route: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${base}${route}`, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = ((await r.json()) as { detail?: string }).detail ?? detail;
    } catch { /* not json */ }
    throw new Error(detail);
  }
  return (await r.json()) as T;
}

function isLoopback(url: string): boolean {
  return /\/\/(127\.0\.0\.1|localhost|\[::1\])(:|\/|$)/.test(url);
}

function engineExe(dir: string): string {
  const name = process.platform === "win32" ? "onboarder-engine.exe" : "onboarder-engine";
  return path.join(dir, "onboarder-engine", name);
}

function ensureExecutable(base: string): void {
  try { fs.chmodSync(engineExe(base), 0o755); } catch { /* best effort */ }
  if (process.platform === "darwin") {
    try { cp.execFileSync("xattr", ["-dr", "com.apple.quarantine", path.join(base, "onboarder-engine")]); }
    catch { /* not quarantined */ }
  }
}

/**
 * Path to the local engine executable. Resolution order:
 *   1. onboarder.enginePath (explicit, for dev/offline)
 *   2. already-prepared copy in globalStorage
 *   3. the engine bundled inside the .vsix (media/engine) — copied to globalStorage
 *   4. download from the GitHub release (only works if the release asset is public)
 * The runtime copy always lives in globalStorage so it is writable / chmod-able even
 * when the extension dir or .vsix-packed perms are not.
 */
async function resolveEngine(context: vscode.ExtensionContext): Promise<string> {
  const explicit = cfg().get<string>("enginePath");
  if (explicit) {
    if (fs.existsSync(explicit) && fs.statSync(explicit).isFile()) return explicit;
    const inner = engineExe(explicit);
    if (fs.existsSync(inner)) return inner;
    throw new Error(`onboarder.enginePath is set but no engine was found at ${explicit}`);
  }

  const asset = `onboarder-engine-${process.platform}-${process.arch}.tar.gz`;
  const base = path.join(context.globalStorageUri.fsPath, "engine", ENGINE_VERSION,
    `${process.platform}-${process.arch}`);
  const exe = engineExe(base);
  if (fs.existsSync(exe)) { ensureExecutable(base); return exe; }
  await fs.promises.mkdir(base, { recursive: true });

  // Engine .tar.gz shipped inside the .vsix — extract it into the writable cache.
  const bundledTar = path.join(context.extensionPath, "media", "engine", asset);
  if (fs.existsSync(bundledTar)) {
    await extractTar(bundledTar, base);
    if (fs.existsSync(exe)) { ensureExecutable(base); return exe; }
  }

  // Fallback: download from the release (public assets only).
  const url = `https://github.com/${ENGINE_REPO}/releases/download/${ENGINE_TAG}/${asset}`;
  const tmp = path.join(base, asset);
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "Onboarder: downloading the local analysis engine (one-time)…" },
    async () => {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`engine download failed: HTTP ${r.status} (${asset})`);
      await fs.promises.writeFile(tmp, Buffer.from(await r.arrayBuffer()));
    });
  await extractTar(tmp, base);
  await fs.promises.unlink(tmp).catch(() => undefined);
  if (!fs.existsSync(exe)) throw new Error("engine binary missing after extraction");
  ensureExecutable(base);
  return exe;
}

function extractTar(tarPath: string, destDir: string): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const p = cp.spawn("tar", ["-xzf", tarPath, "-C", destDir]);
    p.on("error", reject);
    p.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`tar exited with ${code}`))));
  });
}

/** Spawn a local backend process and wait for /health. */
async function spawnBackend(context: vscode.ExtensionContext, proc: cp.ChildProcess, port: number, label: string): Promise<Backend> {
  proc.stdout?.on("data", (d) => output.append(d.toString()));
  proc.stderr?.on("data", (d) => output.append(d.toString()));
  proc.on("exit", (code) => {
    output.appendLine(`[onboarder] ${label} exited (${code})`);
    if (backend?.proc === proc) backend = null;
  });
  context.subscriptions.push({ dispose: () => proc.kill() });

  const baseUrl = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    if (await healthy(baseUrl)) {
      backend = { baseUrl, proc, mode: "local" };
      return backend;
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  proc.kill();
  output.show(true);
  throw new Error(`Onboarder ${label} did not become healthy within 30s — see the Onboarder output channel`);
}

async function spawnEngine(context: vscode.ExtensionContext): Promise<Backend> {
  const exe = await resolveEngine(context);
  const port = await freePort();
  const dataDir = path.join(context.globalStorageUri.fsPath, "data");
  fs.mkdirSync(dataDir, { recursive: true });
  output.appendLine(`[onboarder] starting bundled engine: ${exe} (port ${port}, data ${dataDir})`);
  const proc = cp.spawn(exe, [], {
    env: { ...process.env, PORT: String(port), HOST: "127.0.0.1", ONBOARDER_DATA_DIR: dataDir },
  });
  return spawnBackend(context, proc, port, "engine");
}

async function spawnPythonBackend(context: vscode.ExtensionContext): Promise<Backend> {
  const backendPath = cfg().get<string>("backendPath") || repoDefault(context, "backend");
  if (!fs.existsSync(path.join(backendPath, "pyproject.toml"))) {
    throw new Error("onboarder.engineMode is \"python-dev\" but no backend was found — set onboarder.backendPath to a clone of the Onboarder backend.");
  }
  const port = await freePort();
  const command = (cfg().get<string>("startCommand") || "uv run uvicorn app.main:app --port ${port}")
    .replace("${port}", String(port));
  const [bin, ...args] = command.split(/\s+/);
  output.appendLine(`[onboarder] starting python backend: ${command} (cwd ${backendPath})`);
  const proc = cp.spawn(bin, args, { cwd: backendPath, env: { ...process.env } });
  return spawnBackend(context, proc, port, "python backend");
}

async function ensureBackend(context: vscode.ExtensionContext): Promise<Backend> {
  if (backend && (await healthy(backend.baseUrl))) {
    return backend;
  }

  // 1. Explicit URL override (local sidecar or any hosted backend).
  const url = (cfg().get<string>("backendUrl") || "").replace(/\/$/, "");
  if (url) {
    if (!(await healthy(url))) {
      throw new Error(`Onboarder backend at ${url} is not responding (/health failed)`);
    }
    backend = { baseUrl: url, mode: isLoopback(url) ? "local" : "remote" };
    return backend;
  }

  const mode = cfg().get<string>("engineMode") || "bundled";

  // 2. Developer mode: spawn the Python backend via uv.
  if (mode === "python-dev") {
    return spawnPythonBackend(context);
  }

  // 3. Default: the bundled local engine (in-place, no upload). Fall back to hosted on failure.
  if (mode === "bundled") {
    try {
      return await spawnEngine(context);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      output.appendLine(`[onboarder] bundled engine unavailable: ${msg}`);
      vscode.window.showWarningMessage(
        `Onboarder: couldn't start the local engine (${msg}). Falling back to the hosted backend, which uploads the folder for analysis.`);
    }
  }

  // 4. Hosted fallback (engineMode "hosted", or bundled engine failed).
  if (!(await healthy(DEFAULT_BACKEND_URL))) {
    throw new Error(`Onboarder hosted backend at ${DEFAULT_BACKEND_URL} is not responding`);
  }
  backend = { baseUrl: DEFAULT_BACKEND_URL, mode: "remote" };
  return backend;
}

async function refreshProjects(base: string, wsId: string): Promise<ProjectInfo[]> {
  const projects = await api<ProjectInfo[]>(base, `/workspaces/${wsId}/projects`);
  // In local mode the backend's root_path IS the local folder. In remote mode
  // those paths live on the server — projectRoots is populated at upload time
  // from the folders we zipped, so don't clobber it here.
  if (backend?.mode !== "remote") {
    projectRoots.clear();
    for (const p of projects) {
      if (path.isAbsolute(p.root_path)) {
        projectRoots.set(p.id, p.root_path);
      }
    }
  }
  return projects;
}

// ---------- remote upload mode ----------

function zipFolder(folder: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const tmp = path.join(os.tmpdir(), `onboarder-${crypto.randomBytes(6).toString("hex")}.zip`);
    const excludes: string[] = [];
    for (const d of ZIP_SKIP_DIRS) {
      excludes.push(`${d}/*`, `*/${d}/*`);
    }
    excludes.push(".env", ".env.*", "*/.env", "*/.env.*");
    const proc = cp.spawn("zip", ["-rqX", tmp, ".", "-x", ...excludes], { cwd: folder });
    let err = "";
    proc.stderr?.on("data", (d) => { err += d.toString(); });
    proc.on("error", (e) =>
      reject(new Error(`could not run 'zip' (${e.message}). Install zip, or use a local backend.`)));
    proc.on("exit", (code) => {
      if (code === 0 || code === 12) resolve(tmp);  // 12 = nothing to do (still wrote a zip)
      else reject(new Error(`zip failed (code ${code}) ${err.slice(0, 200)}`));
    });
  });
}

async function uploadZip(base: string, wsId: string, name: string, zipPath: string): Promise<ProjectInfo[]> {
  const buf = fs.readFileSync(zipPath);
  const fd = new FormData();
  fd.append("file", new Blob([buf]), `${name}.zip`);
  const r = await fetch(`${base}/workspaces/${wsId}/projects`, { method: "POST", body: fd });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = ((await r.json()) as { detail?: string }).detail ?? detail; } catch { /* */ }
    throw new Error(detail);
  }
  return ((await r.json()) as { projects: ProjectInfo[] }).projects;
}

async function uploadAllFolders(base: string, wsId: string, folders: readonly vscode.WorkspaceFolder[],
                                report?: (m: string) => void): Promise<void> {
  // Replace any prior projects so re-mapping doesn't accumulate duplicates.
  const existing = await api<ProjectInfo[]>(base, `/workspaces/${wsId}/projects`);
  await Promise.all(existing.map((p) =>
    api(base, `/workspaces/${wsId}/projects/${p.id}`, { method: "DELETE" }).catch(() => undefined)));
  projectRoots.clear();
  for (const folder of folders) {
    report?.(`zipping ${path.basename(folder.uri.fsPath)}…`);
    const zip = await zipFolder(folder.uri.fsPath);
    try {
      report?.(`uploading ${path.basename(folder.uri.fsPath)}…`);
      const created = await uploadZip(base, wsId, path.basename(folder.uri.fsPath), zip);
      for (const p of created) {
        projectRoots.set(p.id, folder.uri.fsPath);  // open files locally even though analysis ran remotely
      }
    } finally {
      fs.rmSync(zip, { force: true });
    }
  }
}

function projectForPath(fsPath: string): string | null {
  let best: string | null = null;
  let bestLen = -1;
  for (const [id, root] of projectRoots) {
    if ((fsPath === root || fsPath.startsWith(root + path.sep)) && root.length > bestLen) {
      best = id;
      bestLen = root.length;
    }
  }
  return best;
}

async function waitForAnalysis(base: string, wsId: string, report?: (msg: string) => void): Promise<void> {
  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    const projects = await refreshProjects(base, wsId);
    const busy = projects.filter((p) => p.status === "pending" || p.status === "analyzing");
    if (projects.length > 0 && busy.length === 0) {
      return;
    }
    report?.(`${projects.length - busy.length}/${projects.length} projects ready`);
    await new Promise((r) => setTimeout(r, 800));
  }
}

async function ensureWorkspace(context: vscode.ExtensionContext, base: string, quick: boolean): Promise<string> {
  if (quick && currentWsId) {
    return currentWsId;
  }
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    throw new Error("Open a folder first — Onboarder maps the current workspace");
  }
  let wsId = context.workspaceState.get<string>("onboarder.wsId");
  if (wsId) {
    try {
      await api(base, `/workspaces/${wsId}`);
    } catch {
      wsId = undefined;
    }
  }
  if (!wsId) {
    const name = vscode.workspace.name || path.basename(folders[0].uri.fsPath);
    const created = await api<{ id: string }>(base, "/workspaces", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    wsId = created.id;
    await context.workspaceState.update("onboarder.wsId", wsId);
  }
  if (backend?.mode === "remote") {
    // Remote backend can't read the local disk — upload the folder(s) instead.
    // Reuse an existing mapping rather than re-uploading on every panel open.
    const existing = await api<ProjectInfo[]>(base, `/workspaces/${wsId}/projects`);
    if (existing.length > 0 && projectRoots.size > 0) {
      currentWsId = wsId;
      return wsId;
    }
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Onboarder: uploading workspace…" },
      async (progress) => {
        await uploadAllFolders(base, wsId!, folders, (m) => progress.report({ message: m }));
        progress.report({ message: "analyzing…" });
        await waitForAnalysis(base, wsId!, (m) => progress.report({ message: m }));
      },
    );
    currentWsId = wsId;
    return wsId;
  }

  for (const folder of folders) {
    await api(base, `/workspaces/${wsId}/projects/local`, {
      method: "POST",
      body: JSON.stringify({ path: folder.uri.fsPath }),
    });
  }
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "Onboarder: analyzing workspace…" },
    (progress) => waitForAnalysis(base, wsId!, (m) => progress.report({ message: m })),
  );
  currentWsId = wsId;
  return wsId;
}

// ---------- graph cache + CodeLens ----------

class GraphCache {
  private data: { nodes: GraphNode[]; edges: GraphEdge[] } | null = null;
  private at = 0;

  async get(base: string, wsId: string): Promise<{ nodes: GraphNode[]; edges: GraphEdge[] }> {
    if (this.data && Date.now() - this.at < 15000) {
      return this.data;
    }
    const g = await api<{ nodes: GraphNode[]; edges: GraphEdge[] }>(base, `/workspaces/${wsId}/graph`);
    this.data = { nodes: g.nodes, edges: g.edges };
    this.at = Date.now();
    return this.data;
  }

  invalidate(): void {
    this.data = null;
  }
}

const graphCache = new GraphCache();

class OnboarderLenses implements vscode.CodeLensProvider {
  private emitter = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this.emitter.event;

  fire(): void {
    this.emitter.fire();
  }

  async provideCodeLenses(doc: vscode.TextDocument): Promise<vscode.CodeLens[]> {
    if (!backend || !currentWsId) {
      return [];
    }
    const projectId = projectForPath(doc.uri.fsPath);
    if (!projectId) {
      return [];
    }
    const root = projectRoots.get(projectId)!;
    const rel = path.relative(root, doc.uri.fsPath).split(path.sep).join("/");
    let graph;
    try {
      graph = await graphCache.get(backend.baseUrl, currentWsId);
    } catch {
      return [];
    }
    const inCount = new Map<string, number>();
    const outCount = new Map<string, number>();
    const handles = new Map<string, number>();
    const reads = new Map<string, number>();
    const writes = new Map<string, number>();
    for (const e of graph.edges) {
      outCount.set(e.src, (outCount.get(e.src) ?? 0) + 1);
      inCount.set(e.dst, (inCount.get(e.dst) ?? 0) + 1);
      if (e.kind === "HANDLES") handles.set(e.dst, (handles.get(e.dst) ?? 0) + 1);
      if (e.kind === "READS") reads.set(e.dst, (reads.get(e.dst) ?? 0) + 1);
      if (e.kind === "WRITES") writes.set(e.dst, (writes.get(e.dst) ?? 0) + 1);
    }
    const lenses: vscode.CodeLens[] = [];
    for (const n of graph.nodes) {
      if (n.project_id !== projectId || n.file !== rel || !n.line_start) {
        continue;
      }
      let title: string | null = null;
      switch (n.kind) {
        case "entry_point":
          title = `$(play) trace ${n.name}`;
          break;
        case "logic": {
          const routes = handles.get(n.id) ?? 0;
          title = routes > 0
            ? `$(map) ${routes} route${routes === 1 ? "" : "s"} · show in map`
            : `$(map) ${inCount.get(n.id) ?? 0} in · ${outCount.get(n.id) ?? 0} out · show in map`;
          break;
        }
        case "data_access":
          title = "$(map) show in map";
          break;
        case "table":
          title = `$(database) ${writes.get(n.id) ?? 0} writers · ${reads.get(n.id) ?? 0} readers · show in map`;
          break;
        default:
          continue;
      }
      const line = Math.max(0, n.line_start - 1);
      lenses.push(new vscode.CodeLens(new vscode.Range(line, 0, line, 0), {
        title,
        command: "onboarder.revealNode",
        arguments: [n.id],
      }));
    }
    return lenses;
  }
}

const lensProvider = new OnboarderLenses();

// ---------- save watcher ----------

const pendingReanalyze = new Set<string>();
let saveTimer: ReturnType<typeof setTimeout> | undefined;

async function flushReanalyze(): Promise<void> {
  if (!backend || !currentWsId) {
    return;
  }
  const ids = [...pendingReanalyze];
  pendingReanalyze.clear();
  try {
    await Promise.all(ids.map((id) =>
      api(backend!.baseUrl, `/workspaces/${currentWsId}/projects/${id}/reanalyze`, { method: "POST" })));
    output.appendLine(`[onboarder] re-analyzing ${ids.length} project(s) after save`);
    await waitForAnalysis(backend.baseUrl, currentWsId);
    graphCache.invalidate();
    lensProvider.fire();
    panel?.webview.postMessage({ command: "refresh" });
  } catch (e) {
    output.appendLine(`[onboarder] auto re-analysis failed: ${e instanceof Error ? e.message : e}`);
  }
}

// ---------- webview ----------

function resolveFrontendDist(context: vscode.ExtensionContext): string {
  const candidates = [
    cfg().get<string>("frontendDist") || "",
    path.join(context.extensionPath, "media", "dist"),
    repoDefault(context, path.join("frontend", "dist")),
  ];
  for (const c of candidates) {
    if (c && fs.existsSync(path.join(c, "index.html"))) {
      return c;
    }
  }
  throw new Error("Built frontend not found — run `npm run build` in frontend/ or set onboarder.frontendDist");
}

function buildHtml(webview: vscode.Webview, distDir: string, apiBase: string, wsId: string): string {
  let html = fs.readFileSync(path.join(distDir, "index.html"), "utf8");
  html = html.replace(/(src|href)="\.\/([^"]+)"/g, (_m, attr, rel) => {
    const uri = webview.asWebviewUri(vscode.Uri.file(path.join(distDir, rel)));
    return `${attr}="${uri}"`;
  });
  const nonce = crypto.randomBytes(16).toString("base64");
  // The webview talks to the backend over fetch + EventSource (SSE); both are
  // governed by connect-src. Localhost covers a local sidecar; a remote backend
  // (e.g. the hosted Railway deploy) needs its own origin allow-listed or every
  // request is blocked and the map can never load.
  let backendOrigin = "";
  try {
    if (apiBase) backendOrigin = new URL(apiBase).origin;
  } catch { /* relative/empty apiBase is same-origin — nothing to add */ }
  const csp = [
    "default-src 'none'",
    `img-src ${webview.cspSource} data: blob:`,
    `style-src ${webview.cspSource} 'unsafe-inline' https://fonts.googleapis.com`,
    "font-src https://fonts.gstatic.com",
    `script-src ${webview.cspSource} 'nonce-${nonce}'`,
    `connect-src http://127.0.0.1:* http://localhost:* ${backendOrigin}`.trim(),
  ].join("; ");
  const boot = `<meta http-equiv="Content-Security-Policy" content="${csp}">` +
    `<script nonce="${nonce}">window.__ONBOARDER__=${JSON.stringify({ apiBase, workspaceId: wsId })};</script>`;
  return html.replace("<head>", `<head>${boot}`);
}

async function openMap(context: vscode.ExtensionContext, quick = false): Promise<void> {
  const be = await ensureBackend(context);
  const wsId = await ensureWorkspace(context, be.baseUrl, quick);
  await refreshProjects(be.baseUrl, wsId);
  lensProvider.fire();

  if (panel) {
    panel.reveal(undefined, true);
    return;
  }
  const distDir = resolveFrontendDist(context);
  panel = vscode.window.createWebviewPanel("onboarder", "Onboarder", vscode.ViewColumn.One, {
    enableScripts: true,
    retainContextWhenHidden: true,
    localResourceRoots: [vscode.Uri.file(distDir)],
  });
  panel.webview.html = buildHtml(panel.webview, distDir, be.baseUrl, wsId);
  panel.onDidDispose(() => { panel = null; });

  panel.webview.onDidReceiveMessage(async (msg: { command?: string; projectId?: string; file?: string; line?: number; name?: string; data?: string; kind?: string }) => {
    if (msg.command === "saveFile" && msg.name && msg.data) {
      try {
        const target = await vscode.window.showSaveDialog({
          defaultUri: vscode.Uri.file(path.join(
            vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? os.homedir(), msg.name)),
        });
        if (!target) return;
        const bytes = msg.kind === "dataurl"
          ? Buffer.from(msg.data.slice(msg.data.indexOf(",") + 1), "base64")
          : Buffer.from(msg.data, "utf8");
        await vscode.workspace.fs.writeFile(target, bytes);
        vscode.window.showInformationMessage(`Onboarder: saved ${path.basename(target.fsPath)}`);
      } catch (e) {
        vscode.window.showErrorMessage(`Onboarder: save failed — ${e instanceof Error ? e.message : e}`);
      }
      return;
    }
    if (msg.command !== "openFile" || !msg.projectId || !msg.file) {
      return;
    }
    try {
      if (projectRoots.size === 0) {
        await refreshProjects(be.baseUrl, wsId);
      }
      const root = projectRoots.get(msg.projectId);
      if (!root) {
        vscode.window.showWarningMessage("Onboarder: this project was uploaded as a zip — no local files to open");
        return;
      }
      const doc = await vscode.workspace.openTextDocument(path.join(root, msg.file));
      const line = Math.max(0, (msg.line ?? 1) - 1);
      await vscode.window.showTextDocument(doc, {
        viewColumn: vscode.ViewColumn.Beside,
        selection: new vscode.Range(line, 0, line, 0),
      });
    } catch (e) {
      vscode.window.showErrorMessage(`Onboarder: could not open file — ${e instanceof Error ? e.message : e}`);
    }
  });
}

// ---------- activation ----------

export function activate(context: vscode.ExtensionContext): void {
  output = vscode.window.createOutputChannel("Onboarder");
  context.subscriptions.push(output);
  currentWsId = null;

  const wrap = (fn: (...a: unknown[]) => Promise<void>) => async (...a: unknown[]) => {
    try {
      await fn(...a);
    } catch (e) {
      vscode.window.showErrorMessage(e instanceof Error ? e.message : String(e));
    }
  };

  context.subscriptions.push(
    vscode.commands.registerCommand("onboarder.openMap", wrap(() => openMap(context))),
    vscode.commands.registerCommand("onboarder.revealNode", wrap(async (nodeId) => {
      await openMap(context, true);
      panel?.webview.postMessage({ command: "select", nodeId });
    })),
    vscode.commands.registerCommand("onboarder.compare", wrap(async () => {
      await openMap(context, true);
      panel?.webview.postMessage({ command: "diff" });
    })),
    vscode.commands.registerCommand("onboarder.ask", wrap(async () => {
      const question = await vscode.window.showInputBox({
        prompt: "Ask Onboarder about this codebase — explain a flow, or report an issue to investigate",
        placeHolder: "e.g. Opening a listing takes 10 seconds — where should I look?",
      });
      if (!question) {
        return;
      }
      await openMap(context, true);
      panel?.webview.postMessage({ command: "chat", question });
    })),
    vscode.commands.registerCommand("onboarder.analyzeTicket", wrap(async () => {
      const be = await ensureBackend(context);
      let st: { jira?: { configured?: boolean }; ado?: { configured?: boolean } } = {};
      try { st = await api(be.baseUrl, "/trackers/status"); } catch { /* offline → manual only */ }
      const picks: (vscode.QuickPickItem & { source: string })[] = [];
      if (st.jira?.configured) picks.push({ label: "Jira issue", source: "jira" });
      if (st.ado?.configured) picks.push({ label: "Azure DevOps work item", source: "ado" });
      picks.push({
        label: "Paste ticket text…", source: "manual",
        detail: picks.length === 0 ? "Connect Jira/ADO in Onboarder Settings to analyze by key" : undefined,
      });
      const pick = picks.length === 1 ? picks[0]
        : await vscode.window.showQuickPick(picks, { placeHolder: "Analyze a ticket from…" });
      if (!pick) return;

      let key = "", title = "", body = "";
      if (pick.source === "manual") {
        body = (await vscode.window.showInputBox({
          prompt: "Paste the ticket description / repro steps",
          placeHolder: "e.g. Out-of-stock products can still be purchased…",
        })) ?? "";
        if (!body.trim()) return;
      } else {
        key = (await vscode.window.showInputBox({
          prompt: pick.source === "jira" ? "Jira issue key" : "Azure DevOps work item id",
          placeHolder: pick.source === "jira" ? "e.g. PROJ-123" : "e.g. 1234",
        })) ?? "";
        if (!key.trim()) return;
      }
      await openMap(context, true);
      panel?.webview.postMessage({ command: "analyzeTicket", source: pick.source, key: key.trim(), title, body });
    })),
    vscode.commands.registerCommand("onboarder.reanalyze", wrap(async () => {
      const be = await ensureBackend(context);
      const wsId = currentWsId ?? context.workspaceState.get<string>("onboarder.wsId");
      if (!wsId) {
        throw new Error("No Onboarder workspace yet — run “Onboarder: Map this workspace” first");
      }
      if (be.mode === "remote") {
        const folders = vscode.workspace.workspaceFolders ?? [];
        await vscode.window.withProgress(
          { location: vscode.ProgressLocation.Notification, title: "Onboarder: re-uploading workspace…" },
          async (progress) => {
            await uploadAllFolders(be.baseUrl, wsId, folders, (m) => progress.report({ message: m }));
            progress.report({ message: "analyzing…" });
            await waitForAnalysis(be.baseUrl, wsId);
          },
        );
      } else {
        const projects = await refreshProjects(be.baseUrl, wsId);
        await Promise.all(projects.map((p) =>
          api(be.baseUrl, `/workspaces/${wsId}/projects/${p.id}/reanalyze`, { method: "POST" })));
        vscode.window.showInformationMessage(`Onboarder: re-analyzing ${projects.length} project(s)`);
        await waitForAnalysis(be.baseUrl, wsId);
      }
      graphCache.invalidate();
      lensProvider.fire();
      panel?.webview.postMessage({ command: "refresh" });
    })),
    vscode.commands.registerCommand("onboarder.setApiKey", wrap(async () => {
      const be = await ensureBackend(context);
      const key = await vscode.window.showInputBox({
        prompt: "Anthropic API key (validated with a free token-count call, stored by the local backend)",
        password: true,
        placeHolder: "sk-ant-…",
      });
      if (!key) {
        return;
      }
      await api(be.baseUrl, "/settings/api-key", {
        method: "PUT",
        body: JSON.stringify({ anthropic_api_key: key }),
      });
      vscode.window.showInformationMessage("Onboarder: key validated — AI summaries, chat and tours are enabled");
    })),
  );

  const langs = ["java", "kotlin", "javascript", "typescript", "typescriptreact", "python", "go", "php", "ruby"];
  context.subscriptions.push(
    vscode.languages.registerCodeLensProvider(
      langs.map((language) => ({ scheme: "file", language })),
      lensProvider,
    ),
  );

  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((doc) => {
      // Save-triggered re-analysis is local-mode only — re-zipping/uploading the
      // whole workspace on every save would be far too heavy. Remote users refresh
      // with the "Re-analyze workspace" command.
      if (backend?.mode !== "local"
          || !cfg().get<boolean>("autoReanalyze", true) || !backend || !currentWsId) {
        return;
      }
      const projectId = projectForPath(doc.uri.fsPath);
      if (!projectId) {
        return;
      }
      pendingReanalyze.add(projectId);
      if (saveTimer) {
        clearTimeout(saveTimer);
      }
      saveTimer = setTimeout(() => void flushReanalyze(), 1500);
    }),
  );

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  status.text = "$(circuit-board) Onboarder";
  status.tooltip = "Map this workspace with Onboarder";
  status.command = "onboarder.openMap";
  status.show();
  context.subscriptions.push(status);
}

export function deactivate(): void {
  backend?.proc?.kill();
}
