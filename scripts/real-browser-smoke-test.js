#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { createRequire } = require("module");
const { spawnSync } = require("child_process");

const repoRoot = path.resolve(__dirname, "..");
const mcpRoot = path.join(repoRoot, "plugins", "chromemcp-browser", "mcp");
const focusScript = path.join(repoRoot, "plugins", "chromemcp-browser", "launcher", "Focus-Chrome.ps1");
const { chromium } = createRequire(path.join(mcpRoot, "package.json"))("playwright");

function usage() {
  return `Usage:
  node scripts/real-browser-smoke-test.js --targets /path/to/targets.json

Environment:
  CHROMEMCP_SMOKE_TARGETS       Path to targets JSON when --targets is omitted.
  CHROMEMCP_CDP_ENDPOINT        CDP endpoint. Default: http://172.28.112.1:9222
  CHROMEMCP_VISIBLE_TESTS=0     Disable best-effort Chrome foreground focus.

Target file format:
  [
    {
      "label": "admin app",
      "url": "https://example.test/login",
      "auth": {
        "type": "form",
        "credentials": {
          "type": "env",
          "path": "/path/to/.secrets/browser.env",
          "usernameKey": "TEST_EMAIL",
          "passwordKey": "TEST_PASSWORD"
        }
      },
      "browseLimit": 5
    }
  ]`;
}

function parseArgs(argv) {
  const args = {
    targetsPath: process.env.CHROMEMCP_SMOKE_TARGETS || "",
    cdpEndpoint: process.env.CHROMEMCP_CDP_ENDPOINT || "http://172.28.112.1:9222",
    visible: process.env.CHROMEMCP_VISIBLE_TESTS !== "0",
  };

  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--targets") {
      args.targetsPath = argv[++i] || "";
    } else if (arg === "--cdp-endpoint") {
      args.cdpEndpoint = argv[++i] || "";
    } else if (arg === "--no-visible") {
      args.visible = false;
    } else if (arg === "--help" || arg === "-h") {
      console.log(usage());
      process.exit(0);
    } else {
      throw new Error(`unknown argument: ${arg}\n\n${usage()}`);
    }
  }

  if (!args.targetsPath) {
    throw new Error(`missing --targets or CHROMEMCP_SMOKE_TARGETS\n\n${usage()}`);
  }

  return args;
}

function parseEnv(filePath) {
  const values = {};

  for (const line of fs.readFileSync(filePath, "utf8").split(/\r?\n/)) {
    if (!line || line.trim().startsWith("#")) continue;

    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) continue;

    let value = match[2].trim();
    if ((value.startsWith("\"") && value.endsWith("\"")) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    values[match[1]] = value;
  }

  return values;
}

function readNestedValue(object, dottedKey) {
  return String(dottedKey || "")
    .split(".")
    .filter(Boolean)
    .reduce((value, key) => (value && typeof value === "object" ? value[key] : undefined), object);
}

function loadCredentials(source, targetLabel) {
  if (!source) return {};
  if (source.username && source.password) {
    return { username: source.username, password: source.password };
  }

  let values;
  if (source.type === "env") {
    values = parseEnv(source.path);
  } else if (source.type === "json") {
    values = JSON.parse(fs.readFileSync(source.path, "utf8"));
  } else {
    throw new Error(`${targetLabel}: unsupported credential source type: ${source.type}`);
  }

  const username = readNestedValue(values, source.usernameKey || source.emailKey || "email");
  const password = readNestedValue(values, source.passwordKey || "password");
  if (!username || !password) {
    throw new Error(`${targetLabel}: credential source did not provide username/password`);
  }

  return { username, password };
}

