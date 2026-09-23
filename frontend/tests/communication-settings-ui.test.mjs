import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const communication = readFileSync(new URL("../src/components/workspace/CommunicationSettingsPanel.tsx", import.meta.url), "utf8");

test("communication channel test feedback stays local to the test button", () => {
  const start = communication.indexOf("async function testChannel");
  const end = communication.indexOf("\n\n  return <>", start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const testChannel = communication.slice(start, end);

  assert.match(testChannel, /setTestResults\(current=>\(\{\.\.\.current,\[channel\]:result\.ok\?"ok":"error"\}\)\)/);
  assert.doesNotMatch(testChannel, /setNotice\(result\.ok\?t\("connectionOk"\)/);
  assert.match(communication, /connection-test-result/);
  assert.match(communication, /actions connection-test-actions/);
  assert.match(communication, /testResults\[channel\]==="ok"\?"✓":"×"/);
});

test("starting a connection test clears any unrelated page notice", () => {
  assert.match(communication, /setTestingChannel\(channel\);setNotice\(""\)/);
});
