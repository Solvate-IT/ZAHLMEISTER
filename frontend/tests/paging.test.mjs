import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {PAGE_SIZE, collectPages, withQuery} from "../src/lib/paging.ts";

const source = path => readFileSync(new URL(`../src/${path}`, import.meta.url), "utf8");

function page(rows, total) {
  const headers = {"Content-Type": "application/json"};
  if (total !== undefined) headers["X-Total-Count"] = String(total);
  return new Response(JSON.stringify(rows), {headers});
}

test("reads a paged list page by page until the total is reached", async () => {
  const queries = [];
  const first = Array.from({length: PAGE_SIZE}, (_, index) => ({id: index}));
  const pages = [page(first, PAGE_SIZE + 2), page([{id: "a"}, {id: "b"}], PAGE_SIZE + 2)];
  const rows = await collectPages(async query => {
    queries.push(query);
    return pages.shift();
  });
  assert.equal(rows.length, PAGE_SIZE + 2);
  assert.deepEqual(queries, [`limit=${PAGE_SIZE}&offset=0`, `limit=${PAGE_SIZE}&offset=${PAGE_SIZE}`]);
});

test("treats a response without a total as the whole list", async () => {
  let calls = 0;
  const rows = await collectPages(async () => {
    calls += 1;
    return page([{id: 1}]);
  });
  assert.deepEqual(rows, [{id: 1}]);
  assert.equal(calls, 1);
});

test("appends the paging query to paths with and without a query string", () => {
  assert.equal(withQuery("/collections", "limit=1"), "/collections?limit=1");
  assert.equal(withQuery("/collections?status=open", "limit=1"), "/collections?status=open&limit=1");
});

test("list screens read every page of the paged endpoints", () => {
  const api = source("lib/api.ts");
  assert.match(api, /lists:\(\)=>requestAll<T\.ParticipantListSummary>\("\/participant-lists"\)/);
  assert.match(api, /collections:\(\)=>requestAll<T\.CollectionSummary>\("\/collections"\)/);
  assert.match(api, /openBalances:\(\)=>requestAll<T\.ParticipantOpenBalance>\("\/collections\/open-balances"\)/);
  assert.match(source("lib/adminApi.ts"), /customers:\(\)=>collectPages<PlatformCustomer>\(/);
});
