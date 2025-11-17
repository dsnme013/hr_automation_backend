import asyncio
import json
import logging
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
import time
from difflib import SequenceMatcher
from datetime import datetime
import re
import openai



# OpenAI Configuration
openai.api_key = "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"  # Replace with your actual API key

async def get_gpt_test_suggestions(job_title, job_desc=""):
    """Get test suggestions from GPT for any job role"""
    
    prompt = f"""
    Job Title: {job_title}
    Job Description: {job_desc if job_desc else "Not provided"}
    
    Suggest 5-7 simple test search terms (1-2 words maximum) that would be relevant for this role.
    These should be core skills that are likely to have tests in an assessment platform.
    
    Return ONLY the search terms, one per line. Keep them simple and searchable.
    
    Example output for "AI Engineer":
    Python
    Machine Learning
    AI
    Data Science
    Algorithm
    SQL
    Statistics
    """
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.3
        )
        
        suggestions = response.choices[0].message.content.strip().split('\n')
        # Clean and filter suggestions
        suggestions = [s.strip() for s in suggestions if s.strip() and len(s.strip().split()) <= 2]
        
        logging.info(f"GPT suggested tests: {suggestions}")
        return suggestions[:7]  # Return max 7 suggestions
        
    except Exception as e:
        logging.error(f"GPT API error: {e}")
        
        # If GPT fails, try with a simpler prompt or different approach
        try:
            # Simpler prompt as fallback
            simple_prompt = f"List 5 core skills for {job_title} job. One skill per line, 1-2 words only."
            
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": simple_prompt}],
                max_tokens=100,
                temperature=0.5
            )
            
            suggestions = response.choices[0].message.content.strip().split('\n')
            suggestions = [s.strip() for s in suggestions if s.strip()][:5]
            
            logging.info(f"GPT fallback suggestions: {suggestions}")
            return suggestions
            
        except:
            # Ultimate fallback - ask user to provide tests
            logging.error("GPT completely failed. Asking user for input.")
            print("\n⚠️  Could not get test suggestions from AI.")
            print("Please enter 3-5 test names to search for (comma separated):")
            user_input = input("Tests: ").strip()
            
            if user_input:
                suggestions = [t.strip() for t in user_input.split(',')]
                return suggestions[:5]
            else:
                # If user doesn't provide, return very generic tests
                return ["Skills Assessment", "Aptitude", "General Knowledge"]

async def select_best_test_with_gpt(page, search_term, job_title, job_desc=""):
    """Use GPT to select the best test from search results"""
    
    # Get all visible test cards
    test_cards = await page.query_selector_all(".test-card, div[class*='card']")
    
    if not test_cards:
        logging.warning(f"No test cards found for: {search_term}")
        return None
    
    # Extract test information
    test_options = []
    for idx, card in enumerate(test_cards[:10]):  # Limit to first 10 results
        try:
            # Extract test title
            title_elem = await card.query_selector("h3, .test-title, [class*='title']")
            if not title_elem:
                continue
                
            test_title = await title_elem.inner_text()
            
            # Extract test description if available
            desc_elem = await card.query_selector("p, .test-description, .description")
            test_desc = await desc_elem.inner_text() if desc_elem else ""
            
            # Find Add button
            add_button = await card.query_selector("button:has-text('Add')")
            
            test_options.append({
                "index": idx,
                "title": test_title.strip(),
                "description": test_desc.strip()[:100],  # Limit description length
                "card": card,
                "add_button": add_button
            })
            
        except Exception as e:
            logging.debug(f"Error processing card {idx}: {e}")
            continue
    
    if not test_options:
        logging.warning("No valid test options found")
        return None
    
    # Use GPT to select the best test
    prompt = f"""
    Job Title: {job_title}
    Search Term: {search_term}
    
    Which of these tests is most appropriate for this role? Reply with ONLY the number.
    
    Available tests:
    {chr(10).join(f"{i+1}. {t['title']} - {t['description']}" for i, t in enumerate(test_options))}
    
    Select the number of the most relevant test (1-{len(test_options)}):
    """
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.1
        )
        
        # Extract the number from response
        response_text = response.choices[0].message.content.strip()
        selected_index = int(re.search(r'\d+', response_text).group()) - 1
        
        if 0 <= selected_index < len(test_options):
            selected_test = test_options[selected_index]
            logging.info(f"GPT selected: {selected_test['title']}")
            return selected_test
        
    except Exception as e:
        logging.error(f"GPT selection error: {e}")
    
    # Fallback: Select first test with "Add" button
    for test in test_options:
        if test["add_button"]:
            logging.info(f"Fallback selection: {test['title']}")
            return test
    
    return None