function normalizeTargets(targetsPath) {
  const raw = JSON.parse(fs.readFileSync(targetsPath, "utf8"));
  const list = Array.isArray(raw) ? raw : raw.targets;
  if (!Array.isArray(list) || list.length === 0) {
    throw new Error("targets file must contain a non-empty array or { targets: [...] }");
  }

  return list.map((target, index) => {
    const label = target.label || `target-${index + 1}`;
    if (!target.url) throw new Error(`${label}: missing url`);

    const auth = target.auth || {};
    const credentials = loadCredentials(auth.credentials, label);

    return {
      label,
      url: target.url,
      authType: auth.type || "form",
      username: credentials.username,
      password: credentials.password,
      usernameSelector:
        auth.usernameSelector ||
        'input[type="email"], input[name="email"], input[name="login"], input[name="username"], input[id*="email" i]',
      passwordSelector: auth.passwordSelector || 'input[type="password"], input[name="password"]',
      submitSelector:
        auth.submitSelector ||
        'button[type="submit"], input[type="submit"], button:has-text("Sign in"), button:has-text("Login"), button:has-text("Log in")',
      successUrlPattern: target.successUrlPattern || "",
      successSelector: target.successSelector || "",
      browseLimit: Number.isInteger(target.browseLimit) ? target.browseLimit : 5,
      actionDelayMs: Number.isInteger(target.actionDelayMs) ? target.actionDelayMs : 700,
    };
  });
}

function focusChrome() {
  if (!fs.existsSync(focusScript)) return;
  const windowsPath = spawnSync("wslpath", ["-w", focusScript], { encoding: "utf8" }).stdout.trim();
  if (!windowsPath) return;

  spawnSync(
    "powershell.exe",
    ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", windowsPath],
    { stdio: "ignore" }
  );
}

async function visibleStep(enabled) {
  if (enabled) focusChrome();
}

