import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/services/api.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const loadApi = () => import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}#${crypto.randomUUID()}`);
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});

// Advance retry delays deterministically, while fetch timeout signals remain real.
function fastRetries(t) {
  let now = 0;
  t.mock.method(Date, "now", () => now);
  t.mock.method(globalThis, "setTimeout", (callback, delay) => {
    now += delay;
    queueMicrotask(callback);
    return 0;
  });
}

test("registration waits through Render gateway failures and POSTs exactly once", async (t) => {
  fastRetries(t);
  const calls = [];
  let probes = 0;
  t.mock.method(globalThis, "fetch", async (path, init) => {
    calls.push([path, init.method ?? "GET"]);
    if (path === "/api/ready") {
      probes++;
      return probes < 3 ? new Response("Render starting", { status: 502 }) : json({ status: "ready" });
    }
    return json({ access_token: "test-access-token" }, 201);
  });
  const { api } = await loadApi();
  await api("/auth/register", { method: "POST", body: JSON.stringify({ email: "test@example.com", password: "test-password" }) });
  assert.deepEqual(calls, [
    ["/api/ready", "GET"], ["/api/ready", "GET"], ["/api/ready", "GET"], ["/api/auth/register", "POST"],
  ]);
});

test("network failure and startup HTML are not mistaken for readiness", async (t) => {
  fastRetries(t);
  let probes = 0;
  let posts = 0;
  t.mock.method(globalThis, "fetch", async (path) => {
    if (path === "/api/ready") {
      if (++probes === 1) throw new TypeError("Failed to fetch");
      return probes === 2 ? new Response("<html>Starting</html>") : json({ status: "ready" });
    }
    posts++;
    return json({ access_token: "test-access-token" });
  });
  const { api } = await loadApi();
  await api("/auth/login", { method: "POST" });
  assert.equal(probes, 3);
  assert.equal(posts, 1);
});

test("readiness timeout prevents registration and session refresh resolves to anonymous", async (t) => {
  fastRetries(t);
  let posts = 0;
  t.mock.method(globalThis, "fetch", async (path) => {
    if (path !== "/api/ready") posts++;
    return new Response("Unavailable", { status: 503 });
  });
  const { api, refreshSession } = await loadApi();
  await assert.rejects(api("/auth/register", { method: "POST" }), (error) => error.status === 503 && /still starting/.test(error.message));
  assert.equal(await refreshSession(), false);
  assert.equal(posts, 0);
});

test("concurrent authentication shares readiness and forwards credentials", async (t) => {
  let probes = 0;
  let finishProbe;
  const probe = new Promise((resolve) => { finishProbe = resolve; });
  t.mock.method(globalThis, "fetch", async (path, init) => {
    assert.equal(init.credentials, "include");
    if (path === "/api/ready") { probes++; return probe; }
    return json({ access_token: "test-access-token" });
  });
  const { api, refreshSession } = await loadApi();
  const refresh = refreshSession();
  const login = api("/auth/login", { method: "POST" });
  assert.equal(probes, 1);
  finishProbe(json({ status: "ready" }));
  assert.equal(await refresh, true);
  await login;
});

test("authentication failure is reported without replaying the POST", async (t) => {
  let posts = 0;
  t.mock.method(globalThis, "fetch", async (path) => {
    if (path === "/api/ready") return json({ status: "ready" });
    posts++;
    return json({ detail: "Incorrect email or password" }, 401);
  });
  const { api } = await loadApi();
  await assert.rejects(api("/auth/login", { method: "POST" }), (error) => error.status === 401 && error.message === "Incorrect email or password");
  assert.equal(posts, 1);
});

test("a gateway failure after readiness never replays account creation", async (t) => {
  let posts = 0;
  t.mock.method(globalThis, "fetch", async (path) => {
    if (path === "/api/ready") return json({ status: "ready" });
    posts++;
    return new Response("Bad gateway", { status: 502 });
  });
  const { api } = await loadApi();
  await assert.rejects(api("/auth/register", { method: "POST" }), (error) => error.status === 502 && /server is unavailable/.test(error.message));
  assert.equal(posts, 1);
});
