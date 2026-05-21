#!/usr/bin/env node
// ChromeMCP auth proxy.
//
// Wraps @playwright/mcp behind a bearer-token check. The MCP server itself
// has no auth, so this proxy is the only thing keeping casual same-host
// processes out of a signed-in Chrome session.
//
// Architecture
// ============
// 1. Spawn @playwright/mcp as a child process listening on UPSTREAM_PORT
//    (default 127.0.0.1:8932). Its stdio is inherited so logs flow through.
// 2. Listen on PUBLIC_PORT (default 127.0.0.1:8931). On each request,
//    validate `Authorization: Bearer <token>` and forward to the upstream
//    if valid; reply 401 otherwise.
// 3. If MCP_NO_AUTH=1, skip the auth check but log a loud warning on EVERY
//    request (per G2 acceptance criteria).
//
// Limitations
// ===========
// The upstream MCP server still listens on 127.0.0.1:UPSTREAM_PORT. A
// determined attacker with shell access on the same machine can connect to
// that port directly and bypass this proxy. The honest threat-model target
// is "casual same-host processes" (rogue install scripts, sibling
// containers sharing loopback), not a co-resident attacker. See SECURITY.md.

'use strict';

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { spawn, spawnSync } = require('node:child_process');
const log = require('./log');
const { Registry } = require('./metrics');

// --- Metrics registry ----------------------------------------------------
// Defined up front so the watchdog (which lives ~150 lines down) can
// increment them without forward-declaration. Exposed at GET /metrics with
// no auth — Prometheus scrape convention is "if you can reach the port,
// you can scrape." Cardinality stays low: tool labels are bounded by the
// MCP tool surface (~20 distinct names today).
const registry = new Registry();
const metricProxyRequests = registry.counter(
  'mcp_proxy_requests_total',
  'Total HTTP requests received by the auth proxy, labelled by path and final status code.',
  ['path', 'status'],
);
const metricToolCalls = registry.counter(
  'mcp_tool_calls_total',
  'Total MCP method invocations seen on /mcp, labelled by tool (params.name for tools/call, the method itself otherwise).',
  ['tool'],
);
const metricToolErrors = registry.counter(
  'mcp_tool_errors_total',
  'Total /mcp requests that returned HTTP status >= 400, labelled by tool and status.',
  ['tool', 'status'],
);
const metricToolDuration = registry.histogram(
  'mcp_tool_duration_seconds',
  'Wall-clock duration of /mcp requests from receive-headers to response-finish, labelled by tool.',
  ['tool'],
);
const metricSessionStarts = registry.counter(
  'mcp_session_starts_total',
  'Total `initialize` calls seen on /mcp (i.e. the number of MCP session starts).',
);
const metricActiveSessions = registry.gauge(
  'mcp_active_sessions',
  'Current count of MCP sessions whose Mcp-Session-Id header was seen within MCP_SESSION_IDLE_MS.',
);
const metricChromeReconnects = registry.counter(
  'mcp_chrome_reconnects_total',
  'Total CDP recovery cycles (healthy → down → healthy → upstream-restart).',
);