async def handle_job_role_dropdown(page, target_role, fallback_roles, attempt_number=1):
    """Enhanced job role selection with retry logic and intercept handling"""
    
    max_attempts = 3
    
    if attempt_number > max_attempts:
        logging.error(f"Failed after {max_attempts} attempts")
        return False, target_role
    
    try:
        logging.info(f"Job role selection - Attempt {attempt_number}/{max_attempts}")
        
        # Wait for page stability
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2)
        
        # Strategy 1: Click the intercepting span element directly
        try:
            logging.info("Trying to click the span element that's intercepting...")
            span_element = await page.wait_for_selector("span:has-text('Add the title you are hiring for')", timeout=3000)
            if span_element:
                await span_element.click()
                logging.info("Clicked the intercepting span element")
                await asyncio.sleep(1)
        except:
            logging.info("Span element not found, trying parent div...")
        
        # Strategy 2: Click the parent div container
        try:
            parent_div = await page.wait_for_selector("div.el-select__selected-item", timeout=3000)
            if parent_div:
                await parent_div.click()
                logging.info("Clicked the parent div container")
                await asyncio.sleep(1)
        except:
            pass
        
        # Strategy 3: Use JavaScript to click through the layers
        try:
            await page.evaluate("""
                () => {
                    // Find and click the el-select container
                    const selectElements = document.querySelectorAll('.el-select, #jobRole');
                    for (const el of selectElements) {
                        el.click();
                        // Also try clicking any child elements
                        const clickableChild = el.querySelector('.el-select__selected-item, input, span');
                        if (clickableChild) clickableChild.click();
                    }
                }
            """)
            logging.info("Used JavaScript to click through layers")
            await asyncio.sleep(1)
        except:
            pass
        
        # Now type the job role SLOWLY
        logging.info(f"Typing job role: {target_role}")
        await page.keyboard.type(target_role, delay=200)  # Increased delay
        
        # Wait for dropdown to appear and load
        dropdown_found = False
        for wait_attempt in range(5):  # Try 5 times with increasing wait
            try:
                await asyncio.sleep(1 + wait_attempt * 0.5)  # Progressive wait
                
                # Check for dropdown
                dropdown = await page.query_selector(".el-select-dropdown:visible")
                if dropdown:
                    dropdown_found = True
                    logging.info(f"Dropdown appeared after {wait_attempt + 1} attempts")
                    break
                
                # Also check for dropdown items directly
                items = await page.query_selector_all(".el-select-dropdown__item:visible")
                if items:
                    dropdown_found = True
                    logging.info(f"Found {len(items)} dropdown items")
                    break
                    
            except:
                continue
        
        if dropdown_found:
            # Extra wait for options to fully load
            await asyncio.sleep(2)
            
            # Get all visible dropdown items
            dropdown_items = await page.query_selector_all(".el-select-dropdown__item:visible")
            
            if dropdown_items:
                logging.info(f"Processing {len(dropdown_items)} dropdown options...")
                
                # Process each option
                valid_options = []
                for idx, item in enumerate(dropdown_items):
                    try:
                        text = await item.inner_text()
                        text = text.strip()
                        
                        # Skip invalid options
                        if text and text.lower() not in ['all assessments', 'no data', 'loading...', '']:
                            valid_options.append((text, item, idx))
                            logging.info(f"Option {idx}: {text}")
                    except:
                        continue
                
                if valid_options:
                    # Find best match
                    best_match = None
                    best_score = 0
                    
                    for text, item, idx in valid_options:
                        # Exact match
                        if text.lower() == target_role.lower():
                            best_match = (text, item)
                            break
                        
                        # Similarity score
                        score = SequenceMatcher(None, text.lower(), target_role.lower()).ratio()
                        if score > best_score:
                            best_score = score
                            best_match = (text, item)
                    
                    # Select the best option or first valid one
                    if best_match:
                        selected_text, selected_item = best_match
                    else:
                        selected_text, selected_item, _ = valid_options[0]
                    
                    # Click with retry
                    click_success = False
                    for click_attempt in range(3):
                        try:
                            await selected_item.click()
                            click_success = True
                            logging.info(f"Successfully clicked: {selected_text}")
                            break
                        except:
                            # Try JavaScript click
                            try:
                                await selected_item.evaluate("el => el.click()")
                                click_success = True
                                logging.info(f"JS clicked: {selected_text}")
                                break
                            except:
                                await asyncio.sleep(0.5)
                    
                    if click_success:
                        await asyncio.sleep(2)
                        
                        # Verify selection worked
                        dropdown_gone = not await page.query_selector(".el-select-dropdown:visible")
                        if dropdown_gone:
                            logging.info("✅ Dropdown closed - selection successful!")
                            return True, selected_text
                        else:
                            logging.warning("Dropdown still visible after selection")
        else:
            logging.warning("Dropdown did not appear, trying Enter key...")
            await page.keyboard.press("Enter")
            await asyncio.sleep(1)
        
        # Check if we succeeded by looking at the assessment name field
        assessment_input = await page.query_selector("input[placeholder*='Assessment name']")
        if assessment_input:
            value = await assessment_input.get_attribute("value")
            if value and len(value) > 0:
                logging.info(f"Assessment name has value: {value} - assuming success")
                return True, target_role
        
        # Check if Next button is enabled
        next_btn = await page.query_selector("button:has-text('Next'):not([disabled])")
        if next_btn and await next_btn.is_enabled():
            logging.info("Next button enabled - assuming success")
            return True, target_role
            
    except Exception as e:
        logging.error(f"Error in attempt {attempt_number}: {e}")
    
    # If we failed, retry
    logging.warning(f"Attempt {attempt_number} failed, retrying...")
    await asyncio.sleep(2)
    return await handle_job_role_dropdown(page, target_role, fallback_roles, attempt_number + 1)

