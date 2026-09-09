# AI Breakthrough Discovery — Agentic Pipeline

A daily, multi-agent pipeline that discovers, verifies, analyzes and reports on
AI breakthroughs — implemented with **Groq** (LLM inference), **Tavily**
(web search), **Flask** (web app / dashboard), **APScheduler** (daily
trigger), and **SQLite** (memory / knowledge base). Deployable to
**Render.com** straight from a GitHub repo.

## How the diagram maps to the code

| Diagram box | Code |
|---|---|
| Daily Scheduler | `app.py` — APScheduler cron job, `RUN_HOUR`/`RUN_MINUTE` |
| Research Manager Agent | `core/agents.py::research_manager_agent` |
| AI Breakthrough Discovery Manager + domain fan-out | `core/agents.py::run_all_domain_agents` over `config.RESEARCH_DOMAINS` |
| Candidate Aggregator | `core/agents.py::candidate_aggregator` |
| Breakthrough Ranker | `core/agents.py::breakthrough_ranker` |
| Deep Research Loop (primary/secondary, evidence, verification, adversarial, gap analyzer, loop) | `core/agents.py::deep_research_loop` |
| Synthesis Agent | `core/agents.py::synthesis_agent` |
| Technical / Impact / Trend / Personal Relevance Agents | `core/agents.py::run_analysis_chain` |
| Report Architect + Technical Writer | `core/agents.py::report_architect_agent`, `technical_writer_agent` |
| Report Quality Loop (Fact/Technical/Writing Critic → Judge → Revision) | `core/agents.py::report_quality_loop` |
| Memory / Knowledge Base | `core/memory.py` (SQLite) |
| Publish (PDF / Web / Email / Dashboard) | `core/report.py` (PDF), `core/delivery.py` (email), `app.py` (web dashboard) |

The whole thing is orchestrated top-to-bottom by `core/pipeline.py::run_pipeline()`.

## Project layout

```
ai-breakthrough-agent/
├── app.py                 # Flask app, routes, scheduler
├── core/
│   ├── config.py           # env vars, domains, thresholds
│   ├── llm.py               # Groq wrapper
│   ├── search.py            # Tavily wrapper
│   ├── agents.py            # every agent in the diagram
│   ├── pipeline.py          # orchestrates the full run
│   ├── memory.py            # SQLite knowledge base
│   ├── report.py            # markdown -> PDF
│   └── delivery.py          # email delivery
├── templates/               # dashboard HTML
├── requirements.txt
├── Procfile
├── render.yaml               # Render blueprint (infra as code)
├── .env.example
└── .gitignore
```

## 1. Local setup

```bash
git clone <your-repo-url>
cd ai-breakthrough-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: set GROQ_API_KEY and TAVILY_API_KEY
```

Get keys:
- Groq: https://console.groq.com/keys
- Tavily: https://app.tavily.com

Run locally:

```bash
export $(grep -v '^#' .env | xargs)   # or use python-dotenv / direnv
python app.py
# open http://localhost:5000
```

Click **"Run now"** on the dashboard to trigger a full pipeline run manually
instead of waiting for the scheduled time — useful for testing.

## 2. Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit: AI breakthrough discovery agentic pipeline"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

`.env` is git-ignored — never commit real API keys.

## 3. Deploy to Render.com

**Option A — Blueprint (recommended, uses `render.yaml`):**
1. Go to https://dashboard.render.com → **New** → **Blueprint**.
2. Connect your GitHub repo. Render reads `render.yaml` automatically and
   provisions a Web Service with a persistent disk mounted at `data/`.
3. When prompted, fill in the secret env vars: `GROQ_API_KEY`, `TAVILY_API_KEY`.
4. Click **Apply** — Render builds (`pip install -r requirements.txt`) and
   starts (`gunicorn app:app ...`) automatically.

**Option B — Manual Web Service:**
1. **New** → **Web Service** → connect the repo.
2. Runtime: Python 3. Build command: `pip install -r requirements.txt`.
   Start command: `gunicorn app:app --workers 1 --threads 4 --timeout 300 --bind 0.0.0.0:$PORT`.
3. Add env vars from `.env.example` (at minimum `GROQ_API_KEY`, `TAVILY_API_KEY`).
4. Add a **Disk** (Settings → Disks) mounted at `data/` if you want the
   SQLite DB and generated PDFs to survive deploys — otherwise they reset
   on every deploy since Render's filesystem is ephemeral outside of disks.
5. Deploy. Render auto-redeploys on every push to `main`.

**Important:** keep `--workers 1`. The in-process scheduler and the
run-in-progress lock in `app.py` are not safe across multiple worker
processes; with `workers 1` there's exactly one scheduler and one pipeline
run at a time, which is what you want for a once-a-day job. If you need more
HTTP concurrency, add `--threads` rather than `--workers`.

## 4. Configuration knobs (env vars)

| Var | Purpose | Default |
|---|---|---|
| `RUN_HOUR` / `RUN_MINUTE` / `TIMEZONE` | when the daily run fires | `6:00 UTC` |
| `GROQ_FAST_MODEL` / `GROQ_SMART_MODEL` | which Groq models cheap vs. heavy agents use | see `.env.example` |
| `TOP_N_BREAKTHROUGHS` | how many breakthroughs go through deep research | `5` |
| `MAX_RESEARCH_LOOP_ITERATIONS` | cap on the evidence↔gap-analysis loop | `2` |
| `MAX_QUALITY_LOOP_ITERATIONS` | cap on the critic↔revision loop | `2` |
| `QUALITY_PASS_THRESHOLD` | composite score (0–10) the Quality Judge requires to PASS | `7.5` |
| `EMAIL_ENABLED` + `SMTP_*` / `EMAIL_TO` | auto-email each report | off |

Research domains (the 6 boxes under "AI Breakthrough Discovery Manager") are
defined in `core/config.py::RESEARCH_DOMAINS` — edit the list to add/remove
domains or change their seed search queries.

## 5. Extending it

- **More domains:** append to `RESEARCH_DOMAINS` in `core/config.py`.
- **Postgres instead of SQLite:** Render Postgres is free-tier friendly;
  swap the `sqlite3` calls in `core/memory.py` for `psycopg2`/SQLAlchemy —
  every other module only calls the functions in `memory.py`, so nothing
  else needs to change.
- **Slack/Discord delivery:** add a `core/delivery.py::send_slack_report()`
  following the same pattern as `send_email_report`, then call it from
  `core/pipeline.py`.
- **Swap Tavily for another search API:** only `core/search.py` needs to change.
- **Run more/less often, or add a second time slot:** add another
  `scheduler.add_job(...)` call in `app.py`.
