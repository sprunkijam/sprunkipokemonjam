#!/usr/bin/env node
/**
 * Package sprunki-base.sb3 with TurboWarp Packager into a static site under dist/.
 * Uses target "zip" so assets are separate (not one giant HTML blob).
 * Post-processes index.html for iOS Safari/Edge viewport height + clearer loading UI.
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
`;

function postProcessIndex(indexPath) {
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

  // Ensure a single loading copy + cellular hint for ~83MB assets
  const loadingCopy = `<div class="loading-text">Loading big music project…</div>
    <p class="hint">Large download (~80MB). On cellular this can take a minute — please wait.</p>`;

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

  // Remove any leftover duplicate loading-text nodes (keep first + following hint)
  html = html.replace(
    /(<div class="loading-text">[\s\S]*?<\/div>\s*<p class="hint">[\s\S]*?<\/p>)([\s\S]*?)(<div class="progress-bar-outer">)/,
    (match, keep, middle, bar) => {
      const cleaned = middle.replace(/<(h1|div) class="loading-text">[\s\S]*?<\/\1>\s*/g, "")
        .replace(/<p class="hint">[\s\S]*?<\/p>\s*/g, "");
      return keep + "\n    " + cleaned + bar;
    }
  );

  fs.writeFileSync(indexPath, html);
  console.log("Post-processed", indexPath, "(iOS height fix + loading copy)");
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
  packager.options.app.windowTitle = "Sprunki Pokemon Jam";
  packager.options.controls.greenFlag.enabled = true;
  packager.options.controls.stopAll.enabled = true;
  packager.options.controls.fullscreen.enabled = true;
  packager.options.loadingScreen.progressBar = true;
  packager.options.loadingScreen.text = "Loading big music project…";
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

  postProcessIndex(indexPath);

  console.log("Wrote static site to", DIST);
  const listing = fs.readdirSync(DIST);
  console.log("dist/ contains:", listing.slice(0, 20).join(", "), listing.length > 20 ? `... (${listing.length} entries)` : "");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
