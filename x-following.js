/* ------------------------------------------------------------------
   Export your X following list to a text file.

   1. Open https://x.com/martinandrle/following while logged in.
   2. Open the browser console (F12, or Cmd+Option+J on Mac).
   3. Paste this whole file, press Enter, and leave the tab alone.

   It scrolls to the bottom collecting handles, then downloads
   following.txt. X renders the list in a virtual scroller, so a few
   accounts can be missed on a fast pass — run it twice and diff if you
   want to be thorough.

   This reads a page you are already logged into. No token, no cookie,
   no third party.
   ------------------------------------------------------------------ */

(async () => {
  const found = new Set();

  // X reserves these paths for its own navigation, not user profiles.
  const RESERVED = new Set([
    "home", "explore", "notifications", "messages", "settings", "compose",
    "search", "i", "following", "followers", "bookmarks", "lists", "topics",
    "jobs", "premium_sign_up", "tos", "privacy", "about", "login", "signup",
  ]);

  const grab = () => {
    document.querySelectorAll('a[role="link"][href^="/"]').forEach((a) => {
      const m = (a.getAttribute("href") || "").match(/^\/([A-Za-z0-9_]{1,15})$/);
      if (m && !RESERVED.has(m[1].toLowerCase())) found.add(m[1]);
    });
  };

  let previous = -1;
  let idleRounds = 0;

  while (idleRounds < 6) {
    grab();
    window.scrollBy(0, window.innerHeight * 2.5);
    await new Promise((r) => setTimeout(r, 900));
    idleRounds = found.size === previous ? idleRounds + 1 : 0;
    previous = found.size;
    console.log(`${found.size} handles…`);
  }

  grab();
  const list = [...found].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
  const blob = new Blob([list.join("\n") + "\n"], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "following.txt";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);

  console.log(`Saved following.txt — ${list.length} handles.`);
})();
