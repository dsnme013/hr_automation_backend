from app import create_app
from app.services import assessment_automation_system
app = create_app()
if __name__ == "__main__":
    assessment_automation_system.start_assessment_automation()
    print("✅ Assessment automation started")
    app.run(host="0.0.0.0", port=5000, debug=True)
