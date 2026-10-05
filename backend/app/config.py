"""Central configuration (environment-driven)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
KB_DIR = DATA_DIR / "knowledge_base"
STANDARDS_FILE = DATA_DIR / "standards" / "standards.json"
MODEL_DIR = DATA_DIR / "models"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'envintel.db'}")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# LLM (optional). Without a key the agents use deterministic templates.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "none").lower()  # anthropic | openai | gemini | none
LLM_MODEL = os.getenv("LLM_MODEL", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

WEATHER_API_URL = os.getenv("WEATHER_API_URL", "https://api.open-meteo.com/v1/forecast")
WEATHER_TIMEOUT_S = float(os.getenv("WEATHER_TIMEOUT_S", "5"))
ENABLE_LIVE_WEATHER = os.getenv("ENABLE_LIVE_WEATHER", "true").lower() == "true"

NETWORK_ID = os.getenv("NETWORK_ID", "VIJAYAWADA_01")
NETWORK_LAT, NETWORK_LON = 16.5062, 80.6480
TIMEZONE = "Asia/Kolkata"

CROSS_STATION_RADIUS_KM = float(os.getenv("CROSS_STATION_RADIUS_KM", "20"))
SOURCE_SEARCH_RADIUS_KM = float(os.getenv("SOURCE_SEARCH_RADIUS_KM", "5"))
STALE_AFTER_HOURS = int(os.getenv("STALE_AFTER_HOURS", "3"))
MIN_COVERAGE = float(os.getenv("MIN_COVERAGE", "0.75"))
BANDIT_EPSILON = float(os.getenv("BANDIT_EPSILON", "0.1"))
ALERT_DEDUP_HOURS = int(os.getenv("ALERT_DEDUP_HOURS", "6"))
ANALYSIS_LOOKBACK_DAYS = int(os.getenv("ANALYSIS_LOOKBACK_DAYS", "30"))
SEED_ON_STARTUP = os.getenv("SEED_ON_STARTUP", "true").lower() == "true"
