/* Kerning taste: tokens, learned weights, and the personal rerank.
 *
 * Shared by index.html and scripts/weekly_email.mjs so the site and the
 * weekly email order an edition the same way. Every function takes the
 * profile explicitly; nothing here reads globals.
 */
(function (root) {
  "use strict";

  const LEXICON = [
    ["typography",3,"typographic"],["typeface",3],["typesetting",3],["kerning",3],
    ["baseline grid",3],["font",3,"fonts"],["variable font",3],["lettering",3],
    ["figma",3],["design system",3,"design systems"],["design token",3,"design tokens"],
    ["ux",3,"user experience"],["ui",3,"user interface"],["usability",3],
    ["interaction design",3],["visual design",3],["graphic design",3],
    ["product design",3],["industrial design",3],["information architecture",3],
    ["wireframe",3],["human interface",3],["material design",3],["skeuomorph",3],
    ["bauhaus",3],["swiss design",3],["illustration",3],["iconography",3],
    ["accessibility",3,"a11y"],["wcag",3],["screen reader",3],["motion design",3],
    ["brand identity",3],["color palette",3],["grid system",3],["web design",3],
    ["logo",3],["legibility",3],["type design",3],
    ["icons",2],["illustrator",2],["branding",2],["palette",2],["colour",2],
    ["layout",2],["css",2],["tailwind",2],["svg",2],["animation",2],["prototype",2,"prototyping"],
    ["poster",2],["dark mode",2],["aesthetic",2,"aesthetics"],
    ["designer",2],["redesign",2],["readability",2],
    ["product strategy",2],["product sense",2],["roadmap",2],
    ["prioritization",2],["prd",2],["user research",2],
    ["outcome-based",2],["product-led",2],
    ["product management",3],["product manager",3],
    ["product discovery",3],["jobs to be done",3,"jtbd"],
    ["opportunity solution tree",3],["dual-track",3],
    ["continuous discovery",3],["product ops",3],
    ["design",1],["craft",1],["interface",1],
  ];

  const MAX_PER_DOMAIN = 2;
  const MAX_PER_SOURCE = 4;
  const TASTE_WEIGHT = 2.0;
  const DOWNVOTE_PENALTY = 8;
  const MATCHES_PROFILE = "matches your profile";

  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));

  function domainOf(url) {
    if (!url) return "";
    try { return new URL(url).hostname.replace(/^www\./, ""); } catch (e) { return ""; }
  }

  function normalizeArticleUrl(raw) {
    const s = String(raw || "").trim();
    if (!s) return "";
    try {
      const u = new URL(/^https?:\/\//i.test(s) ? s : "https://" + s);
      u.hash = "";
      return u.toString();
    } catch (e) {
      return "";
    }
  }

  // For typed input only. normalizeArticleUrl stays lenient because it also
  // builds canonical keys for stored items.
  function looksLikeWebUrl(raw) {
    const s = String(raw || "").trim();
    if (!s || /\s/.test(s)) return false;
    if (/^[a-z][a-z0-9+.-]*:/i.test(s) && !/^https?:\/\//i.test(s)) return false;
    const url = normalizeArticleUrl(s);
    if (!url) return false;
    const host = new URL(url).hostname;
    return /^([a-z0-9-]+\.)+([a-z]{2,}|xn--[a-z0-9-]+)$/i.test(host);
  }

  function canonUrl(url) {
    return normalizeArticleUrl(url).replace(/\/+$/, "").toLowerCase();
  }

  function lexiconFormHits(hay, form) {
    return form.indexOf(" ") >= 0
      ? hay.indexOf(form) >= 0
      : new RegExp("\\b" + form.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b").test(hay);
  }

  function lexiconEntryHits(hay, entry) {
    if (lexiconFormHits(hay, entry[0])) return true;
    for (let i = 2; i < entry.length; i++) {
      if (lexiconFormHits(hay, entry[i])) return true;
    }
    return false;
  }

  function tokensOf(item) {
    const hay = ((item.title || "") + " " + domainOf(item.url)).toLowerCase();
    const set = new Set();
    for (let i = 0; i < LEXICON.length; i++) {
      const entry = LEXICON[i];
      if (entry[1] < 2) continue;
      if (lexiconEntryHits(hay, entry)) set.add(entry[0]);
    }
    const d = domainOf(item.url);
    if (d) set.add("site:" + d);
    (item.authors || []).forEach((a) => {
      if (a) set.add("person:" + String(a).toLowerCase());
    });
    return Array.from(set);
  }

  function isPackPerson(p) {
    if (!p) return false;
    if (p.pack === "x-following") return true;
    return p.addedAt === 0 && p.network === "x";
  }

  // Rating records carry their own title, url, and authors; `items` only
  // fills gaps for older records that lack them.
  function buildWeights(profile, items) {
    const byId = {};
    (items || []).forEach((it) => { if (it && !byId[it.id]) byId[it.id] = it; });
    const seeds = profile.seeds || {};
    const weights = {};
    function bump(tokens, delta) {
      tokens.forEach((t) => {
        weights[t] = clamp((weights[t] || 0) + delta, -6, 6);
      });
    }
    const articleCanons = {};
    (seeds.articles || []).forEach((a) => {
      if (!a || !a.url) return;
      const c = canonUrl(a.url);
      if (c) articleCanons[c] = true;
      bump(tokensOf({ title: a.title || "", url: a.url }), 1);
    });
    (seeds.people || []).forEach((p) => {
      if (!p || !p.handle) return;
      bump(["person:" + String(p.handle).toLowerCase()], 2);
      const seen = new Set();
      (p.links || []).forEach((lnk) => {
        tokensOf({ title: (lnk && lnk.title) || "", url: (lnk && lnk.url) || "" })
          .forEach((t) => { if (t.indexOf("person:") !== 0) seen.add(t); });
      });
      bump(Array.from(seen), 1);
    });
    const ratings = profile.ratings || {};
    Object.keys(ratings).forEach((id) => {
      const rec = ratings[id];
      if (!rec || !rec.r) return;
      const src = byId[id] || {};
      const item = {
        id: id,
        title: src.title || rec.title || "",
        url: src.url || rec.url || "",
        authors: src.authors || rec.authors || [],
      };
      let toks = tokensOf(item);
      if (rec.r < 0) toks = toks.filter((t) => t.indexOf("site:") !== 0);
      // A liked story that also sits in Articles you like is one signal.
      else if (articleCanons[canonUrl(item.url)]) return;
      bump(toks, rec.r);
    });
    return weights;
  }

  // Only the reader's own signals count; the default people pack seeds
  // weights for everyone and must not reorder the published picks.
  function hasLearnedTaste(profile, weights) {
    const seeds = profile.seeds || {};
    const own = Object.keys(profile.ratings || {}).length > 0
      || (seeds.articles || []).length > 0
      || (seeds.people || []).some((p) => !isPackPerson(p));
    return own && Object.keys(weights).some((k) => weights[k]);
  }

  function learnedScore(weights, item) {
    const toks = tokensOf(item);
    let sum = 0;
    toks.forEach((t) => { sum += weights[t] || 0; });
    return sum / Math.sqrt(Math.max(toks.length, 1));
  }

  function downvotedCanons(profile) {
    const set = {};
    const ratings = profile.ratings || {};
    Object.keys(ratings).forEach((id) => {
      const rec = ratings[id];
      if (!rec || !(rec.r < 0)) return;
      const c = canonUrl(rec.url);
      if (c) set[c] = true;
    });
    return set;
  }

  function isDownvoted(profile, item, canons) {
    if (!item) return false;
    const rec = (profile.ratings || {})[item.id];
    if (rec && rec.r < 0) return true;
    const c = canonUrl(item.url);
    return !!(c && (canons || downvotedCanons(profile))[c]);
  }

  // Same caps as diversify() in kerning_fetch.py. Pinned items keep their slots.
  function diversifyItems(items, limit, pinned) {
    const perDomain = {};
    const perSource = {};
    const out = [];
    const taken = new Set();
    function take(it) {
      const d = domainOf(it.url);
      const s = (it.sources || [])[0] || "";
      perDomain[d] = (perDomain[d] || 0) + 1;
      perSource[s] = (perSource[s] || 0) + 1;
      taken.add(it.id);
      out.push(it);
    }
    (pinned || []).forEach(take);
    for (const it of items) {
      if (out.length >= limit) break;
      if (taken.has(it.id)) continue;
      const d = domainOf(it.url);
      const s = (it.sources || [])[0] || "";
      if ((perDomain[d] || 0) >= MAX_PER_DOMAIN || (perSource[s] || 0) >= MAX_PER_SOURCE) continue;
      take(it);
    }
    return out;
  }

  // Rerank an edition's candidates by the profile's taste. Without learned
  // weights the published picks come back as they are.
  function personalize(profile, weights, candidates, picks, pinnedIds) {
    if (!hasLearnedTaste(profile, weights)) return picks.slice();
    const limit = picks.length;
    const canons = downvotedCanons(profile);
    const scored = candidates.map((it) => {
      const learned = learnedScore(weights, it);
      const total = (it.score || 0) + TASTE_WEIGHT * learned
        - (isDownvoted(profile, it, canons) ? DOWNVOTE_PENALTY : 0);
      let reasons = it.reasons || [];
      if (learned >= 0.6 && !reasons.some((r) => r[0] === MATCHES_PROFILE)) {
        reasons = reasons.concat([[MATCHES_PROFILE, 1]]);
      }
      return Object.assign({}, it, { total: total, reasons: reasons });
    }).sort((a, b) => b.total - a.total);
    const pinned = pinnedIds ? scored.filter((it) => pinnedIds[it.id]) : [];
    return diversifyItems(scored, limit, pinned).sort((a, b) => b.total - a.total);
  }

  const api = {
    LEXICON: LEXICON,
    MATCHES_PROFILE: MATCHES_PROFILE,
    clamp: clamp,
    domainOf: domainOf,
    normalizeArticleUrl: normalizeArticleUrl,
    looksLikeWebUrl: looksLikeWebUrl,
    canonUrl: canonUrl,
    lexiconFormHits: lexiconFormHits,
    lexiconEntryHits: lexiconEntryHits,
    tokensOf: tokensOf,
    isPackPerson: isPackPerson,
    buildWeights: buildWeights,
    hasLearnedTaste: hasLearnedTaste,
    learnedScore: learnedScore,
    diversifyItems: diversifyItems,
    personalize: personalize,
  };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.KerningTaste = api;
})(typeof window !== "undefined" ? window : globalThis);
