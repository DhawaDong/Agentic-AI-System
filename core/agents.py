"""
Agent definitions. Each function/class corresponds to one box in the
architecture diagram. They are intentionally plain functions operating on
plain dicts (a shared "context" object) rather than a heavyweight framework —
easy to read, easy to swap models per-agent, easy to unit test.
"""
from __future__ import annotations

import hashlib
import json
import logging

from core import config
from core.llm import call_agent, call_agent_json
from core.search import multi_search, web_search

logger = logging.getLogger("agent.pipeline")


# =============================================================================
# 1. RESEARCH MANAGER AGENT
# =============================================================================
def research_manager_agent() -> dict:
    """Defines today's research objectives, domains and quality thresholds."""
    system = (
        "You are the Research Manager for an autonomous AI-breakthrough discovery "
        "system. You set the day's research objectives and priorities."
    )
    user = (
        "Produce today's research plan as JSON with keys: "
        "'objectives' (list of 3-5 short strings), "
        "'priority_domains' (list of domain keys to emphasize, from: "
        f"{[d['key'] for d in config.RESEARCH_DOMAINS]}), "
        "'quality_bar' (one sentence describing what counts as a genuine breakthrough "
        "vs routine incremental news)."
    )
    plan = call_agent_json(system, user, model=config.FAST_MODEL)
    if not plan:
        plan = {
            "objectives": ["Surface the most significant AI developments of the last 24-48h"],
            "priority_domains": [d["key"] for d in config.RESEARCH_DOMAINS],
            "quality_bar": "Must represent a genuine technical or capability advance, not routine news.",
        }
    logger.info("Research plan: %s", plan)
    return plan


# =============================================================================
# 2. DOMAIN RESEARCH AGENTS (fan-out under "AI Breakthrough Discovery Manager")
# =============================================================================
def domain_research_agent(domain: dict) -> list[dict]:
    """Searches the web for one domain and asks an LLM to shortlist candidates."""
    raw_results = multi_search(domain["queries"], max_results_each=config.TAVILY_MAX_RESULTS)
    if not raw_results:
        return []

    corpus = "\n\n".join(
        f"[{i}] {r.get('title')}\nURL: {r.get('url')}\n{r.get('content', '')[:600]}"
        for i, r in enumerate(raw_results)
    )
    system = (
        f"You are a domain research agent specialised in {domain['label']}. "
        "You review raw web search results and identify genuine candidate "
        "breakthroughs, discarding marketing fluff, duplicate coverage of the "
        "same story, and routine minor updates."
    )
    user = (
        f"Raw search results:\n\n{corpus}\n\n"
        "Return JSON: {\"candidates\": [{\"title\":..., \"summary\":..., "
        "\"source_urls\": [...], \"why_it_matters\":...}]}. "
        "Only include genuinely notable items (max 4)."
    )
    parsed = call_agent_json(system, user, model=config.SMART_MODEL)
    candidates = parsed.get("candidates", [])
    for c in candidates:
        c["domain_key"] = domain["key"]
        c["domain_label"] = domain["label"]
        c.setdefault("source_urls", [])
    return candidates


def run_all_domain_agents(plan: dict) -> list[dict]:
    all_candidates = []
    domains = [d for d in config.RESEARCH_DOMAINS if d["key"] in plan.get("priority_domains", [])] \
        or config.RESEARCH_DOMAINS
    for domain in domains:
        try:
            cands = domain_research_agent(domain)
            logger.info("Domain %s -> %d candidates", domain["key"], len(cands))
            all_candidates.extend(cands)
        except Exception as e:  # noqa: BLE001
            logger.exception("Domain agent failed for %s: %s", domain["key"], e)
    return all_candidates


# =============================================================================
# 3. CANDIDATE AGGREGATOR (dedupe / cluster)
# =============================================================================
def _dedup_hash(title: str) -> str:
    normalized = "".join(ch.lower() for ch in title if ch.isalnum())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def candidate_aggregator(candidates: list[dict]) -> list[dict]:
    """Deduplicates near-identical stories and tags each with a stable hash."""
    seen = {}
    for c in candidates:
        h = _dedup_hash(c.get("title", ""))
        c["dedup_hash"] = h
        if h not in seen:
            seen[h] = c
        else:
            # merge source urls from the duplicate into the kept candidate
            seen[h]["source_urls"] = list(set(seen[h].get("source_urls", []) + c.get("source_urls", [])))
    deduped = list(seen.values())
    logger.info("Aggregator: %d candidates -> %d after dedup", len(candidates), len(deduped))
    return deduped


