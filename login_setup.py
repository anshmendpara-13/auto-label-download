"""
Run ONCE per account to save a logged-in browser session.
Session stored in data/<account_id>/state.json

Usage:
    python login_setup.py lavanyafashion
    python login_setup.py lavanza998
"""

import os
import re
import sys
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

load_dotenv()

LOGIN_URL = "https://supplier.meesho.com/panel/v3/new/root/login"


def get_credentials(account_id):
    if account_id:
        email = os.getenv(f"MEESHO_EMAIL_{account_id}") or os.getenv(f"MEESHO_EMAIL_{account_id.upper()}")
        password = os.getenv(f"MEESHO_PASSWORD_{account_id}") or os.getenv(f"MEESHO_PASSWORD_{account_id.upper()}")
    else:
        email = os.getenv("MEESHO_EMAIL")
        password = os.getenv("MEESHO_PASSWORD")
    return email, password


def try_autofill(page, email, password):
    if not email or not password:
        print("[!] No credentials in .env")
        return False

    try:
        email_input = page.locator("input[name='emailOrPhone']").first
        try:
            email_input.wait_for(state="attached", timeout=15000)
        except PWTimeout:
            email_input = page.locator("input[type='text'], input[type='email']").first
            email_input.wait_for(state="attached", timeout=10000)

        password_input = page.locator("input[name='password']").first
        try:
            password_input.wait_for(state="attached", timeout=5000)
        except PWTimeout:
            password_input = page.locator("input[type='password']").first

        def js_fill(locator, value):
            el = locator.element_handle()
            page.evaluate("""(args) => {
                const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                s.call(args.el, args.val);
                args.el.dispatchEvent(new Event('input', {bubbles:true}));
                args.el.dispatchEvent(new Event('change', {bubbles:true}));
            }""", {"el": el, "val": value})

        js_fill(email_input, email)
        js_fill(password_input, password)
        print(f"[+] Filled: {email}")
        page.locator("button[type='submit']").first.click(force=True)
        print("[+] Submitted")
        return True

    except Exception as e:
        print(f"[!] Auto-fill failed: {e}")
        return False


def save_session(account_id):
    load_dotenv(override=True)
    email, password = get_credentials(account_id)
    state_path = Path(f"data/{account_id}/state.json")
    state_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*50}")
    print(f"  Account : {account_id}")
    print(f"  Email   : {email or '[not in .env]'}")
    print(f"  Save to : {state_path}")
    print(f"{'='*50}\n")

    if not email or not password:
        print(f"[!] Add MEESHO_EMAIL_{account_id.upper()} and MEESHO_PASSWORD_{account_id.upper()} to .env")
        sys.exit(1)

    # Auto-detect: force headless on Linux servers with no display (e.g. Render)
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        headless_mode = True
    elif os.environ.get("RENDER"):
        headless_mode = True
    else:
        headless_mode = os.getenv("HEADLESS", "false").lower() == "true"

    print(f"[+] Browser mode: {'headless' if headless_mode else 'visible'}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless_mode)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="load")
        page.wait_for_timeout(1500)

        if not try_autofill(page, email, password):
            browser.close()
            sys.exit(1)

        print("[+] Waiting for dashboard...")
        try:
            page.wait_for_url(re.compile(r"/growth/([^/]+)/home"), timeout=30000)
            print("[+] Login successful!")
        except PWTimeout:
            if "/root/login" in page.url:
                print("[!] Login failed - wrong credentials or network issue")
                Path("logs").mkdir(exist_ok=True)
                page.screenshot(path=f"logs/login_fail_{account_id}_{datetime.now():%Y%m%d_%H%M%S}.png")
                print("[!] Screenshot saved to logs/")
                browser.close()
                sys.exit(1)
            else:
                try:
                    page.goto("https://supplier.meesho.com/panel/v3/new/growth/home", wait_until="load", timeout=15000)
                    if "/root/login" in page.url:
                        print("[!] Not logged in")
                        browser.close()
                        sys.exit(1)
                except Exception:
                    print("[!] Could not reach dashboard")
                    browser.close()
                    sys.exit(1)

        context.storage_state(path=str(state_path))
        print(f"[+] Saved: {state_path}")
        print(f"[+] Done! Run: python app.py")
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python login_setup.py <account_id>")
        sys.exit(1)
    save_session(sys.argv[1].strip())
