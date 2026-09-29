import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {TERMS_SECTIONS, legalMessages} from "../src/locales/legal.ts";

const source = path => readFileSync(new URL(`../src/${path}`, import.meta.url), "utf8");
const auth = source("components/AuthPanel.tsx");
const api = source("lib/api.ts");

test("every terms section has a title and a text in German and English", () => {
  for (const locale of ["de", "en"]) {
    const messages = legalMessages[locale];
    for (const key of ["portalNavTerms", "portalTermsIntro", "termsVersionLabel", "termsVersionDate", "termsConsentRequired"]) {
      assert.ok(messages[key], `${locale}.${key}`);
    }
    for (const section of TERMS_SECTIONS) {
      assert.ok(messages[`terms_${section}_title`], `${locale} title of ${section}`);
      assert.ok(messages[`terms_${section}_body`], `${locale} text of ${section}`);
    }
  }
});

test("registration requires ticking the terms consent and sends it along", () => {
  assert.match(auth, /<input type="checkbox" checked=\{acceptTerms\} onChange=\{e=>setAcceptTerms\(e\.target\.checked\)\} required\/>/);
  assert.match(auth, /if\(register&&!forgotMode&&!acceptTerms\)\{setError\(t\("termsConsentRequired"\)\);return\}/);
  assert.match(auth, /api\.register\(\{[^}]*accept_terms:true\}\)/);
  assert.match(auth, /<Link href="\/terms\/" target="_blank">/);
  assert.match(auth, /<Link href="\/privacy\/" target="_blank">/);
  assert.match(api, /currency:string;accept_terms:boolean\}/);
});

test("the terms page exists and every public footer links to it", () => {
  assert.match(source("app/terms/page.tsx"), /<PublicLegalPage kind="terms" \/>/);
  assert.match(source("components/PublicLegalPage.tsx"), /\{TERMS_SECTIONS\.map\(section=>/);
  for (const path of ["components/Portal.tsx", "components/PublicPayment.tsx", "components/PublicLegalPage.tsx"]) {
    assert.match(source(path), /href="\/terms\/">\{t\("portalNavTerms"\)\}<\/Link>/, path);
  }
});
