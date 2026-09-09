"""
Central configuration for the AI Breakthrough Discovery agentic system.
All secrets come from environment variables (set locally via .env, or in
Render's dashboard under Environment).
"""
import os

# ---- API keys -------------------------------------------------------------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

# ---- Groq models ------------------------------------------------------------
# You can point different agent tiers at different models to trade off
# cost/speed vs quality. All must be models available on your Groq account.
FAST_MODEL = os.environ.get("GROQ_FAST_MODEL", "llama-3.1-8b-instant")
SMART_MODEL = os.environ.get("GROQ_SMART_MODEL", "llama-3.3-70b-versatile")
REASONING_MODEL = os.environ.get("GROQ_REASONING_MODEL", "deepseek-r1-distill-llama-70b")

# ---- Scheduler --------------------------------------------------------------
RUN_HOUR = int(os.environ.get("RUN_HOUR", "6"))     # 06:00 by default
RUN_MINUTE = int(os.environ.get("RUN_MINUTE", "0"))
TIMEZONE = os.environ.get("TIMEZONE", "UTC")
SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "true").lower() == "true"

# ---- Research domains (fan-out under the Breakthrough Discovery Manager) ---
RESEARCH_DOMAINS = [
    {"key": "llm_foundation_models", "label": "LLM / Foundation Models",
     "queries": ["new large language model release", "foundation model breakthrough",
                 "state of the art LLM benchmark"]},
    {"key": "ai_hardware_infra", "label": "AI Hardware / Infrastructure",
     "queries": ["new AI chip announcement", "AI datacenter infrastructure breakthrough",
                 "inference hardware efficiency record"]},
    {"key": "agents_robotics", "label": "Agents / Robotics",
     "queries": ["autonomous AI agent breakthrough", "robotics foundation model",
                 "humanoid robot AI advance"]},
    {"key": "multimodal_vision_audio", "label": "Multimodal / Vision / Audio",
     "queries": ["multimodal AI model release", "text to video AI breakthrough",
                 "AI audio speech model advance"]},
    {"key": "ai_for_science", "label": "AI for Science / Bio AI",
     "queries": ["AI drug discovery breakthrough", "AI protein folding advance",
                 "AI for scientific discovery"]},
    {"key": "ai_safety_alignment", "label": "AI Safety / Alignment",
     "queries": ["AI safety research breakthrough", "AI alignment new technique",
                 "interpretability research advance"]},
]

# ---- Pipeline tuning ---------------------------------------------------------
TOP_N_BREAKTHROUGHS = int(os.environ.get("TOP_N_BREAKTHROUGHS", "5"))
MAX_RESEARCH_LOOP_ITERATIONS = int(os.environ.get("MAX_RESEARCH_LOOP_ITERATIONS", "2"))
MAX_QUALITY_LOOP_ITERATIONS = int(os.environ.get("MAX_QUALITY_LOOP_ITERATIONS", "2"))
QUALITY_PASS_THRESHOLD = float(os.environ.get("QUALITY_PASS_THRESHOLD", "7.5"))  # out of 10
TAVILY_MAX_RESULTS = int(os.environ.get("TAVILY_MAX_RESULTS", "5"))

# ---- Delivery ---------------------------------------------------------------
REPORTS_DIR = os.environ.get("REPORTS_DIR", "data/reports")
DB_PATH = os.environ.get("DB_PATH", "data/knowledge_base.db")

EMAIL_ENABLED = os.environ.get("EMAIL_ENABLED", "false").lower() == "true"
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USER)
EMAIL_TO = os.environ.get("EMAIL_TO", "")  # comma-separated list

# ---- App ----------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
