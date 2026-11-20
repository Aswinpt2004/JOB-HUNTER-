import os
from pathlib import Path
from typing import Any, Dict, List
import yaml
from dotenv import load_dotenv

# Base paths
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.yaml"
ENV_PATH = ROOT_DIR / ".env"

# Load environment variables
load_dotenv(dotenv_path=ENV_PATH)


VALID_GEMINI_MODELS = {"gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-pro"}


class Config:
    def __init__(self, config_file: Path = CONFIG_PATH):
        self.config_file = config_file
        self.data: Dict[str, Any] = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_file.exists():
            return {}
        with open(self.config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def reload(self) -> None:
        self.data = self._load_config()

    # User Profile
    @property
    def user_profile(self) -> Dict[str, Any]:
        return self.data.get("user_profile", {})

    @property
    def candidate_name(self) -> str:
        return self.user_profile.get("name", "Candidate")

    @property
    def candidate_email(self) -> str:
        return os.getenv("GMAIL_USER") or self.user_profile.get("email", "")

    @property
    def target_roles(self) -> List[str]:
        return self.user_profile.get("target_roles", [])

    @property
    def preferred_locations(self) -> List[str]:
        return self.user_profile.get("preferred_locations", [])

    # Search & Matching Filters
    @property
    def keywords(self) -> List[str]:
        return self.data.get("search_filters", {}).get("keywords", [])

    @property
    def min_match_score(self) -> float:
        return float(self.data.get("search_filters", {}).get("min_match_score", 65.0))

    @property
    def excluded_locations(self) -> List[str]:
        return self.data.get("search_filters", {}).get("excluded_locations", [])

    # LLM Quota & Token Limits
    @property
    def llm_limits(self) -> Dict[str, Any]:
        return self.data.get("llm_limits", {})

    @property
    def llm_max_requests_per_day(self) -> int:
        return int(self.llm_limits.get("max_requests_per_day", 250))

    @property
    def llm_max_tokens_per_day(self) -> int:
        return int(self.llm_limits.get("max_tokens_per_day", 350000))

    @property
    def llm_min_seconds_between_calls(self) -> float:
        return float(self.llm_limits.get("min_seconds_between_calls", 4.0))

    @property
    def llm_max_input_characters(self) -> int:
        return int(self.llm_limits.get("max_input_characters", 3000))

    # Scraper settings
    @property
    def scrapers(self) -> Dict[str, Any]:
        return self.data.get("scrapers", {})

    @property
    def request_delay_min(self) -> int:
        return int(self.scrapers.get("request_delay_min_seconds", 2))

    @property
    def request_delay_max(self) -> int:
        return int(self.scrapers.get("request_delay_max_seconds", 5))

    @property
    def user_agent(self) -> str:
        return self.scrapers.get("user_agent", "JobPilot/1.0 (+https://github.com/jobpilot/bot)")

    @property
    def greenhouse_boards(self) -> List[str]:
        return self.scrapers.get("greenhouse_boards", [])

    @property
    def lever_boards(self) -> List[str]:
        return self.scrapers.get("lever_boards", [])

    @property
    def remotive_categories(self) -> List[str]:
        return self.scrapers.get("remotive_categories", ["software-dev"])

    @property
    def career_pages(self) -> List[Dict[str, str]]:
        return self.scrapers.get("career_pages", [])

    # Sending settings
    @property
    def sending(self) -> Dict[str, Any]:
        return self.data.get("sending", {})

    @property
    def daily_cap(self) -> int:
        return int(self.sending.get("daily_cap", 15))

    @property
    def send_delay_min(self) -> int:
        return int(self.sending.get("delay_min_seconds", 60))

    @property
    def send_delay_max(self) -> int:
        return int(self.sending.get("delay_max_seconds", 180))

    @property
    def sending_hours_start(self) -> int:
        return int(self.sending.get("sending_hours_start", 9))

    @property
    def sending_hours_end(self) -> int:
        return int(self.sending.get("sending_hours_end", 18))

    @property
    def cooldown_days_per_company(self) -> int:
        return int(self.sending.get("cooldown_days_per_company", 30))

    @property
    def followup_days(self) -> int:
        return int(self.sending.get("followup_days", 6))

    # Paths
    @property
    def db_path(self) -> Path:
        rel = self.data.get("paths", {}).get("db_path", "data/jobpilot.db")
        path = ROOT_DIR / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def master_resume_path(self) -> Path:
        rel = self.data.get("paths", {}).get("master_resume_path", "data/master_resume.json")
        path = ROOT_DIR / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def resume_output_dir(self) -> Path:
        rel = self.data.get("paths", {}).get("resume_output_dir", "output/resumes")
        path = ROOT_DIR / rel
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def templates_dir(self) -> Path:
        rel = self.data.get("paths", {}).get("templates_dir", "templates")
        path = ROOT_DIR / rel
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def auto_send_enabled(self) -> bool:
        return bool(self.sending.get("auto_send", False))

    @property
    def resume_style(self) -> Dict[str, Any]:
        return self.data.get("resume_style", {})

    # Company Discovery & Speculative Outreach
    @property
    def company_discovery(self) -> Dict[str, Any]:
        return self.data.get("company_discovery", {})

    @property
    def min_company_employees(self) -> int:
        return int(self.company_discovery.get("min_employees", 20))

    @property
    def preferred_company_employees(self) -> int:
        return int(self.company_discovery.get("preferred_employees", 50))

    @property
    def company_enabled_sources(self) -> Dict[str, bool]:
        return self.company_discovery.get("enabled_sources", {
            "kerala_parks": True,
            "ats_boards": True,
            "github_orgs": True,
            "search_queries": True,
            "seed_list": True
        })

    @property
    def seed_companies(self) -> List[Dict[str, Any]]:
        return self.company_discovery.get("seed_companies", [])

    # API Keys & Secrets
    @property
    def gemini_api_key(self) -> str:
        return os.getenv("GEMINI_API_KEY", "")

    @property
    def gemini_model(self) -> str:
        return self.data.get("gemini_model") or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    @property
    def outreach(self) -> Dict[str, Any]:
        return self.data.get("outreach", {})

    @property
    def require_contact_email(self) -> bool:
        return bool(self.outreach.get("require_contact_email", True))

    @property
    def gmail_user(self) -> str:
        return os.getenv("GMAIL_USER", "")

    @property
    def gmail_app_password(self) -> str:
        return os.getenv("GMAIL_APP_PASSWORD", "")

    def validate_production_environment(self) -> List[str]:
        """
        Validates presence and format of all required production credentials and files.
        Returns a list of error messages (empty if completely valid).
        """
        errors = []
        if not ENV_PATH.exists():
            errors.append("Missing .env file at project root. Create .env with GEMINI_API_KEY, GMAIL_USER, and GMAIL_APP_PASSWORD.")

        if not self.gemini_api_key or self.gemini_api_key.startswith("your_"):
            errors.append("GEMINI_API_KEY is not set or contains default template value in .env. Set a valid Gemini API key.")

        if self.gemini_model not in VALID_GEMINI_MODELS:
            errors.append(f"Configured GEMINI_MODEL '{self.gemini_model}' is invalid. Allowed production models: {sorted(list(VALID_GEMINI_MODELS))}.")

        gmail_u = self.gmail_user.strip().strip("\"'")
        if not gmail_u or "@" not in gmail_u or gmail_u.startswith("your_"):
            errors.append("GMAIL_USER is not set or invalid in .env. Set your real Gmail address.")

        gmail_pw = self.gmail_app_password.replace(" ", "").strip("\"'")
        if not gmail_pw or len(gmail_pw) != 16 or gmail_pw.startswith("your_"):
            errors.append("GMAIL_APP_PASSWORD is not set or not 16 characters in .env. Generate a 16-character Google App Password.")

        if not self.master_resume_path.exists():
            errors.append(f"Master resume file not found at {self.master_resume_path}.")

        if not self.config_file.exists():
            errors.append(f"Configuration file not found at {self.config_file}.")

        return errors

    def require_production_environment(self) -> None:
        """Fails fast by raising RuntimeError if any production credential or file is missing."""
        errors = self.validate_production_environment()
        if errors:
            msg = "Production Environment Validation Failed:\n" + "\n".join(f"  • {e}" for e in errors)
            raise RuntimeError(msg)


# Global singleton
settings = Config()

