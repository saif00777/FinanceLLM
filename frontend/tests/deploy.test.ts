import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const path = new URL("../vercel.json", import.meta.url);
const routeSource = readFileSync(new URL("../src/hooks/useRoute.ts", import.meta.url), "utf-8");

test("the app is a single-page app, so Vercel must serve index.html for deep links (/chat, /architecture)", () => {
  // Without this a refresh on /chat or /architecture asks the host for a file that does not exist and gets a 404.
  assert.ok(existsSync(path), "frontend/vercel.json is missing");
  const config = JSON.parse(readFileSync(path, "utf-8"));
  const fallback = (config.rewrites ?? []).find((rule: { destination: string }) => rule.destination === "/index.html");
  assert.ok(fallback, "no rewrite to /index.html");
  const pattern = new RegExp(`^${fallback.source.replace(/^\//, "/?")}$`);
  for (const route of ["/chat", "/architecture", "/chat/anything", "/some/unknown/page"]) {
    assert.ok(new RegExp(`^(?:${fallback.source})$`).test(route), `${route} is not covered by the fallback`);
  }
  assert.ok(pattern);
});

test("every route the app defines is covered by that fallback", () => {
  const config = existsSync(path) ? JSON.parse(readFileSync(path, "utf-8")) : { rewrites: [] };
  const fallback = (config.rewrites ?? []).find((rule: { destination: string }) => rule.destination === "/index.html");
  const routes = [...routeSource.matchAll(/startsWith\("(\/[a-z]+)"\)/g)].map((m) => m[1]);
  assert.ok(routes.length >= 2, "expected to find the app's routes in useRoute.ts");
  for (const route of routes) assert.ok(fallback && new RegExp(`^(?:${fallback.source})$`).test(route), `${route} not covered`);
});
