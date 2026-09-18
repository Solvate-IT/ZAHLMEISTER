import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const workspace = readFileSync(new URL("../src/components/Workspace.tsx", import.meta.url), "utf8");
const banner = readFileSync(new URL("../src/components/SupportSessionBanner.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");

test("support banner is rendered above the workspace instead of inside page content", () => {
  const supportIndex = workspace.indexOf("{support&&<SupportSessionBanner/>}");
  const workspaceIndex = workspace.indexOf('<div className="workspace">');
  const bodyIndex = workspace.indexOf('<div className="workspace-body">');

  assert.ok(supportIndex >= 0, "support banner must be rendered for support sessions");
  assert.ok(supportIndex < workspaceIndex, "support banner must sit above the complete workspace");
  assert.ok(!workspace.slice(bodyIndex).includes("{support&&<SupportSessionBanner/>}"), "support banner must not be part of normal page content");
});

test("support banner uses a dedicated compact warning style", () => {
  assert.match(banner, /className="support-session-banner"/);
  assert.match(banner, /className="support-session-main"/);
  assert.match(banner, /className="support-session-meta"/);
  assert.match(css, /\.support-session-banner\{[^}]*background:rgba\(179,38,30,\.88\)[^}]*backdrop-filter:blur\(12px\)/);
  assert.match(css, /\.support-session-main\{[^}]*display:flex[^}]*align-items:center[^}]*gap:8px/);
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.support-session-main\{[^}]*flex-wrap:wrap/);
});
