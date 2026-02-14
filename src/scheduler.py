"""
Scheduler for running the meeting prep pipeline on a daily schedule.

Uses APScheduler with cron triggers to run the pipeline at a configured
time (default: 8 AM weekdays).

APScheduler overview:
    - BlockingScheduler: Runs in the foreground (blocks the process)
    - CronTrigger: Fires at specific times (like cron on Linux)
    - misfire_grace_time: If the job misses its scheduled time
      (e.g., computer was asleep), run it anyway within this window

Usage:
    scheduler = MeetingPrepScheduler(config, pipeline_func)
    scheduler.start()  # Blocks and runs pipeline at scheduled time
"""

import logging
from typing import Callable

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import SchedulerConfig

logger = logging.getLogger(__name__)


class MeetingPrepScheduler:
    """
    Schedules the daily meeting prep pipeline.

    Uses APScheduler's BlockingScheduler which runs in the foreground.
    The scheduler will:
    1. Wait until the configured time (default 8:00 AM)
    2. Execute the pipeline function
    3. Go back to waiting for the next day

    If the computer was asleep at 8 AM, the job will run when it wakes up
    (within 1 hour grace period).
    """

    def __init__(self, config: SchedulerConfig, pipeline_func: Callable):
        """
        Args:
            config: Scheduler configuration (time, timezone, etc.)
            pipeline_func: The function to call at scheduled time (no args)
        """
        self.config = config
        self.pipeline_func = pipeline_func
        self.scheduler = BlockingScheduler(
            timezone=pytz.timezone(config.timezone)
        )

    def start(self) -> None:
        """
        Start the scheduler. This blocks the current thread.

        The scheduler will run the pipeline at the configured time.
        Press Ctrl+C to stop.
        """
        # Build the cron trigger
        day_of_week = "mon-fri" if self.config.weekdays_only else "*"

        trigger = CronTrigger(
            hour=self.config.run_hour,
            minute=self.config.run_minute,
            day_of_week=day_of_week,
            timezone=pytz.timezone(self.config.timezone),
        )

        # Add the job
        self.scheduler.add_job(
            self.pipeline_func,
            trigger=trigger,
            id="daily_meeting_prep",
            name="Daily Meeting Prep Brief",
            misfire_grace_time=3600,  # Allow up to 1 hour late
        )

        logger.info(
            "Scheduler started. Pipeline will run at %02d:%02d %s (%s)",
            self.config.run_hour,
            self.config.run_minute,
            "weekdays" if self.config.weekdays_only else "daily",
            self.config.timezone,
        )
        logger.info("Press Ctrl+C to stop.")

        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped.")

    def run_once(self) -> None:
        """Run the pipeline once immediately (for testing/manual use)."""
        logger.info("Running pipeline once (immediate)...")
        self.pipeline_func()