# =============================================================================
# 4. BREAKTHROUGH RANKER
# =============================================================================
def breakthrough_ranker(candidates: list[dict], quality_bar: str) -> list[dict]:
    """Scores candidates on novelty/significance/evidence/impact/reproducibility/
    long-term importance, then returns the top N sorted by composite score."""
    if not candidates:
        return []

    system = (
        "You are the Breakthrough Ranker. Score each candidate 0-10 on: "
        "novelty, technical_significance, evidence_strength, impact, "
        "reproducibility, long_term_importance. "
        f"Quality bar: {quality_bar}"
    )
    listing = "\n\n".join(
        f"[{i}] {c['title']}\n{c.get('summary', '')}" for i, c in enumerate(candidates)
    )
    user = (
        f"Candidates:\n\n{listing}\n\n"
        "Return JSON: {\"scores\": [{\"index\": int, \"novelty\":0-10, "
        "\"technical_significance\":0-10, \"evidence_strength\":0-10, \"impact\":0-10, "
        "\"reproducibility\":0-10, \"long_term_importance\":0-10}]}"
    )
    parsed = call_agent_json(system, user, model=config.SMART_MODEL, max_tokens=2500)
    scores = {s["index"]: s for s in parsed.get("scores", []) if "index" in s}

    for i, c in enumerate(candidates):
        s = scores.get(i, {})
        c["novelty"] = s.get("novelty", 5)
        c["significance"] = s.get("technical_significance", 5)
        c["evidence_strength"] = s.get("evidence_strength", 5)
        c["impact"] = s.get("impact", 5)
        c["reproducibility"] = s.get("reproducibility", 5)
        c["long_term_importance"] = s.get("long_term_importance", 5)
        c["rank_score"] = round(
            0.2 * c["novelty"] + 0.2 * c["significance"] + 0.15 * c["evidence_strength"]
            + 0.2 * c["impact"] + 0.1 * c["reproducibility"] + 0.15 * c["long_term_importance"],
            2,
        )

    ranked = sorted(candidates, key=lambda c: c["rank_score"], reverse=True)
    top = ranked[: config.TOP_N_BREAKTHROUGHS]
    logger.info("Ranker: top scores %s", [(c["title"], c["rank_score"]) for c in top])
    return top


# =============================================================================
# 5. DEEP RESEARCH LOOP (per breakthrough)
# =============================================================================
def primary_source_researcher(breakthrough: dict) -> list[dict]:
    """Tries to find the primary source (paper, official blog/announcement)."""
    query = f"{breakthrough['title']} official announcement OR paper OR blog"
    return web_search(query, max_results=5)


def secondary_source_agent(breakthrough: dict) -> list[dict]:
    """Finds independent secondary coverage / commentary / analysis."""
    query = f"{breakthrough['title']} analysis review reaction"
    return web_search(query, max_results=5)


def evidence_agent(breakthrough: dict, sources: list[dict]) -> dict:
    """Extracts claims and maps them to supporting evidence, ranks sources."""
    corpus = "\n\n".join(
        f"[{i}] {s.get('title')}\nURL: {s.get('url')}\n{s.get('content', '')[:800]}"
        for i, s in enumerate(sources)
    )
    system = "You are the Evidence Agent: extract concrete factual claims and map them to sources."
    user = (
        f"Breakthrough: {breakthrough['title']}\n{breakthrough.get('summary', '')}\n\n"
        f"Sources:\n{corpus}\n\n"
        "Return JSON: {\"claims\": [{\"claim\":..., \"supporting_source_indices\":[...], "
        "\"confidence\":0-10}], \"best_sources\": [index,...]}"
    )
    return call_agent_json(system, user, model=config.SMART_MODEL, max_tokens=2000)


def verification_agent(breakthrough: dict, evidence: dict) -> dict:
    """Fact-checks/benchmark-checks the extracted claims."""
    system = (
        "You are the Verification Agent. Cross-check claims for internal consistency, "
        "plausibility against known benchmarks/prior art, and flag anything unverifiable."
    )
    user = (
        f"Breakthrough: {breakthrough['title']}\n"
        f"Claims: {json.dumps(evidence.get('claims', []))}\n\n"
        "Return JSON: {\"verified_claims\":[...], \"unverified_or_risky_claims\":[...], "
        "\"verification_notes\": \"...\"}"
    )
    return call_agent_json(system, user, model=config.SMART_MODEL, max_tokens=1500)


