import assert from "node:assert/strict";
import { test } from "node:test";
import { THEME_STORAGE_KEY, THEME_COLORS, nextInCycle, parseTheme, resolveTheme } from "../src/lib/theme.ts";

test("a saved preference is read back, and anything else means follow the system", () => {
  for (const value of ["light", "dark", "system"] as const) assert.equal(parseTheme(value), value);
  for (const junk of [null, undefined, "", "Dark", "auto", "blue", "{}", " dark"]) {
    assert.equal(parseTheme(junk as string | null | undefined), "system", `"${junk}"`);
  }
});

test("light and dark are absolute; system follows the operating system", () => {
  assert.equal(resolveTheme("light", true), "light");
  assert.equal(resolveTheme("light", false), "light");
  assert.equal(resolveTheme("dark", true), "dark");
  assert.equal(resolveTheme("dark", false), "dark");
  assert.equal(resolveTheme("system", true), "dark");
  assert.equal(resolveTheme("system", false), "light");
});

test("the toggle cycles light -> dark -> system -> light", () => {
  assert.equal(nextInCycle("light"), "dark");
  assert.equal(nextInCycle("dark"), "system");
  assert.equal(nextInCycle("system"), "light");
});

test("the storage key is namespaced to this app and each resolved theme has a browser-chrome colour", () => {
  assert.match(THEME_STORAGE_KEY, /^financial-assistant\./);
  assert.match(THEME_COLORS.light, /^#[0-9a-f]{6}$/i);
  assert.match(THEME_COLORS.dark, /^#[0-9a-f]{6}$/i);
  assert.notEqual(THEME_COLORS.light, THEME_COLORS.dark);
});
