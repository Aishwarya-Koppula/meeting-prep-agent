"""Tests for configuration loading."""

import pytest
import yaml
from pathlib import Path
from src.config import (
    load_config,
    AppConfig,
    GoogleCalendarConfig,
    AnthropicConfig,
    EmailConfig,
    SchedulerConfig,
    FilterConfig,
)


class TestConfigDefaults:
    """Tests for default configuration values."""

    def test_google_defaults(self):
        config = GoogleCalendarConfig()
        assert config.credentials_path == "./credentials.json"
        assert config.token_path == "./token.json"
        assert config.calendar_ids == ["primary"]
        assert config.lookahead_hours == 24

    def test_anthropic_defaults(self):
        config = AnthropicConfig()
        assert config.model == "claude-sonnet-4-20250514"
        assert config.max_tokens == 1024
        assert config.temperature == 0.7

    def test_email_defaults(self):
        config = EmailConfig()
        assert config.smtp_server == "smtp.gmail.com"
        assert config.smtp_port == 587

    def test_scheduler_defaults(self):
        config = SchedulerConfig()
        assert config.run_hour == 8
        assert config.run_minute == 0
        assert config.timezone == "America/New_York"
        assert config.weekdays_only is True

    def test_filter_defaults(self):
        config = FilterConfig()
        assert config.exclude_all_day is True
        assert config.min_duration_minutes == 10
        assert "OOO" in config.exclude_patterns
        assert "Focus Time" in config.exclude_patterns


class TestLoadConfig:
    """Tests for configuration file loading."""

    def test_load_from_yaml(self, tmp_path):
        config_data = {
            "google": {"calendar_ids": ["work@gmail.com", "personal@gmail.com"]},
            "scheduler": {"run_hour": 7, "weekdays_only": False},
            "filters": {"min_duration_minutes": 15},
            "log_level": "DEBUG",
        }
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(str(config_file))

        assert config.google.calendar_ids == ["work@gmail.com", "personal@gmail.com"]
        assert config.scheduler.run_hour == 7
        assert config.scheduler.weekdays_only is False
        assert config.filters.min_duration_minutes == 15
        assert config.log_level == "DEBUG"

    def test_load_missing_config_uses_defaults(self, tmp_path):
        config_file = tmp_path / "nonexistent.yaml"
        config = load_config(str(config_file))

        # Should use all defaults
        assert config.google.calendar_ids == ["primary"]
        assert config.scheduler.run_hour == 8
        assert config.log_level == "INFO"

    def test_load_empty_config_uses_defaults(self, tmp_path):
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        config = load_config(str(config_file))
        assert config.google.calendar_ids == ["primary"]

    def test_partial_config_merges_with_defaults(self, tmp_path):
        config_data = {"scheduler": {"run_hour": 6}}
        config_file = tmp_path / "partial.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(str(config_file))

        # Scheduler hour should be overridden
        assert config.scheduler.run_hour == 6
        # But other scheduler defaults should remain
        assert config.scheduler.run_minute == 0
        assert config.scheduler.weekdays_only is True
        # And other sections should use defaults
        assert config.google.calendar_ids == ["primary"]
