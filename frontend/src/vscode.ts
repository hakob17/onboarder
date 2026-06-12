const host = typeof window.acquireVsCodeApi === "function" ? window.acquireVsCodeApi() : null;

export const inVsCode = host !== null;

export function openInEditor(projectId: string, file: string, line: number): void {
  host?.postMessage({ command: "openFile", projectId, file, line });
}
