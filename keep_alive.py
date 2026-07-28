"""Keep the SSU Energy Dashboard awake on Streamlit Community Cloud.

Streamlit Community Cloud puts any app with no traffic for 12 hours to
sleep (see https://docs.streamlit.io/deploy/streamlit-community-cloud/
manage-your-app#app-hibernation). Waking a sleeping app requires a real
visitor to click "Yes, get this app back up!" on the sleep screen — a
plain HTTP GET (curl / requests) only fetches a static shell and does
NOT count as the kind of traffic that resets the 12-hour timer or wakes
an already-sleeping app.

This script uses a real (headless) browser via Playwright so it behaves
like an actual visitor:
  1. Open the app URL.
  2. If the app is awake, the visit itself resets the 12-hour clock.
  3. If the app is asleep, find and click the wake-up button, then wait
     for the cold start to finish.

Intended to run on a schedule via GitHub Actions, well under the
12-hour sleep window (see .github/workflows/keep-alive.yml).
"""

from __future__ import annotations

import os
import sys
import time

from playwright.sync_api import sync_playwright

APP_URL = os.environ.get(
    "STREAMLIT_APP_URL",
    "https://ssu-energy-dashboard-usb4padbsjz7yz8tdq36zz.streamlit.app/",
)

# Substring match, case-insensitive — matches Streamlit's wake-up button text.
WAKE_BUTTON_TEXT = "get this app back up"

PAGE_LOAD_TIMEOUT_MS = 60_000
SETTLE_WAIT_MS = 5_000
MAX_WAKE_WAIT_SECONDS = 90


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print(f"Visiting {APP_URL} ...")
        try:
            page.goto(APP_URL, wait_until="load", timeout=PAGE_LOAD_TIMEOUT_MS)
        except Exception as e:
            print(f"Page load failed: {e}")
            browser.close()
            return 1

        # Let the page settle so the sleep screen (if any) has rendered.
        page.wait_for_timeout(SETTLE_WAIT_MS)

        wake_button = page.get_by_text(WAKE_BUTTON_TEXT, exact=False)

        if wake_button.count() > 0:
            print("App is asleep — clicking the wake-up button ...")
            wake_button.first.click()

            start = time.time()
            while time.time() - start < MAX_WAKE_WAIT_SECONDS:
                page.wait_for_timeout(5_000)
                if wake_button.count() == 0:
                    print("Wake-up button is gone — app is coming back up.")
                    break
            else:
                print("Timed out waiting for wake-up to complete; "
                      "next scheduled run will try again.")
        else:
            print("App was already awake — this visit resets its sleep timer.")

        browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
