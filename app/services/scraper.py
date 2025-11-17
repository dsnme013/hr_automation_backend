#!/usr/bin/env python3

import asyncio
import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Optional
from playwright.async_api import async_playwright, Page, BrowserContext
import json
from datetime import datetime
import sys
import httpx
from app.config_paths import RESUME_DIR


print("🚀 BambooHR Resume Scraper starting...")

# Configuration - OPTIMIZED TIMEOUTS
CONFIG = {
    'TIMEOUT': 30000,      # 30 seconds for navigation
    'RETRY_DELAY': 1.0,    # 1 second between retries
    'MAX_RETRIES': 3,      # Retry navigation up to 3 times
    'MIN_PDF_SIZE': 1000,
    'HEADLESS': False,     # Set to True for production
    'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# BambooHR Credentials and API
BAMBOOHR_EMAIL = "support@smoothoperations.ai"
BAMBOOHR_PASSWORD = "SmoothOperations1%"
TOFA_ENDPOINT = "https://n8n.greenoceanpropertymanagement.com/webhook/2f1b815e-31d5-4f0f-b2f6-b07e7637ecf5"
TOFA_API_KEY = "67593101297393632845404167993723"

# Primary domain
BAMBOOHR_DOMAIN = "https://greenoceanpm.bamboohr.com"
DOWNLOAD_DIR = str(RESUME_DIR)

# Setup logging
# Set to DEBUG for more detailed output during troubleshooting
DEBUG_MODE = True  # Set to False for production
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bamboohr_scraper.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def validate_job_id(job_id) -> bool:
    """Validate that job_id is numeric."""
    job_id_str = str(job_id) if isinstance(job_id, (int, str)) else ""
    return job_id_str.isdigit() and len(job_id_str) > 0

def sanitize_filename(name: str) -> str:
    """Sanitize filename by removing/replacing invalid characters."""
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', name)
    sanitized = re.sub(r'\s+', '_', sanitized.strip())
    return sanitized[:50]

async def get_2fa_token() -> Optional[str]:
    """Get 2FA token from API."""
    try:
        logger.info("🔑 Fetching 2FA token...")
        
        headers = {
            "x-api-key": TOFA_API_KEY,
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(TOFA_ENDPOINT, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                token = data.get("token")
                
                if token:
                    logger.info(f"✅ Got 2FA token: {token}")
                    return token
                else:
                    logger.error("❌ No token in API response")
                    return None
            else:
                logger.error(f"❌ 2FA API failed: HTTP {response.status_code}")
                return None
                
    except Exception as e:
        logger.error(f"❌ Error fetching 2FA token: {e}")
        return None

async def safe_goto(page: Page, url: str, wait_until: str = "domcontentloaded", max_retries: int = 3) -> bool:
    """Safely navigate to a URL with retries and better error handling."""
    for attempt in range(max_retries):
        try:
            logger.info(f"Navigating to {url} (attempt {attempt + 1}/{max_retries})")
            
            # Use less strict wait condition
            response = await page.goto(url, wait_until=wait_until, timeout=CONFIG['TIMEOUT'])
            
            # Check if navigation was successful
            if response:
                status = response.status
                if status >= 200 and status < 400:
                    logger.info(f"Successfully navigated to {url}")
                    return True
                else:
                    logger.warning(f"HTTP {status} when navigating to {url}")
            
            # Wait for page to stabilize
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            
            # Check if we're on the expected page
            current_url = page.url
            if url in current_url or current_url.startswith(url):
                return True
                
        except Exception as e:
            logger.warning(f"Navigation attempt {attempt + 1} failed: {str(e)}")
            
            if attempt < max_retries - 1:
                # Wait before retry
                await page.wait_for_timeout(int(CONFIG['RETRY_DELAY'] * 1000))
                
                # Check if we're already on the page we want
                current_url = page.url
                if url in current_url or current_url.startswith(url):
                    logger.info(f"Already on target page: {current_url}")
                    return True
            else:
                logger.error(f"Failed to navigate to {url} after {max_retries} attempts")
                return False
    
    return False

async def auto_login(page: Page, domain: str) -> bool:
    """Automatic login with 2FA support - OPTIMIZED."""
    try:
        logger.info("Starting automatic login...")
        
        # Navigate to login page
        login_url = f"{domain}/login.php"
        if not await safe_goto(page, login_url, "domcontentloaded"):
            return False
        
        # Check if already logged in
        await page.wait_for_load_state("networkidle", timeout=5000)
        if "login" not in page.url.lower():
            logger.info("✅ Already logged in!")
            return True
        
        # Click email login option if available
        try:
            await page.click("text=Log in with Email and Password", timeout=2000)
            await page.wait_for_timeout(500)
        except:
            pass  # Form might already be visible
        
        # Fill credentials
        logger.info("→ Filling credentials...")
        
        # Wait for and fill email field
        await page.wait_for_selector("input#lemail", timeout=5000)
        await page.fill("input#lemail", BAMBOOHR_EMAIL)
        
        # Fill password
        await page.fill("input[type='password']", BAMBOOHR_PASSWORD)
        
        # Submit form
        await page.keyboard.press("Enter")
        logger.info("✅ Login form submitted")
        
        # Wait for navigation or 2FA
        try:
            # Wait for either successful login or 2FA page
            await page.wait_for_url("**/multi_factor_authentication**", timeout=10000)
            logger.info("🔐 2FA page detected")
            
            # Wait a bit for page to fully load
            await page.wait_for_timeout(1000)
            
            # Get and submit 2FA token
            token = await get_2fa_token()
            if not token:
                logger.error("❌ Failed to get 2FA token")
                return False
            
            # Try multiple selectors for 2FA input
            input_selectors = [
                "input[name='code']",
                "input[type='text']:visible",
                "input[placeholder*='code' i]",
                "input[placeholder*='verify' i]",
                "input#code",
                "input.mfa-code-input"
            ]
            
            input_found = False
            for selector in input_selectors:
                try:
                    if await page.locator(selector).count() > 0:
                        logger.info(f"Found 2FA input with selector: {selector}")
                        await page.fill(selector, token)
                        input_found = True
                        break
                except:
                    continue
            
            if not input_found:
                logger.error("❌ Could not find 2FA input field")
                return False
            
            # Submit 2FA
            try:
                submit_button = page.locator("button[type='submit']:visible").first
                if await submit_button.count() > 0:
                    await submit_button.click()
                else:
                    await page.keyboard.press("Enter")
            except:
                await page.keyboard.press("Enter")
            
            logger.info("✅ 2FA submitted")
            
            # Wait for navigation with multiple checks
            for i in range(5):
                await page.wait_for_timeout(1000)
                current_url = page.url.lower()
                
                # Check if we've moved past 2FA
                if "multi_factor_authentication" not in current_url and "login" not in current_url:
                    logger.info(f"✅ Moved past 2FA! Current URL: {page.url}")
                    break
                
                # Check for trust device page
                if "trusted_browser" in current_url or "trust" in current_url:
                    logger.info("📱 Trust device page detected")
                    await handle_trust_device(page)
                    break
            
        except Exception as e:
            # No 2FA required or already passed
            logger.info(f"→ No 2FA required or checking login status...")
            await page.wait_for_load_state("networkidle", timeout=5000)
        
        # Final verification
        await page.wait_for_timeout(2000)
        final_url = page.url.lower()
        
        # More lenient success check
        login_successful = (
            "login" not in final_url and 
            "multi_factor_authentication" not in final_url and
            domain.lower() in final_url
        )
        
        if login_successful:
            logger.info(f"🎉 Login successful! Current URL: {page.url}")
            return True
        else:
            logger.error(f"❌ Login failed. Current URL: {page.url}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Login error: {e}")
        return False

async def handle_trust_device(page: Page) -> bool:
    """Handle trust device page."""
    try:
        logger.info("📱 Handling trust device page...")
        
        # Try to click "Trust this device" or similar
        trust_selectors = [
            "button:has-text('Trust')",
            "button:has-text('Yes')",
            "button:has-text('Continue')",
            "input[type='submit'][value*='Trust' i]",
            "button[type='submit']",
            "a:has-text('Continue')"
        ]
        
        for trust_selector in trust_selectors:
            try:
                if await page.locator(trust_selector).count() > 0:
                    await page.click(trust_selector, timeout=5000)
                    logger.info(f"✅ Clicked trust device button: {trust_selector}")
                    
                    # Wait for navigation
                    await page.wait_for_timeout(2000)
                    
                    # Check if we've moved past trust page
                    current_url = page.url.lower()
                    if "trust" not in current_url and "trusted_browser" not in current_url:
                        return True
                    
                    break
            except Exception as e:
                logger.debug(f"Failed to click {trust_selector}: {e}")
                continue
        
        return True
        
    except Exception as e:
        logger.error(f"Error handling trust device page: {e}")
        return False

async def get_candidates_for_job(page: Page, job_id: str) -> List[Dict[str, str]]:
    """Extract candidate information for a specific job with better error handling."""
    try:
        job_url = f"{BAMBOOHR_DOMAIN}/hiring/jobs/{job_id}"
        logger.info(f"→ Navigating to job page: {job_url}")
        
        # Navigate with retry logic
        if not await safe_goto(page, job_url, "domcontentloaded"):
            logger.error(f"Failed to navigate to job page")
            return []
        
        # Wait for page to stabilize and any dynamic content to load
        logger.info("→ Waiting for dynamic content to load...")
        await page.wait_for_timeout(3000)
        
        # Wait for network to be idle (no requests for 500ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except:
            logger.debug("Network idle timeout, continuing...")
        
        # Try waiting for specific elements that might indicate the page is loaded
        try:
            await page.wait_for_selector("table, .candidate, #candidateList, [data-testid*='candidate']", timeout=5000)
        except:
            logger.info("No immediate candidate elements found, continuing...")
        
        # Debug: Log page info
        page_content = await page.content()
        current_url = page.url
        page_title = await page.title()
        
        logger.info(f"Page title: {page_title}")
        logger.info(f"Current URL: {current_url}")
        
        # Check various error conditions
        if current_url.endswith("/hiring/jobs") or current_url.endswith("/hiring"):
            logger.error(f"❌ Redirected to jobs list instead of specific job")
            await page.screenshot(path=f"job_{job_id}_redirect.png")
            return []
        
        # Only check for explicit "not found" messages
        if "job opening not found" in page_content.lower() or "this job is no longer available" in page_content.lower():
            logger.error(f"❌ Job {job_id} not found or no longer available")
            return []
        
        if "access denied" in page_content.lower() or "unauthorized" in page_content.lower():
            logger.error(f"❌ Access denied to job {job_id}")
            return []
        
        # Look for and click on tabs that might show candidates
        logger.info("→ Looking for candidate tabs or filters...")
        tab_clicked = False
        tab_selectors = [
            # Common tab patterns
            "button:has-text('Candidates')",
            "a:has-text('Candidates')",
            "[role='tab']:has-text('Candidates')",
            "li:has-text('Candidates')",
            # Status tabs
            "button:has-text('Active')",
            "button:has-text('All')",
            "[role='tab']:has-text('Active')",
            "[role='tab']:has-text('All')",
            # Other possible tabs
            "button:has-text('Applications')",
            "a:has-text('Applications')",
            ".tab:has-text('Candidates')",
            ".nav-link:has-text('Candidates')",
            # Generic tab patterns
            "[role='tab']",
            ".tab",
            ".nav-tab"
        ]
        
        for tab_selector in tab_selectors:
            try:
                tab_elements = await page.locator(tab_selector).all()
                if tab_elements:
                    logger.info(f"Found {len(tab_elements)} elements matching: {tab_selector}")
                    # Click the first matching tab
                    await tab_elements[0].click()
                    logger.info(f"✅ Clicked tab: {tab_selector}")
                    tab_clicked = True
                    await page.wait_for_timeout(2000)  # Wait for content to load
                    break
            except Exception as e:
                logger.debug(f"Failed to click {tab_selector}: {e}")
                continue
        
        if not tab_clicked:
            logger.info("No candidate tabs found to click")
        
        # Debug: Log all links on the page
        all_links = await page.locator("a").all()
        logger.info(f"Total links on page: {len(all_links)}")
        
        # Log first 10 links that might be candidates
        logger.info("→ Analyzing page links...")
        candidate_patterns = 0
        for i, link in enumerate(all_links[:30]):  # Check first 30 links
            try:
                href = await link.get_attribute("href") or ""
                text = (await link.inner_text()).strip() or ""
                
                if "candidate" in href.lower() or ("/hiring/" in href and len(text) > 2 and not any(x in text.lower() for x in ['job', 'post', 'create', 'new'])):
                    logger.debug(f"Potential candidate link: {text[:50]} -> {href}")
                    candidate_patterns += 1
            except:
                continue
        
        logger.info(f"Found {candidate_patterns} potential candidate-related links")
        
        # Try multiple strategies to find candidates
        candidates = []
        
        # Expanded candidate selectors
        candidate_selectors = [
            # Direct candidate links
            "a[href*='/hiring/candidates/']",
            "a[href*='candidates'][href*='?']",
            ".candidate-link",
            "tr[data-candidate-id] a",
            "div.candidate-name a",
            "[class*='candidate'] a[href*='candidates']",
            # BambooHR specific selectors
            "table.candidateTable a",
            ".candidate-row a",
            "[data-testid='candidate-link']",
            ".applicant-name a",
            "td.name a",
            # Table-based selectors
            "table a[href*='candidates']",
            "tbody a[href*='candidates']",
            "tr td:first-child a",
            "tr td:nth-child(2) a",
            # More generic patterns
            ".list-item a",
            ".person-name a",
            "[class*='applicant'] a",
            "[class*='name'] a[href*='/hiring/']",
            # Data attribute patterns
            "[data-candidate] a",
            "[data-applicant] a",
            # Grid/card patterns
            ".candidate-card a",
            ".applicant-card a",
            ".grid-item a[href*='candidates']"
        ]
        
        logger.info("→ Searching for candidates with multiple strategies...")
        
        for selector in candidate_selectors:
            try:
                count = await page.locator(selector).count()
                if count > 0:
                    logger.info(f"Found {count} elements with selector: {selector}")
                    links = await page.locator(selector).all()
                    
                    for link in links:
                        try:
                            href = await link.get_attribute("href")
                            name = (await link.inner_text()).strip()
                            
                            if href and name and len(name) > 1:
                                # More flexible pattern matching
                                match = re.search(r'/hiring/candidates/(\d+)', href)
                                if not match:
                                    # Try alternative patterns
                                    match = re.search(r'/candidates/(\d+)', href)
                                
                                if match:
                                    candidate_id = match.group(1)
                                    full_url = f"{BAMBOOHR_DOMAIN}{href}" if not href.startswith("http") else href
                                    
                                    # Avoid duplicates
                                    if not any(c['id'] == candidate_id for c in candidates):
                                        candidates.append({
                                            "id": candidate_id,
                                            "name": name,
                                            "url": full_url
                                        })
                        except:
                            continue
                    
                    if candidates:
                        break
            except:
                continue
        
        # If still no candidates, try a more aggressive search
        if not candidates:
            logger.info("→ Trying broader search for any hiring-related links...")
            
            all_hiring_links = await page.locator("a[href*='/hiring/']").all()
            logger.info(f"Found {len(all_hiring_links)} hiring-related links")
            
            for link in all_hiring_links[:50]:  # Check first 50
                try:
                    href = await link.get_attribute("href") or ""
                    text = (await link.inner_text()).strip() or ""
                    
                    # Skip non-candidate links
                    skip_patterns = ['jobs', 'create', 'new', 'settings', 'reports', 'dashboard']
                    if any(pattern in href.lower() for pattern in skip_patterns):
                        continue
                    
                    # Look for numeric IDs in the URL
                    id_match = re.search(r'/hiring/[^/]+/(\d+)', href)
                    if id_match and text and len(text) > 2:
                        candidate_id = id_match.group(1)
                        full_url = f"{BAMBOOHR_DOMAIN}{href}" if not href.startswith("http") else href
                        
                        if not any(c['id'] == candidate_id for c in candidates):
                            logger.debug(f"Found potential candidate: {text} (ID: {candidate_id})")
                            candidates.append({
                                "id": candidate_id,
                                "name": text,
                                "url": full_url
                            })
                except:
                    continue
        
        # Check for iframes - BambooHR might load content in iframes
        iframes = await page.locator("iframe").count()
        if iframes > 0:
            logger.info(f"→ Found {iframes} iframe(s) on page, checking for candidate content...")
            
            for i in range(iframes):
                try:
                    frame = page.frame_locator(f"iframe").nth(i)
                    
                    # Try to find candidates within the iframe
                    for selector in candidate_selectors[:5]:  # Try first 5 selectors
                        try:
                            frame_links = await frame.locator(selector).all()
                            if frame_links:
                                logger.info(f"Found {len(frame_links)} potential candidates in iframe {i}")
                                
                                for link in frame_links:
                                    try:
                                        href = await link.get_attribute("href")
                                        name = (await link.inner_text()).strip()
                                        
                                        if href and name and len(name) > 1:
                                            match = re.search(r'/hiring/candidates/(\d+)', href)
                                            if match:
                                                candidate_id = match.group(1)
                                                full_url = f"{BAMBOOHR_DOMAIN}{href}" if not href.startswith("http") else href
                                                
                                                if not any(c['id'] == candidate_id for c in candidates):
                                                    candidates.append({
                                                        "id": candidate_id,
                                                        "name": name,
                                                        "url": full_url
                                                    })
                                    except:
                                        continue
                        except:
                            continue
                except Exception as e:
                    logger.debug(f"Error checking iframe {i}: {e}")
        
        # Remove duplicates
        unique_candidates = {c["id"]: c for c in candidates}.values()
        candidates = list(unique_candidates)
        
        if candidates:
            logger.info(f"✅ Found {len(candidates)} unique candidates for job {job_id}")
            for i, candidate in enumerate(candidates[:5], 1):
                logger.info(f"   {i}. {candidate['name']} (ID: {candidate['id']})")
            if len(candidates) > 5:
                logger.info(f"   ... and {len(candidates) - 5} more")
        else:
            logger.warning(f"⚠️ No candidates found for job {job_id}")
            
            # Enhanced debugging
            logger.info("Debugging information:")
            
            # Check for any tables
            tables = await page.locator("table").count()
            logger.info(f"  - Tables on page: {tables}")
            
            # Check for iframes
            iframes = await page.locator("iframe").count()
            logger.info(f"  - Iframes on page: {iframes}")
            
            # Look for any text that might indicate no candidates
            no_results_patterns = ["no candidates", "no applicants", "no applications", "0 results", "empty"]
            for pattern in no_results_patterns:
                if pattern in page_content.lower():
                    logger.info(f"  - Found '{pattern}' in page content - job might have no applicants")
                    break
            
            # Try to find any section that might contain candidates
            logger.info("→ Looking for candidate sections in page...")
            section_selectors = [
                "section", "div[class*='candidate']", "div[class*='applicant']",
                "div[id*='candidate']", "div[id*='applicant']", "main", "article"
            ]
            
            for selector in section_selectors:
                sections = await page.locator(selector).all()
                if sections:
                    logger.debug(f"Found {len(sections)} {selector} elements")
                    for i, section in enumerate(sections[:3]):  # Check first 3
                        try:
                            text = await section.inner_text()
                            if any(word in text.lower() for word in ['candidate', 'applicant', 'application']):
                                logger.info(f"  - Found potential candidate section in {selector}[{i}]")
                                logger.debug(f"    Content preview: {text[:200]}...")
                        except:
                            pass
            
            # Save full page screenshot and HTML for debugging
            await page.screenshot(path=f"job_{job_id}_no_candidates.png", full_page=True)
            
            # Save page HTML for debugging
            with open(f"job_{job_id}_page.html", "w", encoding="utf-8") as f:
                f.write(page_content)
            logger.info(f"  - Saved page HTML to job_{job_id}_page.html for debugging")
        
        return candidates
        
    except Exception as e:
        logger.error(f"Error getting candidates for job {job_id}: {e}")
        await page.screenshot(path=f"job_{job_id}_error.png")
        return []

async def download_resume(context: BrowserContext, page: Page, candidate: Dict[str, str], job_id: str, is_first: bool = False) -> bool:
    """Download resume PDF for a specific candidate."""
    try:
        logger.info(f"   → Processing {candidate['name']} ({candidate['id']})")
        
        # Navigate to candidate page with retry
        if not await safe_goto(page, candidate['url'], "domcontentloaded"):
            logger.error(f"Failed to navigate to candidate page")
            return False
            
        await page.wait_for_timeout(2000)  # Give more time for page to load
        
        # Wait for any dynamic content
        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except:
            pass
        
        # Check if we need to click any tabs first
        logger.debug("      Checking for tabs that might contain resume...")
        tab_selectors = [
            "a[role='tab']:has-text('Resume')",
            "a[role='tab']:has-text('Documents')",
            "a[role='tab']:has-text('Attachments')",
            "button[role='tab']:has-text('Resume')",
            "button[role='tab']:has-text('Documents')",
            ".nav-tab:has-text('Resume')",
            ".nav-link:has-text('Documents')",
            "[data-tab*='resume']",
            "[data-tab*='document']",
            "[data-tab*='attachment']"
        ]
        
        tab_clicked = False
        for tab_selector in tab_selectors:
            try:
                if await page.locator(tab_selector).count() > 0:
                    logger.debug(f"      Found tab: {tab_selector}")
                    await page.click(tab_selector)
                    tab_clicked = True
                    await page.wait_for_timeout(1000)  # Wait for tab content to load
                    break
            except:
                continue
        
        if tab_clicked:
            logger.debug("      Clicked a tab, waiting for content...")
        
        # Debug: Log all links on the page
        if DEBUG_MODE:
            all_links = await page.locator("a").all()
            logger.debug(f"Total links on candidate page: {len(all_links)}")
            
            # Look for potential download links
            download_keywords = ['download', 'resume', 'pdf', 'file', 'attachment', 'document', 'cv']
            potential_downloads = 0
            
            for link in all_links[:30]:  # Check first 30 links
                try:
                    href = await link.get_attribute("href") or ""
                    text = (await link.inner_text()).strip().lower() or ""
                    title = await link.get_attribute("title") or ""
                    
                    if any(keyword in href.lower() + text + title.lower() for keyword in download_keywords):
                        logger.debug(f"Potential download link: text='{text[:50]}', href='{href}'")
                        potential_downloads += 1
                except:
                    continue
            
            logger.debug(f"Found {potential_downloads} potential download links")
            
            # Save first candidate's HTML for debugging
            if is_first:  # Only for first candidate
                page_content = await page.content()
                debug_file = f"candidate_{candidate['id']}_page.html"
                with open(debug_file, "w", encoding="utf-8") as f:
                    f.write(page_content)
                logger.info(f"      📄 Saved candidate page HTML to {debug_file} for debugging")
        
        # Expanded selectors for download link
        download_selectors = [
            # Direct file download patterns
            "a[href*='/files/download']",
            "a[href*='download.php']",
            "a[href*='/download/']",
            "a[href*='getfile']",
            "a[href*='attachment']",
            
            # Resume-specific patterns
            "a[href*='resume']",
            "a[href*='cv']",
            "a[href*='.pdf']",
            
            # Text-based selectors
            "a:has-text('Resume')",
            "a:has-text('Download')",
            "a:has-text('CV')",
            "a:has-text('View')",
            "a:has-text('Open')",
            
            # Button patterns
            "button:has-text('Download')",
            "button:has-text('Resume')",
            "button:has-text('View')",
            
            # Icon-based patterns (download icons)
            "a[class*='download']",
            "button[class*='download']",
            "a[title*='Download']",
            "a[title*='Resume']",
            
            # BambooHR specific patterns
            ".resume-link",
            ".attachment-link",
            ".document-link",
            "[data-testid*='resume']",
            "[data-testid*='download']",
            
            # Table cell patterns (resume might be in a table)
            "td a[href*='download']",
            "td a[href*='pdf']",
            
            # Icon + text combinations
            "a:has(i[class*='download'])",
            "a:has(svg[class*='download'])",
            "a:has(span:has-text('Resume'))",
            
            # Generic file patterns
            "a[href*='fileId']",
            "a[href*='documentId']",
            "a[href*='attachmentId']",
            
            # Attachments section patterns
            ".attachments a",
            ".attachment-list a",
            "#attachments a",
            "[class*='attachment'] a",
            
            # Look for elements with class/id containing resume/attachment words
            ".resume", "#resume",
            ".attachment", "#attachment",
            ".document", "#document",
            "[class*='resume-download']",
            "[id*='resume-download']"
        ]
        
        download_link = None
        href = None
        found_selector = None
        
        logger.debug("      Searching for download link...")
        
        for selector in download_selectors:
            try:
                count = await page.locator(selector).count()
                if count > 0:
                    logger.debug(f"      Found {count} elements with selector: {selector}")
                    
                    # Try each matching element
                    for i in range(min(count, 3)):  # Check up to 3 matches
                        element = page.locator(selector).nth(i)
                        element_href = await element.get_attribute("href")
                        element_text = await element.inner_text() or ""
                        
                        if element_href:
                            logger.debug(f"        Element {i}: href='{element_href}', text='{element_text[:30]}'")
                            
                            # Check if this looks like a resume/file download
                            if any(pattern in element_href.lower() for pattern in ['pdf', 'download', 'file', 'resume', 'attachment']):
                                download_link = element
                                href = element_href
                                found_selector = selector
                                break
                    
                    if href:
                        break
            except Exception as e:
                logger.debug(f"      Error checking selector {selector}: {e}")
                continue
        
        # If still no download link found, try clicking elements that might trigger download
        if not href:
            logger.debug("      No direct download link found, trying clickable elements...")
            
            # Look for clickable elements that might trigger download
            click_selectors = [
                "button:has-text('View Resume')",
                "button:has-text('Download Resume')",
                "a:has-text('View Resume')",
                "a:has-text('Download Resume')",
                "[onclick*='download']",
                "[onclick*='resume']"
            ]
            
            for selector in click_selectors:
                try:
                    if await page.locator(selector).count() > 0:
                        logger.debug(f"      Found clickable element: {selector}")
                        
                        # Set up download listener
                        download_promise = page.wait_for_event("download", timeout=5000)
                        
                        # Click the element
                        await page.click(selector)
                        
                        # Wait for download to start
                        try:
                            download = await download_promise
                            
                            # Save the downloaded file
                            safe_name = sanitize_filename(candidate["name"])
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = f"job_{job_id}_{candidate['id']}_{safe_name}_{timestamp}.pdf"
                            output_path = Path(DOWNLOAD_DIR) / filename
                            
                            await download.save_as(output_path)
                            logger.info(f"      ✅ Downloaded via click: {filename}")
                            return True
                            
                        except asyncio.TimeoutError:
                            logger.debug(f"      No download triggered by {selector}")
                            continue
                except:
                    continue
        
        # Check for iframes that might contain the resume
        if not href:
            logger.debug("      Checking for iframes...")
            iframes = await page.locator("iframe").count()
            if iframes > 0:
                logger.debug(f"      Found {iframes} iframe(s), checking for resume content...")
                
                for i in range(iframes):
                    try:
                        frame = page.frame_locator("iframe").nth(i)
                        
                        # Try to find download links within the iframe
                        for selector in download_selectors[:10]:  # Try first 10 selectors
                            try:
                                frame_elements = await frame.locator(selector).count()
                                if frame_elements > 0:
                                    logger.debug(f"      Found {frame_elements} elements in iframe {i} with selector: {selector}")
                                    
                                    # Get the first element
                                    element = frame.locator(selector).first
                                    element_href = await element.get_attribute("href")
                                    
                                    if element_href:
                                        href = element_href
                                        found_selector = f"iframe[{i}] -> {selector}"
                                        logger.info(f"      Found download link in iframe!")
                                        break
                            except:
                                continue
                        
                        if href:
                            break
                            
                    except Exception as e:
                        logger.debug(f"      Error checking iframe {i}: {e}")
        
        # If still no download link found, try JavaScript-based approaches
        if not href:
            logger.debug("      Trying JavaScript-based download detection...")
            
            # Check for any data attributes that might contain file info
            try:
                # Look for elements with data attributes
                elements_with_data = await page.locator("[data-file-id], [data-document-id], [data-attachment-id], [data-resume-id]").all()
                if elements_with_data:
                    logger.debug(f"      Found {len(elements_with_data)} elements with data attributes")
                    
                # Try to find download functionality via JavaScript
                js_download_check = """
                    // Look for any download-related functions or data
                    const downloadElements = [];
                    
                    // Check all links
                    document.querySelectorAll('a').forEach(link => {
                        const href = link.href || '';
                        const onclick = link.onclick ? link.onclick.toString() : '';
                        const text = link.textContent || '';
                        
                        if (href.includes('download') || href.includes('file') || href.includes('pdf') ||
                            onclick.includes('download') || onclick.includes('file') ||
                            text.toLowerCase().includes('resume') || text.toLowerCase().includes('download')) {
                            downloadElements.push({
                                href: href,
                                text: text.trim(),
                                onclick: onclick.substring(0, 100)
                            });
                        }
                    });
                    
                    return downloadElements;
                """
                
                js_results = await page.evaluate(js_download_check)
                if js_results:
                    logger.debug(f"      JavaScript found {len(js_results)} potential download elements")
                    for result in js_results[:5]:
                        logger.debug(f"        JS element: {result}")
                        
            except Exception as e:
                logger.debug(f"      JavaScript inspection error: {e}")
        
        if not href:
            logger.warning(f"      ⚠️  No resume download link found for {candidate['name']}")
            
            # Take screenshot of candidate page for debugging
            if DEBUG_MODE:
                screenshot_path = f"candidate_{candidate['id']}_no_resume.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                logger.info(f"      📸 Screenshot saved to {screenshot_path}")
            
            return False
        
        logger.info(f"      Found download link with selector: {found_selector}")
        
        # Construct full PDF URL
        pdf_url = f"{BAMBOOHR_DOMAIN}{href}" if href.startswith('/') else href
        logger.info(f"      Downloading from: {pdf_url}")
        
        # Download the file
        headers = {
            "User-Agent": CONFIG['USER_AGENT'],
            "Referer": page.url,
            "Accept": "application/pdf,application/octet-stream,*/*"
        }
        response = await context.request.get(pdf_url, headers=headers, timeout=CONFIG['TIMEOUT'])
        
        if not response.ok:
            logger.error(f"      ❌ HTTP {response.status} fetching PDF for {candidate['name']}")
            
            # Try alternative download method
            logger.info("      Trying alternative download via browser...")
            try:
                # Set up download listener
                download_promise = page.wait_for_event("download", timeout=5000)
                
                # Navigate to download URL
                await page.goto(pdf_url)
                
                # Wait for download
                download = await download_promise
                
                # Save the downloaded file
                safe_name = sanitize_filename(candidate["name"])
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"job_{job_id}_{candidate['id']}_{safe_name}_{timestamp}.pdf"
                output_path = Path(DOWNLOAD_DIR) / filename
                
                await download.save_as(output_path)
                logger.info(f"      ✅ Downloaded via navigation: {filename}")
                return True
                
            except Exception as e:
                logger.error(f"      Alternative download failed: {e}")
                return False
        
        # Get file content
        content = await response.body()
        
        # Validate file size
        if len(content) < CONFIG['MIN_PDF_SIZE']:
            logger.warning(f"      ⚠️  Small file ({len(content)} bytes) for {candidate['name']}")
        
        # Create filename
        safe_name = sanitize_filename(candidate["name"])
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"job_{job_id}_{candidate['id']}_{safe_name}_{timestamp}.pdf"
        output_path = Path(DOWNLOAD_DIR) / filename
        
        # Ensure directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file
        with open(output_path, "wb") as f:
            f.write(content)
        
        logger.info(f"      ✅ Saved {filename} ({len(content):,} bytes)")
        return True
        
    except Exception as e:
        logger.error(f"      ❌ Error downloading resume for {candidate['name']}: {e}")
        
        # Take screenshot on error
        if DEBUG_MODE:
            try:
                screenshot_path = f"candidate_{candidate['id']}_error.png"
                await page.screenshot(path=screenshot_path)
                logger.info(f"      📸 Error screenshot saved to {screenshot_path}")
            except:
                pass
        
        return False

async def save_candidate_metadata(candidates: List[Dict], job_id: str):
    """Save candidate metadata to JSON file."""
    try:
        metadata = {
            "job_id": job_id,
            "scraped_at": datetime.now().isoformat(),
            "total_candidates": len(candidates),
            "candidates": candidates
        }
        
        metadata_path = Path(DOWNLOAD_DIR) / f"job_{job_id}_metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        logger.info(f"📄 Saved metadata to {metadata_path}")
        
    except Exception as e:
        logger.error(f"Error saving metadata: {e}")

async def scrape_job(job_id: str, use_manual_login: bool = False):
    """Main function to scrape resumes for a specific job."""
    if not validate_job_id(job_id):
        logger.error("❌ Invalid job ID")
        return
    
    Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
    
    logger.info(f"🚀 Starting scrape for job ID: {job_id}")
    logger.info(f"📁 Download directory: {DOWNLOAD_DIR}")
    logger.info(f"🐛 Debug mode: {'ON' if DEBUG_MODE else 'OFF'}")
    
    async with async_playwright() as playwright:
        try:
            # Launch browser
            browser = await playwright.chromium.launch(
                headless=CONFIG['HEADLESS'],
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            
            # Create context
            context = await browser.new_context(
                user_agent=CONFIG['USER_AGENT'],
                viewport={'width': 1920, 'height': 1080},
                accept_downloads=True
            )
            
            page = await context.new_page()
            
            # Enable console logging for debugging
            page.on("console", lambda msg: logger.debug(f"Browser console: {msg.text}"))
            
            # Login (automatic or manual)
            if use_manual_login:
                logger.info("🔐 Manual login mode")
                login_url = f"{BAMBOOHR_DOMAIN}/login.php"
                await page.goto(login_url, wait_until="domcontentloaded")
                logger.info("→ Please complete login and 2FA in the browser...")
                input("   👉 Press ENTER after login completion: ")
                login_success = True
            else:
                # Automatic login
                login_success = await auto_login(page, BAMBOOHR_DOMAIN)
                
            if not login_success:
                logger.error("❌ Login failed")
                # Offer manual login as fallback
                retry = input("\n🔄 Would you like to try manual login? (y/n): ").lower()
                if retry == 'y':
                    logger.info("🔐 Switching to manual login...")
                    login_url = f"{BAMBOOHR_DOMAIN}/login.php"
                    await page.goto(login_url, wait_until="domcontentloaded")
                    logger.info("→ Please complete login and 2FA in the browser...")
                    input("   👉 Press ENTER after login completion: ")
                    login_success = True
                else:
                    return
            
            # Handle trust device page if needed
            current_url = page.url.lower()
            if "trusted_browser" in current_url or "trust" in current_url:
                await handle_trust_device(page)
            
            # IMPORTANT: Wait after login/trust handling before navigation
            logger.info("→ Waiting for session to stabilize...")
            await page.wait_for_timeout(3000)  # Give the session time to fully establish
            
            # Try to go to home page first (helps establish session)
            logger.info("→ Navigating to home page first...")
            if await safe_goto(page, f"{BAMBOOHR_DOMAIN}/home", "domcontentloaded"):
                await page.wait_for_timeout(1000)
            
            # Now navigate to hiring section
            logger.info("→ Navigating to hiring section...")
            if not await safe_goto(page, f"{BAMBOOHR_DOMAIN}/hiring", "domcontentloaded"):
                logger.error("Failed to navigate to hiring section")
                # Try direct navigation to job page as fallback
                logger.info("→ Trying direct navigation to job page...")
            
            # Get candidates
            candidates = await get_candidates_for_job(page, job_id)
            
            if not candidates:
                logger.warning("⚠️ No candidates found for this job ID")
                logger.info(f"Final URL: {page.url}")
                logger.info("Check the screenshot 'job_XX_no_candidates.png' to see what page was loaded")
                
                # Offer manual inspection
                if not CONFIG['HEADLESS']:
                    manual_check = input("\n🔍 Would you like to manually inspect the page? (y/n): ").lower()
                    if manual_check == 'y':
                        logger.info("→ Browser is open. Please check if you can see candidates on the page.")
                        logger.info("   - Try clicking on any tabs or filters")
                        logger.info("   - Look for 'Candidates', 'Applications', or 'Active' tabs")
                        input("   👉 Press ENTER when ready to continue (or Ctrl+C to exit): ")
                        
                        # Try searching for candidates again
                        logger.info("→ Retrying candidate search...")
                        candidates = await get_candidates_for_job(page, job_id)
                        
                        if candidates:
                            logger.info(f"✅ Found {len(candidates)} candidates after manual intervention!")
                        else:
                            logger.info("Still no candidates found. The job might have no applicants.")
                
                if not candidates:
                    return
            
            # Save metadata
            await save_candidate_metadata(candidates, job_id)
            
            # Download resumes
            logger.info(f"📥 Starting download of {len(candidates)} resumes...")
            successful_downloads = 0
            failed_downloads = []
            
            for i, candidate in enumerate(candidates, 1):
                logger.info(f"\n[{i}/{len(candidates)}] Processing {candidate['name']}")
                
                success = await download_resume(context, page, candidate, job_id, is_first=(i==1))
                if success:
                    successful_downloads += 1
                else:
                    failed_downloads.append(candidate)
                
                # Small delay between downloads
                if i < len(candidates):
                    await page.wait_for_timeout(int(CONFIG['RETRY_DELAY'] * 1000))
            
            # Summary
            logger.info("\n" + "="*50)
            logger.info("📊 SCRAPING SUMMARY")
            logger.info("="*50)
            logger.info(f"Job ID: {job_id}")
            logger.info(f"Total candidates: {len(candidates)}")
            logger.info(f"✅ Successful downloads: {successful_downloads}")
            logger.info(f"❌ Failed downloads: {len(failed_downloads)}")
            
            if failed_downloads:
                logger.warning("\nFailed downloads:")
                for candidate in failed_downloads[:10]:  # Show first 10
                    logger.warning(f"   - {candidate['name']} (ID: {candidate['id']})")
                if len(failed_downloads) > 10:
                    logger.warning(f"   ... and {len(failed_downloads) - 10} more")
                
                # If all downloads failed, offer manual inspection
                if successful_downloads == 0 and not CONFIG['HEADLESS']:
                    logger.info("\n⚠️  All downloads failed. This might be a selector issue.")
                    inspect = input("\n🔍 Would you like to manually inspect a candidate page? (y/n): ").lower()
                    if inspect == 'y':
                        # Navigate to first candidate
                        first_candidate = candidates[0]
                        logger.info(f"→ Navigating to {first_candidate['name']}'s page...")
                        await page.goto(first_candidate['url'])
                        
                        logger.info("\n📋 Please check the page for:")
                        logger.info("   - Any 'Download', 'Resume', 'View', or 'PDF' links/buttons")
                        logger.info("   - File attachments section")
                        logger.info("   - Document tabs or sections")
                        logger.info("   - Right-click on any resume link and check the URL")
                        
                        input("\n👉 Press ENTER when you've identified how to download resumes: ")
                        
                        # Ask for selector hint
                        hint = input("\n💡 If you found a pattern, describe it (or press ENTER to skip): ").strip()
                        if hint:
                            logger.info(f"User hint: {hint}")
                            logger.info("Please update the download_selectors in the script with this information.")
            
            logger.info(f"\n📁 Files saved to: {DOWNLOAD_DIR}")
            
            # If in debug mode and downloads failed, remind about HTML files
            if DEBUG_MODE and failed_downloads:
                logger.info("\n🐛 Debug files created:")
                logger.info(f"   - candidate_{candidates[0]['id']}_page.html (first candidate's page)")
                logger.info("   - job_XX_no_candidates.png (if no candidates found)")
                logger.info("   - candidate_XX_no_resume.png (for failed downloads)")
                logger.info("\nAnalyze these files to identify the correct selectors.")
            
        except Exception as e:
            logger.error(f"Fatal error during scraping: {e}")
            # Take a screenshot for debugging
            try:
                await page.screenshot(path=f"job_{job_id}_fatal_error.png", full_page=True)
                logger.info(f"Screenshot saved: job_{job_id}_fatal_error.png")
            except:
                pass
            raise
        finally:
            try:
                await browser.close()
                logger.info("Browser closed")
            except:
                pass

def main():
    """Entry point for the script."""
    print("\n🤖 BambooHR Resume Scraper - ADVANCED DOWNLOAD DEBUG VERSION")
    print("=" * 50)
    print("✨ Features:")
    print("   - Enhanced resume download detection")
    print("   - 40+ different download selectors")
    print("   - Tab clicking for hidden content")
    print("   - Iframe support for embedded content")
    print("   - JavaScript-based download detection")
    print("   - Alternative download methods")
    print("   - HTML export for first candidate")
    print("   - Manual inspection mode for debugging")
    print("   - Screenshots on failures")
    print("=" * 50)
    
    try:
        job_id = input("\nEnter job ID to scrape: ").strip()
        
        if not job_id:
            print("❌ No job ID provided")
            return
        
        if not validate_job_id(job_id):
            print("❌ Invalid job ID. Please provide a numeric value.")
            return
        
        # Ask for login preference
        login_mode = input("\nLogin mode:\n1. Automatic (with 2FA)\n2. Manual\nChoose (1 or 2): ").strip()
        use_manual = login_mode == "2"
        
        start_time = datetime.now()
        print(f"\n🚀 Starting scrape for job ID: {job_id}")
        
        asyncio.run(scrape_job(job_id, use_manual_login=use_manual))
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        print(f"\n⏱️ Completed in {duration:.1f} seconds")
        
    except KeyboardInterrupt:
        print("\n⚠️ Scraping interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()