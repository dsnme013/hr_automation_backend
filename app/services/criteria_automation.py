import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Tuple
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout
# from app.services.criteria_automation import runpipeline as create_criteria_assessment_pipeline



# ═══════════════════════ CONFIGURATION ═══════════════════════
DEFAULT_BASE = "https://hireselect.criteriacorp.com"
PROFILE_DIR = os.getenv("CRITERIA_PROFILE_DIR", str(Path.home() / ".criteria_profile"))
PROFILE_DIR = str(Path(PROFILE_DIR).expanduser().resolve())

OUT_DIR = Path("criteria_runs")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def save_screenshot(page: Page, tag: str):
    try:
        path = OUT_DIR / f"{tag}_{ts()}.png"
        page.screenshot(path=str(path), full_page=True)
        print(f"📸 Screenshot: {path}")
    except:
        pass

def wait_and_click(page: Page, selector: str, timeout: int = 40000) -> bool:
    try:
        element = page.locator(selector).first
        element.wait_for(state="visible", timeout=timeout)
        element.click()
        page.wait_for_timeout(500)
        return True
    except:
        return False

# ═══════════════════════ LOGIN HANDLER ═══════════════════════
def ensure_logged_in(page: Page) -> bool:
    """Ensure user is logged in."""
    print("🔐 Checking login status...")

    if "dashboard" in page.url or page.locator("text='Dashboard'").count() > 0:
        print("✅ Already logged in")
        return True

    print("📝 Please complete login in the browser...")

    if "/login" not in page.url:
        page.goto(f"{DEFAULT_BASE}/login", wait_until="domcontentloaded")

    save_screenshot(page, "login_page")

    deadline = time.time() + 300
    while time.time() < deadline:
        if page.locator("text='Dashboard'").count() > 0 or \
           page.locator("text='Create Job'").count() > 0 or \
           "/dashboard" in page.url:
            print("✅ Login successful!")
            return True
        page.wait_for_timeout(5000)

    print("❌ Login timeout")
    return False


# ═══════════════════════ STEP 1: JOB SETUP ═══════════════════════
def step1_job_setup(page: Page, job_title: str) -> bool:
    print("\n═══ STEP 1: Job Setup ═══")
    page.wait_for_timeout(5000)
    print(f"📝 Entering job title: {job_title}")

    selectors = [
        "input[placeholder*='Enter the job title']",
        "input[placeholder*='job title']",
        "form input[type='text']:first-child",
        "input[type='text']:visible"
    ]

    for sel in selectors:
        try:
            field = page.locator(sel).first
            if field.count() > 0 and field.is_visible():
                field.click()
                field.fill(job_title)
                print("✅ Job title entered")
                break
        except:
            continue

    print("🎯 Verifying ASSESSMENTS is selected")
    try:
        assessments_element = page.locator("text='ASSESSMENTS'").first
        if assessments_element.count() > 0:
            assessments_element.click()
            print("✅ ASSESSMENTS option selected")
    except:
        print("⚠️  ASSESSMENTS might already be selected")

    save_screenshot(page, "step1_complete")

    print("🔄 Clicking Continue...")
    for sel in [
        "button:has-text('Continue')",
        "button[type='submit']:has-text('Continue')"
    ]:
        if wait_and_click(page, sel, timeout=6000):
            print("✅ Clicked Continue")
            return True
    print("❌ Could not click Continue")
    return False