def adversarial_skeptic_agent(breakthrough: dict, evidence: dict, verification: dict) -> dict:
    """Actively tries to find reasons the breakthrough might be overstated/wrong."""
    system = (
        "You are an adversarial Skeptic Agent. Your job is to argue against the "
        "breakthrough being as significant as claimed: 'What could be wrong here?' "
        "Consider: hype, cherry-picked benchmarks, lack of independent replication, "
        "narrow applicability, conflicts of interest."
    )
    user = (
        f"Breakthrough: {breakthrough['title']}\n"
        f"Verified claims: {json.dumps(verification.get('verified_claims', []))}\n"
        f"Unverified/risky claims: {json.dumps(verification.get('unverified_or_risky_claims', []))}\n\n"
        "Return JSON: {\"skeptical_points\": [...], \"severity\": \"low|medium|high\"}"
    )
    return call_agent_json(system, user, model=config.SMART_MODEL, max_tokens=1200)


def research_gap_analyzer(breakthrough: dict, evidence: dict, verification: dict,
                           skepticism: dict) -> dict:
    """Decides whether more research is needed or if we have enough to synthesize."""
    system = "You are the Research Gap Analyzer. Decide if the research is sufficient."
    user = (
        f"Evidence claims: {len(evidence.get('claims', []))}\n"
        f"Unverified/risky claims: {json.dumps(verification.get('unverified_or_risky_claims', []))}\n"
        f"Skeptical severity: {skepticism.get('severity')}\n\n"
        "Return JSON: {\"sufficient\": true|false, \"missing_evidence\": [...], "
        "\"follow_up_queries\": [...] }"
    )
    return call_agent_json(system, user, model=config.FAST_MODEL, max_tokens=800)


def synthesis_agent(breakthrough: dict, evidence: dict, verification: dict,
                     skepticism: dict) -> dict:
    """Synthesizes everything gathered into a coherent researched brief."""
    system = "You are the Synthesis Agent: produce a balanced, evidence-grounded brief."
    user = (
        f"Breakthrough: {breakthrough['title']}\n"
        f"Summary: {breakthrough.get('summary','')}\n"
        f"Verified claims: {json.dumps(verification.get('verified_claims', []))}\n"
        f"Skeptical points: {json.dumps(skepticism.get('skeptical_points', []))}\n\n"
        "Return JSON: {\"synthesis\": \"2-4 paragraph balanced brief\", "
        "\"key_facts\": [...], \"caveats\": [...]}"
    )
    return call_agent_json(system, user, model=config.SMART_MODEL, max_tokens=1500)


def deep_research_loop(breakthrough: dict) -> dict:
    """Orchestrates the primary/secondary -> evidence -> verification -> skeptic ->
    gap-analysis loop -> synthesis, for a single breakthrough."""
    primary = primary_source_researcher(breakthrough)
    secondary = secondary_source_agent(breakthrough)
    sources = primary + secondary

    evidence, verification, skepticism = {}, {}, {}
    for iteration in range(1, config.MAX_RESEARCH_LOOP_ITERATIONS + 1):
        evidence = evidence_agent(breakthrough, sources)
        verification = verification_agent(breakthrough, evidence)
        skepticism = adversarial_skeptic_agent(breakthrough, evidence, verification)
        gap = research_gap_analyzer(breakthrough, evidence, verification, skepticism)

        if gap.get("sufficient", True) or iteration == config.MAX_RESEARCH_LOOP_ITERATIONS:
            break

        follow_ups = gap.get("follow_up_queries", [])
        if not follow_ups:
            break
        logger.info("Research gap found for %s, iteration %d, follow-up: %s",
                    breakthrough["title"], iteration, follow_ups)
        extra = multi_search(follow_ups, max_results_each=3)
        sources = sources + extra

    synthesis = synthesis_agent(breakthrough, evidence, verification, skepticism)

    return {
        **breakthrough,
        "sources": sources,
        "evidence": evidence,
        "verification": verification,
        "skepticism": skepticism,
        "synthesis": synthesis,
    }


