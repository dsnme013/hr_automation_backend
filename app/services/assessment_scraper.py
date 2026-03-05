#!/usr/bin/env python3
"""
RecruitAI — Auto Assessment Creator
- Enter ONLY the job title
- Topics auto-generated
- After saving, reads the exam link from the "Exam Created!" page
- Copies the link to your clipboard automatically
"""

import asyncio
import logging
import subprocess
import sys
from playwright.async_api import async_playwright, Page

# ─── CONFIG ──────────────────────────────────────────────────────────────────
BASE_URL          = " https://7679-2401-4900-1c0e-27a7-9828-1b57-c63d-30ab.ngrok-free.app"
ANTHROPIC_API_KEY = ""   # Optional: paste your key for unknown job titles
DEFAULT_DURATION  = 60
HEADLESS          = False
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler("recruitai.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─── CLIPBOARD ───────────────────────────────────────────────────────────────
def copy_to_clipboard(text: str) -> bool:
    try:
        subprocess.run("clip", input=text.encode("utf-8"), check=True, shell=True)
        return True
    except Exception as e:
        log.warning(f"Clipboard error: {e}")
        return False


# ─── AUTO-GENERATE TOPICS ────────────────────────────────────────────────────
def generate_topics(job_title: str) -> str:
    TOPIC_MAP = {
        "python":           "Python, Django, FastAPI, REST APIs, SQL, Git, OOP, Data Structures",
        "django":           "Django, Python, REST APIs, PostgreSQL, ORM, Authentication, Celery",
        "fastapi":          "FastAPI, Python, REST APIs, Pydantic, Async, SQLAlchemy, JWT",
        "javascript":       "JavaScript, ES6+, Node.js, React, HTML, CSS, REST APIs, Git",
        "react":            "React, JavaScript, TypeScript, Redux, HTML, CSS, REST APIs, Git",
        "node":             "Node.js, Express, JavaScript, REST APIs, MongoDB, SQL, Git",
        "java":             "Java, Spring Boot, OOP, SQL, REST APIs, Maven, JUnit, Git",
        "data science":     "Python, Pandas, NumPy, Scikit-learn, SQL, Statistics, Machine Learning",
        "machine learning": "Python, Scikit-learn, TensorFlow, PyTorch, Statistics, Pandas, NumPy",
        "devops":           "Docker, Kubernetes, CI/CD, Linux, AWS, Terraform, Git, Shell Scripting",
        "cloud":            "AWS, Azure, GCP, Docker, Kubernetes, Terraform, CI/CD, Linux",
        "android":          "Kotlin, Java, Android SDK, REST APIs, SQLite, MVVM, Jetpack Compose",
        "ios":              "Swift, Objective-C, UIKit, SwiftUI, REST APIs, Core Data, Xcode",
        "flutter":          "Flutter, Dart, REST APIs, State Management, Firebase, Git",
        "sql":              "SQL, MySQL, PostgreSQL, Query Optimization, Joins, Stored Procedures",
        "frontend":         "HTML, CSS, JavaScript, React, TypeScript, REST APIs, Responsive Design",
        "backend":          "Python, Node.js, REST APIs, SQL, Authentication, Caching, Docker, Git",
        "fullstack":        "React, Node.js, JavaScript, REST APIs, SQL, Docker, Git, HTML/CSS",
        "web":              "HTML, CSS, JavaScript, React, Node.js, REST APIs, SQL, Git",
        "qa":               "Manual Testing, Selenium, Python, Test Cases, API Testing, JIRA, SQL",
        "security":         "Network Security, Cryptography, Python, Linux, Penetration Testing, OWASP",
        "golang":           "Go, REST APIs, Concurrency, Docker, SQL, Microservices, Git",
        "php":              "PHP, Laravel, MySQL, REST APIs, HTML, CSS, JavaScript, Git",
        "ruby":             "Ruby, Rails, REST APIs, PostgreSQL, RSpec, Git, HTML/CSS",
        "blockchain":       "Solidity, Ethereum, Web3.js, Smart Contracts, Cryptography, Node.js",
        "embedded":         "C, C++, RTOS, Microcontrollers, I2C/SPI/UART, Linux Kernel, ARM",
        "ui":               "Figma, HTML, CSS, JavaScript, React, UX Design, Responsive Design",
        "ux":               "Figma, User Research, Wireframing, Prototyping, HTML, CSS, Usability Testing",
        "analyst":          "SQL, Excel, Python, Data Visualization, Tableau, Power BI, Statistics",
        "typescript":       "TypeScript, JavaScript, React, Node.js, REST APIs, OOP, Git",
        "angular":          "Angular, TypeScript, JavaScript, HTML, CSS, REST APIs, RxJS, Git",
        "vue":              "Vue.js, JavaScript, TypeScript, HTML, CSS, REST APIs, Vuex, Git",
        "rust":             "Rust, Systems Programming, Memory Management, Concurrency, Git",
        "scala":            "Scala, Spark, Functional Programming, Akka, SQL, SBT, Git",
    }

    title_lower = job_title.lower()
    for key, topics in TOPIC_MAP.items():
        if key in title_lower:
            log.info(f"  Topics matched: {topics}")
            return topics

    # Try Claude API if key is set
    if ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content":
                    f"List 6-8 key technical topics/skills for a '{job_title}' job role. "
                    "Comma-separated, short names only. No explanations."}]
            )
            topics = msg.content[0].text.strip()
            log.info(f"  Claude topics: {topics}")
            return topics
        except Exception as e:
            log.warning(f"  Claude API error: {e}")

    fallback = "Data Structures, Algorithms, OOP, SQL, REST APIs, Git, Problem Solving"
    log.info(f"  Fallback topics: {fallback}")
    return fallback


