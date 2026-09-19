import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const collections=readFileSync(new URL("../src/components/workspace/CollectionsPage.tsx",import.meta.url),"utf8");
const workspace=readFileSync(new URL("../src/components/Workspace.tsx",import.meta.url),"utf8");
const settings=readFileSync(new URL("../src/components/workspace/SettingsPage.tsx",import.meta.url),"utf8");
const api=readFileSync(new URL("../src/lib/api.ts",import.meta.url),"utf8");
const ux=readFileSync(new URL("../src/locales/ux.ts",import.meta.url),"utf8");

test("real collection dispatch requires an explicit confirmation step",()=>{
  assert.match(collections,/type PendingSendState=/);
  assert.match(collections,/setConfirmSend\(\{item:selected,kind\}\)/);
  assert.match(collections,/function SendConfirmationModal/);
  assert.match(collections,/onConfirm=\{confirmDispatch\}/);
  assert.match(collections,/t\("reallySendNow"\)/);
  assert.doesNotMatch(collections,/if\(detail&&sendNow\)await dispatch\(detail,"initial"\)/);
});

test("test delivery targets the signed-in account and supports phone channels when configured",()=>{
  assert.match(workspace,/<CollectionsPage user=\{user\}/);
  assert.match(settings,/t\("phone"\)/);
  assert.match(collections,/function TestMessageModal/);
  assert.match(collections,/api\.testCollectionMessage/);
  assert.match(collections,/row\.mode==="internal"&&row\.configured/);
  assert.match(api,/testCollectionMessage:/);
});

test("send safety copy is translated through the central i18n layer",()=>{
  assert.match(ux,/sendTestMessage:"Test senden"/);
  assert.match(ux,/confirmRealSend:"Versand bestätigen"/);
  assert.match(ux,/reallySendNow:"Jetzt wirklich versenden"/);
  assert.match(ux,/sendTestMessage:"Send test"/);
});