# ═══════════════════════ STEP 2: OCCUPATION ═══════════════════════
def step2_occupation_search(page: Page, search_term: str = "python developer") -> bool:
    """Step 2: Search for occupation"""
    print("\n═══ STEP 2: Occupation Selection ═══")
    
    page.wait_for_timeout(3000)
    
    print(f"🔍 Searching for occupation: {search_term}")
    
    try:
        # Find the occupation search input
        occupation_input_selectors = [
            "main input[type='text']",
            "main input[type='search']",
            "input[placeholder*='occupation']",
            "section input[type='text']:visible",
            "input[type='text']:not(nav input):not(header input):visible"
        ]
        
        search_input_found = False
        search_input = None
        
        for selector in occupation_input_selectors:
            try:
                inputs = page.locator(selector).all()
                for input_elem in inputs:
                    if input_elem.is_visible():
                        placeholder = input_elem.get_attribute("placeholder") or ""
                        
                        if "search candidates" in placeholder.lower() or "web developer" in placeholder.lower():
                            continue
                        
                        search_input = input_elem
                        search_input_found = True
                        break
                        
                if search_input_found:
                    break
            except:
                continue
        
        if not search_input_found:
            all_inputs = page.locator("input[type='text']:visible").all()
            
            for input_elem in all_inputs:
                try:
                    input_y = input_elem.bounding_box()["y"]
                    if input_y > 200:
                        search_input = input_elem
                        search_input_found = True
                        break
                except:
                    continue
        
        if search_input_found and search_input:
            search_input.click()
            page.wait_for_timeout(500)
            search_input.fill("")
            page.wait_for_timeout(200)
            search_input.fill(search_term)
            print(f"✅ Entered search term: {search_term}")
            page.wait_for_timeout(500)
            
            print("🔍 Triggering search...")
            
            search_button_clicked = False
            search_button_selectors = [
                "button[type='submit']:visible",
                "button:has(svg):visible",
                "button.primary:visible"
            ]
            
            for selector in search_button_selectors:
                try:
                    button = page.locator(selector).first
                    if button.count() > 0 and button.is_visible():
                        button_y = button.bounding_box()["y"]
                        if button_y > 200:
                            button.click()
                            search_button_clicked = True
                            print("✅ Clicked search button")
                            break
                except:
                    continue
            
            if not search_button_clicked:
                search_input.press("Enter")
                print("⏎ Pressed Enter to search")
            
            print("⏳ Waiting for search results...")
            page.wait_for_timeout(4000)
            
            if "/search" in page.url and "Results" in page.title():
                print("❌ ERROR: Ended up on wrong search page!")
                page.go_back()
                page.wait_for_timeout(3000)
                return False
            
            save_screenshot(page, "occupation_results")
            
            print("📌 Selecting occupation from results...")
            
            try:
                page.wait_for_selector("button:has-text('Select')", timeout=20000)
                
                select_buttons = page.locator("button:has-text('Select')").all()
                
                if select_buttons:
                    select_buttons[0].click()
                    print("✅ Selected first occupation")
                    page.wait_for_timeout(3000)
                    save_screenshot(page, "occupation_selected")
                    return True
                else:
                    print("❌ No Select buttons found")
                    return False
                    
            except PWTimeout:
                print("❌ No occupation results appeared")
                return False
                
        else:
            print("❌ Could not find occupation search input")
            return False
            
    except Exception as e:
        print(f"❌ Occupation search failed: {e}")
        return False

# ═══════════════════════ STEP 3: TEST BATTERY ═══════════════════════
def step3_test_battery(page: Page) -> bool:
    print("\n═══ STEP 3: Test Battery Selection ═══")
    page.wait_for_timeout(2000)
    save_screenshot(page, "test_battery_page")

    if wait_and_click(page, "button:has-text('Select')", timeout=9000):
        print("✅ Clicked Select button")
        return True
    print("❌ Could not find Select button")
    return False


# ═══════════════════════ STEP 4: LINK EXTRACTION ═══════════════════════
# def step4_capture_link_ultimate(page: Page) -> Tuple[Optional[str], bool]:
#     print("\n═══ STEP 4: Capture Assessment Link ═══")
#     try:
#         page.wait_for_selector("text='Your job has been created!'", timeout=18000)
#         print("✅ Success modal appeared!")
#         save_screenshot(page, "success_modal")

#         text = page.content()
#         urls = re.findall(r'https?://[^\s<>"]+', text)
#         for url in urls:
#             if "ondemandassessment" in url:
#                 print(f"✅ Found link: {url}")
#                 return url, True

