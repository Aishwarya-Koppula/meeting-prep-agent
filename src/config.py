"""
Configuration management for the Meeting Prep Agent.

Two-layer config strategy:
  1. .env file     -> secrets (API keys, passwords) - NEVER committed to git
  2. config.yaml   -> preferences (schedule, filters) - safe to commit

pydantic-settings automatically reads from .env files and environment variables.
YAML is loaded manually and merged in.

Usage:
    from src.config import load_config
    config = load_config()  # loads .env + config.yaml
    print(config.anthropic.api_key)  # from .env
    print(config.scheduler.run_hour)  # from config.yaml
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
from typing import List, Optional
import yaml


class GoogleCalendarConfig(BaseSettings):
    """Google Calendar API configuration."""
    enabled: bool = True
    credentials_path: str = "./credentials.json"
    token_path: str = "./token.json"
    scopes: List[str] = ["https://www.googleapis.com/auth/calendar.readonly"]
    calendar_ids: List[str] = ["primary"]
    lookahead_hours: int = 24  # How far ahead to fetch events

    model_config = {"env_prefix": "GOOGLE_"}


class OutlookConfig(BaseSettings):
    """Microsoft Outlook + Teams configuration (via Microsoft Graph API)."""
    enabled: bool = False
    client_id: str = ""  # Azure App Registration client ID
    token_path: str = "./outlook_token.json"
    scopes: List[str] = [
        "Calendars.Read",
        "OnlineMeetings.Read",
        "offline_access",
    ]
    lookahead_hours: int = 24

    model_config = {"env_prefix": "OUTLOOK_"}


class AnthropicConfig(BaseSettings):
    """Claude AI API configuration."""
    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 1024
    temperature: float = 0.7

    model_config = {"env_prefix": "ANTHROPIC_"}


class EmailConfig(BaseSettings):
    """Email delivery configuration (Gmail SMTP)."""
    sender: str = ""
    app_password: str = ""
    recipient: str = ""
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    subject_template: str = "Your Meeting Prep Brief - {date}"

    model_config = {"env_prefix": "EMAIL_"}


class SchedulerConfig(BaseSettings):
    """Scheduling configuration."""
    run_hour: int = 8      # Hour to run (24h format)
    run_minute: int = 0    # Minute to run
    timezone: str = "America/New_York"
    weekdays_only: bool = True  # Skip weekends?


class IcalConfig(BaseSettings):
    """iCal / ICS subscription feeds (UniTime, course schedules, etc.)."""
    enabled: bool = True
    lookahead_hours: int = 24
    sources_path: str = "./ical_sources.json"

    model_config = {"env_prefix": "ICAL_"}


class FilterConfig(BaseSettings):
    """Event filtering rules."""
    exclude_all_day: bool = True
    exclude_cancelled: bool = True
    min_duration_minutes: int = 10
    min_attendees: int = 0
    exclude_patterns: List[str] = [
        "OOO",
        "Out of Office",
        "Block",
        "Focus Time",
        "Lunch",
        "Break",
    ]


class AppConfig(BaseSettings):
    """
    Root configuration that combines all sub-configs.

    Load order (later overrides earlier):
    1. Default values defined here
    2. config.yaml file
    3. .env file
    4. Environment variables
    """
    google: GoogleCalendarConfig = Field(default_factory=GoogleCalendarConfig)
    outlook: OutlookConfig = Field(default_factory=OutlookConfig)
    ical: IcalConfig = Field(default_factory=IcalConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    log_level: str = "INFO"
    timezone: str = "America/New_York"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """
    Load configuration from YAML file + .env overrides.

    How it works:
    1. Read config.yaml for non-secret preferences
    2. pydantic-settings automatically reads .env for secrets
    3. Environment variables override everything (useful for CI/CD)

    Args:
        config_path: Path to YAML config file (default: config.yaml)

    Returns:
        AppConfig with all settings merged
    """
    yaml_data = {}
    config_file = Path(config_path)

    if config_file.exists():
        with open(config_file) as f:
            yaml_data = yaml.safe_load(f) or {}

    # Build sub-configs from YAML data, letting .env override secrets
    google_data = yaml_data.get("google", {})
    outlook_data = yaml_data.get("outlook", {})
    ical_data = yaml_data.get("ical", {})
    anthropic_data = yaml_data.get("anthropic", {})
    email_data = yaml_data.get("email", {})
    scheduler_data = yaml_data.get("scheduler", {})
    filter_data = yaml_data.get("filters", {})

    config = AppConfig(
        google=GoogleCalendarConfig(**google_data),
        outlook=OutlookConfig(**outlook_data),
        ical=IcalConfig(**ical_data),
        anthropic=AnthropicConfig(**anthropic_data),
        email=EmailConfig(**email_data),
        scheduler=SchedulerConfig(**scheduler_data),
        filters=FilterConfig(**filter_data),
        log_level=yaml_data.get("log_level", "INFO"),
        timezone=yaml_data.get("timezone", "America/New_York"),
    )

    return config
