// ChromeMCP leveled logger.
//
// Two output formats, switched via MCP_LOG_FORMAT:
//   * 'text' (default) - "auth-proxy: <msg>\n" — backward-compatible with
//                        what the proxy emitted before G7.
//   * 'json'           - one JSON object per line:
//                        {"ts":"2026-05-19T00:00:00.000Z","level":"INFO",
//                         "source":"auth-proxy","msg":"..."}
//
// Level gating via MCP_LOG_LEVEL (case-insensitive; default INFO):
//   DEBUG  INFO  WARN  ERROR
//
// All output goes to stderr so it doesn't collide with proxied HTTP traffic
// on stdout (the proxy doesn't actually use stdout, but this keeps things
// predictable for any future code path that does).

'use strict';

const LEVELS = { DEBUG: 10, INFO: 20, WARN: 30, ERROR: 40 };

function resolveLevel() {
  const raw = (process.env.MCP_LOG_LEVEL || 'INFO').toUpperCase();
  return LEVELS[raw] != null ? LEVELS[raw] : LEVELS.INFO;
}

const MIN_LEVEL = resolveLevel();
const FORMAT    = (process.env.MCP_LOG_FORMAT || 'text').toLowerCase();
const SOURCE    = process.env.MCP_LOG_SOURCE || 'auth-proxy';

function emit(level, msg, extra) {
  if (LEVELS[level] < MIN_LEVEL) return;
  if (FORMAT === 'json') {
    const obj = { ts: new Date().toISOString(), level, source: SOURCE, msg };
    if (extra && typeof extra === 'object') Object.assign(obj, extra);
    process.stderr.write(JSON.stringify(obj) + '\n');
  } else {
    // Backward-compatible text format. If `extra` is provided, append
    // key=value pairs for human readability without going full JSON.
    let line = `${SOURCE}: ${msg}`;
    if (extra && typeof extra === 'object') {
      const tail = Object.keys(extra)
        .map((k) => `${k}=${JSON.stringify(extra[k])}`)
        .join(' ');
      if (tail) line += ` (${tail})`;
    }
    process.stderr.write(line + '\n');
  }
}

module.exports = {
  debug: (msg, extra) => emit('DEBUG', msg, extra),
  info:  (msg, extra) => emit('INFO',  msg, extra),
  warn:  (msg, extra) => emit('WARN',  msg, extra),
  error: (msg, extra) => emit('ERROR', msg, extra),
  format: FORMAT,
  level:  Object.keys(LEVELS).find((k) => LEVELS[k] === MIN_LEVEL),
};