# ─── MAIN AUTOMATION ─────────────────────────────────────────────────────────
async def create_assessment(job_role: str, topics: str, duration: int) -> str:
    """Returns exam link string."""
    exam_link = ""

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"ngrok-skip-browser-warning": "true"},
        )
        page = await context.new_page()

        # ── 1. Open site ──────────────────────────────────────────────────
        log.info(f"-> Opening {BASE_URL}")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_load_state("networkidle", timeout=10_000)

        # ── 2. Recruiter Portal ───────────────────────────────────────────
        log.info("-> Recruiter Portal")
        for sel in ["text=Recruiter Portal", "div:has-text('Recruiter Portal')"]:
            try:
                if await page.locator(sel).count() > 0:
                    await page.locator(sel).first.click()
                    break
            except Exception:
                continue
        await page.wait_for_load_state("networkidle", timeout=10_000)
        await page.wait_for_timeout(1500)

        # ── 3. Create Job Role ────────────────────────────────────────────
        log.info("-> Create Job Role")
        for sel in ["button:has-text('Create Job Role')", "text=Create Job Role", "text=+ Create"]:
            try:
                if await page.locator(sel).count() > 0:
                    await page.locator(sel).first.click()
                    break
            except Exception:
                continue
        await page.wait_for_load_state("networkidle", timeout=10_000)
        await page.wait_for_timeout(1500)

        # ── 4. Fill Job Role ──────────────────────────────────────────────
        log.info(f"-> Job Role: {job_role}")
        for sel in ["input[placeholder*='Senior Python']", "input[placeholder*='Position']",
                    "input[placeholder*='Role']", "input[placeholder*='Job']"]:
            try:
                if await page.locator(sel).count() > 0:
                    await page.locator(sel).first.fill(job_role)
                    break
            except Exception:
                continue
        await page.wait_for_timeout(400)

        # ── 5. Fill Topics ────────────────────────────────────────────────
        log.info(f"-> Topics: {topics}")
        for sel in ["input[placeholder*='Django']", "input[placeholder*='Topics']",
                    "input[placeholder*='Fast API']", "input[name*='topic']"]:
            try:
                if await page.locator(sel).count() > 0:
                    await page.locator(sel).first.fill(topics)
                    break
            except Exception:
                continue
        await page.wait_for_timeout(400)

        # ── 6. Duration ───────────────────────────────────────────────────
        log.info(f"-> Duration: {duration}")
        for sel in ["input[type='number']", "input[placeholder*='60']"]:
            try:
                if await page.locator(sel).count() > 0:
                    await page.locator(sel).first.triple_click()
                    await page.locator(sel).first.fill(str(duration))
                    break
            except Exception:
                continue
        await page.wait_for_timeout(400)

        # ── 7. Brain icon ─────────────────────────────────────────────────
        log.info("-> Brain icon (generate questions)")
        brain_clicked = False
        all_buttons = await page.locator("button").all()
        for btn in all_buttons:
            try:
                text = (await btn.inner_text()).strip().lower()
                if text not in ("cancel", "save exam", "save", "create job role", "+ create job role"):
                    box = await btn.bounding_box()
                    if box and box["width"] < 60 and box["height"] < 60:
                        await btn.click()
                        brain_clicked = True
                        log.info(f"  Brain icon clicked ({box['width']}x{box['height']})")
                        break
            except Exception:
                continue

        if brain_clicked:
            log.info("  Waiting for questions to generate (8s)...")
            await page.wait_for_timeout(8000)
        else:
            log.warning("  Brain icon not found")

        # ── 8. Save Exam ──────────────────────────────────────────────────
        log.info("-> Save Exam")
        for sel in ["button:has-text('Save Exam')", "button:has-text('Save')", "button[type='submit']"]:
            try:
                if await page.locator(sel).count() > 0:
                    await page.locator(sel).first.click()
                    log.info(f"  Saved via: {sel}")
                    break
            except Exception:
                continue

        # ── 9. Wait for "Exam Created!" success page ──────────────────────
        log.info("-> Waiting for Exam Created page...")
        try:
            await page.wait_for_selector("text=Exam Created", timeout=15_000)
            log.info("  'Exam Created!' page detected!")
        except Exception:
            log.warning("  'Exam Created!' text not found — trying anyway")

        await page.wait_for_timeout(1500)
        await page.screenshot(path="step_exam_created.png")

        # ── 10. Extract the exam link from the input box ──────────────────
        log.info("-> Extracting exam link from success page...")

        # The link is inside an <input> field on the "Exam Created!" page
        # as seen in the screenshot: https://685e-2409-... shown in the input
        link_selectors = [
            "input[type='text'][value*='http']",
            "input[value*='http']",
            "input[readonly][value*='http']",
            "input[type='url']",
            "input[class*='link']",
            "input[class*='url']",
            "input[id*='link']",
            "input[id*='url']",
        ]

        for sel in link_selectors:
            try:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    val = await loc.first.get_attribute("value") or ""
                    if val.startswith("http"):
                        exam_link = val
                        log.info(f"  Got link from input ({sel}): {exam_link}")
                        break
            except Exception:
                continue

        # Fallback: select all text in any visible input and read it
        if not exam_link:
            try:
                inputs = await page.locator("input").all()
                for inp in inputs:
                    try:
                        val = await inp.get_attribute("value") or ""
                        if val.startswith("http"):
                            exam_link = val
                            log.info(f"  Got link from input scan: {exam_link}")
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        # Fallback: click the clipboard icon button next to the input
        # (this copies to clipboard; we then read it back via JS)
        if not exam_link:
            log.info("  Trying clipboard button...")
            try:
                # Grant clipboard permissions
                await context.grant_permissions(["clipboard-read", "clipboard-write"])

                clip_selectors = [
                    "button[class*='clipboard']",
                    "button[aria-label*='copy']",
                    "button[aria-label*='Copy']",
                    "button[title*='copy']",
                    "button[title*='Copy']",
                    "button svg",        # icon button with SVG
                ]
                for sel in clip_selectors:
                    btns = await page.locator(sel).all()
                    for btn in btns:
                        try:
                            box = await btn.bounding_box()
                            if box and box["width"] < 60:
                                await btn.click()
                                await page.wait_for_timeout(500)
                                # Read clipboard
                                exam_link = await page.evaluate("navigator.clipboard.readText()")
                                if exam_link and exam_link.startswith("http"):
                                    log.info(f"  Got link from clipboard: {exam_link}")
                                    break
                        except Exception:
                            continue
                    if exam_link:
                        break
            except Exception as e:
                log.warning(f"  Clipboard button method failed: {e}")

        # Fallback: scrape any URL-like text from the page
        if not exam_link:
            try:
                import re
                content = await page.content()
                urls = re.findall(r'https?://[^\s"\'<>]+', content)
                # Filter to exam-related URLs
                for url in urls:
                    if BASE_URL in url and url != BASE_URL and url != BASE_URL + "/":
                        exam_link = url.rstrip("\\,;")
                        log.info(f"  Extracted link from page HTML: {exam_link}")
                        break
            except Exception as e:
                log.warning(f"  HTML scan failed: {e}")

        await page.wait_for_timeout(1500)
        await browser.close()

    return exam_link


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  RecruitAI — Auto Assessment Creator")
    print("=" * 55)
    print(f"  Target : {BASE_URL}")
    print("=" * 55)
    print()

    job_role = input("  Enter Job Title (e.g. Python Developer): ").strip()
    if not job_role:
        print("  Job title is required. Exiting.")
        sys.exit(1)

    dur_input = input(f"  Duration in minutes [default {DEFAULT_DURATION}]: ").strip()
    try:
        duration = int(dur_input) if dur_input else DEFAULT_DURATION
    except ValueError:
        duration = DEFAULT_DURATION

    print()
    print("  Generating technical topics...")
    topics = generate_topics(job_role)

    print()
    print("  ── Assessment Details ──────────────────────")
    print(f"  Job Role  : {job_role}")
    print(f"  Topics    : {topics}")
    print(f"  Duration  : {duration} minutes")
    print("  ────────────────────────────────────────────")
    print()

    confirm = input("  Create this assessment? (y/n) [y]: ").strip().lower()
    if confirm == "n":
        print("  Cancelled.")
        sys.exit(0)

    print()
    exam_link = asyncio.run(create_assessment(job_role, topics, duration))

    print()
    print("=" * 55)
    print(f"  Assessment '{job_role}' created successfully!")
    print("=" * 55)

    if exam_link:
        print()
        print("  Exam Link (share with candidates):")
        print(f"  {exam_link}")
        print()
        if copy_to_clipboard(exam_link):
            print("  Copied to clipboard! Just Ctrl+V to paste anywhere.")
        else:
            print("  Copy the link above manually.")
    else:
        print()
        print("  Link not captured automatically.")
        print("  Check step_exam_created.png — the link is shown on that page.")