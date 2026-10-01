import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const css = readFileSync(new URL("../src/app/mobile-workspace.css", import.meta.url), "utf8");
const globals = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");
const lists = readFileSync(new URL("../src/components/workspace/ListsPage.tsx", import.meta.url), "utf8");
const workspace = readFileSync(new URL("../src/components/Workspace.tsx", import.meta.url), "utf8");
const userMenu = readFileSync(new URL("../src/components/UserMenu.tsx", import.meta.url), "utf8");
const userMenuCss = readFileSync(new URL("../src/components/UserMenu.module.css", import.meta.url), "utf8");

test("phone workspace uses a denser type and spacing scale without shrinking form controls", () => {
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.workspace-body\{[^}]*font-size:\.94rem[^}]*padding:14px 10px 98px/);
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.page-title h1\{font-size:1\.5rem/);
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.card\{[^}]*padding:16px/);
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.payment-amount\{font-size:2\.35rem/);
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.workspace-body \.input,\.workspace-body \.select,\.workspace-body \.textarea\{font-size:1rem/);
});

test("mobile bottom navigation keeps only overview and collections in two equal columns", () => {
  assert.match(globals, /@media\(max-width:900px\)\{[\s\S]*?\.mobile-nav\{display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.mobile-nav\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.mobile-nav button\{[^}]*min-width:0[^}]*width:100%[^}]*min-height:52px[^}]*padding:10px 0[^}]*display:flex[^}]*justify-content:center[^}]*text-align:center[^}]*font-size:calc\(\.82rem \+ 2px\)/);
  assert.match(workspace, /const mobileNav=primaryNav\.filter\(n=>n\.id!=="lists"\)/);
  assert.match(workspace, /<nav className="mobile-nav">\{mobileNav\.map/);
});

test("contact lists move into the mobile user menu before settings", () => {
  assert.match(workspace, /<UserMenu name=\{user\.display_name\} onLists=\{\(\)=>navigate\("lists"\)\} onSettings=/);
  assert.match(userMenu, /className=\{styles\.mobileOnly\}[^>]*onClick=\{\(\) => select\(onLists\)\}[^>]*>\{t\("participantLists"\)\}<\/button>[\s\S]*>\{t\("settings"\)\}<\/button>/);
  assert.match(userMenuCss, /\.options \.mobileOnly\{display:none\}[\s\S]*@media\(max-width:900px\)\{\.options \.mobileOnly\{display:block\}\}/);
});

test("participant deletion uses an accessible inline svg control on phones", () => {
  assert.match(lists, /className="table participant-table"/);
  assert.match(lists, /className="actions participant-row-actions"/);
  assert.match(lists, /className="button ghost small danger-text participant-action"[^>]*aria-label=\{t\("delete"\)\}/);
  assert.match(lists, /participant-action-icon/);
  assert.match(lists, /<svg/);
  assert.doesNotMatch(lists, /✏|🗑/);
});

test("phone participant rows keep the remaining action compact and reduce row height", () => {
  assert.match(css, /\.participant-action-icon\{display:none/);
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.participant-table\{min-width:560px/);
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.participant-table th,\.participant-table td\{padding:9px 10px/);
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.participant-row-actions\{[^}]*flex-wrap:nowrap[^}]*gap:4px/);
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.participant-action\{width:40px;height:40px;min-height:40px;padding:0/);
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.participant-action-label\{display:none\}/);
  assert.match(css, /@media\(max-width:620px\)\{[\s\S]*?\.participant-action-icon\{display:inline-flex/);
  assert.ok(css.indexOf(".participant-action-icon{display:none") < css.indexOf("@media(max-width:620px)"), "base icon hiding must precede the phone override");
});

test("participant import result controls close their fragment before the form container", () => {
  const importModal = lists.slice(lists.indexOf("function ImportModal"));
  assert.match(importModal, /\{rows&&<>[\s\S]*<\/button><\/>}<\/div><\/Modal>/);
});
