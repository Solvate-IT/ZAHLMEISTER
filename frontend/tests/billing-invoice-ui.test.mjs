import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const page=readFileSync(new URL("../src/components/workspace/BillingPage.tsx",import.meta.url),"utf8");
const api=readFileSync(new URL("../src/lib/api.ts",import.meta.url),"utf8");
const locale=readFileSync(new URL("../src/locales/billing.ts",import.meta.url),"utf8");

test("billing history exposes authenticated invoice PDF downloads",()=>{
  assert.match(api,/billingInvoicePdf:/);
  assert.match(page,/saveDownload\(api\.billingInvoicePdf\(item\.id\)\)/);
  assert.match(page,/t\("billingInvoicePdf"\)/);
  assert.match(locale,/de:"Rechnung anzeigen"/);
  assert.match(locale,/en:"View invoice"/);
});

test("paid invoices still waiting for a Mollie number show a clear processing state",()=>{
  assert.match(page,/!item\.invoice_number&&item\.status==="paid".*t\("billingInvoicePreparing"\)/s);
  assert.match(locale,/billingInvoicePreparing/);
});
