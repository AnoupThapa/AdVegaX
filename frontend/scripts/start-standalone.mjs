// Runs the production build exactly as the Docker image does: the Next.js standalone server
// (`.next/standalone/server.js`) with the static assets copied next to it.
// Usage: npm run build && npm run start:standalone   (PORT and HOSTNAME may be set)
import { cpSync, existsSync, rmSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const root = path.resolve(import.meta.dirname, "..");
const standalone = path.join(root, ".next", "standalone");
const server = path.join(standalone, "server.js");
if (!existsSync(server)) {
  console.error("No standalone build found. Run `npm run build` first.");
  process.exit(1);
}
const target = path.join(standalone, ".next", "static");
rmSync(target, { recursive: true, force: true });
cpSync(path.join(root, ".next", "static"), target, { recursive: true });
// Like the Docker image: public files (screenshots, icons) are served next to the server too.
const publicDir = path.join(root, "public");
if (existsSync(publicDir)) {
  cpSync(publicDir, path.join(standalone, "public"), { recursive: true });
}

process.env.PORT ??= "3000";
process.env.HOSTNAME ??= "localhost";
process.env.NODE_ENV = "production";
// A bare Windows path (C:\...) is not a valid ESM specifier; import it as a file:// URL.
await import(pathToFileURL(server).href);
