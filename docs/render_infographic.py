"""Re-render asktube_architecture_flow_infographic.png from the SVG.

Run this after editing the SVG, or the two files drift apart silently - the PNG
is what gets embedded in slides and READMEs, so a stale PNG is the version most
people actually see.

    cd docs && python render_infographic.py

Two details are load-bearing and were not obvious:

* **System Chrome, not a downloaded Chromium.** The SVG is set in Consolas, a
  Windows font. Rendering it anywhere without Consolas silently substitutes a
  fallback face and every text block reflows. `channel="chrome"` uses the
  browser already installed, which also avoids a ~150 MB download.
* **device_scale_factor=2.** The SVG's viewBox is 1600x1080; the committed PNG
  is 3200x2160. Rendering at 1x would quietly halve the resolution of a file
  whose whole purpose is to be legible when projected.

Verified on 2026-08-10: against the previous PNG, an untouched region shows a
mean absolute difference of 1.5/255 (antialiasing) and a best-alignment offset
of dx=0, dy=0 - so the output is faithful, not merely similar. The mode changes
from RGBA to RGB, which loses nothing: the old alpha channel was 255 everywhere.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
SVG = HERE / "asktube_architecture_flow_infographic.svg"
PNG = HERE / "asktube_architecture_flow_infographic.png"


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        page = browser.new_page(
            viewport={"width": 1600, "height": 1080},
            device_scale_factor=2,
        )
        page.goto(SVG.resolve().as_uri())
        page.wait_for_timeout(800)  # let font loading settle before capturing
        page.screenshot(path=str(PNG), omit_background=True)
        browser.close()

    print(f"rendered {PNG.name}")


if __name__ == "__main__":
    main()
