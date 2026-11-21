import os
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Base paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT_DIR / "config.yaml"
ENV_PATH = ROOT_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH)


class Settings:
    def __init__(self, config_path: Path = CONFIG_PATH):
        self._config_path = config_path
        self._data: Dict[str, Any] = {}
        self.reload()

    def reload(self):
        if not self._config_path.exists():
            raise FileNotFoundError(f"Configuration file not found at {self._config_path}")
        with open(self._config_path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}

    # Paths
    @property
    def root_dir(self) -> Path:
        return ROOT_DIR

    @property
    def db_path(self) -> Path:
        p = self._data.get("paths", {}).get("db_path", "data/jobpilot.db")
        return ROOT_DIR / p

    @property
    def master_resume_path(self) -> Path:
        p = self._data.get("paths", {}).get("master_resume_path", "data/master_resume.json")
        return ROOT_DIR / p

    @property
    def resume_output_dir(self) -> Path:
        p = self._data.get("paths", {}).get("resume_output_dir", "output/resumes")
        out = ROOT_DIR / p
        out.mkdir(parents=True, exist_ok=True)
        return out

    @property
    def packets_dir(self) -> Path:
        p = self._data.get("apply_routes", {}).get("packet", {}).get("output_dir", "output/packets")
        out = ROOT_DIR / p
        out.mkdir(parents=True, exist_ok=True)
        return out

    @property
    def answers_path(self) -> Path:
        p = self._data.get("paths", {}).get("answers_path", "data/answers.json")
        return ROOT_DIR / p

    # Profile
    @property
    def user_profile(self) -> Dict[str, Any]:
        return self._data.get("user_profile", {})

    @property
    def user_name(self) -> str:
        return self.user_profile.get("name", "Candidate")

    @property
    def user_email(self) -> str:
        return self.user_profile.get("email", "")

    @property
    def user_phone(self) -> str:
        return self.user_profile.get("phone", "")

    @property
    def target_roles(self) -> List[str]:
        return self.user_profile.get("target_roles", [])

    @property
    def preferred_locations(self) -> List[str]:
        return self.user_profile.get("preferred_locations", [])

    # Search filters
    @property
    def search_filters(self) -> Dict[str, Any]:
        return self._data.get("search_filters", {})

    @property
    def keywords(self) -> List[str]:
        return self.search_filters.get("keywords", [])

    @property
    def excluded_locations(self) -> List[str]:
        return self.search_filters.get("excluded_locations", [])

    @property
    def min_match_score(self) -> float:
        return float(self.search_filters.get("min_match_score", 65))

    # LLM & Gemini
    @property
    def gemini_api_key(self) -> str:
        key = os.getenv("GEMINI_API_KEY", "")
        return key.strip()

    @property
    def gemini_model(self) -> str:
        return self._data.get("gemini_model", "gemini-3.5-flash-lite")

    @property
    def llm_max_requests_per_day(self) -> int:
        return int(self._data.get("llm_limits", {}).get("max_requests_per_day", 250))

    @property
    def llm_max_tokens_per_day(self) -> int:
        return int(self._data.get("llm_limits", {}).get("max_tokens_per_day", 350000))

    @property
    def llm_min_seconds_between_calls(self) -> float:
        return float(self._data.get("llm_limits", {}).get("min_seconds_between_calls", 4.0))

    @property
    def llm_max_input_characters(self) -> int:
        return int(self._data.get("llm_limits", {}).get("max_input_characters", 3000))

    # Email, SMTP & IMAP
    @property
    def smtp_host(self) -> str:
        return os.getenv("SMTP_HOST", "smtp.gmail.com")

    @property
    def smtp_port(self) -> int:
        return int(os.getenv("SMTP_PORT", 465))

    @property
    def imap_host(self) -> str:
        return os.getenv("IMAP_HOST", "imap.gmail.com")

    @property
    def imap_port(self) -> int:
        return int(os.getenv("IMAP_PORT", 993))

    @property
    def smtp_user(self) -> str:
        return (os.getenv("SMTP_USER") or os.getenv("GMAIL_USER") or "").strip()

    @property
    def smtp_password(self) -> str:
        return (os.getenv("SMTP_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD") or "").strip()

    @property
    def sending_config(self) -> Dict[str, Any]:
        return self._data.get("sending", {})

    @property
    def auto_send(self) -> bool:
        return bool(self.sending_config.get("auto_send", False))

    @property
    def daily_send_cap(self) -> int:
        return int(self.sending_config.get("daily_cap", 15))

    @property
    def send_delay_min_seconds(self) -> int:
        return int(self.sending_config.get("delay_min_seconds", 60))

    @property
    def send_delay_max_seconds(self) -> int:
        return int(self.sending_config.get("delay_max_seconds", 180))

    @property
    def sending_hours_start(self) -> int:
        return int(self.sending_config.get("sending_hours_start", 9))

    @property
    def sending_hours_end(self) -> int:
        return int(self.sending_config.get("sending_hours_end", 18))

    @property
    def cooldown_days_per_company(self) -> int:
        return int(self.sending_config.get("cooldown_days_per_company", 30))

    @property
    def followup_days(self) -> int:
        return int(self.sending_config.get("followup_days", 6))

    # Sources & API Keys
    @property
    def sources_config(self) -> Dict[str, Any]:
        return self._data.get("sources", {})

    @property
    def adzuna_app_id(self) -> str:
        return os.getenv("ADZUNA_APP_ID", "").strip()

    @property
    def adzuna_app_key(self) -> str:
        return os.getenv("ADZUNA_APP_KEY", "").strip()

    @property
    def jooble_api_key(self) -> str:
        return os.getenv("JOOBLE_API_KEY", "").strip()

    @property
    def careerjet_affiliate_id(self) -> str:
        return os.getenv("CAREERJET_AFFILIATE_ID", "").strip()

    @property
    def rapidapi_key(self) -> str:
        return os.getenv("RAPIDAPI_KEY", "").strip()

    # Apply routes & styling
    @property
    def apply_routes_config(self) -> Dict[str, Any]:
        return self._data.get("apply_routes", {})

    @property
    def resume_style(self) -> Dict[str, Any]:
        return self._data.get("resume_style", {})

    @property
    def company_discovery_config(self) -> Dict[str, Any]:
        return self._data.get("company_discovery", {})

    @property
    def scrapers_config(self) -> Dict[str, Any]:
        return self._data.get("scrapers", {})

    def fail_fast_check_gemini(self):
        if not self.gemini_api_key or self.gemini_api_key.startswith("your_"):
            raise ValueError(
                "GEMINI_API_KEY is missing or unconfigured in .env! "
                "Please configure a valid Google Gemini API key to run LLM operations."
            )

    def fail_fast_check_smtp(self):
        if not self.smtp_user or not self.smtp_password or self.smtp_password.startswith("your_"):
            raise ValueError(
                "SMTP_USER or SMTP_PASSWORD is not configured in .env! "
                "Cold email sending requires a valid Gmail account and App Password."
            )


settings = Settings()