const PUBLIC_PORT   = parseInt(process.env.MCP_PUBLIC_PORT   || '8931', 10);
const PUBLIC_HOST   = process.env.MCP_PUBLIC_HOST            || '127.0.0.1';
const UPSTREAM_PORT = parseInt(process.env.MCP_UPSTREAM_PORT || '8932', 10);
const UPSTREAM_HOST = process.env.MCP_UPSTREAM_HOST          || '127.0.0.1';
const CDP_ENDPOINT  = process.env.MCP_CDP_ENDPOINT           || '';
const NO_AUTH       = process.env.MCP_NO_AUTH === '1';
const TOKEN_PATH    = process.env.MCP_TOKEN_PATH
  || path.join(process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config'), 'chromemcp', 'token');
const PLAYWRIGHT_CLI = process.env.MCP_PLAYWRIGHT_CLI
  || path.join(__dirname, 'node_modules', '@playwright', 'mcp', 'cli.js');
const VISIBLE_INTERACTIONS = process.env.MCP_VISIBLE_INTERACTIONS !== '0';
const VISIBLE_FOCUS_INTERVAL_MS = parseInt(process.env.MCP_VISIBLE_FOCUS_INTERVAL_MS || '750', 10);
const PROJECT_ROOT = path.dirname(__dirname);
const FOCUS_CHROME_SCRIPT = process.env.MCP_FOCUS_CHROME_SCRIPT
  || path.join(PROJECT_ROOT, 'launcher', 'Focus-Chrome.ps1');

function fail(msg, code = 1) {
  log.error(msg);
  process.exit(code);
}

// --- Visible interaction support ----------------------------------------
// Playwright MCP already attaches to the visible Windows Chrome profile via
// CDP. This helper nudges that Chrome window to the foreground before browser
// tool calls so users can monitor actions from Codex, Claude, Cursor, etc.
let lastVisibleFocusAt = 0;
let visibleFocusInflight = false;
let focusScriptWindowsPath = null;
let focusScriptPathResolved = false;

function findWindowsExe(name) {
  if (name === 'powershell.exe') {
    for (const candidate of [
      '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
      '/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe',
    ]) {
      try {
        if (fs.existsSync(candidate)) return candidate;
      } catch {}
    }
  }
  return name;
}

function resolveWindowsPath(linuxPath) {
  const result = spawnSync('wslpath', ['-w', linuxPath], { encoding: 'utf8' });
  if (result.status !== 0) return null;
  return result.stdout.trim();
}

function isBrowserToolCall(requestContext) {
  return requestContext.toolName && requestContext.toolName.startsWith('browser_');
}

function focusChromeForVisibleInteraction(requestContext) {
  if (!VISIBLE_INTERACTIONS || !isBrowserToolCall(requestContext)) return;
  if (!fs.existsSync(FOCUS_CHROME_SCRIPT)) return;

  const now = Date.now();
  if (visibleFocusInflight || now - lastVisibleFocusAt < VISIBLE_FOCUS_INTERVAL_MS) return;

  if (!focusScriptPathResolved) {
    focusScriptWindowsPath = resolveWindowsPath(FOCUS_CHROME_SCRIPT);
    focusScriptPathResolved = true;
  }
  if (!focusScriptWindowsPath) return;

  visibleFocusInflight = true;
  lastVisibleFocusAt = now;

  const child = spawn(findWindowsExe('powershell.exe'), [
    '-NoProfile',
    '-ExecutionPolicy',
    'Bypass',
    '-File',
    focusScriptWindowsPath,
  ], {
    stdio: 'ignore',
    detached: true,
  });

  child.on('exit', () => { visibleFocusInflight = false; });
  child.on('error', () => { visibleFocusInflight = false; });
  child.unref();
}

// --- Token resolution ----------------------------------------------------
function getOrCreateToken() {
  if (process.env.MCP_AUTH_TOKEN) return process.env.MCP_AUTH_TOKEN.trim();
  try {
    const t = fs.readFileSync(TOKEN_PATH, 'utf8').trim();
    if (t.length >= 32) return t;
  } catch (e) {
    if (e.code !== 'ENOENT') throw e;
  }
  // First-run generation.
  fs.mkdirSync(path.dirname(TOKEN_PATH), { recursive: true, mode: 0o700 });
  const token = crypto.randomBytes(32).toString('hex');
  fs.writeFileSync(TOKEN_PATH, token + '\n', { mode: 0o600 });
  // Re-apply perms in case mode-on-create was ignored by the FS.
  try { fs.chmodSync(TOKEN_PATH, 0o600); } catch {}
  log.info(`generated new token at ${TOKEN_PATH}`);
  return token;
}

const TOKEN = NO_AUTH ? null : getOrCreateToken();

// --- Auth check ----------------------------------------------------------
// Constant-time comparison so the auth check doesn't leak timing.
function tokenMatches(provided) {
  if (!provided || !TOKEN) return false;
  const a = Buffer.from(provided);
  const b = Buffer.from(TOKEN);
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

function authorized(req) {
  const h = req.headers['authorization'] || '';
  // 'Bearer <token>' (case-insensitive scheme).
  const m = /^Bearer\s+(\S+)/i.exec(h);
  if (!m) return false;
  return tokenMatches(m[1]);
}

function reply401(res, why) {
  if (res.headersSent) return res.end();
  res.writeHead(401, {
    'content-type': 'application/json',
    'www-authenticate': 'Bearer realm="ChromeMCP"',
  });
  res.end(JSON.stringify({
    jsonrpc: '2.0',
    id: null,
    error: {
      code: -32001,
      message: `Unauthorized: ${why}`,
    },
  }));
}

// --- Spawn upstream @playwright/mcp --------------------------------------
const upstreamArgs = [
  PLAYWRIGHT_CLI,
  '--port', String(UPSTREAM_PORT),
  '--host', UPSTREAM_HOST,
  '--allowed-hosts', `${UPSTREAM_HOST}:${UPSTREAM_PORT},localhost:${UPSTREAM_PORT}`,
];
if (CDP_ENDPOINT) {
  upstreamArgs.push('--cdp-endpoint', CDP_ENDPOINT);
}
// Default extras unless caller explicitly overrides.
const extra = process.env.MCP_PLAYWRIGHT_EXTRA_ARGS
  ? JSON.parse(process.env.MCP_PLAYWRIGHT_EXTRA_ARGS)
  : ['--shared-browser-context'];
for (const a of extra) upstreamArgs.push(a);

// `child` is reassigned by the CDP watchdog on recovery (it restarts the
// @playwright/mcp child so it builds a fresh CDP WebSocket against the
// just-relaunched Chrome). `expectingChildExit` suppresses the normal
// "child died → I die too" behavior during those intentional restarts.
let child = null;
let expectingChildExit = false;

function spawnUpstream() {
  const c = spawn(process.execPath, upstreamArgs, {
    stdio: 'inherit',
    env: process.env,
  });
  c.on('exit', (code, signal) => {
    if (expectingChildExit) {
      log.info('upstream @playwright/mcp exited (intentional restart)');
      return;
    }
    log.error('upstream @playwright/mcp exited; shutting down', { code, signal });
    process.exit(code === null ? 1 : code);
  });
  return c;
}

child = spawnUpstream();

for (const sig of ['SIGTERM', 'SIGINT', 'SIGHUP']) {
  process.on(sig, () => {
    expectingChildExit = true;
    if (watchdogTimer) clearInterval(watchdogTimer);
    try { child && child.kill(sig); } catch {}
    setTimeout(() => process.exit(0), 500).unref();
  });
}

// --- CDP watchdog --------------------------------------------------------
// Polls $CDP_ENDPOINT/json/version every PROBE_INTERVAL_MS. On transition
// to down: log + start short-circuiting /mcp with -32099. On recovery:
// restart the @playwright/mcp child so it rebuilds the CDP WebSocket.
// After RELAUNCH_AFTER_MS without recovery: trigger ../chrome to relaunch
// Chrome on the Windows side (skippable with MCP_NO_AUTO_CHROME=1). After
// BAIL_AFTER_MS: exit(1) so the supervisor restarts the whole stack.
const WATCHDOG_DISABLED = process.env.MCP_NO_WATCHDOG === '1';
const PROBE_INTERVAL_MS  = parseInt(process.env.MCP_CDP_PROBE_INTERVAL_MS  || '10000', 10);
const RELAUNCH_AFTER_MS  = parseInt(process.env.MCP_CDP_RELAUNCH_AFTER_MS  || '60000', 10);
const BAIL_AFTER_MS      = parseInt(process.env.MCP_CDP_BAIL_AFTER_MS      || '180000', 10);

let cdpHealthy        = true;    // optimistic: pre-flight verified CDP before we got here
let cdpDownSince      = null;    // ms epoch
// Reconnect counter is now mirrored to mcp_chrome_reconnects_total — read
// the current value via `metricChromeReconnects.get()`.
let chromeRelaunchInflight = false;
let cdpRestartInflight = false;
let watchdogTimer = null;

function parseCdpUrl() {
  if (!CDP_ENDPOINT) return null;
  try {
    const u = new URL(CDP_ENDPOINT + '/json/version');
    return { host: u.hostname, port: parseInt(u.port || '80', 10), path: u.pathname };
  } catch {
    return null;
  }
}

function probeCDPRemote() {
  return new Promise((resolve) => {
    const u = parseCdpUrl();
    if (!u) return resolve(false);
    const req = http.request({ host: u.host, port: u.port, path: u.path, method: 'GET', timeout: 3000 }, (res) => {
      res.resume();
      resolve(res.statusCode >= 200 && res.statusCode < 500);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
    req.end();
  });
}

async function restartUpstreamForCdpRecovery(downMs) {
  if (cdpRestartInflight) return;
  cdpRestartInflight = true;
  try {
    log.info('restarting @playwright/mcp upstream so it rebuilds the CDP socket');
    expectingChildExit = true;
    try { child && child.kill('SIGTERM'); } catch {}
    // Give it a moment to exit cleanly; SIGKILL if not.
    await new Promise((r) => setTimeout(r, 1500));
    try { child && child.kill && child.kill('SIGKILL'); } catch {}
    await new Promise((r) => setTimeout(r, 300));
    expectingChildExit = false;
    child = spawnUpstream();
    await waitForUpstream(15000);
    metricChromeReconnects.inc();
    log.info('upstream restarted', {
      mcp_chrome_reconnects_total: metricChromeReconnects.get(),
      down_seconds: +(downMs / 1000).toFixed(1),
    });
  } finally {
    cdpRestartInflight = false;
  }
}

function triggerChromeRelaunch() {
  if (process.env.MCP_NO_AUTO_CHROME === '1') return;
  if (chromeRelaunchInflight) return;
  const chromeScript = path.join(__dirname, '..', 'chrome');
  try { fs.accessSync(chromeScript, fs.constants.X_OK); } catch { return; }
  chromeRelaunchInflight = true;
  log.warn(`CDP down ≥${(RELAUNCH_AFTER_MS/1000)|0}s; firing ${chromeScript} to relaunch Chrome on Windows`);
  const sub = spawn('bash', [chromeScript], { stdio: 'ignore', detached: true });
  sub.on('error', () => {});
  sub.unref();
  // Re-allow another relaunch attempt after one minute so we don't loop fire.
  setTimeout(() => { chromeRelaunchInflight = false; }, 60000).unref();
}

async function watchdog() {
  const ok = await probeCDPRemote();
  const now = Date.now();
  if (ok) {
    if (!cdpHealthy) {
      const downMs = now - (cdpDownSince || now);
      cdpHealthy = true;
      cdpDownSince = null;
      log.info(`CDP reachable again at ${CDP_ENDPOINT}`, { down_seconds: +(downMs/1000).toFixed(1) });
      // Force the upstream to rebuild its CDP WebSocket. Without this, the
      // child may continue erroring against the dead socket.
      await restartUpstreamForCdpRecovery(downMs);
    }
    return;
  }
  if (cdpHealthy) {
    cdpHealthy = false;
    cdpDownSince = now;
    log.warn(`CDP unreachable at ${CDP_ENDPOINT}; short-circuiting /mcp until it recovers`);
  }
  const downMs = now - cdpDownSince;
  if (downMs >= RELAUNCH_AFTER_MS) triggerChromeRelaunch();
  if (downMs >= BAIL_AFTER_MS) {
    log.error(`CDP unreachable for ≥${(BAIL_AFTER_MS/1000)|0}s; exiting so supervisor restarts the stack`);
    expectingChildExit = true;
    try { child && child.kill('SIGTERM'); } catch {}
    setTimeout(() => process.exit(1), 500).unref();
  }
}

if (!WATCHDOG_DISABLED && CDP_ENDPOINT) {
  watchdogTimer = setInterval(() => { watchdog().catch(() => {}); }, PROBE_INTERVAL_MS);
}

// --- Wait for upstream to come up before opening public port -------------
function probeUpstream() {
  return new Promise((resolve) => {
    const req = http.request({
      host: UPSTREAM_HOST, port: UPSTREAM_PORT,
      method: 'GET', path: '/', timeout: 1000,
    }, (res) => { res.resume(); resolve(true); });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
    req.end();
  });
}

async function waitForUpstream(timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await probeUpstream()) return true;
    await new Promise(r => setTimeout(r, 200));
  }
  return false;
}

// --- Active session tracking --------------------------------------------
// Mcp-Session-Id is set by the upstream on `initialize` and echoed back on
// every subsequent request. We mark last-seen and prune sessions idle
// for > MCP_SESSION_IDLE_MS so the gauge reflects current concurrency
// rather than cumulative.
const SESSION_IDLE_MS = parseInt(process.env.MCP_SESSION_IDLE_MS || '300000', 10);
const sessionLastSeen = new Map();
function touchSession(sid) {
  if (sid) sessionLastSeen.set(String(sid), Date.now());
}
function pruneSessions() {
  const cutoff = Date.now() - SESSION_IDLE_MS;
  for (const [sid, ts] of sessionLastSeen) {
    if (ts < cutoff) sessionLastSeen.delete(sid);
  }
}
setInterval(pruneSessions, 60_000).unref();
metricActiveSessions.bindDynamic(() => {
  pruneSessions();
  return [{ labels: {}, value: sessionLastSeen.size }];
});

// --- Helpers for forwarding to upstream ---------------------------------
function buildForwardHeaders(reqHeaders) {
  const fwd = { ...reqHeaders };
  // Hop-by-hop headers per RFC 7230 §6.1.
  delete fwd.connection;
  delete fwd['proxy-connection'];
  delete fwd['keep-alive'];
  delete fwd['transfer-encoding'];
  delete fwd['te'];
  delete fwd.trailer;
  delete fwd.upgrade;
  // Strip the bearer token — upstream doesn't need it.
  delete fwd.authorization;
  fwd.host = `${UPSTREAM_HOST}:${UPSTREAM_PORT}`;
  return fwd;
}

const SECRET_KEY_TYPES = new Map([
  ['cookie', 'cookie'],
  ['cookies', 'cookie'],
  ['authorization', 'authorization'],
  ['token', 'token'],
  ['access_token', 'token'],
  ['refresh_token', 'token'],
  ['api_key', 'api_key'],
  ['secret', 'secret'],
  ['password', 'password'],
]);

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function normalizeSecretType(key) {
  const normalized = String(key || '').toLowerCase().replace(/-/g, '_');
  if (normalized === 'x_api_key') return 'api_key';
  return SECRET_KEY_TYPES.get(normalized) || 'secret';
}

function rememberSensitiveValue(values, value, type) {
  if (typeof value !== 'string') return;
  const trimmed = value.trim();
  if (trimmed.length < 8) return;
  values.set(trimmed, type);
}

function extractSensitiveValuesFromCode(code) {
  const values = new Map();
  if (typeof code !== 'string' || !code) return values;

  const secretKeys = 'cookie|cookies|Cookie|Authorization|Bearer|token|access_token|refresh_token|api_key|x-api-key|secret|password';
  const keyValueRe = new RegExp(
    `(?:\\b(?:const|let|var)\\s+)?["']?(${secretKeys})["']?\\s*[:=]\\s*(["'\`])([\\s\\S]*?)\\2`,
    'gi',
  );
  for (const match of code.matchAll(keyValueRe)) {
    let value = match[3];
    if (/^Bearer$/i.test(match[1])) {
      value = value.replace(/^Bearer\s+/i, '');
    }
    rememberSensitiveValue(values, value, normalizeSecretType(match[1]));
  }

  const bearerRe = /\bBearer\s+([A-Za-z0-9._~+/=-]{8,})/gi;
  for (const match of code.matchAll(bearerRe)) {
    rememberSensitiveValue(values, match[1], 'authorization');
  }

  const cookiesAssignmentRe = /\bcookies\b\s*=\s*\[([\s\S]*?)\]/gi;
  for (const match of code.matchAll(cookiesAssignmentRe)) {
    const block = match[1];
    const cookieValueRe = /\bvalue\s*:\s*(["'`])([\s\S]*?)\1/gi;
    for (const valueMatch of block.matchAll(cookieValueRe)) {
      rememberSensitiveValue(values, valueMatch[2], 'cookie');
    }
  }

  return values;
}

function extractRequestContext(body) {
  const context = {
    toolName: null,
    sensitiveValues: new Map(),
  };
  try {
    const parsed = JSON.parse(body.toString('utf8'));
    const params = parsed && parsed.params;
    context.toolName = params && params.name ? String(params.name) : null;
    const args = params && params.arguments;
    if (context.toolName === 'browser_run_code_unsafe' && args) {
      for (const [value, type] of extractSensitiveValuesFromCode(args.code)) {
        context.sensitiveValues.set(value, type);
      }
    }
  } catch {}
  return context;
}

function redactSecretPatterns(text) {
  let redacted = text;
  const keyAlternation = 'cookie|cookies|Cookie|Authorization|token|access_token|refresh_token|api_key|x-api-key|secret|password';

  redacted = redacted.replace(/\bBearer\s+([A-Za-z0-9._~+/=-]{8,})/gi, 'Bearer [REDACTED:authorization]');

  redacted = redacted.replace(
    new RegExp(`(["']?(${keyAlternation})["']?\\s*[:=]\\s*)(["'\`])([\\s\\S]*?)\\3`, 'gi'),
    (_match, prefix, key, quote) => `${prefix}${quote}[REDACTED:${normalizeSecretType(key)}]${quote}`,
  );

  redacted = redacted.replace(
    new RegExp(`\\b(const|let|var)\\s+(${keyAlternation})\\s*=\\s*([^;\\n]+)`, 'gi'),
    (_match, decl, key) => `${decl} ${key} = "[REDACTED:${normalizeSecretType(key)}]"`,
  );

  return redacted;
}

function redactText(text, sensitiveValues = new Map()) {
  if (typeof text !== 'string' || !text) return text;
  let redacted = text;
  const entries = [...sensitiveValues.entries()].sort((a, b) => b[0].length - a[0].length);
  for (const [value, type] of entries) {
    redacted = redacted.replace(new RegExp(escapeRegExp(value), 'g'), `[REDACTED:${type}]`);
  }
  return redactSecretPatterns(redacted);
}

function redactJsonValue(value, sensitiveValues) {
  if (typeof value === 'string') return redactText(value, sensitiveValues);
  if (Array.isArray(value)) return value.map((item) => redactJsonValue(item, sensitiveValues));
  if (value && typeof value === 'object') {
    const out = {};
    for (const [key, child] of Object.entries(value)) {
      out[key] = redactJsonValue(child, sensitiveValues);
    }
    return out;
  }
  return value;
}

function parseMarkdownSections(text) {
  const sections = new Map();
  if (typeof text !== 'string') return sections;
  const sectionHeaders = text.split(/^### /m).slice(1);
  for (const section of sectionHeaders) {
    const firstNewlineIndex = section.indexOf('\n');
    if (firstNewlineIndex === -1) continue;
    const sectionName = section.substring(0, firstNewlineIndex);
    const sectionContent = section.substring(firstNewlineIndex + 1).trim();
    sections.set(sectionName, sectionContent);
  }
  return sections;
}

function jsonValueType(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  return typeof value;
}

function parseJsonResult(rawResult) {
  if (rawResult === undefined) {
    return {
      value: null,
      jsonType: 'undefined',
      raw: null,
      parseError: null,
    };
  }
  if (rawResult === 'undefined') {
    return {
      value: null,
      jsonType: 'undefined',
      raw: rawResult,
      parseError: null,
    };
  }
  try {
    const value = JSON.parse(rawResult);
    return {
      value,
      jsonType: jsonValueType(value),
      raw: rawResult,
      parseError: null,
    };
  } catch (e) {
    return {
      value: null,
      jsonType: 'unparsed',
      raw: rawResult,
      parseError: e && e.message ? e.message : String(e),
    };
  }
}

function enrichStructuredToolResult(payload, requestContext) {
  const toolName = requestContext.toolName;
  if (toolName !== 'browser_evaluate' && toolName !== 'browser_run_code_unsafe') return payload;
  const result = payload && payload.result;
  if (!result || typeof result !== 'object' || !Array.isArray(result.content)) return payload;
  const textItem = result.content.find((item) => item && item.type === 'text' && typeof item.text === 'string');
  if (!textItem) return payload;

  const sections = parseMarkdownSections(textItem.text);
  const error = sections.get('Error');
  const rawResult = sections.get('Result');
  result.structuredContent = result.structuredContent && typeof result.structuredContent === 'object'
    ? result.structuredContent
    : {};
  result.structuredContent.chromemcp = {
    schemaVersion: 1,
    tool: toolName,
    status: result.isError || error ? 'error' : 'ok',
    result: result.isError || error ? null : parseJsonResult(rawResult),
    error: result.isError || error ? { message: error || textItem.text } : null,
  };
  return payload;
}

function processResponseJsonPayload(payload, requestContext) {
  const redacted = redactJsonValue(payload, requestContext.sensitiveValues);
  return enrichStructuredToolResult(redacted, requestContext);
}

function redactResponseBody(bodyText, requestContext = { sensitiveValues: new Map(), toolName: null }) {
  if (!bodyText) return bodyText;
  if (bodyText.split('\n').some((line) => line.startsWith('data: '))) {
    return bodyText.split('\n').map((line) => {
      if (!line.startsWith('data: ')) return redactText(line, requestContext.sensitiveValues);
      const data = line.slice(6);
      try {
        return `data: ${JSON.stringify(processResponseJsonPayload(JSON.parse(data), requestContext))}`;
      } catch {
        return `data: ${redactText(data, requestContext.sensitiveValues)}`;
      }
    }).join('\n');
  }

  try {
    const suffix = bodyText.endsWith('\n') ? '\n' : '';
    return JSON.stringify(processResponseJsonPayload(JSON.parse(bodyText), requestContext)) + suffix;
  } catch {
    return redactText(bodyText, requestContext.sensitiveValues);
  }
}

function replyUpstreamError(res, err) {
  if (res.headersSent) { try { res.destroy(); } catch {} return; }
  res.writeHead(502, { 'content-type': 'application/json' });
  res.end(JSON.stringify({
    jsonrpc: '2.0', id: null,
    error: { code: -32099, message: `Upstream @playwright/mcp unreachable: ${err.message}` },
  }) + '\n');
}

function captureUpstreamSession(upstreamRes) {
  // The MCP transport echoes the session ID on the response of `initialize`.
  // Header name is case-insensitive in Node's parser; check both spellings.
  const sid = upstreamRes.headers['mcp-session-id'] || upstreamRes.headers['Mcp-Session-Id'];
  if (sid) touchSession(sid);
}

// --- The proxy server itself --------------------------------------------
const proxyServer = http.createServer((req, res) => {
  const startNs = process.hrtime.bigint();
  const reqPath = (req.url || '/').split('?')[0];

  // Every response — successful, 401, 503, anything — gets counted here.
  res.on('finish', () => {
    metricProxyRequests.inc({ path: reqPath, status: String(res.statusCode) });
  });

  // /healthz — unauthenticated, returns proxy + cdp state.
  if (reqPath === '/healthz' && (req.method === 'GET' || req.method === 'HEAD')) {
    res.writeHead(200, { 'content-type': 'application/json' });
    if (req.method === 'HEAD') return res.end();
    return res.end(JSON.stringify({
      status: 'ok',
      cdp: {
        endpoint: CDP_ENDPOINT,
        healthy: cdpHealthy,
        downSeconds: cdpDownSince ? Math.round((Date.now() - cdpDownSince) / 1000) : 0,
        reconnects: metricChromeReconnects.get(),
      },
    }) + '\n');
  }

  // /metrics — unauthenticated, Prometheus text exposition format.
  // Same security posture as /healthz: anyone who can reach the port can
  // scrape. Cardinality is bounded by the MCP tool surface, so we don't
  // need rate limiting here.
  if (reqPath === '/metrics' && (req.method === 'GET' || req.method === 'HEAD')) {
    res.writeHead(200, { 'content-type': 'text/plain; version=0.0.4; charset=utf-8' });
    if (req.method === 'HEAD') return res.end();
    return res.end(registry.serialize());
  }

  // Auth gate.
  if (NO_AUTH) {
    log.warn(`MCP_NO_AUTH=1 — unauthenticated request`, {
      remote: req.socket.remoteAddress,
      method: req.method,
      url: req.url,
    });
  } else if (!authorized(req)) {
    const hadHeader = !!req.headers['authorization'];
    return reply401(res, hadHeader ? 'invalid bearer token' : 'missing Authorization: Bearer <token>');
  }

  // Short-circuit /mcp while CDP is down (G4).
  if (!cdpHealthy && reqPath.startsWith('/mcp')) {
    const downSec = Math.max(1, Math.round((Date.now() - (cdpDownSince || Date.now())) / 1000));
    res.writeHead(503, { 'content-type': 'application/json', 'retry-after': '5' });
    return res.end(JSON.stringify({
      jsonrpc: '2.0', id: null,
      error: {
        code: -32099,
        message: `Chrome temporarily unavailable (CDP down ${downSec}s). Retry in a few seconds.`,
        data: { cdpEndpoint: CDP_ENDPOINT, downSeconds: downSec, reconnects: metricChromeReconnects.get() },
      },
    }) + '\n');
  }

  // Track client's incoming session header (subsequent calls in a session
  // carry this; initialize creates it).
  touchSession(req.headers['mcp-session-id']);

  // For /mcp POSTs we buffer the body so we can extract method+tool for
  // metric labels. Other paths (and /mcp GET/HEAD) stream straight through.
  const isMcpPost = req.method === 'POST' && reqPath.startsWith('/mcp');
  if (!isMcpPost) {
    forwardStreamingRequest(req, res);
    return;
  }

  const chunks = [];
  let total = 0;
  let overLimit = false;
  const LIMIT = parseInt(process.env.MCP_BODY_BUFFER_LIMIT || '262144', 10);
  req.on('data', (chunk) => {
    total += chunk.length;
    if (total > LIMIT) overLimit = true;
    chunks.push(chunk);
  });
  req.on('end', () => {
    const body = Buffer.concat(chunks);
    let toolLabel = '_unknown';
    let methodName = null;
    if (overLimit) {
      toolLabel = '_oversize';
    } else if (body.length > 0) {
      try {
        const parsed = JSON.parse(body.toString('utf8'));
        methodName = parsed && typeof parsed.method === 'string' ? parsed.method : null;
        if (methodName === 'tools/call') {
          toolLabel = (parsed.params && parsed.params.name) || '_unknown';
        } else if (methodName) {
          toolLabel = methodName;
        }
        if (methodName === 'initialize') metricSessionStarts.inc();
      } catch {
        toolLabel = '_unparseable';
      }
    }
    metricToolCalls.inc({ tool: toolLabel });

    forwardBufferedRequest(req, body, res, () => {
      const dur = Number(process.hrtime.bigint() - startNs) / 1e9;
      metricToolDuration.observe({ tool: toolLabel }, dur);
      if (res.statusCode >= 400) {
        metricToolErrors.inc({ tool: toolLabel, status: String(res.statusCode) });
      }
    });
  });
  req.on('error', () => {});
});

function forwardBufferedRequest(req, body, res, onFinish) {
  const headers = buildForwardHeaders(req.headers);
  headers['content-length'] = String(body.length);
  const requestContext = extractRequestContext(body);
  focusChromeForVisibleInteraction(requestContext);
  const upstreamReq = http.request({
    host: UPSTREAM_HOST, port: UPSTREAM_PORT,
    method: req.method, path: req.url,
    headers,
  });
  upstreamReq.on('response', (upstreamRes) => {
    captureUpstreamSession(upstreamRes);
    const chunks = [];
    upstreamRes.on('data', (chunk) => chunks.push(chunk));
    upstreamRes.on('end', () => {
      const responseHeaders = { ...upstreamRes.headers };
      delete responseHeaders['content-length'];
      const upstreamBody = Buffer.concat(chunks).toString('utf8');
      const safeBody = redactResponseBody(upstreamBody, requestContext);
      res.writeHead(upstreamRes.statusCode || 502, responseHeaders);
      res.end(safeBody);
    });
    res.on('finish', () => { if (onFinish) onFinish(); });
  });
  upstreamReq.on('error', (e) => {
    replyUpstreamError(res, e);
    if (onFinish) onFinish();
  });
  upstreamReq.write(body);
  upstreamReq.end();
}

function forwardStreamingRequest(req, res) {
  const upstreamReq = http.request({
    host: UPSTREAM_HOST, port: UPSTREAM_PORT,
    method: req.method, path: req.url,
    headers: buildForwardHeaders(req.headers),
  });
  upstreamReq.on('response', (upstreamRes) => {
    captureUpstreamSession(upstreamRes);
    res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
    upstreamRes.pipe(res);
  });
  upstreamReq.on('error', (e) => replyUpstreamError(res, e));
  req.on('error', () => { try { upstreamReq.destroy(); } catch {} });
  req.pipe(upstreamReq);
}

proxyServer.on('error', (e) => fail(`failed to bind ${PUBLIC_HOST}:${PUBLIC_PORT}: ${e.message}`));

(async () => {
  const ok = await waitForUpstream();
  if (!ok) {
    fail(`upstream @playwright/mcp did not come up on ${UPSTREAM_HOST}:${UPSTREAM_PORT} within 15s`);
  }
  proxyServer.listen(PUBLIC_PORT, PUBLIC_HOST, () => {
    if (NO_AUTH) {
      log.warn('⚠  MCP_NO_AUTH=1 — auth DISABLED. Any process on this machine can drive Chrome.');
    } else {
      log.info(`listening on ${PUBLIC_HOST}:${PUBLIC_PORT}, forwarding to ${UPSTREAM_HOST}:${UPSTREAM_PORT} (auth required)`);
    }
  });
})();
