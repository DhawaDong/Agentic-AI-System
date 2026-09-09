"""
Flask entrypoint.

Routes:
    GET  /                    dashboard (recent runs + reports)
    GET  /runs/<id>           run detail
    GET  /reports/<id>        report detail (rendered markdown)
    GET  /reports/<id>/pdf    download the PDF
    POST /trigger             manually kick off a pipeline run (also used by the
                               "Run now" button on the dashboard)
    GET  /healthz             health check for Render

The daily scheduler (APScheduler) fires run_pipeline() automatically at
RUN_HOUR:RUN_MINUTE (config.py / env vars), independent of any HTTP traffic —
this is the "DAILY SCHEDULER" box at the top of the diagram.
"""
import logging
import os
import threading

from flask import Flask, abort, jsonify, redirect, render_template, send_file, url_for

from apscheduler.schedulers.background import BackgroundScheduler

from core import config, memory
from core.pipeline import run_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("agent.app")

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY

memory.init_db()

_run_lock = threading.Lock()
_run_in_progress = False


def _run_pipeline_safely():
    global _run_in_progress
    if not _run_lock.acquire(blocking=False):
        logger.warning("Pipeline run requested but one is already in progress; skipping.")
        return
    global_state = {}
    try:
        _run_in_progress = True
        result = run_pipeline()
        global_state["result"] = result
    except Exception:
        logger.exception("Scheduled/triggered pipeline run failed.")
    finally:
        _run_in_progress = False
        _run_lock.release()


# ---- scheduler --------------------------------------------------------------
scheduler = BackgroundScheduler(timezone=config.TIMEZONE)
if config.SCHEDULER_ENABLED:
    scheduler.add_job(
        _run_pipeline_safely,
        trigger="cron",
        hour=config.RUN_HOUR,
        minute=config.RUN_MINUTE,
        id="daily_breakthrough_run",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: daily run at %02d:%02d %s",
                config.RUN_HOUR, config.RUN_MINUTE, config.TIMEZONE)
else:
    logger.info("Scheduler disabled via SCHEDULER_ENABLED=false")


# ---- routes -------------------------------------------------------------------
@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/")
def dashboard():
    runs = memory.list_runs(limit=15)
    reports = memory.list_reports(limit=15)
    reports_by_run = {r["run_id"]: r for r in reports}
    return render_template(
        "dashboard.html",
        runs=runs,
        reports_by_run=reports_by_run,
        run_in_progress=_run_in_progress,
        scheduler_enabled=config.SCHEDULER_ENABLED,
        run_hour=config.RUN_HOUR,
        run_minute=config.RUN_MINUTE,
        timezone=config.TIMEZONE,
    )


@app.route("/trigger", methods=["POST"])
def trigger():
    if _run_in_progress:
        return jsonify({"status": "already_running"}), 409
    thread = threading.Thread(target=_run_pipeline_safely, daemon=True)
    thread.start()
    return redirect(url_for("dashboard"))


@app.route("/runs/<int:run_id>")
def run_detail(run_id):
    run = memory.get_run(run_id)
    if not run:
        abort(404)
    report = memory.latest_report_for_run(run_id)
    return render_template("run_detail.html", run=run, report=report)


@app.route("/reports/<int:report_id>")
def report_detail(report_id):
    report = memory.get_report(report_id)
    if not report:
        abort(404)
    return render_template("report_detail.html", report=report)


@app.route("/reports/<int:report_id>/pdf")
def report_pdf(report_id):
    report = memory.get_report(report_id)
    if not report or not report.get("pdf_path") or not os.path.exists(report["pdf_path"]):
        abort(404)
    return send_file(report["pdf_path"], as_attachment=True,
                      download_name=f"{report['title']}.pdf")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
