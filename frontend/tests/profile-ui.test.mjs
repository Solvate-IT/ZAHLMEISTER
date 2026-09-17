import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const billing = readFileSync(new URL("../src/components/workspace/BillingPage.tsx", import.meta.url), "utf8");
const settings = readFileSync(new URL("../src/components/workspace/SettingsPage.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");

test("new billing profiles default to Austria and keep Austria first", () => {
  assert.match(billing, /const DEFAULT_COUNTRY:CountryCode="AT"/);
  assert.match(billing, /country:DEFAULT_COUNTRY/);
  assert.match(billing, /preferredCountries/);
});

test("profile language is a supported-locale dropdown", () => {
  assert.match(settings, /supportedLocales/);
  assert.match(settings, /setLocale/);
  assert.match(settings, /<select[^>]+value=\{locale\}/);
  assert.match(settings, /supportedLocales\.map/);
});

test("account restore bypasses browser cache", () => {
  assert.match(api, /request<T\.AccountUser>\("\/auth\/me",\{cache:"no-store"\}\)/);
});

test("resend verification handles already verified accounts", () => {
  assert.match(api, /status:"verified"\|"sent"\|"already_verified"/);
  assert.match(settings, /result\.status==="already_verified"/);
  assert.match(settings, /api\.restore\(\)/);
});
