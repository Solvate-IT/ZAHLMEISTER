import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const action = readFileSync(new URL("../src/components/AccountAction.tsx", import.meta.url), "utf8");

test("successful email verification clears any stale login and returns to login", () => {
  assert.match(action, /clearToken/);
  assert.match(action, /await clearToken\(\)/);
  assert.match(action, /router\.replace\("\/\?auth=login"\)/);
  assert.match(action, /t\("login"\)/);
});
