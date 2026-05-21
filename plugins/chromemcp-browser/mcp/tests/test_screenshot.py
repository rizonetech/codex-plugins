#!/usr/bin/env python3
"""Covers: browser_take_screenshot (fullPage + viewport), browser_resize."""
import base64
import sys
sys.path.insert(0, sys.path[0] or ".")
from _harness import assert_true, run_test, fail
from mcp.client import McpClient


def main():
    c = McpClient()
    c.initialize()
    with c.scoped_tab(
        c.data_url(
            "<!doctype html><title>screenshot-fixture</title>"
            "<div style='background:red;width:200px;height:150px'>X</div>"
        )
    ):
        # Resize before screenshotting so we have a known geometry.
        c.call_tool("browser_resize", {"width": 480, "height": 320})

        # Viewport screenshot
        r1 = c.call_tool("browser_take_screenshot", {"type": "png", "fullPage": False})
        img1 = c.tool_image(r1)
        assert_true(img1 is not None, "browser_take_screenshot returned no image content")
        # PNG sanity: bytes should decode and be > a few KB for a 480x320 fixture
        png1 = base64.b64decode(img1["data"])
        assert_true(png1.startswith(b"\x89PNG\r\n\x1a\n"), "viewport screenshot is not a PNG")
        assert_true(len(png1) > 500, f"viewport screenshot suspiciously small ({len(png1)} bytes)")

        # Full-page screenshot
        r2 = c.call_tool("browser_take_screenshot", {"type": "png", "fullPage": True})
        img2 = c.tool_image(r2)
        assert_true(img2 is not None, "browser_take_screenshot fullPage returned no image content")
        png2 = base64.b64decode(img2["data"])
        assert_true(png2.startswith(b"\x89PNG\r\n\x1a\n"), "fullPage screenshot is not a PNG")
        assert_true(len(png2) > 500, f"fullPage screenshot suspiciously small ({len(png2)} bytes)")


if __name__ == "__main__":
    run_test("screenshot", main)
