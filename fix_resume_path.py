"""
fix_resume_path.py — Run from project root.
Finds exactly which line reads the resume folder and fixes it.
"""
import os
import re

TARGET = os.path.join("app", "services", "clint_recruitment_system.py")
lines  = open(TARGET, encoding="utf-8").readlines()

print(f"Total lines: {len(lines)}")
print()

# Show all lines mentioning resumes / RESUME_FOLDER / downloaded
print("=== All resume-related lines ===")
for i, line in enumerate(lines):
    if any(k in line for k in ["resumes", "RESUME", "downloaded", "resume_folder", "os.walk", "os.listdir"]):
        print(f"  {i+1:4d}: {line.rstrip()}")

print()

# Check what folder actually exists on disk
base = os.path.dirname(os.path.abspath(__file__))
candidates = [
    os.path.join(base, "downloaded_resumes"),
    os.path.join(base, "resumes"),
    os.path.join(base, "app", "services", "resumes"),
    os.path.join(base, "app", "services", "downloaded_resumes"),
]
print("=== Folder existence check ===")
for p in candidates:
    exists = os.path.exists(p)
    count  = 0
    if exists:
        for root, dirs, files in os.walk(p):
            count += sum(1 for f in files if f.lower().endswith(('.pdf','.docx','.txt')))
    print(f"  {'✅' if exists else '❌'} {p}  {'→ ' + str(count) + ' resume(s)' if exists else ''}")

print()

# Now fix every occurrence of the wrong resumes path
fixed = 0
new_lines = []
for i, line in enumerate(lines):
    # Fix RESUME_FOLDER pointing to wrong place
    if re.match(r'\s*RESUME_FOLDER\s*=', line) and "downloaded_resumes" not in line:
        indent = len(line) - len(line.lstrip())
        new_line = ' ' * indent + 'RESUME_FOLDER    = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "downloaded_resumes")\n'
        print(f"  Fixed RESUME_FOLDER (line {i+1})")
        print(f"    FROM: {line.rstrip()}")
        print(f"    TO  : {new_line.rstrip()}")
        new_lines.append(new_line)
        fixed += 1

    # Fix PROJECT_ROOT if missing
    elif re.match(r'\s*PROJECT_ROOT\s*=', line) and "dirname(os.path.dirname(os.path.dirname" not in line:
        indent = len(line) - len(line.lstrip())
        new_line = ' ' * indent + 'PROJECT_ROOT     = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n'
        new_lines.append(new_line)
        fixed += 1

    # Fix run_recruitment_with_invite_link resume scan — replace os.listdir with os.walk
    elif "os.listdir(resume_folder)" in line:
        # Replace the whole list comprehension block
        new_lines.append('    resume_files = []\n')
        new_lines.append('    for root, dirs, files in os.walk(resume_folder):\n')
        new_lines.append('        for f in files:\n')
        new_lines.append('            if f.lower().endswith((\'.pdf\', \'.docx\', \'.txt\')):\n')
        new_lines.append('                resume_files.append(os.path.join(root, f))\n')
        print(f"  Fixed os.listdir → os.walk (line {i+1})")
        fixed += 1

    # Skip the old lines that were part of the list comprehension
    elif "f.lower().endswith" in line and "resume_files" not in line and "resume_path" not in line:
        continue  # skip old listdir lines
    elif line.strip().startswith("for f in os.listdir"):
        continue

    else:
        new_lines.append(line)

# Also fix RESUME_FOLDER lookup inside run_recruitment_with_invite_link
final_lines = []
for i, line in enumerate(new_lines):
    # Fix the folder search list — add RESUME_FOLDER as first option
    if "for p in [RESUME_DIR" in line and "RESUME_FOLDER" not in line:
        new_line = line.replace(
            "for p in [RESUME_DIR",
            "for p in [RESUME_FOLDER, RESUME_DIR"
        )
        final_lines.append(new_line)
        print(f"  Fixed folder search to include RESUME_FOLDER")
        fixed += 1
    elif 'for p in [os.path.join(PROJECT_DIR' in line:
        # Replace old path list with correct one
        final_lines.append('    for p in [RESUME_FOLDER, RESUME_DIR]:\n')
        fixed += 1
    else:
        final_lines.append(line)

open(TARGET, "w", encoding="utf-8").writelines(final_lines)

print()
print(f"{'='*60}")
print(f"Fixed {fixed} issue(s) in {TARGET}")
print(f"{'='*60}")
print("Run: python run.py")