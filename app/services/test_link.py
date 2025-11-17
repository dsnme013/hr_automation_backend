import asyncio
import json
import logging
from pathlib import Path
from playwright.async_api import async_playwright
import re
from datetime import datetime
import time

# Configuration
import os
USER_DATA_DIR = r"D:\interview link\testlify_browser_profile"
OUTPUT_DIR = "assessment_links"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


async def extract_invite_link_from_assessment(assessment_name):

    """
    Navigate to specific assessment and extract the public invite link using multiple advanced methods
    """
    
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            viewport={'width': 1280, 'height': 900}
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        try:
            # Step 1: Navigate to assessments list
            logging.info("Navigating to assessments page...")
            await page.goto("https://app.testlify.com/assessments", wait_until="networkidle")
            await asyncio.sleep(3)
            
            # Check if login needed
            if await page.query_selector("input[type='email']"):
                print("⚠️ Please log in manually...")
                input("Press ENTER after logging in: ")
                await page.wait_for_load_state("networkidle")
            
            # Step 2: Find and click on the specific assessment
            logging.info(f"Looking for assessment: {assessment_name}")
            
            # Try multiple selectors to find the assessment
            assessment_found = False
            
            # Method 1: Click on text directly
            try:
                assessment_link = await page.wait_for_selector(f"text={assessment_name}", timeout=5000)
                if assessment_link:
                    await assessment_link.click()
                    assessment_found = True
                    logging.info("Clicked on assessment name directly")
            except:
                pass
            
            # Method 2: Find in table rows
            if not assessment_found:
                try:
                    rows = await page.query_selector_all("tr, .assessment-row, [class*='row']")
                    for row in rows:
                        row_text = await row.inner_text()
                        if assessment_name in row_text:
                            # Click on the row or find a link within it
                            links = await row.query_selector_all("a, .clickable, td:first-child")
                            if links:
                                await links[0].click()
                                assessment_found = True
                                logging.info("Clicked on assessment via table row")
                                break
                            else:
                                await row.click()
                                assessment_found = True
                                logging.info("Clicked on assessment row")
                                break
                except:
                    pass
            
            if not assessment_found:
                logging.error(f"Could not find assessment: {assessment_name}")
                await page.screenshot(path="assessment_not_found.png")
                return None
            
            # Wait for assessment page to load
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)
            
            # Step 3: Extract the invite link using ADVANCED METHODS
            logging.info("Extracting invite link using advanced methods...")
            candidate_link = None
            
            # METHOD 1: Try to click "Copy public link" and intercept clipboard
            try:
                logging.info("Trying Method 1: Direct copy public link...")
                
                # Set up clipboard monitoring
                await page.evaluate("window.originalClipboard = '';")
                
                # Multiple selectors for copy public link
                copy_selectors = [
                    "text=Copy public link",
                    "*:has-text('Copy public link')",
                    "button:has-text('Copy public link')",
                    "a:has-text('Copy public link')",
                    "[title*='Copy public link']",
                    "[aria-label*='Copy public link']",
                    ".copy-public-link",
                    "*[class*='copy'][class*='public']",
                    "svg[class*='copy'] + span:has-text('Copy public link')",
                    "span:has-text('Copy public link')"
                ]
                
                copy_element = None
                for selector in copy_selectors:
                    try:
                        copy_element = await page.wait_for_selector(selector, timeout=3000)
                        if copy_element:
                            logging.info(f"Found copy element with selector: {selector}")
                            break
                    except:
                        continue
                
                if copy_element:
                    # Get original clipboard
                    try:
                        original_clipboard = await page.evaluate("() => navigator.clipboard.readText().catch(() => '')")
                    except:
                        original_clipboard = ""
                    
                    # Click the copy element
                    await copy_element.click()
                    await asyncio.sleep(3)
                    
                    # Check clipboard multiple times
                    for attempt in range(5):
                        try:
                            new_clipboard = await page.evaluate("() => navigator.clipboard.readText().catch(() => '')")
                            if new_clipboard and new_clipboard != original_clipboard and "candidate.testlify.com" in new_clipboard:
                                candidate_link = new_clipboard
                                logging.info(f"✅ Got link from clipboard: {candidate_link}")
                                break
                        except:
                            pass
                        await asyncio.sleep(1)
                        
            except Exception as e:
                logging.error(f"Method 1 failed: {e}")
            
            # METHOD 2: Send invite to dummy email and extract link
            if not candidate_link:
                try:
                    logging.info("Trying Method 2: Send invite to extract link...")
                    
                    # Find email input field
                    email_input = await page.wait_for_selector("input[type='email'], input[placeholder*='email'], input[name*='email']", timeout=5000)
                    
                    if email_input:
                        # Use a dummy email
                        dummy_email = "testextract@gmail.com"
                        
                        # Clear and fill email
                        await email_input.click()
                        await email_input.fill("")
                        await email_input.type(dummy_email)
                        
                        logging.info(f"Entered dummy email: {dummy_email}")
                        
                        # Set up network monitoring for invite API calls
                        invite_data = []
                        
                        async def capture_invite_request(request):
                            if "invite" in request.url.lower() or "send" in request.url.lower():
                                try:
                                    if request.method == "POST":
                                        post_data = request.post_data
                                        if post_data:
                                            invite_data.append({
                                                'url': request.url,
                                                'data': post_data,
                                                'headers': dict(request.headers)
                                            })
                                except:
                                    pass
                        
                        async def capture_invite_response(response):
                            if "invite" in response.url.lower() or "send" in response.url.lower():
                                try:
                                    if response.status == 200:
                                        content_type = response.headers.get("content-type", "")
                                        if "json" in content_type:
                                            body = await response.text()
                                            # Look for invite links in response
                                            links = re.findall(r'https://candidate\.testlify\.com/[^"\'\\s]+', body)
                                            if links:
                                                invite_data.extend(links)
                                except:
                                    pass
                        
                        page.on("request", capture_invite_request)
                        page.on("response", capture_invite_response)
                        
                        # Click invite button
                        invite_button = await page.wait_for_selector("button:has-text('Invite'), .invite-btn, [class*='invite']", timeout=5000)
                        if invite_button:
                            await invite_button.click()
                            logging.info("Clicked invite button")
                            
                            # Wait for network requests to complete
                            await asyncio.sleep(5)
                            
                            # Check captured data
                            for data in invite_data:
                                if isinstance(data, str) and "candidate.testlify.com" in data:
                                    candidate_link = data
                                    logging.info(f"✅ Found link from invite API: {candidate_link}")
                                    break
                                elif isinstance(data, dict):
                                    # Parse the request/response data
                                    data_str = str(data)
                                    links = re.findall(r'https://candidate\.testlify\.com/[^"\'\\s]+', data_str)
                                    if links:
                                        candidate_link = links[0]
                                        logging.info(f"✅ Found link from invite data: {candidate_link}")
                                        break
                    
                except Exception as e:
                    logging.error(f"Method 2 failed: {e}")
            
            # METHOD 3: Look for existing invitations and extract from 3-dots menu
            if not candidate_link:
                try:
                    logging.info("Trying Method 3: Extract from existing invitations...")
                    
                    # Scroll down to find candidates section
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2)
                    
                    # Look for 3-dots menu (⋮) in candidates table
                    three_dots_selectors = [
                        "button[class*='menu']",
                        "*[class*='dropdown']",
                        "button:has-text('⋮')",
                        "button:has-text('...')",
                        "*[aria-label*='menu']",
                        "*[aria-label*='options']",
                        "td:last-child button",
                        ".actions button"
                    ]
                    
                    three_dots_element = None
                    for selector in three_dots_selectors:
                        try:
                            elements = await page.query_selector_all(selector)
                            for element in elements:
                                # Check if this is in the candidates table area
                                is_visible = await element.is_visible()
                                if is_visible:
                                    three_dots_element = element
                                    logging.info(f"Found 3-dots menu with selector: {selector}")
                                    break
                            if three_dots_element:
                                break
                        except:
                            continue
                    
                    if three_dots_element:
                        # Click the 3-dots menu
                        await three_dots_element.click()
                        await asyncio.sleep(2)
                        
                        # Look for "Copy invitation link" option
                        copy_invitation_selectors = [
                            "text=Copy invitation link",
                            "*:has-text('Copy invitation link')",
                            "text=Copy invite link",
                            "*:has-text('Copy invite link')",
                            ".copy-invitation",
                            "*[class*='copy'][class*='invitation']"
                        ]
                        
                        copy_invitation_element = None
                        for selector in copy_invitation_selectors:
                            try:
                                copy_invitation_element = await page.wait_for_selector(selector, timeout=3000)
                                if copy_invitation_element:
                                    logging.info(f"Found copy invitation with selector: {selector}")
                                    break
                            except:
                                continue
                        
                        if copy_invitation_element:
                            # Get original clipboard
                            try:
                                original_clipboard = await page.evaluate("() => navigator.clipboard.readText().catch(() => '')")
                            except:
                                original_clipboard = ""
                            
                            # Click copy invitation link
                            await copy_invitation_element.click()
                            await asyncio.sleep(3)
                            
                            # Check clipboard
                            for attempt in range(5):
                                try:
                                    new_clipboard = await page.evaluate("() => navigator.clipboard.readText().catch(() => '')")
                                    if new_clipboard and new_clipboard != original_clipboard and "candidate.testlify.com" in new_clipboard:
                                        candidate_link = new_clipboard
                                        logging.info(f"✅ Got invitation link from 3-dots menu: {candidate_link}")
                                        break
                                except:
                                    pass
                                await asyncio.sleep(1)
                
                except Exception as e:
                    logging.error(f"Method 3 failed: {e}")
            
            # METHOD 4: Enhanced DOM search with JavaScript execution
            if not candidate_link:
                try:
                    logging.info("Trying Method 4: Enhanced DOM search...")
                    
                    candidate_link = await page.evaluate("""
                        async () => {
                            // Wait for any dynamic content to load
                            await new Promise(resolve => setTimeout(resolve, 2000));
                            
                            const patterns = [
                                /https:\\/\\/candidate\\.testlify\\.com\\/auth\\/signup\\?[^\\s"'<>]+/g,
                                /https:\\/\\/candidate\\.testlify\\.com\\/[^\\s"'<>]+/g
                            ];
                            
                            const searchLocations = [
                                document.documentElement.outerHTML,
                                JSON.stringify(window),
                                ...Array.from(document.querySelectorAll('script')).map(s => s.textContent),
                                ...Array.from(document.querySelectorAll('*')).map(el => {
                                    return Array.from(el.attributes).map(attr => attr.value).join(' ');
                                })
                            ];
                            
                            for (const location of searchLocations) {
                                if (!location) continue;
                                for (const pattern of patterns) {
                                    const matches = location.match(pattern);
                                    if (matches && matches.length > 0) {
                                        // Return the first valid-looking invite link
                                        for (const match of matches) {
                                            if (match.includes('signup') || match.includes('invite')) {
                                                return match;
                                            }
                                        }
                                    }
                                }
                            }
                            
                            return null;
                        }
                    """)
                    
                    if candidate_link:
                        logging.info(f"✅ Found link via enhanced DOM search: {candidate_link}")
                        
                except Exception as e:
                    logging.error(f"Method 4 failed: {e}")
            
            # METHOD 5: Force interaction with all possible elements
            if not candidate_link:
                try:
                    logging.info("Trying Method 5: Force interaction with all elements...")
                    
                    # Get all clickable elements
                    clickable_elements = await page.query_selector_all("button, a, span, div[onclick], *[class*='copy'], *[class*='invite'], *[class*='link']")
                    
                    original_clipboard = ""
                    try:
                        original_clipboard = await page.evaluate("() => navigator.clipboard.readText().catch(() => '')")
                    except:
                        pass
                    
                    for i, element in enumerate(clickable_elements[:20]):  # Limit to first 20 elements
                        try:
                            # Get element text to see if it's relevant
                            element_text = await element.inner_text()
                            element_classes = await element.get_attribute("class") or ""
                            
                            # Skip if obviously not related to copying/inviting
                            relevant_keywords = ['copy', 'invite', 'link', 'share', 'public']
                            if not any(keyword in element_text.lower() or keyword in element_classes.lower() 
                                     for keyword in relevant_keywords):
                                continue
                            
                            logging.info(f"Trying element {i}: '{element_text[:30]}...' | Classes: {element_classes[:50]}...")
                            
                            # Click the element
                            await element.click()
                            await asyncio.sleep(2)
                            
                            # Check clipboard
                            try:
                                new_clipboard = await page.evaluate("() => navigator.clipboard.readText().catch(() => '')")
                                if new_clipboard and new_clipboard != original_clipboard and "candidate.testlify.com" in new_clipboard:
                                    candidate_link = new_clipboard
                                    logging.info(f"✅ Found link from element interaction: {candidate_link}")
                                    break
                            except:
                                pass
                                
                        except:
                            continue
                            
                except Exception as e:
                    logging.error(f"Method 5 failed: {e}")
            
            # Save results
            if candidate_link:
                # Clean the link
                candidate_link = candidate_link.strip()
                
                # Remove any extra parameters that might cause issues
                if "?" in candidate_link:
                    base_url, params = candidate_link.split("?", 1)
                    # Keep only essential parameters
                    param_pairs = params.split("&")
                    essential_params = []
                    for param in param_pairs:
                        if any(key in param.lower() for key in ['key=', 'id=', 'token=', 'invite=']):
                            essential_params.append(param)
                    
                    if essential_params:
                        candidate_link = base_url + "?" + "&".join(essential_params)
                        # Add required parameters if missing
                        if "isPublic" not in candidate_link:
                            candidate_link += "&isPublic=true"
                        if "embed" not in candidate_link:
                            candidate_link += "&embed=false"
                
                logging.info(f"✅ Successfully extracted invite link: {candidate_link}")
                
                # Save to file
                Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
                
                output_data = {
                    "assessment_name": assessment_name,
                    "invite_link": candidate_link,
                    "extracted_at": datetime.now().isoformat(),
                    "assessment_url": page.url
                }
                
                output_file = Path(OUTPUT_DIR) / f"invite_link_{assessment_name.replace(' ', '_')}.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(output_data, f, indent=2)
                
                print("\n" + "="*60)
                print("✅ INVITE LINK EXTRACTED SUCCESSFULLY")
                print("="*60)
                print(f"Assessment: {assessment_name}")
                print(f"Invite Link: {candidate_link}")
                print(f"Saved to: {output_file}")
                print("="*60)
                
                # Test the link
                print("\n🧪 Testing the extracted link...")
                test_page = await context.new_page()
                try:
                    await test_page.goto(candidate_link, timeout=10000)
                    await asyncio.sleep(3)
                    
                    # Check if the page loaded successfully
                    title = await test_page.title()
                    if "404" in title or "not found" in title.lower():
                        print("⚠️ Warning: The extracted link appears to be invalid (404)")
                        print("This might be because the link requires the assessment to be published")
                    else:
                        print("✅ Link appears to be working!")
                        print(f"Page title: {title}")
                        
                except Exception as e:
                    print(f"⚠️ Could not test link: {e}")
                finally:
                    await test_page.close()
                
                return candidate_link
            else:
                logging.error("❌ Could not extract invite link with any method")
                await page.screenshot(path="all_methods_failed.png")
                
                print("\n" + "="*60)
                print("❌ ALL EXTRACTION METHODS FAILED")
                print("="*60)
                print("Debug Information:")
                print(f"Current URL: {page.url}")
                
                # Enhanced debug info
                try:
                    # Check for any copy-related elements
                    copy_elements = await page.query_selector_all("*[class*='copy'], *:has-text('copy'), *:has-text('Copy')")
                    if copy_elements:
                        print(f"\nFound {len(copy_elements)} copy-related elements:")
                        for i, elem in enumerate(copy_elements[:5]):
                            try:
                                text = await elem.inner_text()
                                classes = await elem.get_attribute("class") or ""
                                visible = await elem.is_visible()
                                print(f"  {i+1}. Text: '{text[:50]}...', Classes: '{classes[:50]}...', Visible: {visible}")
                            except:
                                pass
                    
                    # Check for any invite-related elements
                    invite_elements = await page.query_selector_all("*[class*='invite'], *:has-text('invite'), *:has-text('Invite')")
                    if invite_elements:
                        print(f"\nFound {len(invite_elements)} invite-related elements:")
                        for i, elem in enumerate(invite_elements[:5]):
                            try:
                                text = await elem.inner_text()
                                classes = await elem.get_attribute("class") or ""
                                visible = await elem.is_visible()
                                print(f"  {i+1}. Text: '{text[:50]}...', Classes: '{classes[:50]}...', Visible: {visible}")
                            except:
                                pass
                                
                except:
                    pass
                
                print("\nPlease check the screenshot: all_methods_failed.png")
                print("Consider manually copying the link and sharing it with the script developer")
                print("="*60)
                
                return None
                
        except Exception as e:
            logging.error(f"Error: {e}")
            await page.screenshot(path="error_screenshot.png")
            return None
        finally:
            await context.close()

async def main():
    """Main function to run the extraction"""
    print("🚀 ADVANCED Testlify Invite Link Extractor")
    print("=" * 50)
    print("This script uses 5 different methods to extract invite links:")
    print("1. Direct 'Copy public link' button")
    print("2. Send dummy invite and capture API response")
    print("3. Extract from existing invitation 3-dots menu")
    print("4. Enhanced DOM search")
    print("5. Force interaction with all relevant elements")
    print("=" * 50)
    
    assessment_name = input("Enter assessment name: ").strip()
    if not assessment_name:
        print("Assessment name is required!")
        return
    invite_link = await extract_invite_link_from_assessment(assessment_name)
    if invite_link:
        print(f"\n✅ SUCCESS! Invite link:\n{invite_link}")
    else:
        print("\n❌ Could not extract invite link.")

if __name__ == "__main__":
    asyncio.run(main())

def get_invite_link(assessment_name):
    """
    Synchronous wrapper for extracting invite link for automation/pipelines.
    Usage: link = get_invite_link("Data Scientist")
    """
    import asyncio
    return asyncio.run(extract_invite_link_from_assessment(assessment_name))














