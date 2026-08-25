import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DB = os.getenv("MYSQL_DB", "fleetguard")

DATABASE_URL = os.getenv("DATABASE_URL") or (
    f"mysql+pymysql://{MYSQL_USER}:{quote_plus(MYSQL_PASSWORD)}"
    f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
)

SQL_ECHO = os.getenv("SQL_ECHO", "0") == "1"

SIGNALS = [
    "coolant_temp_variance",
    "oil_pressure_dips",
    "battery_voltage_sag",
    "dtc_recurrence_rate",
    "harsh_braking_frequency",
    "overload_duty_share",
    "high_rpm_dwell_time",
    "short_trip_ratio",
    "idle_time_pct",
]

SIGNAL_LABELS = {
    "coolant_temp_variance": "Coolant temp variance",
    "oil_pressure_dips": "Oil pressure dips",
    "battery_voltage_sag": "Battery voltage sag",
    "dtc_recurrence_rate": "DTC recurrence rate",
    "harsh_braking_frequency": "Harsh braking frequency",
    "overload_duty_share": "Overload duty share",
    "high_rpm_dwell_time": "High-RPM dwell time",
    "short_trip_ratio": "Short-trip ratio",
    "idle_time_pct": "Idle time %",
}

LABEL_HORIZON_DAYS = 90
ROLLING_WEEKS = 4

AMBER_THRESHOLD = 0.40
RED_THRESHOLD = 0.70

URGENT_RUL_DAYS = 7

FAILURE_THRESHOLD_INDEX = 30.0
WEIGHT_AGE = 70.0
WEIGHT_STRESS = 30.0

TREND_WEEKS = 10

BACKTEST_LOOKBACK_DAYS = 90
BACKTEST_EPISODE_DAYS = 45

MIN_CORRELATION = 0.05
DEFAULT_TOP_N_SIGNALS = 5

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
AGENT_MAX_TOOL_ROUNDS = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "6"))

CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
).split(",")