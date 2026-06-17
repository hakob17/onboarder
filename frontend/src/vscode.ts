const host = typeof window.acquireVsCodeApi === "function" ? window.acquireVsCodeApi() : null;

export const inVsCode = host !== null;

export function openInEditor(projectId: string, file: string, line: number): void {
  host?.postMessage({ command: "openFile", projectId, file, line });
}

/** Save an artifact: in VS Code route to the host (showSaveDialog + write);
 *  in the browser trigger a download. `data` is a data: URL for binary, plain text otherwise. */
export function saveArtifact(name: string, data: string, kind: "dataurl" | "text"): void {
  if (host) {
    host.postMessage({ command: "saveFile", name, data, kind });
    return;
  }
  const a = document.createElement("a");
  a.download = name;
  a.href = kind === "dataurl" ? data : `data:application/json;charset=utf-8,${encodeURIComponent(data)}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