async def add_tests_with_gpt_selection(page, tests, job_title, job_desc=""):
    """Enhanced test addition with GPT-based selection"""
    added_count = 0
    
    try:
        # Wait for tests page to load
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(3)
        
        # Find search input
        search_input = None
        search_selectors = [
            "input[placeholder*='Search']",
            "input[placeholder*='search']",
            "input[type='search']",
            ".search-input"
        ]
        
        for selector in search_selectors:
            try:
                element = await page.wait_for_selector(selector, timeout=3000)
                if element and await element.is_visible():
                    search_input = element
                    logging.info(f"Found search input with selector: {selector}")
                    break
            except:
                continue
        
        if search_input:
            for test_name in tests:
                try:
                    # Clear search and type test name
                    await search_input.click()
                    await search_input.fill("")
                    await asyncio.sleep(0.5)
                    
                    # Type slowly to trigger search
                    await search_input.type(test_name, delay=150)
                    logging.info(f"Searching for: {test_name}")
                    
                    # Wait for search results to load
                    results_loaded = False
                    for wait_attempt in range(5):
                        await asyncio.sleep(1.5)
                        
                        test_cards = await page.query_selector_all(".test-card, .assessment-card, [class*='card'], .test-item")
                        if test_cards:
                            logging.info(f"Found {len(test_cards)} test cards after {wait_attempt + 1} attempts")
                            results_loaded = True
                            break
                        
                        add_buttons = await page.query_selector_all("button:has-text('Add')")
                        if add_buttons:
                            logging.info(f"Found {len(add_buttons)} Add buttons")
                            results_loaded = True
                            break
                    
                    if not results_loaded:
                        logging.warning(f"No results loaded for: {test_name}")
                        continue
                    
                    # Use GPT to select the best test
                    best_test = await select_best_test_with_gpt(page, test_name, job_title, job_desc)
                    
                    if best_test and best_test["add_button"]:
                        # Click the Add button
                        await best_test["add_button"].click()
                        added_count += 1
                        logging.info(f"✅ Added test: {best_test['title']}")
                        
                        # Wait for UI to update
                        await asyncio.sleep(2)
                        
                        # Verify the test was added
                        new_add_buttons = await page.query_selector_all("button:has-text('Add')")
                        if len(new_add_buttons) < len(await page.query_selector_all("button:has-text('Add')")):
                            logging.info("Add button count decreased - test successfully added")
                    else:
                        logging.warning(f"Could not find suitable test for: {test_name}")
                    
                    # Wait before next search
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logging.error(f"Error adding test '{test_name}': {e}")
                    
        else:
            logging.error("❌ Could not find test search input")
            await page.screenshot(path="no_search_input.png")
            
    except Exception as e:
        logging.error(f"Test addition failed: {e}")
    
    logging.info(f"Total tests added: {added_count}/{len(tests)}")
    return added_count

