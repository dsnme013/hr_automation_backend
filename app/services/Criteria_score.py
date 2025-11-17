"""
Criteria Corp - Complete Score Scraper v4
FIXED: Properly extracts ALL jobs from custom dropdown (not just "Manager" jobs)
"""

import argparse
import json
import csv
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from playwright.sync_api import sync_playwright, Page
import re

# Configuration
DEFAULT_BASE = "https://hireselect.criteriacorp.com"
OUT_DIR = Path("criteria_scores")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def ts() -> str:
    """Generate timestamp"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def save_screenshot(page: Page, tag: str):
    """Save screenshot"""
    try:
        path = OUT_DIR / f"{tag}_{ts()}.png"
        page.screenshot(path=str(path), full_page=True)
        print(f"📸 Screenshot: {path}")
    except Exception as e:
        print(f"⚠️  Screenshot failed: {e}")

# ═══════════════════════ MANUAL LOGIN ═══════════════════════
def wait_for_manual_login(page: Page) -> bool:
    """Wait for user to login manually"""
    print("\n🔐 Opening Criteria Corp login page...")
    print("=" * 70)
    print("   PLEASE LOGIN MANUALLY IN THE BROWSER")
    print("=" * 70)
    print()
    print("📋 Instructions:")
    print("   1. The browser will open to the login page")
    print("   2. Enter your email and password")
    print("   3. Complete any 2FA or verification if needed")
    print("   4. Wait until you see the Dashboard or Results page")
    print("   5. The script will automatically continue!")
    print()
    print("⏳ Waiting for you to login... (5 minute timeout)")
    print()
    
    try:
        page.goto(f"{DEFAULT_BASE}/login", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        save_screenshot(page, "01_login_page")
        
        if "dashboard" in page.url.lower() or "result" in page.url.lower():
            print("✅ Already logged in!")
            save_screenshot(page, "02_logged_in")
            return True
        
        deadline = time.time() + 300
        last_url = page.url
        
        while time.time() < deadline:
            current_url = page.url
            
            if current_url != last_url:
                print(f"   → Navigated to: {current_url}")
                last_url = current_url
            
            if "dashboard" in current_url.lower() or "result" in current_url.lower() or "home" in current_url.lower():
                print()
                print("✅ Login detected! Dashboard reached.")
                save_screenshot(page, "02_logged_in")
                page.wait_for_timeout(2000)
                return True
            
            if page.locator("text='Dashboard'").count() > 0 or \
               page.locator("text='Results'").count() > 0:
                print()
                print("✅ Login successful!")
                save_screenshot(page, "02_logged_in")
                return True
            
            page.wait_for_timeout(2000)
        
        print()
        print("❌ Login timeout")
        return False
        
    except Exception as e:
        print(f"❌ Login error: {e}")
        return False

# ═══════════════════════ NAVIGATE TO RESULTS ═══════════════════════
def navigate_to_results(page: Page) -> bool:
    """Navigate to Results page"""
    print("\n📊 Navigating to Results page...")
    
    try:
        if "result" in page.url.lower():
            print("✅ Already on Results page")
            return True
        
        results_selectors = [
            "a:has-text('Results')",
            "nav a:has-text('Results')",
            "[href*='resultLanding']",
            "a[href*='result']",
            "button:has-text('Results')"
        ]
        
        for selector in results_selectors:
            try:
                tab = page.locator(selector).first
                if tab.count() > 0 and tab.is_visible():
                    tab.click()
                    print("✅ Clicked Results tab")
                    page.wait_for_timeout(3000)
                    page.wait_for_load_state("networkidle", timeout=15000)
                    save_screenshot(page, "03_results_page")
                    return True
            except:
                continue
        
        try:
            page.goto(f"{DEFAULT_BASE}/resultLanding", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
            print("✅ Navigated to Results page")
            save_screenshot(page, "03_results_page")
            return True
        except:
            pass
        
        print("⚠️  Could not navigate to Results page")
        return False
        
    except Exception as e:
        print(f"❌ Navigation error: {e}")
        return False

# ═══════════════════════ GET JOBS - FIXED FOR CUSTOM DROPDOWN ═══════════════════════
def get_available_jobs(page: Page) -> List[Dict]:
    """Get list of available jobs - FIXED for custom dropdown"""
    print("\n📋 Getting available jobs...")
    print("=" * 70)
    
    jobs = []
    
    try:
        page.wait_for_timeout(3000)
        
        print("🔍 Step 1: Looking for 'Select a Job' button...")
        save_screenshot(page, "04a_before_dropdown")
        
        # Find and click the "Select a Job" button
        button_selectors = [
            "button:has-text('Select a Job')",
            "div:has-text('Select a Job')",
            "[class*='select']:has-text('Select')",
            "button:has-text('Select')"
        ]
        
        dropdown_clicked = False
        for selector in button_selectors:
            try:
                button = page.locator(selector).first
                if button.count() > 0 and button.is_visible():
                    button.click()
                    print(f"✅ Clicked dropdown button: {selector}")
                    dropdown_clicked = True
                    page.wait_for_timeout(2000)  # Wait for dropdown to expand
                    break
            except:
                continue
        
        if not dropdown_clicked:
            print("⚠️  Could not find dropdown button")
            return []
        
        save_screenshot(page, "04b_dropdown_open")
        
        print("\n🔍 Step 2: Extracting ALL jobs from dropdown...")
        
        # After dropdown opens, find ALL job items
        # Looking at the screenshot, jobs appear as clickable items with:
        # - Job title (e.g., "Finance Assistant")
        # - Job ID and creator info below
        # - Candidate count on the right
        
        # Strategy 1: Look for divs/elements that contain job titles
        # The dropdown shows items in a scrollable list
        
        # Try to find all clickable job items
        job_item_selectors = [
            "div[role='option']",
            "li[role='option']",
            "[class*='job-item']",
            "[class*='dropdown-item']",
            "div[class*='result'] a",
            "a[href*='job']"
        ]
        
        all_jobs_found = []
        
        # Method 1: Try structured dropdown items
        for selector in job_item_selectors:
            try:
                items = page.locator(selector).all()
                if len(items) > 0:
                    print(f"   Found {len(items)} items with selector: {selector}")
                    
                    for item in items:
                        try:
                            text = item.inner_text().strip()
                            if text and len(text) > 3:
                                all_jobs_found.append({
                                    'element': item,
                                    'text': text,
                                    'selector': selector
                                })
                        except:
                            continue
                    
                    if all_jobs_found:
                        break
            except:
                continue
        
        # Method 2: If no structured items, look for all links/divs in the visible dropdown area
        if not all_jobs_found:
            print("   Trying broader search...")
            
            # Look for the dropdown menu container
            dropdown_containers = [
                "div[class*='dropdown-menu']",
                "div[class*='menu']",
                "ul[class*='dropdown']",
                "[role='menu']",
                "[role='listbox']"
            ]
            
            for container_selector in dropdown_containers:
                try:
                    container = page.locator(container_selector).first
                    if container.count() > 0 and container.is_visible():
                        print(f"   Found dropdown container: {container_selector}")
                        
                        # Get all clickable items within
                        items = container.locator("a, button, div[role='option'], li").all()
                        print(f"   Found {len(items)} items inside")
                        
                        for item in items:
                            try:
                                text = item.inner_text().strip()
                                if text and len(text) > 3:
                                    # Check if it looks like a job listing
                                    if any(indicator in text for indicator in ['Manager', 'Assistant', 'Director', 'Job ID', 'Created By']):
                                        all_jobs_found.append({
                                            'element': item,
                                            'text': text,
                                            'selector': container_selector
                                        })
                            except:
                                continue
                        
                        if all_jobs_found:
                            break
                except:
                    continue
        
        # Method 3: Last resort - look for ANY visible text that contains job indicators
        if not all_jobs_found:
            print("   Using text parsing method...")
            
            # Get all visible text elements
            all_visible = page.locator("body *").all()
            
            for elem in all_visible[:200]:  # Limit to first 200 elements
                try:
                    if not elem.is_visible():
                        continue
                    
                    text = elem.inner_text().strip()
                    
                    # Look for job-like patterns
                    if text and 10 < len(text) < 500:
                        # Check if contains job indicators
                        if 'Job ID:' in text or 'Created By:' in text:
                            all_jobs_found.append({
                                'element': elem,
                                'text': text,
                                'selector': 'text-search'
                            })
                except:
                    continue
        
        # Now parse the found items to extract job information
        print(f"\n   Processing {len(all_jobs_found)} potential job items...")
        
        seen_titles = set()
        
        for item_data in all_jobs_found:
            try:
                text = item_data['text']
                
                # Extract job title (first line)
                lines = text.split('\n')
                job_title = lines[0].strip()
                
                # Skip if already seen
                if job_title in seen_titles or not job_title:
                    continue
                
                # Skip non-job items (like "Search by job title...")
                if len(job_title) < 5 or 'search' in job_title.lower():
                    continue
                
                # Extract candidate count (look for numbers)
                candidate_count = "?"
                for line in lines:
                    # Look for standalone number (candidate count)
                    if line.strip().isdigit():
                        candidate_count = line.strip()
                        break
                
                # Extract Job ID if present
                job_id = ""
                for line in lines:
                    if 'Job ID:' in line:
                        match = re.search(r'Job ID:\s*([A-Z0-9-]+)', line)
                        if match:
                            job_id = match.group(1)
                        break
                
                seen_titles.add(job_title)
                
                job_info = {
                    "index": len(jobs) + 1,
                    "title": job_title,
                    "candidate_count": candidate_count,
                    "job_id": job_id,
                    "full_text": text,
                    "element": item_data['element']
                }
                
                jobs.append(job_info)
                print(f"  ✓ {len(jobs)}. {job_title} ({candidate_count} candidates)")
                
            except Exception as e:
                continue
        
        # Final results
        print("\n" + "=" * 70)
        
        if jobs:
            print(f"✅ SUCCESS! Found {len(jobs)} jobs:\n")
            for job in jobs:
                print(f"  {job['index']}. {job['title']} ({job['candidate_count']} candidates)")
        else:
            print("❌ NO JOBS FOUND")
            print("\n⚠️  Browser will stay open for 2 minutes to inspect...")
        
        print("=" * 70)
        
        return jobs
        
    except Exception as e:
        print(f"❌ Error getting jobs: {e}")
        import traceback
        traceback.print_exc()
        save_screenshot(page, "error_jobs")
        return []

# ═══════════════════════ SELECT JOB ═══════════════════════
def select_job(page: Page, job_title: str, job_info: Dict = None) -> bool:
    """Select a specific job from dropdown"""
    print(f"\n🎯 Selecting job: {job_title}")
    
    try:
        # If we have the element, click it directly
        if job_info and 'element' in job_info:
            try:
                element = job_info['element']
                element.click()
                print(f"✅ Clicked job element directly")
                page.wait_for_timeout(3000)
                page.wait_for_load_state("networkidle", timeout=15000)
                save_screenshot(page, "05_job_selected")
                return True
            except Exception as e:
                print(f"   ⚠️ Direct click failed: {e}, trying other methods...")
        
        # Fallback: Try to find and click by text
        # Re-open dropdown if needed
        try:
            button = page.locator("button:has-text('Select a Job'), button:has-text('Select')").first
            if button.count() > 0:
                button.click()
                page.wait_for_timeout(1500)
        except:
            pass
        
        # Try clicking by text match
        click_selectors = [
            f"*:has-text('{job_title}'):visible",
            f"a:has-text('{job_title}')",
            f"div:has-text('{job_title}')",
            f"button:has-text('{job_title}')"
        ]
        
        for selector in click_selectors:
            try:
                elements = page.locator(selector).all()
                for elem in elements:
                    try:
                        text = elem.inner_text().strip()
                        if job_title in text and len(text) < 500:  # Not too long
                            elem.click()
                            print(f"✅ Clicked: {selector}")
                            page.wait_for_timeout(3000)
                            page.wait_for_load_state("networkidle", timeout=15000)
                            save_screenshot(page, "05_job_selected")
                            return True
                    except:
                        continue
            except:
                continue
        
        print(f"❌ Could not select job: {job_title}")
        return False
        
    except Exception as e:
        print(f"❌ Error selecting job: {e}")
        return False

# ═══════════════════════ EXTRACT SCORES ═══════════════════════
def extract_candidate_scores(page: Page, job_title: str) -> List[Dict]:
    """Extract all candidate scores"""
    print(f"\n📊 Extracting candidate scores for: {job_title}")
    
    candidates = []
    
    try:
        page.wait_for_timeout(3000)
        save_screenshot(page, "06_candidates_table")
        
        rows = page.locator("table tbody tr").all()
        
        if not rows:
            print("❌ No table rows found")
            return []
        
        print(f"📋 Found {len(rows)} candidate rows")
        
        headers = []
        header_elements = page.locator("table thead th").all()
        for h in header_elements:
            header_text = h.inner_text().strip()
            if header_text:
                headers.append(header_text)
        
        print(f"📊 Columns: {len(headers)} columns")
        
        for idx, row in enumerate(rows, 1):
            try:
                cells = row.locator("td").all()
                
                if len(cells) == 0:
                    continue
                
                candidate = {
                    "id": idx,
                    "job_title": job_title,
                    "name": "",
                    "email": "",
                    "status": "",
                    "overall_score": "",
                    "scores": {}
                }
                
                for cell_idx, cell in enumerate(cells):
                    try:
                        cell_text = cell.inner_text().strip()
                        
                        if cell_idx == 0:
                            link = cell.locator("a").first
                            if link.count() > 0:
                                candidate["name"] = link.inner_text().strip()
                            else:
                                candidate["name"] = cell_text.split('\n')[0].strip()
                            
                            if '@' in cell_text:
                                lines = cell_text.split('\n')
                                for line in lines:
                                    if '@' in line:
                                        candidate["email"] = line.strip()
                                        break
                            
                            if 'incoming' in cell_text.lower():
                                candidate["status"] = "Incoming"
                            elif 'completed' in cell_text.lower():
                                candidate["status"] = "Completed"
                        
                        elif cell_idx < len(headers):
                            header = headers[cell_idx]
                            candidate["scores"][header] = cell_text
                    
                    except:
                        continue
                
                if candidate["name"]:
                    candidates.append(candidate)
                    print(f"  ✓ {idx}. {candidate['name']}")
            
            except Exception as e:
                continue
        
        print(f"\n✅ Extracted {len(candidates)} candidates")
        return candidates
        
    except Exception as e:
        print(f"❌ Error extracting: {e}")
        return []

# ═══════════════════════ GET DETAILED SCORES ═══════════════════════
def get_detailed_scores(page: Page, candidates: List[Dict]) -> List[Dict]:
    """Get detailed Talent Signal scores"""
    print("\n🔍 Getting detailed Talent Signal scores...")
    
    for idx, candidate in enumerate(candidates, 1):
        try:
            print(f"  [{idx}/{len(candidates)}] {candidate['name']}...", end=" ")
            
            candidate_link = page.locator(f"a:has-text('{candidate['name']}')").first
            
            if candidate_link.count() > 0 and candidate_link.is_visible():
                candidate_link.click()
                page.wait_for_timeout(2000)
                save_screenshot(page, f"07_detail_{idx}")
                
                talent_signal = ""
                
                large_nums = page.locator("text=/^\\d{2,3}$/").all()
                for num in large_nums[:3]:
                    try:
                        text = num.inner_text().strip()
                        if text.isdigit() and 0 <= int(text) <= 100:
                            talent_signal = text
                            break
                    except:
                        continue
                
                if not talent_signal:
                    try:
                        page_text = page.inner_text("body")
                        match = re.search(r'Talent Signal[:\s]+(\d{1,3})', page_text, re.IGNORECASE)
                        if match:
                            talent_signal = match.group(1)
                    except:
                        pass
                
                candidate["talent_signal"] = talent_signal
                candidate["overall_score"] = talent_signal
                
                print(f"✓ Talent Signal: {talent_signal}")
                
                page.go_back()
                page.wait_for_timeout(1500)
            else:
                print("⚠️ Could not click")
        
        except Exception as e:
            print(f"⚠️ Error: {e}")
            continue
    
    return candidates

# ═══════════════════════ EXPORT ═══════════════════════
def export_to_json(candidates: List[Dict], job_title: str) -> str:
    """Export to JSON"""
    safe_title = job_title.replace(' ', '_').replace('/', '_')
    filename = f"{safe_title}_{ts()}.json"
    filepath = OUT_DIR / filename
    
    data = {
        "job_title": job_title,
        "extracted_at": datetime.now().isoformat(),
        "total_candidates": len(candidates),
        "candidates": candidates
    }
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ JSON: {filepath}")
    return str(filepath)

def export_to_csv(candidates: List[Dict], job_title: str) -> str:
    """Export to CSV"""
    safe_title = job_title.replace(' ', '_').replace('/', '_')
    filename = f"{safe_title}_{ts()}.csv"
    filepath = OUT_DIR / filename
    
    if not candidates:
        return ""
    
    flat = []
    for c in candidates:
        row = {
            "id": c.get("id"),
            "job_title": c.get("job_title"),
            "name": c.get("name"),
            "email": c.get("email"),
            "status": c.get("status"),
            "overall_score": c.get("overall_score"),
            "talent_signal": c.get("talent_signal", "")
        }
        row.update(c.get("scores", {}))
        flat.append(row)
    
    fieldnames = set()
    for row in flat:
        fieldnames.update(row.keys())
    fieldnames = sorted(list(fieldnames))
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flat)
    
    print(f"✅ CSV: {filepath}")
    return str(filepath)

# ═══════════════════════ MAIN ═══════════════════════
def main():
    parser = argparse.ArgumentParser(description="Criteria Score Scraper v4 - Fixed for custom dropdown")
    parser.add_argument("--job", help="Specific job title")
    parser.add_argument("--all-jobs", action="store_true", help="Scrape all jobs")
    parser.add_argument("--detailed", action="store_true", help="Get Talent Signal scores")
    parser.add_argument("--format", choices=["json", "csv", "both"], default="both")
    
    args = parser.parse_args()
    
    print("\n" + "═" * 70)
    print("   CRITERIA CORP - SCORE SCRAPER V4")
    print("   FIXED: Custom Dropdown + All Jobs")
    print("═" * 70)
    print(f"Mode: {'All Jobs' if args.all_jobs else ('Job: ' + args.job if args.job else 'Interactive')}")
    print(f"Detailed: {'Yes' if args.detailed else 'No'}")
    print("═" * 70)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=300)
        context = browser.new_context(viewport={"width": 1600, "height": 900})
        page = context.new_page()
        
        try:
            if not wait_for_manual_login(page):
                raise Exception("Login failed")
            
            if not navigate_to_results(page):
                raise Exception("Could not navigate to Results")
            
            jobs = get_available_jobs(page)
            
            if not jobs:
                print("\n❌ No jobs found")
                print("\n⏳ Browser will stay open for 2 minutes for inspection...")
                page.wait_for_timeout(120000)
                return
            
            jobs_to_scrape = []
            
            if args.all_jobs:
                jobs_to_scrape = jobs
            elif args.job:
                for job in jobs:
                    if args.job.lower() in job["title"].lower():
                        jobs_to_scrape.append(job)
                        break
                if not jobs_to_scrape:
                    print(f"\n❌ Job not found: {args.job}")
                    print("\n📋 Available jobs:")
                    for job in jobs:
                        print(f"  - {job['title']}")
                    page.wait_for_timeout(30000)
                    return
            else:
                print("\n📋 Available Jobs:")
                for job in jobs:
                    print(f"  {job['index']}. {job['title']} ({job['candidate_count']} candidates)")
                
                choice = input("\nEnter job number (or 'all'): ").strip()
                
                if choice.lower() == 'all':
                    jobs_to_scrape = jobs
                else:
                    try:
                        idx = int(choice)
                        found = [j for j in jobs if j["index"] == idx]
                        if found:
                            jobs_to_scrape.append(found[0])
                    except:
                        print("Invalid choice")
                        return
            
            for job in jobs_to_scrape:
                job_title = job["title"]
                print(f"\n{'═' * 70}")
                print(f"SCRAPING: {job_title}")
                print(f"{'═' * 70}")
                
                if not select_job(page, job_title, job):
                    print(f"❌ Could not select: {job_title}")
                    continue
                
                candidates = extract_candidate_scores(page, job_title)
                
                if not candidates:
                    print(f"⚠️ No candidates found")
                    continue
                
                if args.detailed:
                    candidates = get_detailed_scores(page, candidates)
                
                if args.format in ["json", "both"]:
                    export_to_json(candidates, job_title)
                
                if args.format in ["csv", "both"]:
                    export_to_csv(candidates, job_title)
                
                print(f"\n📊 Statistics:")
                print(f"   Total: {len(candidates)}")
                
                if args.detailed:
                    scores = [int(c.get("talent_signal", 0) or 0) for c in candidates if c.get("talent_signal")]
                    if scores:
                        print(f"   Average: {sum(scores)/len(scores):.1f}")
                        print(f"   Highest: {max(scores)}")
                        print(f"   Lowest: {min(scores)}")
            
            print("\n" + "═" * 70)
            print("   COMPLETE!")
            print("═" * 70)
            print(f"📁 Files saved in: {OUT_DIR}")
            
            print("\n⏳ Browser stays open for 10 seconds...")
            page.wait_for_timeout(10000)
            
        except KeyboardInterrupt:
            print("\n\n⚠️ Interrupted")
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            save_screenshot(page, "error_final")
            print("\n⏳ Browser open for 60 seconds for debugging...")
            page.wait_for_timeout(60000)
        finally:
            browser.close()
            print("\n👋 Done!")

if __name__ == "__main__":
    main()