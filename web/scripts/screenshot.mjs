// Real-time headless screenshot via the Chrome DevTools Protocol (used for visual checks / docs).
// Usage: node scripts/screenshot.mjs <url> <out.png> [width] [height] [waitMs]
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, out, width = "1440", height = "900", wait = "9000"] = process.argv.slice(2);
const chrome = process.env.CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const port = 9300 + Math.floor(Math.random() * 500);
const proc = spawn(chrome, [
  "--headless=new", `--remote-debugging-port=${port}`, "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
  "--hide-scrollbars", `--window-size=${width},${height}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), "cdp-"))}`, "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 50 && !target; i++) {
  await sleep(200);
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page"); } catch {}
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pending = new Map();
const logs = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result ?? m.error); pending.delete(m.id); }
  if (m.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(m.params.type))
    logs.push(`${m.params.type}: ${m.params.args.map((a) => a.value ?? a.description).join(" ")}`);
  if (m.method === "Runtime.exceptionThrown") logs.push(`exception: ${m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text}`);
};
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send("Runtime.enable");
await send("Page.enable");
if (process.env.COOKIE) {
  await send("Network.enable");
  const [name, ...v] = process.env.COOKIE.split("=");
  await send("Network.setCookie", { name, value: v.join("="), url: new URL(url).origin });
}
const mobile = Number(width) < 600;
await send("Emulation.setDeviceMetricsOverride", { width: Number(width), height: Number(height), deviceScaleFactor: 1, mobile });
await send("Page.navigate", { url });
await sleep(Number(wait));
// EVAL="js" runs a snippet in the page (e.g. click a button), then EVAL_WAIT ms pass before the capture
if (process.env.EVAL) {
  await send("Runtime.evaluate", { expression: process.env.EVAL });
  await sleep(Number(process.env.EVAL_WAIT ?? 3000));
}
// KEYS="+,+" presses keys before the capture (e.g. zoom in photo mode)
for (const k of (process.env.KEYS ?? "").split(",").filter(Boolean)) {
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: k, text: k });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: k });
  await sleep(400);
}
if (process.env.KEYS) await sleep(800);
// CLICK="x,y" clicks a point (e.g. a municipality) before the capture
if (process.env.CLICK) {
  const [x, y] = process.env.CLICK.split(",").map(Number);
  for (const type of ["mouseMoved", "mousePressed", "mouseReleased"])
    await send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 });
  await sleep(1500);
}
const shot = await send("Page.captureScreenshot", { format: "png" });
writeFileSync(out, Buffer.from(shot.data, "base64"));
console.log(logs.length ? logs.join("\n") : "no console errors");
ws.close();
proc.kill();
process.exit(0);
