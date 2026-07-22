import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import { inVsCode } from "./vscode";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// PWA: register the service worker so the web app installs and loads offline.
// Skip it inside the VS Code / Antigravity webview (this same build is bundled
// there) and on insecure origins where service workers aren't allowed.
if (
  import.meta.env.PROD &&
  !inVsCode &&
  "serviceWorker" in navigator &&
  window.isSecureContext
) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js", { scope: "./" }).catch(() => {
      /* registration is best-effort; the app works without it */
    });
  });
}
