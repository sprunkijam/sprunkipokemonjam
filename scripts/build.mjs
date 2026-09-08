#!/usr/bin/env node
/**
 * Package sprunki-base.sb3 with TurboWarp Packager into a static site under dist/.
 * Uses target "zip" so assets are separate (not one giant HTML blob).
 * Post-processes index.html for iOS Safari/Edge viewport height + clearer loading UI.
 * Also writes dist/version.json and injects a lightweight update checker so mobile
 * browsers (iPhone Safari/Edge) can pick up new deploys without a hard refresh.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createRequire } from "module";
import { execFileSync } from "child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const require = createRequire(import.meta.url);
const Packager = require("@turbowarp/packager");

const SB3 = path.join(root, "sprunki-base.sb3");
const DIST = path.join(root, "dist");
const ZIP_OUT = path.join(root, ".packager-out.zip");

const MOBILE_FIX_CSS = `
    /* iOS Safari/Edge: percent height needs html/body height; 100dvh avoids 0-height canvas */
    html, body { width: 100%; height: 100%; height: 100dvh; min-height: 100%; min-height: -webkit-fill-available; background: #111827; margin: 0; }
    #app, #loading, #error, #launch { width: 100%; height: 100%; min-height: 100dvh; }
    #loading .loading-text { font-size: 22px; }
    #loading .hint { font-size: 14px; opacity: 0.85; max-width: 280px; margin-top: 12px; }
    /* Launch: lighter overlay, flag in lower third (baked stage title only; no overlay title) */
    #launch {
      background-color: rgba(0, 0, 0, 0.45) !important;
    }
    #launch.screen {
      justify-content: flex-end;
      padding-bottom: max(12vh, 72px);
      padding-top: max(3vh, 16px);
      box-sizing: border-box;
    }
    #launch .green-flag {
      width: 88px;
      height: 88px;
      flex-shrink: 0;
      z-index: 1;
    }
    #spj-update-banner {
      position: fixed; left: 0; right: 0; bottom: 0; z-index: 2147483646;
      display: none; align-items: center; justify-content: center;
      padding: 14px 16px calc(14px + env(safe-area-inset-bottom, 0px));
      background: #fbbf24; color: #111827; font: 600 16px/1.3 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      text-align: center; cursor: pointer; -webkit-tap-highlight-color: transparent;
      box-shadow: 0 -4px 16px rgba(0,0,0,0.35); user-select: none;
    }
    #spj-update-banner[data-show="1"] { display: flex; }
`;

const PWA_HEAD_TAGS = `
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Sprunki Pokémon Jam">
    <link rel="apple-touch-icon" href="./apple-touch-icon.png">
    <link rel="icon" type="image/png" sizes="32x32" href="./favicon-32.png">
    <link rel="icon" type="image/png" sizes="48x48" href="./favicon-48.png">
    <link rel="shortcut icon" href="./favicon.ico">
    <link rel="manifest" href="./manifest.webmanifest">
`;

function getBuildId() {
  try {
    return execFileSync("git", ["rev-parse", "--short", "HEAD"], {
      cwd: root,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return String(Date.now());
  }
}

function writeVersionJson(distDir, build) {
  const payload = { build, builtAt: new Date().toISOString() };
  const out = path.join(distDir, "version.json");
  fs.writeFileSync(out, JSON.stringify(payload));
  console.log("Wrote", out, payload);
}

function buildUpdateCheckerScript(build) {
  // Keep this self-contained; injected into index.html at build time.
  // Escaping: build id is short SHA / digits only — safe inside double quotes.
  //
  // Stale-HTML loop (esp. itch.io CDN): version.json is fetched no-store while
  // index.html can stay cached, so CURRENT !== data.build forever and the banner
  // reappears after every reload. Persist one attempt per target build in
  // sessionStorage; if we are still on an older HTML after that, stay quiet.
  return `<script>