# =============================================================================
# 6. ANALYSIS CHAIN: technical / impact / trend / personal relevance
# =============================================================================
def technical_analyst_agent(researched: dict) -> str:
    system = "You are the Technical Analyst Agent. Explain the technical mechanics clearly."
    user = (
        f"Breakthrough: {researched['title']}\n"
        f"Synthesis: {researched['synthesis'].get('synthesis','')}\n"
        f"Key facts: {json.dumps(researched['synthesis'].get('key_facts', []))}\n\n"
        "Write a technical analysis (2-3 paragraphs): how it works, what makes it different "
        "from prior approaches, and any technical limitations."
    )
    return call_agent(system, user, model=config.SMART_MODEL, max_tokens=800)


def impact_analyst_agent(researched: dict) -> str:
    system = "You are the Impact Analyst Agent. Assess real-world impact."
    user = (
        f"Breakthrough: {researched['title']}\n"
        f"Synthesis: {researched['synthesis'].get('synthesis','')}\n"
        f"Caveats: {json.dumps(researched['synthesis'].get('caveats', []))}\n\n"
        "Write an impact analysis (1-2 paragraphs): who benefits, what industries/use cases "
        "are affected, and how significant is this compared to recent similar work."
    )
    return call_agent(system, user, model=config.SMART_MODEL, max_tokens=600)


def trend_future_agent(researched: dict) -> str:
    system = "You are the Trend / Future Agent. Situate this within the broader trajectory of AI."
    user = (
        f"Breakthrough: {researched['title']}\n"
        f"Synthesis: {researched['synthesis'].get('synthesis','')}\n\n"
        "Write 1 short paragraph on what trend this fits into and what it suggests may "
        "come next (6-12 months out)."
    )
    return call_agent(system, user, model=config.FAST_MODEL, max_tokens=400)


def personal_relevance_agent(researched: dict, interests: list[str] | None = None) -> str:
    interests = interests or ["software engineering", "AI product building", "research"]
    system = "You are the Personal Relevance Agent. Make this concrete and actionable for the reader."
    user = (
        f"Breakthrough: {researched['title']}\n"
        f"Synthesis: {researched['synthesis'].get('synthesis','')}\n"
        f"Reader interests: {', '.join(interests)}\n\n"
        "Write 2-4 bullet points on why this specifically matters to someone with these "
        "interests, and any concrete action worth considering (e.g. a tool to try, a paper "
        "to read, a risk to watch)."
    )
    return call_agent(system, user, model=config.FAST_MODEL, max_tokens=400)


def run_analysis_chain(researched: dict) -> dict:
    researched["technical_analysis"] = technical_analyst_agent(researched)
    researched["impact_analysis"] = impact_analyst_agent(researched)
    researched["trend_analysis"] = trend_future_agent(researched)
    researched["personal_relevance"] = personal_relevance_agent(researched)
    return researched


# =============================================================================
# 7. REPORT ARCHITECT + TECHNICAL WRITER
# =============================================================================
def report_architect_agent(analyzed_breakthroughs: list[dict], objectives: list[str]) -> dict:
    system = "You are the Report Architect Agent. Design a clear outline for today's report."
    titles = [b["title"] for b in analyzed_breakthroughs]
    user = (
        f"Today's objectives: {objectives}\n"
        f"Breakthroughs to cover, in ranked order: {titles}\n\n"
        "Return JSON: {\"report_title\": \"...\", \"sections\": [\"Executive Summary\", "
        "one section per breakthrough title, \"Cross-Cutting Trends\", \"Sources\"]}"
    )
    outline = call_agent_json(system, user, model=config.FAST_MODEL, max_tokens=600)
    if not outline.get("sections"):
        outline = {
            "report_title": "AI Breakthrough Discovery — Daily Report",
            "sections": ["Executive Summary"] + titles + ["Cross-Cutting Trends", "Sources"],
        }
    return outline


