import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const collections=readFileSync(new URL("../src/components/workspace/CollectionsPage.tsx",import.meta.url),"utf8");
const lists=readFileSync(new URL("../src/components/workspace/ListsPage.tsx",import.meta.url),"utf8");
const workspace=readFileSync(new URL("../src/components/Workspace.tsx",import.meta.url),"utf8");
const settings=readFileSync(new URL("../src/components/workspace/SettingsPage.tsx",import.meta.url),"utf8");
const api=readFileSync(new URL("../src/lib/api.ts",import.meta.url),"utf8");
const ux=readFileSync(new URL("../src/locales/ux.ts",import.meta.url),"utf8");
const toast=readFileSync(new URL("../src/components/ToastHost.tsx",import.meta.url),"utf8");

test("real collection dispatch requires an explicit confirmation step",()=>{
  assert.match(collections,/type PendingSendState=/);
  assert.match(collections,/setConfirmSend\(\{item:selected,kind\}\)/);
  assert.match(collections,/function SendConfirmationModal/);
  assert.match(collections,/onConfirm=\{confirmDispatch\}/);
  assert.match(collections,/t\("reallySendNow"\)/);
  assert.doesNotMatch(collections,/if\(detail&&sendNow\)await dispatch\(detail,"initial"\)/);
});

test("test message queues a single email to the signed-in creator and shows receipt",()=>{
  assert.match(collections,/api\.testCollectionMessage\(item\.id,"email"\)/);
  assert.match(collections,/testMessageQueued/);
  assert.match(collections,/showToast\(\{message:t\("testMessageQueued"/);
  assert.match(toast,/setTimeout\(\(\) => setToast\(null\), toast\.action \? 8000 : 2000\)/);
  assert.doesNotMatch(collections,/function TestMessageModal/);
});

test("send errors remain visible over the confirmation dialog and link to payment settings",()=>{
  assert.match(collections,/showToast\(\{message:t\("paymentAccountRequired"\),kind:"error",action:/);
  assert.match(collections,/href:"\/app\?view=settings&section=payment"/);
  assert.match(toast,/className=\{`toast app-toast/);
});

test("the selected template is used for both test and real sending",()=>{
  assert.match(collections,/templates\.length>1/);
  assert.match(collections,/onTest\(templateId\)/);
  assert.match(collections,/dispatch\(pending\.item,pending\.kind,templateId\)/);
  assert.match(collections,/api\.updateCollection\(item\.id,\{message_template_id:templateId\}\)/);
});

test("manual send prepares the draft before the user clicks to open an app",()=>{
  const assistant=collections.slice(collections.indexOf("function ExternalSendAssistant"),collections.indexOf("function Metric"));
  assert.match(assistant,/api\.createExternalDraft/);
  assert.match(assistant,/draft\.launch_uri/);
  assert.match(assistant,/openExternalUri\(draft\.launch_uri\)/);
});

test("delete and cancel actions are kept separate from delivery",()=>{
  assert.match(api,/deleteCollection:/);
  assert.match(api,/cancelCollection:/);
  assert.match(collections,/item\.status==="cancelled"/);
  assert.match(collections,/api\.deleteCollection/);
  assert.match(collections,/api\.cancelCollection/);
});

test("channel summaries exclude disabled channels in both collection views",()=>{
  assert.match(collections,/function activeChannelSummary/);
  assert.match(collections,/activeChannelSummary\(item,t,/g);
  assert.match(collections,/enabledChannels\.map\(channel=>/);
  assert.match(lists,/contactChannels\.filter\(channel=>!organizationDisabled\?\.has\(channel\)\)/);
  assert.match(api,/communicationSettings:/);
});

test("collection and list rows open by mouse and keyboard",()=>{
  assert.match(collections,/onClick=\{\(\)=>void open\(c\.id\)\}/);
  assert.match(lists,/onClick=\{\(\)=>void openList\(l\.id\)\}/);
  assert.match(collections,/onKeyDown=\{e=>\{if\(e\.key==="Enter"/);
  assert.match(lists,/onKeyDown=\{e=>\{if\(e\.key==="Enter"/);
});

test("send safety copy is translated through the central i18n layer",()=>{
  assert.match(ux,/sendTestMessage:"Test senden"/);
  assert.match(ux,/confirmRealSend:"Versand bestätigen"/);
  assert.match(ux,/reallySendNow:"Jetzt wirklich versenden"/);
  assert.match(ux,/sendTestMessage:"Send test"/);
});