#         print("❌ Could not extract link automatically")
#         return None, False
#     except PWTimeout:
#         print("⚠️  Modal did not appear")
#         save_screenshot(page, "no_modal")
#         return None, False
def step4_capture_link_ultimate(page: Page) -> Tuple[Optional[str], bool]:
    print("\n═══ STEP 4: Capture Assessment Link ═══")
    try:
        page.wait_for_selector("text='Your job has been created!'", timeout=20000)
        print("✅ Success modal appeared!")
        save_screenshot(page, "success_modal")

        html = page.inner_html("body")

        # 1) Try direct full URL
        full = re.findall(r'https:\/\/www\.ondemandassessment\.com\/o\/[A-Za-z0-9_-]+\/landing\?u=\d+', html)
        if full:
            link = full[0].replace("\\/", "/")
            print(f"✅ Found full link: {link}")
            return link, True

        # 2) Try escaped URL
        escaped = re.findall(r'https:\\/\\/www\.ondemandassessment\.com\\/o\\/[A-Za-z0-9_-]+\\/landing\?u=\d+', html)
        if escaped:
            link = escaped[0].replace("\\/", "/")
            print(f"✅ Found escaped link: {link}")
            return link, True

        # 3) Try partial URL
        partial = re.findall(r'\/o\/[A-Za-z0-9_-]+\/landing\?u=\d+', html)
        if partial:
            link = "https://www.ondemandassessment.com" + partial[0]
            print(f"✅ Found partial link: {link}")
            return link, True

        print("❌ Could not extract link automatically")
        return None, False

    except PWTimeout:
        print("⚠️ Modal did not appear")
        save_screenshot(page, "no_modal")
        return None, False


# ═══════════════════════ CORE AUTOMATION ═══════════════════════
def run_automation(page: Page, job_title: str, occupation_search: str = "python developer") -> Dict:
    result = {
        "status": "started",
        "job_title": job_title,
        "occupation_search": occupation_search,
        "assessment_link": None,
        "timestamps": {"start": ts()},
    }
    try:
        print("\n🚀 Starting job creation process...")
        page.goto(f"{DEFAULT_BASE}/createJob", wait_until="domcontentloaded")
        save_screenshot(page, "create_job_page")

        # Step 1
        if not step1_job_setup(page, job_title):
            raise Exception("Step 1 failed")
        result["timestamps"]["step1"] = ts()

        # Step 2
        step2_occupation_search(page, occupation_search)
        result["timestamps"]["step2"] = ts()

        # Step 3
        step3_test_battery(page)
        result["timestamps"]["step3"] = ts()

        # Step 4
        link, success = step4_capture_link_ultimate(page)
        result["assessment_link"] = link or None
        result["status"] = "completed" if success else "completed_no_link"
        result["timestamps"]["completed"] = ts()

    except Exception as e:
        print(f"❌ Automation failed: {e}")
        save_screenshot(page, "error_state")
        result["status"] = "failed"
        result["error"] = str(e)

    return result


# ═══════════════════════ PERSISTENT BROWSER LAUNCH ═══════════════════════
def _launch_persistent_browser(headless: bool = True, slowmo: int = 0):
    profile_path = Path(PROFILE_DIR).expanduser().resolve()
    if (profile_path / "Default").exists():
        profile_path = profile_path / "Default"
    profile_path.mkdir(parents=True, exist_ok=True)

    p = sync_playwright().start()
    context = p.chromium.launch_persistent_context(
        str(profile_path),
        headless=headless,
        slow_mo=slowmo,
        viewport={"width": 1440, "height": 900},
        ignore_https_errors=True,
        args=[
            "--start-maximized",
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    page = context.new_page()
    return p, context, page


# ═══════════════════════ MAIN PIPELINE ═══════════════════════
def runpipeline(job_title: str, occupation: str = "python developer",
                *, headless: bool = True, slowmo: int = 0) -> Optional[str]:
    p, context, page = _launch_persistent_browser(headless=headless, slowmo=slowmo)
    try:
        page.goto(DEFAULT_BASE, wait_until="domcontentloaded")
        if not ensure_logged_in(page):
            if headless:
                print("🔁 Retrying login in visible mode...")
                context.close()
                p.stop()
                return runpipeline(job_title, occupation, headless=False)
            else:
                raise RuntimeError("Manual login required. Run once visibly.")

        result = run_automation(page, job_title, occupation)
        return (result or {}).get("assessment_link")

    finally:
        context.close()
        p.stop()


# ═══════════════════════ CLI ENTRY ═══════════════════════
def main():
    parser = argparse.ArgumentParser(description="Criteria Corp Automation (Fixed Version)")
    parser.add_argument("--job-title", required=True)
    parser.add_argument("--occupation", default="python developer")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    print("═" * 60)
    print("CRITERIA AUTOMATION - FIXED VERSION")
    print("═" * 60)

    link = runpipeline(args.job_title, args.occupation, headless=args.headless)
    print("\nResult:")
    print("✅ Link:" if link else "❌ No link extracted.", link or "")
    print("═" * 60)


if __name__ == "__main__":
    main()

