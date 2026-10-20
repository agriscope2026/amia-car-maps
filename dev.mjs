// Start the whole local stack with one command (from the repo root):  node dev.mjs
//   1. local database (web/scripts/localdb.mjs start)
//   2. render worker on :8001 (WORKER_TOKEN taken from web/.env.local)
//   3. web app on :3000
// Ctrl+C stops the worker and the web app (the database keeps running; stop it with: cd web && npm run db:stop).
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { createServer } from "node:net";
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

// the local admin login is DEV_ADMIN_EMAIL / DEV_ADMIN_PASSWORD from web/.env.local – with the local database it is
// (re)set on every start, so the login printed below always works
const ADMIN = { email: env.DEV_ADMIN_EMAIL || "admin@example.com", password: env.DEV_ADMIN_PASSWORD || "" };
if (env.DATABASE_URL) {
  if (ADMIN.password.length >= 8) {
    const r = spawnSync(process.execPath, [join(WEB, "scripts", "localdb.mjs"), "add-user", ADMIN.email, ADMIN.password, "admin"],
      { encoding: "utf-8" });
    if (r.status !== 0) console.error(`Could not set the local admin login:\n${r.stderr || r.stdout}`);
  } else {
    console.warn("Set DEV_ADMIN_EMAIL and DEV_ADMIN_PASSWORD (8+ characters) in web/.env.local to fix the local admin login.");
  }
  // development only: sample activities while the list is empty (remove: cd web && node scripts/localdb.mjs activities-demo --clear)
  spawnSync(process.execPath, [join(WEB, "scripts", "localdb.mjs"), "activities-demo", "--if-empty"], { stdio: "inherit" });
}

// ports 3000 (web) and 8001 (worker) must be free – usually they are held by an earlier `node dev.mjs` that is
// still running (another terminal, or one closed without Ctrl+C). `node dev.mjs --restart` stops it first.
const PORTS = { 3000: "web app", 8001: "worker" };

function canListen(port, host) {
  return new Promise((resolve) => {
    const srv = createServer()
      .once("error", (e) => resolve(e.code !== "EADDRINUSE" && e.code !== "EACCES"))
      .once("listening", () => srv.close(() => resolve(true)))
      .listen(port, host);
  });
}

// the web app listens on all addresses, the worker on 127.0.0.1 only: check both
const portFree = async (port) => (await canListen(port, "127.0.0.1")) && (await canListen(port, "::"));

/** PIDs listening on a port (Windows: netstat; elsewhere: lsof). */
function listeners(port) {
  if (win) {
    const out = spawnSync("netstat", ["-ano", "-p", "TCP"], { encoding: "utf-8" }).stdout ?? "";
    return [...new Set(out.split(/\r?\n/).filter((l) => /LISTENING/.test(l) && new RegExp(`:${port}\\s`).test(l))
      .map((l) => l.trim().split(/\s+/).pop()).filter((p) => p && p !== "0"))];
  }
  const out = spawnSync("lsof", ["-ti", `tcp:${port}`, "-sTCP:LISTEN"], { encoding: "utf-8" }).stdout ?? "";
  return [...new Set(out.split(/\s+/).filter(Boolean))];
}

function processName(pid) {
  if (!win) return spawnSync("ps", ["-p", pid, "-o", "comm="], { encoding: "utf-8" }).stdout?.trim() || "?";
  const out = spawnSync("tasklist", ["/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"], { encoding: "utf-8" }).stdout ?? "";
  return out.split(",")[0]?.replace(/"/g, "").trim() || "?";
}

function stopPid(pid) {
  if (win) spawnSync("taskkill", ["/PID", pid, "/T", "/F"], { stdio: "ignore" });
  else spawnSync("kill", [pid], { stdio: "ignore" });
}

const restart = process.argv.includes("--restart");
let busy = [];
for (const port of Object.keys(PORTS)) if (!(await portFree(Number(port)))) busy.push(port);
if (busy.length && restart) {
  for (const port of busy) for (const pid of listeners(port)) {
    console.log(`Stopping ${processName(pid)} (PID ${pid}) on port ${port}…`);
    stopPid(pid);
  }
  await new Promise((r) => setTimeout(r, 1500));
  busy = [];
  for (const port of Object.keys(PORTS)) if (!(await portFree(Number(port)))) busy.push(port);
}
if (busy.length) {
  console.error("\nCannot start: these ports are already in use:");
  for (const port of busy) {
    const who = listeners(port).map((pid) => `${processName(pid)} PID ${pid}`).join(", ") || "unknown process";
    console.error(`  ${port} (${PORTS[port]}) – held by ${who}`);
  }
  console.error("\nUsually this is an earlier `node dev.mjs` that is still running. Stop it with Ctrl+C in its terminal, or run:");
  console.error("  node dev.mjs --restart     (stops whatever holds these ports, then starts)\n");
  process.exit(1);
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

console.log("\nStarting… dashboard http://localhost:3000 · admin http://localhost:3000/admin"
  + (ADMIN.password ? ` – login ${ADMIN.email} / ${ADMIN.password}` : "") + "\nPress Ctrl+C to stop.\n");