window.__SPJ_BUILD__ = "${build}";
(function () {
  var CURRENT = window.__SPJ_BUILD__;
  var POLL_MS = 60000;
  var checking = false;
  var prompted = false;
  var STUCK_PREFIX = "spj_update_attempt_";

  function prePlay() {
    var loading = document.getElementById("loading");
    var launch = document.getElementById("launch");
    if (loading && !loading.hidden) return true;
    if (launch && !launch.hidden) return true;
    return false;
  }

  function attemptKey(nextBuild) {
    return STUCK_PREFIX + nextBuild;
  }

  function alreadyTried(nextBuild) {
    try {
      return sessionStorage.getItem(attemptKey(nextBuild)) === "1";
    } catch (e) {
      return false;
    }
  }

  function markTried(nextBuild) {
    try {
      sessionStorage.setItem(attemptKey(nextBuild), "1");
    } catch (e) {}
  }

  function clearAttempt(nextBuild) {
    try {
      sessionStorage.removeItem(attemptKey(nextBuild));
    } catch (e) {}
  }

  function hardReload(nextBuild) {
    markTried(nextBuild);
    try {
      var url = new URL(location.href);
      url.searchParams.set("v", nextBuild);
      // Unique bust so CDNs that key only on path still get a new URL
      url.searchParams.set("_spj", String(Date.now()));
      location.replace(url.toString());
    } catch (e) {
      location.reload();
    }
  }

  function showBanner(nextBuild) {
    if (prompted) return;
    prompted = true;
    markTried(nextBuild);
    var el = document.getElementById("spj-update-banner");
    if (!el) {
      el = document.createElement("div");
      el.id = "spj-update-banner";
      el.setAttribute("role", "button");
      el.tabIndex = 0;
      el.textContent = "New version available — tap to update";
      document.body.appendChild(el);
    }
    el.setAttribute("data-show", "1");
    var go = function () {
      hardReload(nextBuild);
    };
    el.onclick = go;
    el.onkeydown = function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
    };
  }

  function applyUpdate(nextBuild) {
    if (prompted) return;
    // Already reloaded for this build but HTML is still stale — do not loop.
    if (alreadyTried(nextBuild)) return;
    if (prePlay()) {
      hardReload(nextBuild);
      return;
    }
    showBanner(nextBuild);
  }

  function check() {
    if (checking || prompted) return;
    checking = true;
    fetch("version.json?_=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.build) return;
        if (data.build === CURRENT) {
          clearAttempt(data.build);
          return;
        }
        applyUpdate(data.build);
      })
      .catch(function () {})
      .then(function () { checking = false; });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") check();
  });
  setInterval(check, POLL_MS);
  setTimeout(check, 8000);
})();
</script>`;
}


const PUBLIC = path.join(root, "public");

function copyPublicAssets(distDir) {
  if (!fs.existsSync(PUBLIC)) {
    console.warn("No public/ directory — skipping PWA asset copy");
    return;
  }
  const walkCopy = (srcDir, destDir) => {
    fs.mkdirSync(destDir, { recursive: true });
    for (const ent of fs.readdirSync(srcDir, { withFileTypes: true })) {
      const s = path.join(srcDir, ent.name);
      const d = path.join(destDir, ent.name);
      if (ent.isDirectory()) walkCopy(s, d);
      else {
        fs.copyFileSync(s, d);
        console.log("Copied", path.relative(root, s), "->", path.relative(root, d));
      }
    }
  };
  walkCopy(PUBLIC, distDir);
}

function postProcessIndex(indexPath, build) {
  let html = fs.readFileSync(indexPath, "utf8");

  // Inject CSS into existing <style> block (before closing </style>), else before </head>
  if (html.includes("</style>")) {
    html = html.replace("</style>", `${MOBILE_FIX_CSS}\n  </style>`);
  } else if (html.includes("</head>")) {
    html = html.replace("</head>", `  <style>${MOBILE_FIX_CSS}\n  </style>\n</head>`);
  } else {
    throw new Error("Could not find </style> or </head> to inject mobile CSS");
  }

  // Prefer a non-black loading/chrome background so a hung load is not pure black
  html = html.replace(
    /:root, body\.is-fullscreen \{\s*background-color:\s*#000000;\s*\}/,
    ":root, body.is-fullscreen {\n      background-color: #111827;\n    }"
  );
  html = html.replace(
    /\.screen \{\s*([\s\S]*?)background-color:\s*#000000;/,
    ".screen {\n$1background-color: #111827;"
  );
  html = html.replace(
    /<meta name="theme-color" content="#000000">/,
    '<meta name="theme-color" content="#111827">'
  );


  // iOS Add-to-Home-Screen / PWA standalone
  if (!html.includes("apple-mobile-web-app-capable")) {
    if (html.includes("</head>")) {
      html = html.replace("</head>", `${PWA_HEAD_TAGS}
