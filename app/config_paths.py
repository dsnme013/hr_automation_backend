import os
from pathlib import Path

# project root: .../backend/talentflow_migrated - Copy/
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# allow overrides via env; default to project-root/resumes
RESUME_DIR = Path(os.environ.get("RESUME_DIR", PROJECT_ROOT / "resumes"))
PROCESSED_RESUME_DIR = Path(os.environ.get("PROCESSED_RESUME_DIR", PROJECT_ROOT / "processed_resumes"))

RESUME_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_RESUME_DIR.mkdir(parents=True, exist_ok=True)
