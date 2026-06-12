const fs = require("fs");
const path = require("path");

const src = path.resolve(__dirname, "..", "..", "frontend", "dist");
const dest = path.resolve(__dirname, "..", "media", "dist");

if (!fs.existsSync(path.join(src, "index.html"))) {
  console.error(`frontend build not found at ${src} — run "npm run build" in frontend/ first`);
  process.exit(1);
}
fs.rmSync(dest, { recursive: true, force: true });
fs.cpSync(src, dest, { recursive: true });
console.log(`bundled frontend → ${dest}`);