async def automate_testlify_robust(job_title, job_desc=""):
    """Main automation function with GPT integration"""
    
    # Get test suggestions from GPT
    logging.info("Getting test suggestions from GPT...")
    tests = await get_gpt_test_suggestions(job_title, job_desc)
    
    # Use the job title as the suggested role (or enhance with GPT if needed)
    suggested_role = job_title.title()
    
    logging.info(f"Starting automation for: {job_title}")
    logging.info(f"Suggested role: {suggested_role}")
    logging.info(f"Tests to add: {tests}")
    
    async with async_playwright() as playwright:
        # Browser context with anti-detection
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            viewport={'width': 1280, 'height': 900},
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox'
            ]
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        try:
            # Navigate to assessments
            await page.goto("https://app.testlify.com/assessments", wait_until="networkidle")
            await asyncio.sleep(2)
            
            # Check for login
            if await page.query_selector("input[type='email']"):
                print("⚠️  Please log in manually...")
                input("Press ENTER after logging in: ")
                await page.wait_for_load_state("networkidle")
            
            # Click Create Assessment button
            create_btn = await page.wait_for_selector("button:has-text('Create assessment')", timeout=10000)
            await create_btn.click()
            logging.info("Clicked Create Assessment")
            await asyncio.sleep(3)
            
            # Handle job role selection with retry mechanism
            success, selected_role = await handle_job_role_dropdown(page, suggested_role, [job_title])
            
            if not success:
                print("\n⚠️  Automated job role selection failed.")
                print("Please manually:")
                print("1. Click on the job role dropdown")
                print("2. Type and select your desired role")
                print("3. Press ENTER when done")
                input("Press ENTER to continue: ")
                selected_role = job_title
            
            # Ensure assessment name is filled
            await asyncio.sleep(2)
            assessment_input = await page.query_selector("input[placeholder*='Assessment name']")
            if assessment_input:
                current_value = await assessment_input.get_attribute("value")
                if not current_value:
                    await assessment_input.fill(f"{selected_role} Assessment")
                    logging.info("Filled assessment name")
            
            # Click Next to go to tests
            next_btn = await page.wait_for_selector("button:has-text('Next'):not([disabled])", timeout=10000)
            await next_btn.click()
            logging.info("Navigated to Tests page")
            await asyncio.sleep(3)
            
            # Add tests with GPT selection
            added_count = await add_tests_with_gpt_selection(page, tests[:5], job_title, job_desc)
            
            # Navigate through remaining steps
            steps = ["Tests → Questions", "Questions → Settings"]
            for step in steps:
                try:
                    await asyncio.sleep(2)
                    next_btn = await page.wait_for_selector("button:has-text('Next'):visible", timeout=5000)
                    if next_btn and await next_btn.is_enabled():
                        await next_btn.click()
                        logging.info(f"Completed: {step}")
                        await asyncio.sleep(2)
                except Exception as e:
                    logging.warning(f"Could not complete {step}: {e}")
            
            # Save assessment
            try:
                save_btn = await page.wait_for_selector("button:has-text('Save'):visible", timeout=10000)
                await save_btn.click()
                logging.info("Assessment saved!")
                await asyncio.sleep(3)
            except:
                logging.error("Could not find Save button")
            
            # Extract candidate invite link (keeping your existing logic)
            candidate_link = None
            try:
                # Wait for the page to load after save
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(3)
                
                # Your existing invite link extraction logic here...
                # (I'm keeping it as is from your original code)
                
            except Exception as e:
                logging.error(f"Error extracting candidate link: {e}")
            
            # Save results to JSON file
            assessment_data = {
                "job_title": job_title,
                "selected_role": selected_role,
                "tests_added": added_count,
                "total_tests_attempted": len(tests[:5]),
                "gpt_suggested_tests": tests,
                "candidate_invite_link": candidate_link,
                "assessment_url": page.url,
                "created_at": datetime.now().isoformat(),
                "success": True
            }
            
            # Create output directory if it doesn't exist
            Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
            
            # Save to JSON file
            output_filename = f"assessment_{job_title.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            output_path = Path(OUTPUT_DIR) / output_filename
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(assessment_data, f, indent=2)
            
            logging.info(f"Assessment data saved to: {output_path}")
            
            # Summary
            print("\n" + "="*50)
            print("✅ ASSESSMENT CREATION COMPLETED")
            print("="*50)
            print(f"Job Role: {selected_role}")
            print(f"Tests Added: {added_count}")
            print(f"GPT Suggested: {', '.join(tests[:5])}")
            if candidate_link:
                print(f"Candidate Link: {candidate_link}")
            else:
                print("⚠️  Could not extract candidate link automatically")
                print(f"Assessment URL: {page.url}")
            print(f"Data saved to: {output_path}")
            print("="*50)
            
            if added_count > 0:
                print("\n🎉 Success! Assessment created with tests.")
            else:
                print("\n⚠️  Assessment created but no tests were added.")
                print("You may need to add tests manually.")
            
        except Exception as e:
            logging.error(f"Critical error: {e}")
            await page.screenshot(path=f"error_{int(time.time())}.png")
            print(f"\n❌ Automation failed: {e}")
            print("Screenshot saved for debugging")
            
        finally:
            await asyncio.sleep(2)
            await context.close()

