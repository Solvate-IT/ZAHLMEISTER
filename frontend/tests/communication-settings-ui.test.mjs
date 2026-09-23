import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const communication = readFileSync(new URL("../src/components/workspace/CommunicationSettingsPanel.tsx", import.meta.url), "utf8");

test("communication channel test feedback stays local to the test button", () => {
  assert.match(communication, /setTestResults\(current=>\(\{\.\.\.current,\[channel\]:result\.ok\?"ok":"error"\}\)\)/);
  assert.match(communication, /connection-test-result/);
  assert.match(communication, /testResults\[channel\]==="ok"\?"✓":"×"/);
  assert.doesNotMatch(communication, /setNotice\(result\.ok\?t\("connectionOk"\)/);
});

test("starting a connection test clears any unrelated page notice", () => {
  assert.match(communication, /setTestingChannel\(channel\);setNotice\(""\)/);
});
