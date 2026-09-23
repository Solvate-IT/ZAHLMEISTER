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

test("test preview opens one participant draft at a time without recording delivery",()=>{
  assert.match(collections,/api\.previewCollectionDispatch/);
  assert.match(collections,/function TestMessageModal/);
  assert.match(collections,/openExternalUri\(current\.launch_uri\)/);
  const preview=collections.slice(collections.indexOf("function TestMessageModal"),collections.indexOf("function ExternalSendAssistant"));
  assert.doesNotMatch(preview,/api\.testCollectionMessage|api\.markExternalOpened|api\.confirmExternalResult/);
  assert.match(api,/previewCollectionDispatch:/);
});

test("channel summaries exclude disabled channels in both collection views",()=>{
  assert.match(collections,/function activeChannelSummary/);
  assert.match(collections,/activeChannelSummary\(item,t,/g);
  assert.match(api,/communicationSettings:/);
});

test("send safety copy is translated through the central i18n layer",()=>{
  assert.match(ux,/sendTestMessage:"Test senden"/);
  assert.match(ux,/confirmRealSend:"Versand bestätigen"/);
  assert.match(ux,/reallySendNow:"Jetzt wirklich versenden"/);
  assert.match(ux,/sendTestMessage:"Send test"/);
});
