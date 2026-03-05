"""
Run this once from your project root:
    python add_post_assessment_routes.py
"""
import os

TARGET = os.path.join("app", "routes", "automation.py")

ROUTES = '''

# ─── POST-ASSESSMENT AUTOMATION ROUTES (added by patch) ──────────────────────

@automation_bp.route('/api/post-assessment/status', methods=['GET', 'OPTIONS'])
def post_assessment_status():
    """Status of the 24/7 post-assessment automation thread"""
    if request.method == 'OPTIONS':
        return '', 200
    try:
        from app.services.post_assessment_automation import get_automation_status
        return jsonify({"success": True, "automation": get_automation_status()}), 200
    except Exception as e:
        logger.error(f"post_assessment_status error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@automation_bp.route('/api/post-assessment/run-now', methods=['POST', 'OPTIONS'])
def post_assessment_run_now():
    """Manually trigger one check cycle right now"""
    if request.method == 'OPTIONS':
        return '', 200
    try:
        import threading as _t
        from app.services.post_assessment_automation import run_once_now
        data      = request.json or {}
        job_title = data.get('job_title')
        _t.Thread(target=run_once_now, args=(job_title,), daemon=True).start()
        return jsonify({
            "success": True,
            "message": f"Check triggered for: {job_title or 'ALL jobs'}"
        }), 200
    except Exception as e:
        logger.error(f"post_assessment_run_now error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
'''

content = open(TARGET, encoding='utf-8').read()

if '/api/post-assessment/status' in content:
    print("Routes already exist in", TARGET)
else:
    with open(TARGET, 'a', encoding='utf-8') as f:
        f.write(ROUTES)
    print(f"Routes added to {TARGET}")
    print("Restart Flask to apply.")