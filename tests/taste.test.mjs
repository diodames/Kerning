import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { buildWeights, personalize, tokensOf, hasLearnedTaste, looksLikeWebUrl } = require("../taste.js");

function profile(extra) {
  return Object.assign({
    ratings: {}, saved: [], seeds: { people: [], resources: [], articles: [] }, deleted: {},
  }, extra || {});
}

function item(id, title, url, extra) {
  return Object.assign({ id: id, title: title, url: url, score: 5, sources: ["hn"], reasons: [] }, extra || {});
}

test("tokens include lexicon terms, site, and authors", () => {
  const toks = tokensOf({ title: "Variable font tricks", url: "https://www.example.com/a", authors: ["Ann"] });
  assert.ok(toks.includes("font"));
  assert.ok(toks.includes("variable font"));
  assert.ok(toks.includes("site:example.com"));
  assert.ok(toks.includes("person:ann"));
});

test("typed URLs need a real-looking host", () => {
  for (const ok of ["example.com", "https://www.example.com/a?b=1", "http://sub.example.co.uk/x",
    "blog.example.dev/post#top", "xn--bcher-kva.example"]) {
    assert.equal(looksLikeWebUrl(ok), true, ok);
  }
  for (const bad of ["", "nope", "foo bar.com", "https://localhost", "example.", "ftp://example.com",
    "mailto:a@example.com", "javascript:alert(1)", "example.c0m"]) {
    assert.equal(looksLikeWebUrl(bad), false, bad);
  }
});

test("ratings move weights; downvotes skip the site token", () => {
  const p = profile({ ratings: {
    a: { r: 1, title: "Typography basics", url: "https://type.example/a" },
    b: { r: -1, title: "Figma plugin", url: "https://plug.example/b" },
  } });
  const w = buildWeights(p, []);
  assert.equal(w.typography, 1);
  assert.equal(w["site:type.example"], 1);
  assert.equal(w.figma, -1);
  assert.equal(w["site:plug.example"], undefined);
});

test("without learned taste the published picks come back unchanged", () => {
  const picks = [item("1", "One", "https://a.example/1"), item("2", "Two", "https://b.example/2")];
  const cands = picks.concat([item("3", "Typography", "https://c.example/3", { score: 50 })]);
  const p = profile({ seeds: { people: [{ network: "x", handle: "pack", addedAt: 0, pack: "x-following" }],
    resources: [], articles: [] } });
  const w = buildWeights(p, []);
  assert.equal(hasLearnedTaste(p, w), false);
  assert.deepEqual(personalize(p, w, cands, picks).map((i) => i.id), ["1", "2"]);
});

test("taste promotes matching candidates and penalises downvotes", () => {
  const picks = [item("1", "Generic news", "https://a.example/1", { score: 6 }),
    item("2", "Other news", "https://b.example/2", { score: 5.5 })];
  const cands = picks.concat([item("3", "Typography and kerning", "https://c.example/3", { score: 4 })]);
  const p = profile({ ratings: {
    x: { r: 1, title: "Typography and kerning notes", url: "https://c.example/old" },
    "1": { r: -1, title: "Generic news", url: "https://a.example/1" },
  } });
  const w = buildWeights(p, []);
  const out = personalize(p, w, cands, picks);
  assert.deepEqual(out.map((i) => i.id), ["3", "2"]);
  assert.ok(out[0].reasons.some((r) => r[0] === "matches your profile"));
});

test("diversity caps two per domain; pinned items keep their slot", () => {
  const p = profile({ ratings: { x: { r: 1, title: "Typography", url: "https://same.example/x" } } });
  const w = buildWeights(p, []);
  const cands = [1, 2, 3, 4].map((n) => item("s" + n, "Typography " + n, "https://same.example/" + n, { score: 10 - n }))
    .concat([item("o", "Other", "https://other.example/o", { score: 1 })]);
  const picks = cands.slice(0, 3);
  assert.deepEqual(personalize(p, w, cands, picks).map((i) => i.id), ["s1", "s2", "o"]);
  const pinned = personalize(p, w, cands, picks, { s4: true }).map((i) => i.id);
  assert.ok(pinned.includes("s4"));
  assert.equal(pinned.length, 3);
});
