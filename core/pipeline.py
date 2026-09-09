"""
Top-level orchestrator. Runs the full pipeline end to end, exactly mirroring
the architecture diagram top to bottom, and persists everything to the
knowledge base as it goes.
"""
import logging

from core import agents, config, memory
from core.report import render_pdf
from core.delivery import send_email_report

logger = logging.getLogger("agent.pipeline")


def run_pipeline() -> dict:
    """Runs one full end-to-end cycle. Returns a summary dict."""
    plan = agents.research_manager_agent()
    run_id = memory.create_run(plan)
    logger.info("=== Starting run %s ===", run_id)

    try:
        # --- fan-out domain research -> aggregate -> rank ---------------------
        candidates = agents.run_all_domain_agents(plan)
        deduped = agents.candidate_aggregator(candidates)
        top_breakthroughs = agents.breakthrough_ranker(deduped, plan.get("quality_bar", ""))

        if not top_breakthroughs:
            memory.finish_run(run_id, status="completed_empty")
            return {"run_id": run_id, "status": "completed_empty", "breakthroughs": 0}

        for b in top_breakthroughs:
            memory.save_breakthrough(run_id, b)
            for s in b.get("source_urls", []):
                memory.mark_source_seen(s, b["title"], run_id)

        # --- deep research loop + analysis chain, per breakthrough -------------
        analyzed = []
        for b in top_breakthroughs:
            researched = agents.deep_research_loop(b)
            for s in researched.get("sources", []):
                url = s.get("url")
                if url:
                    memory.mark_source_seen(url, s.get("title", ""), run_id)
            analyzed.append(agents.run_analysis_chain(researched))

        # --- report architect + writer -----------------------------------------
        outline = agents.report_architect_agent(analyzed, plan.get("objectives", []))
        draft = agents.technical_writer_agent(outline, analyzed, plan.get("objectives", []))

        # --- quality loop --------------------------------------------------------
        quality_result = agents.report_quality_loop(draft, analyzed)
        final_markdown = quality_result["report_markdown"]
        judge = quality_result["judge_result"]

        # --- publish ---------------------------------------------------------------
        pdf_path = render_pdf(outline.get("report_title", "AI Breakthrough Report"),
                               final_markdown, run_id)
        report_id = memory.save_report(
            run_id, outline.get("report_title", "AI Breakthrough Report"),
            final_markdown, judge.get("composite_score", 0), pdf_path,
        )

        if config.EMAIL_ENABLED:
            try:
                send_email_report(outline.get("report_title", "AI Breakthrough Report"),
                                   final_markdown, pdf_path)
            except Exception as e:  # noqa: BLE001
                logger.exception("Email delivery failed: %s", e)

        memory.finish_run(run_id, status="completed")
        logger.info("=== Run %s completed. report_id=%s quality=%s ===",
                    run_id, report_id, judge.get("composite_score"))
        return {
            "run_id": run_id,
            "report_id": report_id,
            "status": "completed",
            "breakthroughs": len(analyzed),
            "quality_score": judge.get("composite_score"),
        }

    except Exception as e:  # noqa: BLE001
        logger.exception("Pipeline run %s failed: %s", run_id, e)
        memory.finish_run(run_id, status="failed", error=str(e))
        raise
