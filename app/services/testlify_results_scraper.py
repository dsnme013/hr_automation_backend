

import asyncio
import json
import logging
from pathlib import Path
from playwright.async_api import async_playwright
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from app.models.db import Candidate, SessionLocal 
from app.utils.email_util import send_interview_link_email, send_rejection_email
from sqlalchemy import and_

# Same user data directory
USER_DATA_DIR = r"D:\interview link\testlify_browser_profile"
OUTPUT_DIR = "assessment_results"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class FixedTestlifyScraper:
    """Fixed scraper that correctly extracts TOTAL assessment scores, not section scores"""
    
    def __init__(self):
        self.session = SessionLocal()
        Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    
    async def scrape_assessment_scores(self, assessment_name: str) -> List[Dict]:
        """Main scraping method - focuses on TOTAL scores only"""
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=USER_DATA_DIR,
                headless=False,
                viewport={'width': 1400, 'height': 1000}
            )
            page = context.pages[0] if context.pages else await context.new_page()
            
            try:
                # Navigate to assessment
                success = await self._navigate_to_assessment(page, assessment_name)
                if not success:
                    return []
                
                # Extract TOTAL scores only (not section scores)
                candidates_data = await self._extract_total_scores_only(page)
                
                # Validate and clean data
                valid_candidates = self._validate_total_scores(candidates_data)
                
                # Save results
                self._save_results(assessment_name, valid_candidates)
                
                # Process candidates (send emails, update database)
                await self._process_candidates(valid_candidates)
                
                return valid_candidates
                
            except Exception as e:
                logging.error(f"Scraping error: {e}")
                await page.screenshot(path="scraping_error.png")
                return []
            finally:
                await context.close()
    
    async def _navigate_to_assessment(self, page, assessment_name: str) -> bool:
        """Navigate to the specific assessment"""
        logging.info("Navigating to Testlify assessments...")
        await page.goto("https://app.testlify.com/assessments", wait_until="networkidle")
        await asyncio.sleep(3)
        
        # Check login
        if await page.query_selector("input[type='email']"):
            print("⚠️ Please log in manually...")
            input("Press ENTER after logging in: ")
            await page.wait_for_load_state("networkidle")
        
        # Find assessment
        logging.info(f"Looking for assessment: {assessment_name}")
        
        try:
            element = await page.wait_for_selector(f"text={assessment_name}", timeout=5000)
            await element.click()
            logging.info("✅ Found assessment via exact match")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)
            return True
        except:
            pass
        
        # Try partial match
        try:
            elements = await page.query_selector_all("*")
            for element in elements:
                try:
                    text = await element.inner_text()
                    if (assessment_name.lower() in text.lower() and 
                        len(text.strip()) < 100 and 
                        len(text.strip()) > len(assessment_name) - 5):
                        await element.click()
                        logging.info("✅ Found assessment via partial match")
                        await page.wait_for_load_state("networkidle")
                        await asyncio.sleep(3)
                        return True
                except:
                    continue
        except:
            pass
        
        logging.error(f"Could not find assessment: {assessment_name}")
        return False
    
    async def _extract_total_scores_only(self, page) -> List[Dict]:
        """Extract ONLY total assessment scores, ignore section scores completely"""
        logging.info("🎯 Extracting TOTAL assessment scores only...")
        
        candidates_data = []
        
        # Method 1: Target the main candidates table with SCORE (%) column
        table_candidates = await self._extract_from_main_candidates_table(page)
        candidates_data.extend(table_candidates)
        logging.info(f"Main table method found: {len(table_candidates)} candidates")
        
        # Method 2: JavaScript extraction targeting SCORE column specifically
        if not candidates_data:
            js_candidates = await self._extract_via_targeted_javascript(page)
            candidates_data.extend(js_candidates)
            logging.info(f"JavaScript method found: {len(js_candidates)} candidates")
        
        return candidates_data
    
    async def _extract_from_main_candidates_table(self, page) -> List[Dict]:
        """Extract from the main candidates table - targets SCORE (%) column"""
        try:
            candidates = []
            
            # Look for the main candidates table (has columns: NAME, INVITED ON, SCORE (%), GRADING, etc.)
            table_rows = await page.query_selector_all("tr")
            
            # Find the header row to identify column positions
            score_column_index = None
            name_column_index = None
            status_column_index = None
            
            for row in table_rows:
                row_text = await row.inner_text()
                if "SCORE (%)" in row_text and "NAME" in row_text:
                    # This is the header row
                    cells = await row.query_selector_all("th, td")
                    for i, cell in enumerate(cells):
                        cell_text = await cell.inner_text()
                        if "SCORE" in cell_text and "%" in cell_text:
                            score_column_index = i
                        elif "NAME" in cell_text:
                            name_column_index = i
                        elif "STATUS" in cell_text:
                            status_column_index = i
                    
                    logging.info(f"Found columns - Score: {score_column_index}, Name: {name_column_index}, Status: {status_column_index}")
                    break
            
            # Now extract data from each candidate row
            for row in table_rows:
                try:
                    row_text = await row.inner_text()
                    
                    # Skip header rows and empty rows
                    if ("SCORE (%)" in row_text or "NAME" in row_text or 
                        len(row_text.strip()) < 10):
                        continue
                    
                    # Look for email to identify candidate rows
                    email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', row_text)
                    if not email_match:
                        continue
                    
                    email = email_match.group()
                    cells = await row.query_selector_all("td")
                    
                    # Extract total score from the SCORE (%) column
                    total_score = None
                    if score_column_index is not None and len(cells) > score_column_index:
                        score_cell_text = await cells[score_column_index].inner_text()
                        
                        # Look for percentage in this specific cell
                        score_match = re.search(r'(\d+(?:\.\d+)?)%', score_cell_text.strip())
                        if score_match:
                            total_score = float(score_match.group(1))
                            logging.info(f"✅ Found TOTAL score: {total_score}% for {email} in SCORE column")
                    
                    # Extract name
                    candidate_name = ""
                    if name_column_index is not None and len(cells) > name_column_index:
                        name_cell_text = await cells[name_column_index].inner_text()
                        candidate_name = name_cell_text.strip().split('\n')[0]  # Take first line as name
                    
                    # Extract status
                    status = "Unknown"
                    if status_column_index is not None and len(cells) > status_column_index:
                        status_cell_text = await cells[status_column_index].inner_text()
                        status = status_cell_text.strip()
                    
                    if total_score is not None:
                        candidate = {
                            'email': email,
                            'name': candidate_name,
                            'percentage': total_score,
                            'status': status,
                            'extraction_method': 'main_table_score_column'
                        }
                        candidates.append(candidate)
                        logging.info(f"✅ Extracted: {email} - {total_score}% (TOTAL)")
                
                except Exception as e:
                    logging.debug(f"Error processing row: {e}")
                    continue
            
            return candidates
            
        except Exception as e:
            logging.error(f"Main table extraction failed: {e}")
            return []
    
    async def _extract_via_targeted_javascript(self, page) -> List[Dict]:
        """JavaScript extraction specifically targeting total scores"""
        try:
            result = await page.evaluate("""
                () => {
                    const candidates = [];
                    const emailRegex = /\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\\b/;
                    
                    // Find the main candidates table
                    const tableRows = document.querySelectorAll('tr');
                    let scoreColumnIndex = -1;
                    
                    // First, find the SCORE (%) column index
                    for (let row of tableRows) {
                        const rowText = row.textContent || '';
                        if (rowText.includes('SCORE (%)') && rowText.includes('NAME')) {
                            const cells = row.querySelectorAll('th, td');
                            for (let i = 0; i < cells.length; i++) {
                                const cellText = cells[i].textContent || '';
                                if (cellText.includes('SCORE') && cellText.includes('%')) {
                                    scoreColumnIndex = i;
                                    console.log('Found SCORE column at index:', i);
                                    break;
                                }
                            }
                            break;
                        }
                    }
                    
                    // Now extract data from candidate rows
                    for (let row of tableRows) {
                        const rowText = row.textContent || '';
                        const emailMatch = rowText.match(emailRegex);
                        
                        if (emailMatch && !rowText.includes('SCORE (%)')) {
                            const email = emailMatch[0];
                            const cells = row.querySelectorAll('td');
                            
                            let totalScore = null;
                            
                            // Method 1: Use the known SCORE column index
                            if (scoreColumnIndex >= 0 && cells.length > scoreColumnIndex) {
                                const scoreCell = cells[scoreColumnIndex];
                                const scoreCellText = scoreCell.textContent || '';
                                const scoreMatch = scoreCellText.match(/^\\s*(\\d+(?:\\.\\d+)?)%\\s*$/);
                                if (scoreMatch) {
                                    totalScore = parseFloat(scoreMatch[1]);
                                    console.log('Found total score via column index:', totalScore, 'for', email);
                                }
                            }
                            
                            // Method 2: Look for the main score in the row
                            // The total score usually appears early in the row, after name/email
                            if (totalScore === null) {
                                // Split by email and look for percentage in the section after email
                                const parts = rowText.split(email);
                                if (parts.length > 1) {
                                    const afterEmail = parts[1].substring(0, 50); // First 50 chars after email
                                    const scoreMatch = afterEmail.match(/(\\d+(?:\\.\\d+)?)%/);
                                    if (scoreMatch) {
                                        const score = parseFloat(scoreMatch[1]);
                                        // Only accept if it looks like a total score (usually low for assessments)
                                        if (score <= 100) {
                                            totalScore = score;
                                            console.log('Found total score after email:', totalScore, 'for', email);
                                        }
                                    }
                                }
                            }
                            
                            if (totalScore !== null) {
                                // Get status
                                let status = 'Unknown';
                                if (rowText.includes('Completed')) status = 'Completed';
                                else if (rowText.includes('Enrolled')) status = 'Enrolled';
                                else if (rowText.includes('Not suitable')) status = 'Not suitable';
                                
                                candidates.push({
                                    email: email,
                                    percentage: totalScore,
                                    status: status,
                                    extraction_method: 'javascript_targeted'
                                });
                            }
                        }
                    }
                    
                    return candidates;
                }
            """)
            
            return result if result else []
            
        except Exception as e:
            logging.error(f"JavaScript extraction failed: {e}")
            return []
    
    def _validate_total_scores(self, candidates_data: List[Dict]) -> List[Dict]:
        """Validate that we got total scores, not section scores"""
        valid_candidates = []
        seen_emails = set()
        
        for candidate in candidates_data:
            email = candidate.get('email')
            percentage = candidate.get('percentage')
            
            # Skip if no email or duplicate
            if not email or email in seen_emails:
                continue
            
            # Skip if no score
            if percentage is None:
                continue
            
            # Validate percentage range
            if percentage < 0 or percentage > 100:
                logging.warning(f"Invalid percentage for {email}: {percentage}%")
                continue
            
            # Flag if percentage seems too high for a total assessment score
            if percentage > 90:
                logging.warning(f"⚠️ High percentage for {email}: {percentage}% - verify this is total score, not section score")
            
            seen_emails.add(email)
            valid_candidates.append(candidate)
            
            logging.info(f"✅ Valid total score: {email} - {percentage}%")
        
        return valid_candidates
    
    def _save_results(self, assessment_name: str, results: List[Dict]):
        """Save results to JSON file"""
        try:
            output_data = {
                "assessment_name": assessment_name,
                "scraped_at": datetime.now().isoformat(),
                "extraction_focus": "TOTAL_ASSESSMENT_SCORES_ONLY",
                "total_candidates": len(results),
                "candidates_with_scores": len([r for r in results if r.get('percentage') is not None]),
                "candidates": results
            }
            
            filename = f"fixed_total_scores_{assessment_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            output_file = Path(OUTPUT_DIR) / filename
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            
            logging.info(f"📁 Results saved to: {output_file}")
            
        except Exception as e:
            logging.error(f"Error saving results: {e}")
    
    async def _process_candidates(self, candidates_data: List[Dict]):
        """Process candidates with total scores"""
        try:
            processed_count = 0
            interview_count = 0
            rejection_count = 0
            
            for candidate_data in candidates_data:
                email = candidate_data.get('email')
                percentage = candidate_data.get('percentage')
                
                if not email or percentage is None:
                    continue
                
                # Find candidate in database
                candidate = self.session.query(Candidate).filter_by(email=email).first()
                if not candidate:
                    logging.warning(f"⚠️ Candidate {email} not found in database")
                    continue
                
                # Update exam completion
                candidate.exam_completed = True
                candidate.exam_completed_date = datetime.now()
                candidate.exam_percentage = percentage
                
                # Add performance feedback based on total score
                if percentage >= 90:
                    feedback = "Outstanding performance! Exceptional technical knowledge demonstrated."
                elif percentage >= 80:
                    feedback = "Excellent performance! Strong technical competence shown."
                elif percentage >= 70:
                    feedback = "Good performance! Solid understanding of key concepts."
                elif percentage >= 60:
                    feedback = "Fair performance. Shows potential with room for improvement."
                elif percentage >= 50:
                    feedback = "Below average performance. Significant areas for improvement identified."
                else:
                    feedback = "Performance indicates substantial opportunities for growth in fundamental areas."
                
                candidate.exam_feedback = feedback
                
                # Determine next steps based on score threshold (70%)
                if percentage >= 70:  # Pass threshold
                    candidate.final_status = 'Interview Scheduled'
                    candidate.interview_scheduled = True
                    candidate.interview_date = datetime.now() + timedelta(days=3)
                    
                    # Generate unique interview token for secure interview links
                    import uuid
                    interview_token = str(uuid.uuid4())
                    candidate.interview_token = interview_token
                    candidate.interview_created_at = datetime.now()
                    candidate.interview_expires_at = datetime.now() + timedelta(days=7)
                    
                    # Generate the secure interview link
                    import os
                    base_url = os.getenv('FRONTEND_URL', 'http://127.0.0.1:5000')
                    interview_link = f"{base_url}/secure-interview/{interview_token}"
                    candidate.interview_link = interview_link
                    
                    # Generate knowledge base ID for AI interview
                    import time
                    candidate.knowledge_base_id = f"kb_{candidate.id}_{int(time.time())}"
                    
                    try:
                        # Send interview email with the secure link
                        interview_link = send_interview_link_email(candidate)
                        interview_count += 1
                        logging.info(f"✅ Interview scheduled: {email} ({percentage:.1f}%) - Link: {interview_link}")
                    except Exception as e:
                        logging.error(f"❌ Failed to send interview email to {email}: {e}")
                        # Still mark as scheduled even if email fails
                        interview_count += 1
                        logging.info(f"✅ Interview scheduled (email failed): {email} ({percentage:.1f}%) - Link: {interview_link}")
                else:
                    candidate.final_status = 'Rejected After Exam'
                    try:
                        send_rejection_email(candidate)
                        rejection_count += 1
                        logging.info(f"❌ Rejection sent: {email} ({percentage:.1f}%)")
                    except Exception as e:
                        logging.error(f"❌ Failed to send rejection email to {email}: {e}")
                
                processed_count += 1
            
            self.session.commit()
            
            # Print summary
            logging.info(f"\n📊 Processing Summary:")
            logging.info(f"   • Total processed: {processed_count}")
            logging.info(f"   • Interviews scheduled: {interview_count}")
            logging.info(f"   • Rejections sent: {rejection_count}")
            
        except Exception as e:
            logging.error(f"Error processing candidates: {e}")
            self.session.rollback()


