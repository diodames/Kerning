import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { stampProfile, mergeProfiles, sameProfile, TOMB_TTL_MS } = require("../merge.js");

const T0 = 1_760_000_000_000;

function profile(extra) {
  return Object.assign({
    weights: {}, ratings: {}, saved: [],
    seeds: { people: [], resources: [], articles: [] }, deleted: {},
  }, extra || {});
}

function edit(prev, mutate, now) {
  const next = JSON.parse(JSON.stringify(prev));
  mutate(next);
  return stampProfile(prev, next, now);
}

test("newer rating wins", () => {
  const base = profile();
  const a = edit(base, (p) => { p.ratings.x = { r: 1, at: T0 }; }, T0);
  const b = edit(base, (p) => { p.ratings.x = { r: -1, at: T0 + 5 }; }, T0 + 5);
  assert.equal(mergeProfiles(a, b, T0 + 10).ratings.x.r, -1);
  assert.equal(mergeProfiles(b, a, T0 + 10).ratings.x.r, -1);
});

test("removing a saved story on one device survives the merge", () => {
  const story = { id: "s1", title: "Grid", url: "https://a.example/grid", at: T0 };
  const shared = edit(profile(), (p) => { p.saved.push(story); }, T0);
  const phone = edit(shared, (p) => { p.saved = []; }, T0 + 100);
  assert.equal(phone.deleted["saved:s1"], T0 + 100);
  assert.deepEqual(mergeProfiles(shared, phone, T0 + 200).saved, []);
  assert.deepEqual(mergeProfiles(phone, shared, T0 + 200).saved, []);
});

test("re-adding after a removal beats the tombstone", () => {
  const story = { id: "s1", title: "Grid", url: "https://a.example/grid", at: T0 };
  const saved = edit(profile(), (p) => { p.saved.push(story); }, T0);
  const removed = edit(saved, (p) => { p.saved = []; }, T0 + 10);
  const readded = edit(removed, (p) => { p.saved.push(Object.assign({}, story, { at: T0 + 20 })); }, T0 + 20);
  assert.equal(readded.deleted["saved:s1"], undefined);
  assert.equal(mergeProfiles(removed, readded, T0 + 30).saved.length, 1);
});

test("concurrent additions on both devices keep both", () => {
  const base = profile();
  const laptop = edit(base, (p) => {
    p.seeds.people.push({ id: "bsky:adactio.com", network: "bsky", handle: "adactio.com", addedAt: T0 });
    p.saved.push({ id: "s1", url: "https://a.example", at: T0 });
  }, T0);
  const phone = edit(base, (p) => {
    p.seeds.resources.push({ id: "rss:b.example/feed", kind: "rss", feed: "https://b.example/feed", addedAt: T0 + 1 });
    p.saved.push({ id: "s2", url: "https://b.example", at: T0 + 1 });
  }, T0 + 1);
  const merged = mergeProfiles(laptop, phone, T0 + 2);
  assert.deepEqual(merged.seeds.people.map((p) => p.id), ["bsky:adactio.com"]);
  assert.deepEqual(merged.seeds.resources.map((r) => r.id), ["rss:b.example/feed"]);
  assert.deepEqual(merged.saved.map((s) => s.id), ["s2", "s1"]);
});

test("catalog defaults never revive a resource deleted elsewhere", () => {
  const def = { id: "rss:nngroup", kind: "rss", feed: "https://nngroup.com/feed", addedAt: 0 };
  const old = edit(profile(), (p) => { p.seeds.resources.push(Object.assign({}, def)); }, T0);
  assert.equal(old.seeds.resources[0].mt, 0);
  const pruned = edit(old, (p) => { p.seeds.resources = []; }, T0 + 10);
  const fresh = edit(profile(), (p) => { p.seeds.resources.push(Object.assign({}, def)); }, T0 + 50);
  assert.deepEqual(mergeProfiles(fresh, pruned, T0 + 60).seeds.resources, []);
});

test("unchanged entries keep their mt; renames bump it", () => {
  const a = edit(profile(), (p) => {
    p.seeds.articles.push({ id: "art:x", url: "https://x.example", title: "X", addedAt: T0 });
  }, T0);
  const same = edit(a, () => {}, T0 + 10);
  assert.equal(same.seeds.articles[0].mt, T0);
  const renamed = edit(a, (p) => { p.seeds.articles[0].title = "Y"; }, T0 + 20);
  assert.equal(renamed.seeds.articles[0].mt, T0 + 20);
  assert.equal(mergeProfiles(a, renamed, T0 + 30).seeds.articles[0].title, "Y");
});

test("sameProfile ignores key order and weights", () => {
  const a = { weights: { css: 1 }, ratings: { x: { r: 1, at: 1 } }, saved: [], deleted: {} };
  const b = { deleted: {}, saved: [], ratings: { x: { at: 1, r: 1 } } };
  assert.ok(sameProfile(a, b));
  assert.ok(!sameProfile(a, { ratings: { x: { r: -1, at: 1 } }, saved: [], deleted: {} }));
});

test("old tombstones are pruned", () => {
  const p = profile({ deleted: { "saved:old": T0, "saved:new": T0 + TOMB_TTL_MS } });
  const merged = mergeProfiles(p, profile(), T0 + TOMB_TTL_MS + 1);
  assert.equal(merged.deleted["saved:old"], undefined);
  assert.equal(merged.deleted["saved:new"], T0 + TOMB_TTL_MS);
});

test("catalog flags merge and weights are left to the caller", () => {
  const a = profile({ weights: { css: 3 }, seeds: { people: [], resources: [], articles: [], resourcesCatalog: 1 } });
  const b = profile({ seeds: { people: [], resources: [], articles: [], peopleCatalog: 2 } });
  const merged = mergeProfiles(a, b, T0);
  assert.equal(merged.seeds.resourcesCatalog, 1);
  assert.equal(merged.seeds.peopleCatalog, 2);
  assert.deepEqual(merged.weights, {});
  assert.ok(sameProfile(merged, mergeProfiles(merged, b, T0)));
});
