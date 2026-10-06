// Start the whole local stack with one command (from the repo root):  node dev.mjs
//   1. local database (web/scripts/localdb.mjs start)
//   2. render worker on :8001 (WORKER_TOKEN taken from web/.env.local)
//   3. web app on :3000
// Ctrl+C stops the worker and the web app (the database keeps running; stop it with: cd web && npm run db:stop).
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const ROOT = import.meta.dirname;
const WEB = join(ROOT, "web");
const WORKER = join(ROOT, "worker");
const win = process.platform === "win32";

const env = {};
const envFile = join(WEB, ".env.local");
if (existsSync(envFile)) {
  for (const line of readFileSync(envFile, "utf-8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m) env[m[1]] = m[2];
  }
}
if (!env.WORKER_TOKEN) {
  console.error("Set WORKER_TOKEN in web/.env.local (copy web/.env.example first).");
  process.exit(1);
}

const python = join(WORKER, ".venv", win ? "Scripts/python.exe" : "bin/python");
if (!existsSync(python)) {
  console.error("Worker environment missing. Run: cd worker && python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt");
  process.exit(1);
}
if (!existsSync(join(WEB, "node_modules"))) {
  console.error("Run: cd web && npm install");
  process.exit(1);
}

if (env.DATABASE_URL) {
  if (!existsSync(join(ROOT, ".localdb", "data"))) {
    console.error("Local database not set up. Run: cd web && npm run db:setup && npm run db:reset");
    process.exit(1);
  }
  spawnSync(process.execPath, [join(WEB, "scripts", "localdb.mjs"), "start"], { stdio: "inherit" });
  spawnSync(process.execPath, [join(WEB, "scripts", "localdb.mjs"), "migrate"], { stdio: "inherit" });
}

const children = [];
function start(name, color, cmd, args, opts) {
  const child = spawn(cmd, args, { ...opts, shell: false, stdio: ["ignore", "pipe", "pipe"] });
  const prefix = `\x1b[${color}m[${name}]\x1b[0m `;
  const out = (d) => process.stdout.write(d.toString().replace(/^(?=.)/gm, prefix));
  child.stdout.on("data", out);
  child.stderr.on("data", out);
  child.on("exit", (code) => {
    console.log(`${prefix}exited (${code})`);
    shutdown();
  });
  children.push(child);
}

start("worker", 36, python, ["-m", "uvicorn", "agriclimate.api:app", "--port", "8001"], {
  cwd: WORKER,
  env: { ...process.env, WORKER_TOKEN: env.WORKER_TOKEN, PYTHONIOENCODING: "utf-8" },
});
start("web", 32, process.execPath, [join(WEB, "node_modules", "next", "dist", "bin", "next"), "dev", "-p", "3000"], {
  cwd: WEB,
  env: process.env,
});

let stopping = false;
function shutdown() {
  if (stopping) return;
  stopping = true;
  for (const c of children) {
    if (c.exitCode !== null) continue;
    if (win) spawnSync("taskkill", ["/pid", String(c.pid), "/T", "/F"], { stdio: "ignore" });
    else c.kill("SIGTERM");
  }
  setTimeout(() => process.exit(0), 500);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

console.log("\nStarting… dashboard http://localhost:3000 · admin http://localhost:3000/admin (admin@example.com / admin-local-123)\nPress Ctrl+C to stop.\n");