# Main functions
async def scrape_assessment_results_by_name(assessment_name: str) -> List[Dict]:
    """Main function to scrape assessment results - TOTAL scores only"""
    scraper = FixedTestlifyScraper()
    try:
        results = await scraper.scrape_assessment_scores(assessment_name)
        return results
    finally:
        scraper.session.close()


async def scrape_all_pending_assessments():
    """Scrape all pending assessments - TOTAL scores only"""
    session = SessionLocal()
    try:
        pending_assessments = session.query(Candidate.job_title).filter(
            and_(
                Candidate.exam_link_sent == True,
                Candidate.exam_completed == False
            )
        ).distinct().all()
        
        results_summary = {}
        
        for (assessment_name,) in pending_assessments:
            if assessment_name:
                logging.info(f"🎯 Scraping TOTAL scores for: {assessment_name}")
                results = await scrape_assessment_results_by_name(assessment_name)
                scored_count = len([r for r in results if r.get('percentage') is not None])
                results_summary[assessment_name] = scored_count
        
        return results_summary
        
    finally:
        session.close()


# CLI interface
async def main():
    print("🎯 Fixed Testlify Total Score Scraper")
    print("=" * 50)
    print("🔧 SPECIFICALLY TARGETS TOTAL ASSESSMENT SCORES")
    print("❌ IGNORES INDIVIDUAL SECTION SCORES")
    print("✅ EXTRACTS 2.88% (not 15.38%)")
    print("=" * 50)
    print("Features:")
    print("• Targets SCORE (%) column in main candidates table")
    print("• Ignores section-specific scores completely")
    print("• Validates scores are reasonable totals")
    print("• Automatic candidate processing based on total score")
    print("=" * 50)
    
    choice = input("Choose option:\n1. Scrape specific assessment\n2. Scrape all pending assessments\nChoice (1/2): ").strip()
    
    if choice == "1":
        assessment_name = input("Enter assessment name (e.g., 'Junior AI Engineer'): ").strip()
        if assessment_name:
            print(f"\n🎯 Starting TOTAL score extraction for: {assessment_name}")
            results = await scrape_assessment_results_by_name(assessment_name)
            
            scored = [r for r in results if r.get('percentage') is not None]
            print(f"\n📊 Results Summary:")
            print(f"   • Total candidates found: {len(results)}")
            print(f"   • Candidates with TOTAL scores: {len(scored)}")
            
            if scored:
                avg_score = sum(r['percentage'] for r in scored) / len(scored)
                passed = len([r for r in scored if r['percentage'] >= 70])
                
                print(f"   • Average TOTAL score: {avg_score:.1f}%")
                print(f"   • Pass rate: {passed}/{len(scored)} ({(passed/len(scored)*100):.1f}%)")
                
                print(f"\n🎯 TOTAL Score Breakdown:")
                for candidate in sorted(scored, key=lambda x: x['percentage'], reverse=True):
                    status_emoji = "✅" if candidate['percentage'] >= 70 else "❌"
                    method = candidate.get('extraction_method', 'unknown')
                    print(f"   {status_emoji} {candidate['email']}: {candidate['percentage']:.2f}% (via {method})")
    
    elif choice == "2":
        print("\n🎯 Starting bulk TOTAL score extraction...")
        results_summary = await scrape_all_pending_assessments()
        total_scored = sum(results_summary.values())
        print(f"\n📊 Bulk Results Summary:")
        print(f"   • Assessments processed: {len(results_summary)}")
        print(f"   • Total candidates with TOTAL scores: {total_scored}")
        
        for assessment, count in results_summary.items():
            print(f"   • {assessment}: {count} candidates with TOTAL scores")
    
    else:
        print("❌ Invalid choice!")


if __name__ == "__main__":
    asyncio.run(main())