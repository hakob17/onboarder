import { toPng, toSvg } from "html-to-image";
import type { Graph } from "./api";
import { saveArtifact } from "./vscode";

function stageEl(): HTMLElement | null {
  return document.querySelector(".map-stage");
}

function bg(): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue("--canvas").trim();
  return v || "#ffffff";
}

// skipFonts avoids html-to-image hanging on cross-origin web-font embedding;
// exported text falls back to system sans, which is fine for a diagram.
export async function exportPng(name: string): Promise<void> {
  const el = stageEl();
  if (!el) return;
  const url = await toPng(el, { backgroundColor: bg(), pixelRatio: 2, skipFonts: true });
  saveArtifact(`${name}.png`, url, "dataurl");
}

export async function exportSvg(name: string): Promise<void> {
  const el = stageEl();
  if (!el) return;
  const url = await toSvg(el, { backgroundColor: bg(), skipFonts: true });
  saveArtifact(`${name}.svg`, url, "dataurl");
}

export function exportJson(name: string, graph: Graph): void {
  const artifact = {
    onboarder: { version: 1, exported_at: new Date().toISOString() },
    nodes: graph.nodes,
    edges: graph.edges,
    cross_edges: graph.cross_edges,
  };
  saveArtifact(`${name}.json`, JSON.stringify(artifact, null, 2), "text");
}
