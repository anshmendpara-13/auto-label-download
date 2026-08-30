"""
Meesho Supplier Panel - Automatic Label Downloader

Flow per account:
  1. Load session from data/<account>/state.json
  2. Accept all Pending orders
  3. Download labels for Ready-to-Ship orders
  4. Save PDF to downloads/<date>/<account>/
"""

import os
import re
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

load_dotenv()

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "./downloads"))
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
DATA_DIR = Path("data")

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(f"logs/run_{datetime.now():%Y%m%d}.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("meesho_bot")


class SessionExpired(Exception):
    pass


def get_state_path(account_id):
    return Path(f"data/{account_id}/state.json") if account_id else Path("browser_profile/state.json")


def get_seller_slug(page):
    page.goto("https://supplier.meesho.com/panel/v3/new/growth/home", wait_until="load", timeout=60000)
    if "/root/login" in page.url:
        raise SessionExpired("Redirected to login")
        
    # Wait up to 15 seconds for client-side routing to append the seller slug
    try:
        page.wait_for_url(re.compile(r"/growth/([^/]+)/home"), timeout=15000)
    except Exception:
        if "/root/login" in page.url:
            raise SessionExpired("Redirected to login")
            
    match = re.search(r"/growth/([^/]+)/home", page.url)
    if not match:
        raise RuntimeError(f"Cannot detect seller slug. URL: {page.url}")
    return match.group(1)


def close_promo_popup(page):
    try:
        btn = page.locator("[class*='modal'] button").filter(has_text=re.compile(r"[✕✗×]|close", re.I)).first
        if btn.is_visible(timeout=4000):
            btn.click()
            log.info("Closed promo popup")
    except Exception:
        pass


def accept_pending_orders(page, seller_slug):
    url = f"https://supplier.meesho.com/panel/v3/new/fulfillment/{seller_slug}/orders/pending"
    log.info("Opening Pending orders...")
    page.goto(url, wait_until="load", timeout=60000)
    if "/root/login" in page.url:
        raise SessionExpired()

    select_all = page.locator("thead input[type='checkbox']").first
    try:
        select_all.wait_for(state="visible", timeout=10000)
    except PWTimeout:
        log.info("No pending orders")
        return

    select_all.click()

    accept_btn = page.get_by_role("button", name=re.compile(r"accept selected orders", re.I))
    if accept_btn.count() == 0:
        log.info("No accept button found")
        return
    accept_btn.first.click()

    try:
        confirm = page.get_by_role("button", name=re.compile(r"accept order", re.I))
        confirm.wait_for(state="visible", timeout=8000)
        confirm.click()
        log.info("Confirmed accept")
    except PWTimeout:
        pass

    log.info("Waiting for processing...")
    try:
        processing = page.get_by_text(re.compile(r"processing", re.I))
        # Wait up to 5 seconds for processing text/indicator to appear
        try:
            processing.wait_for(state="visible", timeout=5000)
        except PWTimeout:
            pass
        
        # Wait up to 10 seconds for it to disappear
        processing.wait_for(state="hidden", timeout=10000)
        
        # If successfully processed, check for success modal
        try:
            success = page.get_by_text(re.compile(r"orders? accepted successfully", re.I))
            success.wait_for(state="visible", timeout=5000)
            log.info(success.inner_text())
            page.get_by_role("button", name=re.compile(r"got it", re.I)).click()
        except PWTimeout:
            pass
    except PWTimeout:
        log.warning("Processing took more than 10 seconds, refreshing page...")
        page.reload(wait_until="load")


def apply_not_downloaded_filter(page):
    try:
        page.get_by_text(re.compile(r"^label downloaded$", re.I)).click(timeout=8000)
        page.get_by_role("option", name=re.compile(r"not downloaded", re.I)).click(timeout=8000)
        page.wait_for_load_state("load")
        log.info("Filter: Not Downloaded")
    except PWTimeout:
        log.warning("Could not apply filter")


def download_labels(page, seller_slug, account_id):
    url = f"https://supplier.meesho.com/panel/v3/new/fulfillment/{seller_slug}/orders/ready-to-ship"
    log.info("Opening Ready to Ship...")
    page.goto(url, wait_until="load", timeout=60000)
    if "/root/login" in page.url:
        raise SessionExpired()

    apply_not_downloaded_filter(page)

    select_all = page.locator("thead input[type='checkbox']").first
    try:
        select_all.wait_for(state="visible", timeout=10000)
    except PWTimeout:
        log.info("No ready-to-ship orders")
        return None

    select_all.click()

    label_btn = page.get_by_role("button", name=re.compile(r"^label$", re.I)).first
    label_btn.click()
    log.info("Generating labels...")

    try:
        result = page.get_by_text(re.compile(r"labels generated successfully for \d+", re.I))
        result.wait_for(state="visible", timeout=180000)
        msg = result.inner_text()
        log.info(msg)
        m = re.search(r"(\d+)", msg)
        if m:
            log.info(f"Labels: {m.group(1)}")
    except PWTimeout:
        log.warning("No success message, trying download anyway")

    with page.expect_download(timeout=60000) as dl_info:
        dialog = page.locator("[role='dialog']")
        dialog.wait_for(state="visible", timeout=15000)
        dialog.locator("button", has_text="Label").click()

    download = dl_info.value
    acc_folder = account_id or "default"
    dest_dir = DOWNLOAD_DIR / datetime.now().strftime("%Y-%m-%d") / acc_folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / download.suggested_filename
    download.save_as(dest)
    log.info(f"Saved: {dest}")
    return dest


def try_auto_login(account_id):
    if not account_id:
        return False
    log.info(f"[{account_id}] Attempting automatic session generation via login_setup.py...")
    import subprocess
    try:
        # Run login_setup.py as a subprocess to generate the session
        cmd = [sys.executable, "login_setup.py", account_id]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            log.info(f"[{account_id}] Automatic session generation succeeded!")
            return True
        else:
            log.error(f"[{account_id}] login_setup.py failed with return code {res.returncode}")
            if res.stdout:
                for line in res.stdout.splitlines():
                    if line.strip():
                        log.info(f"[{account_id}][login] {line.strip()}")
            if res.stderr:
                for line in res.stderr.splitlines():
                    if line.strip():
                        log.error(f"[{account_id}][login-error] {line.strip()}")
            return False
    except Exception as e:
        log.error(f"[{account_id}] Failed to execute login_setup: {e}")
        return False


def run_once(account_id=None, is_retry=False):
    state_file = get_state_path(account_id)
    label = account_id or "default"

    if not state_file.exists():
        log.warning(f"[{label}] Session file not found: {state_file}")
        if not is_retry and account_id:
            if try_auto_login(account_id):
                run_once(account_id, is_retry=True)
                return
        log.error(f"[{label}] No session: {state_file}")
        return

    log.info(f"[{label}] Starting...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(storage_state=str(state_file), accept_downloads=True)
        page = context.new_page()

        try:
            slug = get_seller_slug(page)
            log.info(f"[{label}] Slug: {slug}")
            close_promo_popup(page)
            accept_pending_orders(page, slug)
            download_labels(page, slug, account_id)
            log.info(f"[{label}] Complete")

        except SessionExpired:
            log.error(f"[{label}] Session invalid")
            try: context.close()
            except: pass
            try: browser.close()
            except: pass

            if not is_retry and account_id:
                if try_auto_login(account_id):
                    run_once(account_id, is_retry=True)
                    return
            log.error(f"[{label}] Run failed due to expired session.")

        except Exception as e:
            log.exception(f"[{label}] Failed: {e}")
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                page.screenshot(path=f"logs/error_{label}_{ts}.png")
            except Exception:
                pass

        finally:
            try: context.close()
            except: pass
            try: browser.close()
            except: pass


def run_all():
    load_dotenv(override=True)
    accounts = [a.strip() for a in os.getenv("ACCOUNTS", "").split(",") if a.strip()]

    if not accounts and DATA_DIR.exists():
        accounts = [d.name for d in DATA_DIR.iterdir() if d.is_dir() and (d / "state.json").exists()]

    if not accounts:
        log.warning("No accounts configured")
        return

    log.info(f"Running {len(accounts)} account(s): {accounts}")
    for i, acc in enumerate(accounts):
        if i > 0:
            time.sleep(15)
        log.info(f"\n{'='*50}")
        log.info(f"  {acc}  ({i+1}/{len(accounts)})")
        log.info(f"{'='*50}")
        try:
            run_once(acc)
        except Exception as e:
            log.error(f"Error for {acc}: {e}")
    log.info("All done")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_once(sys.argv[1].strip())
    else:
        run_all()