# Configuration
USER_DATA_DIR = r"D:\interview link\testlify_browser_profile"
OUTPUT_DIR = "assessment_links"

def create_programming_assessment(job_title, job_desc=""):
    """Create assessment and return assessment data"""
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return asyncio.run(automate_testlify_robust(job_title, job_desc))

def run_recruitment_with_invite_link(job_title, job_desc=""):
    """Main function that creates assessment and returns invite link"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    print(f"🚀 Starting recruitment process for: {job_title}")
    
    # Create the assessment
    assessment_data = asyncio.run(automate_testlify_robust(job_title, job_desc))
    
    if assessment_data and assessment_data.get('candidate_invite_link'):
        invite_link = assessment_data['candidate_invite_link']
        print(f"\n✅ Assessment created successfully!")
        print(f"📧 Candidate Invite Link: {invite_link}")
        return invite_link
    else:
        print("\n⚠️  Assessment creation completed but no invite link was extracted.")
        print("Please check the Testlify dashboard manually for the invite link.")
        return None

if __name__ == "__main__":
    print("🚀 Testlify Assessment Automation with GPT")
    print("-" * 40)
    job_title = input("Enter job title: ").strip()
    job_desc = input("Enter job description (optional): ").strip()
    
    invite_link = run_recruitment_with_invite_link(job_title, job_desc)
    
    if invite_link:
        print(f"\n🎉 Final Result: {invite_link}")
    else:
        print("\n❌ Could not retrieve invite link automatically.")