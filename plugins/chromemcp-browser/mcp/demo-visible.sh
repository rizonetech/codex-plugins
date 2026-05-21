#!/usr/bin/env bash
# Visible-effect demo: opens a new tab, navigates to example.com,
# takes a screenshot, saves it to disk, and closes the tab again.
# Run after ./chrome && ./mcp-up.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"
URL="${MCP_URL:-http://localhost:8931/mcp}"
OUT_DIR="$(pwd)/demo-output"
mkdir -p "$OUT_DIR"

TOKEN_PATH="${MCP_TOKEN_PATH:-${XDG_CONFIG_HOME:-$HOME/.config}/chromemcp/token}"
TOKEN=""
if [ "${MCP_NO_AUTH:-}" != "1" ]; then
  if [ -n "${MCP_AUTH_TOKEN:-}" ]; then
    TOKEN="$MCP_AUTH_TOKEN"
  elif [ -r "$TOKEN_PATH" ]; then
    TOKEN="$(tr -d '\n\r ' < "$TOKEN_PATH")"
  else
    echo "ERROR: no auth token at $TOKEN_PATH. Run ./mcp-up or ./mcp-token first." >&2
    exit 2
  fi
fi

python3 - "$URL" "$OUT_DIR" "$TOKEN" <<'PYEOF'
import json, sys, urllib.request, urllib.error, base64, time, os

MCP_URL  = sys.argv[1]
OUT_DIR  = sys.argv[2]
TOKEN    = sys.argv[3]
HEADERS_BASE = {"Content-Type": "application/json",
                "Accept":       "application/json, text/event-stream"}
if TOKEN:
    HEADERS_BASE["Authorization"] = "Bearer " + TOKEN

def post(payload, sid=None, expect=True):
    h = dict(HEADERS_BASE)
    if sid: h["Mcp-Session-Id"] = sid
    req = urllib.request.Request(MCP_URL, data=json.dumps(payload).encode(),
                                 headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", errors="replace")
            new_sid = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id") or sid
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        new_sid = sid
    if not expect:
        return None, new_sid
    payloads = [ln[6:] for ln in body.splitlines() if ln.startswith("data: ")]
    if not payloads:
        return json.loads(body) if body.strip() else None, new_sid
    return json.loads(payloads[-1]), new_sid

def call_tool(name, args, sid, req_id):
    resp, _ = post({"jsonrpc":"2.0","id":req_id,"method":"tools/call",
                    "params":{"name": name, "arguments": args}}, sid=sid)
    if "error" in resp:
        raise SystemExit(f"FAIL {name}: {resp['error']}")
    return resp["result"]

# 1. handshake
init, sid = post({
    "jsonrpc":"2.0","id":1,"method":"initialize",
    "params":{"protocolVersion":"2025-03-26","capabilities":{},
              "clientInfo":{"name":"chromemcp-demo","version":"0.1.0"}}})
post({"jsonrpc":"2.0","method":"notifications/initialized"}, sid=sid, expect=False)
print(f"[+] MCP session: {sid}")

# 2. open a new tab
print("[+] Opening new tab via browser_tabs(action=new, url=https://example.com)...")
res = call_tool("browser_tabs", {"action": "new", "url": "https://example.com"}, sid, 2)
print("    -> Chrome should now show a new 'Example Domain' tab.")
print()
time.sleep(1)  # give the page a moment to paint

# 3. grab a screenshot of that tab
print("[+] Capturing screenshot via browser_take_screenshot...")
res = call_tool("browser_take_screenshot", {"type": "png", "fullPage": False}, sid, 3)

png_b64 = None
for c in res.get("content", []):
    if c.get("type") == "image" and c.get("mimeType","").startswith("image/"):
        png_b64 = c.get("data")
        break
if not png_b64:
    print("    !! screenshot tool returned no image content. Raw result:")
    print("   ", json.dumps(res, indent=2)[:600])
    raise SystemExit(1)

png_path = os.path.join(OUT_DIR, "example-com.png")
with open(png_path, "wb") as f:
    f.write(base64.b64decode(png_b64))
size_kb = os.path.getsize(png_path) / 1024
print(f"    -> Saved {size_kb:.1f} KB PNG to: {png_path}")
print()

# 4. clean up: close the tab we opened so user state is restored
# Find the index by listing tabs first.
print("[+] Closing the demo tab so we leave Chrome the way we found it...")
list_res = call_tool("browser_tabs", {"action": "list"}, sid, 4)
text = next((c.get("text","") for c in list_res.get("content",[]) if c.get("type")=="text"), "")
example_idx = None
for line in text.splitlines():
    line = line.strip()
    if "example.com" in line.lower():
        # lines look like "- 0: (current) [Title](url)" or "- 1: [Title](url)"
        try:
            example_idx = int(line.split(":",1)[0].lstrip("- ").strip())
            break
        except Exception:
            pass

if example_idx is not None:
    call_tool("browser_tabs", {"action": "close", "index": example_idx}, sid, 5)
    print(f"    -> Closed tab index {example_idx}.")
else:
    print("    -> Could not find example.com tab in list; leaving as-is.")

print()
print("Demo complete. Open the PNG to verify Chrome was driven from WSL:")
print(f"    explorer.exe '{png_path.replace('/mnt/r/', 'R:\\\\').replace('/', '\\\\')}'")
PYEOF