</head>`);
    } else {
      throw new Error("Could not find </head> to inject PWA meta tags");
    }
  }

  // Ensure a single loading copy (no size / cellular hint)
  const loadingCopy = `<div class="loading-text">Loading Sprunki Pokémon Jam</div>`;

  // Packager emits <h1 class="loading-text">…</h1> when loadingScreen.text is set
  if (/<h1 class="loading-text">[\s\S]*?<\/h1>/.test(html)) {
    html = html.replace(/<h1 class="loading-text">[\s\S]*?<\/h1>/, loadingCopy);
  } else if (/<div class="loading-text">[\s\S]*?<\/div>/.test(html)) {
    html = html.replace(/<div class="loading-text">[\s\S]*?<\/div>/, loadingCopy);
  } else if (html.includes('<div id="loading" class="screen">')) {
    html = html.replace(
      /<div id="loading" class="screen">\s*(<noscript>[\s\S]*?<\/noscript>)?/,
      (match, noscript) =>
        `<div id="loading" class="screen">\n    ${noscript ? noscript + "\n    " : ""}${loadingCopy}\n    `
    );
  }

  // Remove any leftover duplicate loading-text / hint nodes (keep first loading copy)
  html = html.replace(
    /(<div class="loading-text">[\s\S]*?<\/div>)([\s\S]*?)(<div class="progress-bar-outer">)/,
    (match, keep, middle, bar) => {
      const cleaned = middle.replace(/<(h1|div) class="loading-text">[\s\S]*?<\/\1>\s*/g, "")
        .replace(/<p class="hint">[\s\S]*?<\/p>\s*/g, "");
      return keep + "\n    " + cleaned + bar;
    }
  );

  // Cache-bust packager runtime so CDNs / iOS don't keep a stale script.js
  html = html.replace(
    /(<script\s+src=["'])script\.js(["']><\/script>)/i,
    `$1script.js?v=${build}$2`
  );

  // Embed build id + update poller (banner CSS already in MOBILE_FIX_CSS)
  const updateScript = buildUpdateCheckerScript(build);
  if (html.includes("</body>")) {
    html = html.replace("</body>", `${updateScript}\n</body>`);
  } else {
    html += "\n" + updateScript;
  }

  fs.writeFileSync(indexPath, html);
  console.log("Post-processed", indexPath, "(iOS height/PWA standalone + lowered green flag + loading copy + update checker, build=" + build + ")");
}

async function main() {
  if (!fs.existsSync(SB3)) {
    console.error("Missing sprunki-base.sb3 at", SB3);
    process.exit(1);
  }

  console.log("Loading project...", SB3, `(${(fs.statSync(SB3).size / 1e6).toFixed(1)} MB)`);
  const projectData = fs.readFileSync(SB3);
  const loadedProject = await Packager.loadProject(projectData, (type, a, b) => {
    if (typeof b === "number" && b > 0) {
      process.stdout.write(`\r  load ${type}: ${a}/${b}   `);
    } else if (typeof a === "number") {
      process.stdout.write(`\r  load ${type}: ${(a * 100).toFixed(0)}%   `);
    }
  });
  console.log("\nLoaded.");

  const packager = new Packager.Packager();
  packager.project = loadedProject;
  packager.options.target = "zip";
  packager.options.turbo = false;
  packager.options.autoplay = false; // click-to-start needed for mobile audio
  packager.options.resizeMode = "preserve-ratio";
  packager.options.app.packageName = "sprunkipokemonjam";
  packager.options.app.windowTitle = "Sprunki Pokémon Jam";
  packager.options.controls.greenFlag.enabled = true;
  packager.options.controls.stopAll.enabled = true;
  packager.options.controls.fullscreen.enabled = true;
  packager.options.loadingScreen.progressBar = true;
  packager.options.loadingScreen.text = "Loading Sprunki Pokémon Jam";
  packager.options.appearance.background = "#111827";

  packager.addEventListener("zip-progress", ({ detail }) => {
    if (detail && typeof detail.progress === "number") {
      process.stdout.write(`\r  zip ${(detail.progress * 100).toFixed(0)}%   `);
    }
  });

  console.log("Packaging (target=zip)...");
  const result = await packager.package();
  console.log("\nPackaged:", result.filename, result.type, `${(result.data.byteLength / 1e6).toFixed(1)} MB`);

  let data = result.data;
  if (data instanceof ArrayBuffer) data = new Uint8Array(data);

  fs.mkdirSync(DIST, { recursive: true });
  for (const name of fs.readdirSync(DIST)) {
    fs.rmSync(path.join(DIST, name), { recursive: true, force: true });
  }

  if (result.type === "application/zip" || packager.options.target === "zip") {
    fs.writeFileSync(ZIP_OUT, data);
    try {
      execFileSync("unzip", ["-o", ZIP_OUT, "-d", DIST], { stdio: "inherit" });
    } catch {
      execFileSync(
        "python3",
        ["-c",
          "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])",
          ZIP_OUT,
          DIST],
        { stdio: "inherit" }
      );
    }
    try { fs.unlinkSync(ZIP_OUT); } catch {}
  } else {
    fs.writeFileSync(path.join(DIST, "index.html"), data);
  }

  const indexPath = path.join(DIST, "index.html");
  if (!fs.existsSync(indexPath)) {
    const htmls = [];
    const walk = (dir) => {
      for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, ent.name);
        if (ent.isDirectory()) walk(p);
        else if (ent.name.endsWith(".html")) htmls.push(p);
      }
    };
    walk(DIST);
    if (htmls.length === 1 && path.dirname(htmls[0]) === DIST) {
      fs.renameSync(htmls[0], indexPath);
    } else if (htmls.length) {
      fs.copyFileSync(htmls[0], indexPath);
    } else {
      console.error("No index.html produced in dist/");
      process.exit(1);
    }
  }

  const buildId = getBuildId();
  writeVersionJson(DIST, buildId);
  copyPublicAssets(DIST);
  postProcessIndex(indexPath, buildId);

  console.log("Wrote static site to", DIST);
  const listing = fs.readdirSync(DIST);
  console.log("dist/ contains:", listing.slice(0, 20).join(", "), listing.length > 20 ? `... (${listing.length} entries)` : "");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