async function login(page, target, visible) {
  await visibleStep(visible);
  await page.goto(target.url, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForTimeout(1000);
  await visibleStep(visible);

  if (target.authType === "none") return;
  if (target.authType !== "form") throw new Error(`${target.label}: unsupported auth type: ${target.authType}`);
  if (!target.username || !target.password) throw new Error(`${target.label}: missing form credentials`);

  const passwordInput = page.locator(target.passwordSelector).first();
  const passwordVisible = await passwordInput.isVisible({ timeout: 1500 }).catch(() => false);
  if (!/login|signin|sign-in/i.test(page.url()) && !passwordVisible) {
    return;
  }

  const usernameInput = page.locator(target.usernameSelector).first();
  await usernameInput.waitFor({ state: "visible", timeout: 20000 });
  await passwordInput.waitFor({ state: "visible", timeout: 20000 });
  await usernameInput.fill(target.username);
  await passwordInput.fill(target.password);
  await visibleStep(visible);

  const submit = page.locator(target.submitSelector).first();
  await Promise.all([
    page.waitForLoadState("domcontentloaded", { timeout: 30000 }).catch(() => {}),
    submit.click(),
  ]);

  for (let attempt = 0; attempt < 20; attempt += 1) {
    const stillVisible = await passwordInput.isVisible({ timeout: 250 }).catch(() => false);
    if (!stillVisible) break;
    await page.waitForTimeout(500);
  }

  const passwordStillVisible = await passwordInput.isVisible({ timeout: 500 }).catch(() => false);
  if (passwordStillVisible) {
    const body = (await page.locator("body").innerText({ timeout: 5000 }).catch(() => "")).slice(0, 500);
    throw new Error(`still on login form after submit; visible text starts: ${body.replace(/\s+/g, " ")}`);
  }
}

async function assertSuccess(page, target) {
  if (target.successUrlPattern) {
    const pattern = new RegExp(target.successUrlPattern);
    if (!pattern.test(page.url())) {
      throw new Error(`${target.label}: current URL did not match successUrlPattern`);
    }
  }

  if (target.successSelector) {
    await page.locator(target.successSelector).first().waitFor({ state: "visible", timeout: 10000 });
  }
}

async function browseSafeLinks(page, target, visible) {
  const origin = new URL(page.url()).origin;
  const links = await page.locator("a[href]").evaluateAll((elements, pageOrigin) => {
    const unsafe = /logout|delete|destroy|remove|impersonate|download|export|mailto:|tel:/i;
    const seen = new Set();
    const output = [];

    for (const element of elements) {
      const text = (element.innerText || element.getAttribute("aria-label") || element.getAttribute("title") || "")
        .trim()
        .replace(/\s+/g, " ");
      const href = element.href;
      if (!href || !text || unsafe.test(href) || unsafe.test(text)) continue;

      let url;
      try {
        url = new URL(href);
      } catch {
        continue;
      }

      if (url.origin !== pageOrigin) continue;
      url.hash = "";

      const normalized = url.toString();
      if (seen.has(normalized)) continue;

      seen.add(normalized);
      output.push({ text: text.slice(0, 80), href: normalized });
    }

    return output.slice(0, 12);
  }, origin);

  const visited = [];
  for (const link of links) {
    if (visited.length >= target.browseLimit) break;

    try {
      await visibleStep(visible);
      await page.goto(link.href, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.waitForTimeout(target.actionDelayMs);
      await visibleStep(visible);

      const title = (await page.title().catch(() => "")).trim();
      const heading = (await page.locator("h1, h2").first().innerText({ timeout: 3000 }).catch(() => ""))
        .trim()
        .replace(/\s+/g, " ");
      const hasError = await page
        .locator("text=/server error|exception|trace|not found|forbidden|unauthorized/i")
        .first()
        .isVisible({ timeout: 1000 })
        .catch(() => false);

      visited.push({ text: link.text, url: page.url(), title, heading, hasError });
    } catch (error) {
      visited.push({ text: link.text, url: link.href, error: error.message.split("\n")[0] });
    }
  }

  return visited;
}

async function testTarget(context, target, visible) {
  const page = await context.newPage();
  page.setDefaultTimeout(20000);

  const result = { label: target.label };

  try {
    await login(page, target, visible);
    await assertSuccess(page, target);
    result.afterLoginUrl = page.url();
    result.title = await page.title().catch(() => "");
    result.heading = await page.locator("h1, h2").first().innerText({ timeout: 5000 }).catch(() => "");
    result.visited = await browseSafeLinks(page, target, visible);
    result.ok = !result.visited.some((visit) => visit.hasError || visit.error);
  } catch (error) {
    result.ok = false;
    result.error = error.message.split("\n")[0];
    result.afterLoginUrl = page.url();
    result.title = await page.title().catch(() => "");
    result.visited = [];
  } finally {
    await page.close().catch(() => {});
  }

  return result;
}

function printResult(result) {
  console.log(`SITE ${result.label}: ${result.ok ? "PASS" : "FAIL"}`);
  console.log(`  afterLoginUrl: ${result.afterLoginUrl || ""}`);
  console.log(`  title: ${(result.title || "").replace(/\s+/g, " ")}`);
  if (result.heading) console.log(`  heading: ${String(result.heading).replace(/\s+/g, " ")}`);
  if (result.error) console.log(`  error: ${result.error}`);

  for (const visit of result.visited) {
    const status = visit.error ? `ERROR ${visit.error}` : visit.hasError ? "ERROR_TEXT" : "OK";
    const label = (visit.heading || visit.title || "").replace(/\s+/g, " ");
    console.log(`  visit ${status}: ${visit.text} -> ${visit.url} :: ${label}`);
  }
}

(async () => {
  const options = parseArgs(process.argv);
  const targets = normalizeTargets(options.targetsPath);
  const browser = await chromium.connectOverCDP(options.cdpEndpoint);
  const context = browser.contexts()[0] || (await browser.newContext());

  const results = [];
  for (const target of targets) {
    results.push(await testTarget(context, target, options.visible));
  }

  await browser.close();

  for (const result of results) {
    printResult(result);
  }

  if (results.some((result) => !result.ok)) {
    process.exitCode = 1;
  }
})().catch((error) => {
  console.error(`FAIL: ${error.message}`);
  process.exitCode = 1;
});
