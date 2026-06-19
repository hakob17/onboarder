const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

// Bundle the PyInstaller engine into the extension as a single .tar.gz, so it
// ships inside the .vsix (extracted to globalStorage at runtime). A single
// archive — rather than the unpacked onedir — avoids vsce's secret scanner
// choking on PyInstaller's internal symlinks. Build first: backend/build_engine.sh
const distDir = path.resolve(__dirname, "..", "..", "backend", "dist");
const exeName = process.platform === "win32" ? "onboarder-engine.exe" : "onboarder-engine";
if (!fs.existsSync(path.join(distDir, "onboarder-engine", exeName))) {
  console.error(`engine build not found in ${distDir} — run backend/build_engine.sh first`);
  process.exit(1);
}
const destDir = path.resolve(__dirname, "..", "media", "engine");
fs.rmSync(destDir, { recursive: true, force: true });
fs.mkdirSync(destDir, { recursive: true });

const asset = `onboarder-engine-${process.platform}-${process.arch}.tar.gz`;
const out = path.join(destDir, asset);
const r = spawnSync("tar", ["-czf", out, "-C", distDir, "onboarder-engine"], { stdio: "inherit" });
if (r.status !== 0) process.exit(r.status ?? 1);
console.log(`bundled engine → ${out} (${(fs.statSync(out).size / 1e6).toFixed(1)} MB)`);
