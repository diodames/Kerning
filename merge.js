/* Kerning profile merge: per-entry last-write-wins with tombstones.
 *
 * Every rating, saved story, person, resource, and article carries `mt`, the
 * time it last changed. Removing one writes `deleted[key] = time`. Merging
 * two profiles keeps, for each key, the newer entry unless a newer tombstone
 * outlives it. `weights` is derived, so callers rebuild it after a merge.
 */
(function (root) {
  "use strict";

  const TOMB_TTL_MS = 90 * 86400 * 1000;
  const SEED_KINDS = ["people", "resources", "articles"];

  function clone(x) {
    return JSON.parse(JSON.stringify(x));
  }

  function seedPrefix(kind) {
    return kind === "people" ? "person:" : kind === "resources" ? "resource:" : "article:";
  }

  // key -> { kind, value } for every syncable entry.
  function entries(p) {
    const out = new Map();
    if (!p) return out;
    Object.keys(p.ratings || {}).forEach((id) => {
      if (p.ratings[id]) out.set("rating:" + id, { kind: "ratings", id: id, value: p.ratings[id] });
    });
    (p.saved || []).forEach((s) => {
      if (s && s.id) out.set("saved:" + s.id, { kind: "saved", value: s });
    });
    const seeds = p.seeds || {};
    SEED_KINDS.forEach((kind) => {
      (seeds[kind] || []).forEach((v) => {
        if (v && v.id) out.set(seedPrefix(kind) + v.id, { kind: kind, value: v });
      });
    });
    return out;
  }

  function sameContent(a, b) {
    const x = Object.assign({}, a, { mt: 0 });
    const y = Object.assign({}, b, { mt: 0 });
    return JSON.stringify(x) === JSON.stringify(y);
  }

  function pruneTombs(deleted, now) {
    const out = {};
    Object.keys(deleted || {}).forEach((k) => {
      const t = Number(deleted[k]) || 0;
      if (now - t < TOMB_TTL_MS) out[k] = t;
    });
    return out;
  }

  /* Stamp `next` against the last saved `prev`: changed or new entries get
   * mt = now, removed ones get a tombstone. Catalog defaults (addedAt 0)
   * start at mt 0 so seeding a fresh device never revives a deleted one.
   * Mutates and returns next. */
  function stampProfile(prev, next, now) {
    now = now || Date.now();
    const before = entries(prev);
    const after = entries(next);
    const deleted = Object.assign({}, (prev && prev.deleted) || {}, next.deleted || {});
    after.forEach((cur, key) => {
      const old = before.get(key);
      if (old && sameContent(old.value, cur.value)) {
        cur.value.mt = Number(old.value.mt) || 0;
        return;
      }
      if (!old && cur.value.addedAt === 0 && !cur.value.mt) {
        cur.value.mt = 0;
        return;
      }
      cur.value.mt = now;
      if (deleted[key] && deleted[key] < now) delete deleted[key];
    });
    before.forEach((_, key) => {
      if (!after.has(key)) deleted[key] = now;
    });
    next.deleted = pruneTombs(deleted, now);
    return next;
  }

  function mergeProfiles(a, b, now) {
    now = now || Date.now();
    a = a || {};
    b = b || {};
    const ea = entries(a);
    const eb = entries(b);
    const deleted = {};
    [a.deleted || {}, b.deleted || {}].forEach((d) => {
      Object.keys(d).forEach((k) => {
        deleted[k] = Math.max(deleted[k] || 0, Number(d[k]) || 0);
      });
    });

    const keys = [];
    const seen = new Set();
    ea.forEach((_, k) => { seen.add(k); keys.push(k); });
    eb.forEach((_, k) => { if (!seen.has(k)) keys.push(k); });

    const out = {
      weights: {},
      ratings: {},
      saved: [],
      seeds: { people: [], resources: [], articles: [] },
    };
    keys.forEach((k) => {
      const x = ea.get(k);
      const y = eb.get(k);
      let win = x || y;
      if (x && y && (Number(y.value.mt) || 0) > (Number(x.value.mt) || 0)) win = y;
      const mt = Number(win.value.mt) || 0;
      if (deleted[k] && deleted[k] >= mt) return;
      const value = clone(win.value);
      if (win.kind === "ratings") out.ratings[win.id] = value;
      else if (win.kind === "saved") out.saved.push(value);
      else out.seeds[win.kind].push(value);
    });
    out.saved.sort((p, q) => (Number(q.at) || 0) - (Number(p.at) || 0));

    const sa = a.seeds || {};
    const sb = b.seeds || {};
    if (sa.resourcesCatalog || sb.resourcesCatalog) out.seeds.resourcesCatalog = 1;
    const pc = Math.max(Number(sa.peopleCatalog) || 0, Number(sb.peopleCatalog) || 0);
    if (pc) out.seeds.peopleCatalog = pc;
    out.deleted = pruneTombs(deleted, now);
    return out;
  }

  function stableStringify(x) {
    if (Array.isArray(x)) return "[" + x.map(stableStringify).join(",") + "]";
    if (x && typeof x === "object") {
      return "{" + Object.keys(x).filter((k) => x[k] !== undefined).sort()
        .map((k) => JSON.stringify(k) + ":" + stableStringify(x[k])).join(",") + "}";
    }
    return JSON.stringify(x);
  }

  // True when two profiles hold the same synced content, in any key order.
  function sameProfile(a, b) {
    const strip = (p) => {
      const c = Object.assign({}, p || {});
      delete c.weights;
      return stableStringify(c);
    };
    return strip(a) === strip(b);
  }

  const api = { stampProfile: stampProfile, mergeProfiles: mergeProfiles, sameProfile: sameProfile,
    TOMB_TTL_MS: TOMB_TTL_MS };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.KerningMerge = api;
})(typeof window !== "undefined" ? window : globalThis);
