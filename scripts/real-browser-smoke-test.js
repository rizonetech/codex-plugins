#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { createRequire } = require("module");

const repoRoot = path.resolve(__dirname, "..");
const mcpRoot = path.join(repoRoot, "plugins", "chromemcp-browser", "mcp");
const { chromium } = createRequire(path.join(mcpRoot, "package.json"))("playwright");

const cdpEndpoint = process.env.CHROMEMCP_CDP_ENDPOINT || "http://172.28.112.1:9222";
const clientapp2Root = process.env.CLIENTAPP2_ROOT || "/home/<user>/www/clientapp2";
const clientappRoot = process.env.CLIENTAPP_ROOT || "/home/<user>/www/clientapp";

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

function loadCredentials() {
  const clientapp2 = parseEnv(path.join(clientapp2Root, ".secrets", "clientapp2-testing.env"));
  const clientapp = JSON.parse(
    fs.readFileSync(path.join(clientappRoot, ".secrets", "clientapp-browser-credentials.json"), "utf8")
  );

  const specs = [
    {
      label: "clientapp2",
      url: "http://app2.example.invalid/admin/login",
      email: clientapp2.CLIENTAPP2_TEST_EMAIL,
      password: clientapp2.CLIENTAPP2_TEST_PASSWORD,
    },
    {
      label: "clientapp",
      url: "https://app.example.invalid/console/login",
      email: clientapp.email,
      password: clientapp.password,
    },
  ];

  for (const spec of specs) {
    if (!spec.email || !spec.password) {
      throw new Error(`${spec.label}: missing email/password in secrets`);
    }
  }

  return specs;
}

async function login(page, spec) {
  await page.goto(spec.url, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForTimeout(1000);

  if (!/login/i.test(page.url())) {
    return;
  }

  const emailInput = page
    .locator('input[type="email"], input[name="email"], input[name="login"], input[id*="email" i]')
    .first();
  const passwordInput = page.locator('input[type="password"], input[name="password"]').first();

  await emailInput.waitFor({ state: "visible", timeout: 20000 });
  await passwordInput.waitFor({ state: "visible", timeout: 20000 });
  await emailInput.fill(spec.email);
  await passwordInput.fill(spec.password);

  const submit = page
    .locator(
      'button[type="submit"], input[type="submit"], button:has-text("Sign in"), button:has-text("Login"), button:has-text("Log in")'
    )
    .first();

  await Promise.all([
    page.waitForLoadState("domcontentloaded", { timeout: 30000 }).catch(() => {}),
    submit.click(),
  ]);

  for (let attempt = 0; attempt < 20; attempt += 1) {
    const passwordVisible = await passwordInput.isVisible({ timeout: 250 }).catch(() => false);
    if (!/login/i.test(page.url()) || !passwordVisible) break;
    await page.waitForTimeout(500);
  }

  const passwordStillVisible = await passwordInput.isVisible({ timeout: 500 }).catch(() => false);
  if (/login/i.test(page.url()) && passwordStillVisible) {
    const body = (await page.locator("body").innerText({ timeout: 5000 }).catch(() => "")).slice(0, 500);
    throw new Error(`still on login page after submit; visible text starts: ${body.replace(/\s+/g, " ")}`);
  }
}

async function browseSafeLinks(page, limit = 5) {
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
    if (visited.length >= limit) break;

    try {
      await page.goto(link.href, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.waitForTimeout(700);

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

async function testSite(context, spec) {
  const page = await context.newPage();
  page.setDefaultTimeout(20000);

  const result = { label: spec.label };

  try {
    await login(page, spec);
    result.afterLoginUrl = page.url();
    result.title = await page.title().catch(() => "");
    result.heading = await page.locator("h1, h2").first().innerText({ timeout: 5000 }).catch(() => "");
    result.visited = await browseSafeLinks(page, 5);
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
  const specs = loadCredentials();
  const browser = await chromium.connectOverCDP(cdpEndpoint);
  const context = browser.contexts()[0] || (await browser.newContext());

  const results = [];
  for (const spec of specs) {
    results.push(await testSite(context, spec));
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