def technical_writer_agent(outline: dict, analyzed_breakthroughs: list[dict],
                            objectives: list[str]) -> str:
    system = (
        "You are the Technical Writer Agent. Write a polished, well-structured markdown "
        "report a technically sophisticated reader would enjoy: precise, evidence-grounded, "
        "no hype, no filler."
    )
    breakthroughs_json = json.dumps([
        {
            "title": b["title"],
            "domain": b.get("domain_label"),
            "rank_score": b.get("rank_score"),
            "synthesis": b["synthesis"].get("synthesis"),
            "key_facts": b["synthesis"].get("key_facts"),
            "caveats": b["synthesis"].get("caveats"),
            "technical_analysis": b.get("technical_analysis"),
            "impact_analysis": b.get("impact_analysis"),
            "trend_analysis": b.get("trend_analysis"),
            "personal_relevance": b.get("personal_relevance"),
            "sources": [s.get("url") for s in b.get("sources", [])[:5]],
        }
        for b in analyzed_breakthroughs
    ], indent=2)

    user = (
        f"Report title: {outline.get('report_title')}\n"
        f"Section outline: {outline.get('sections')}\n"
        f"Today's objectives: {objectives}\n\n"
        f"Breakthrough data:\n{breakthroughs_json}\n\n"
        "Write the full report in markdown, following the outline. Include an Executive "
        "Summary at the top (bullet list of the breakthroughs with one line each), then one "
        "full section per breakthrough (technical analysis, impact, trend, why it matters), "
        "a short 'Cross-Cutting Trends' section synthesizing patterns across all of them, "
        "and a 'Sources' section listing URLs grouped by breakthrough."
    )
    return call_agent(system, user, model=config.SMART_MODEL, temperature=0.4, max_tokens=4000)


# =============================================================================
# 8. REPORT QUALITY LOOP: fact / technical / writing critics -> judge -> revise
# =============================================================================
def fact_critic_agent(report_md: str, analyzed_breakthroughs: list[dict]) -> dict:
    system = "You are the Fact Critic. Check the report against the underlying evidence for accuracy."
    facts = json.dumps([b["synthesis"].get("key_facts") for b in analyzed_breakthroughs])
    user = f"Report:\n{report_md[:6000]}\n\nKnown key facts:\n{facts}\n\n" \
           "Return JSON: {\"score\": 0-10, \"issues\": [...]}"
    return call_agent_json(system, user, model=config.SMART_MODEL, max_tokens=800)


def technical_critic_agent(report_md: str) -> dict:
    system = "You are the Technical Critic. Check technical explanations for correctness and clarity."
    user = f"Report:\n{report_md[:6000]}\n\nReturn JSON: {{\"score\": 0-10, \"issues\": [...]}}"
    return call_agent_json(system, user, model=config.SMART_MODEL, max_tokens=800)


def writing_critic_agent(report_md: str) -> dict:
    system = "You are the Writing Critic. Check structure, clarity, tone, and lack of hype/filler."
    user = f"Report:\n{report_md[:6000]}\n\nReturn JSON: {{\"score\": 0-10, \"issues\": [...]}}"
    return call_agent_json(system, user, model=config.FAST_MODEL, max_tokens=800)


def quality_judge_agent(fact_review: dict, technical_review: dict, writing_review: dict) -> dict:
    scores = [fact_review.get("score", 5), technical_review.get("score", 5),
              writing_review.get("score", 5)]
    composite = round(sum(scores) / len(scores), 2)
    all_issues = (fact_review.get("issues", []) + technical_review.get("issues", [])
                  + writing_review.get("issues", []))
    verdict = "PASS" if composite >= config.QUALITY_PASS_THRESHOLD else "FAIL"
    return {"composite_score": composite, "verdict": verdict, "issues": all_issues}


def revision_agent(report_md: str, judge_result: dict) -> str:
    system = "You are the Revision Agent. Fix the report to address every listed issue, minimally."
    user = (
        f"Current report:\n{report_md}\n\n"
        f"Issues to fix: {json.dumps(judge_result.get('issues', []))}\n\n"
        "Return the full corrected markdown report, same structure, issues resolved."
    )
    return call_agent(system, user, model=config.SMART_MODEL, temperature=0.3, max_tokens=4000)


def report_quality_loop(report_md: str, analyzed_breakthroughs: list[dict]) -> dict:
    judge_result = {}
    for iteration in range(1, config.MAX_QUALITY_LOOP_ITERATIONS + 1):
        fact_review = fact_critic_agent(report_md, analyzed_breakthroughs)
        technical_review = technical_critic_agent(report_md)
        writing_review = writing_critic_agent(report_md)
        judge_result = quality_judge_agent(fact_review, technical_review, writing_review)
        logger.info("Quality loop iteration %d: %s", iteration, judge_result)

        if judge_result["verdict"] == "PASS" or iteration == config.MAX_QUALITY_LOOP_ITERATIONS:
            break
        report_md = revision_agent(report_md, judge_result)

    return {"report_markdown": report_md, "judge_result": judge_result}
