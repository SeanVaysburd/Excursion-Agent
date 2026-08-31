"""ICS hard/soft parsing and free-window computation over the synthetic
sample-week structure (generated in-test, no committed-file coupling)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from scripts.make_sample_calendar import build_fully_blocked, build_week, monday_of
from src import config
from src.tools.base import RunContext
from src.tools.calendar_tool import free_windows, parse_blocks

WEEK = monday_of(date(2026, 9, 7))  # a fixed Monday


@pytest.fixture()
def calendar_path(tmp_path):
    path = tmp_path / "calendar.ics"
    path.write_bytes(build_week(WEEK).to_ical())
    return path


def test_soft_detection_via_summary_and_x_soft(calendar_path):
    ctx = RunContext(scenario="test")
    blocks = parse_blocks(ctx, calendar_path)
    by_summary = {b.summary: b for b in blocks}
    assert by_summary["Brunch with Alex (tentative)"].soft
    assert by_summary["Volunteer shift"].soft  # X-SOFT:true, vText compare
    assert not by_summary["Family afternoon"].soft
    assert all(b.start.tzinfo is not None for b in blocks), "naive datetime leaked"


def test_saturday_matches_s1_window(calendar_path):
    ctx = RunContext(scenario="test")
    saturday = WEEK + timedelta(days=5)
    windows = free_windows(ctx, calendar_path, saturday)
    assert [w.label for w in windows] == ["06:00-14:00", "20:00-22:00"]
    s1 = windows[0]
    # The tentative brunch overlaps the S1 window as a SOFT flag, not a cut.
    assert [b.summary for b in s1.soft_conflicts] == ["Brunch with Alex (tentative)"]


def test_workday_windows_cut_by_hard_blocks(calendar_path):
    ctx = RunContext(scenario="test")
    monday = WEEK
    windows = free_windows(ctx, calendar_path, monday)
    assert [w.label for w in windows] == ["06:00-09:00", "17:30-22:00"]


def test_tuesday_evening_class_is_merged_hard(calendar_path):
    ctx = RunContext(scenario="test")
    tuesday = WEEK + timedelta(days=1)
    windows = free_windows(ctx, calendar_path, tuesday)
    assert [w.label for w in windows] == ["06:00-09:00", "20:00-22:00"]
    # 17:30-18:00 is a 30-minute sliver: below MIN_WINDOW_MINUTES, discarded.
    assert all(w.minutes >= config.MIN_WINDOW_MINUTES for w in windows)


def test_fully_blocked_week_yields_zero_windows(tmp_path):
    path = tmp_path / "blocked.ics"
    path.write_bytes(build_fully_blocked(WEEK).to_ical())
    ctx = RunContext(scenario="test")
    for offset in range(7):
        assert free_windows(ctx, path, WEEK + timedelta(days=offset)) == []


def test_overlapping_hard_blocks_are_merged(tmp_path):
    from icalendar import Calendar

    from scripts.make_sample_calendar import _event

    calendar = Calendar()
    calendar.add("PRODID", "test")
    calendar.add("VERSION", "2.0")
    from datetime import time

    day = WEEK
    calendar.add_component(_event(day, time(9, 0), time(12, 0), "A"))
    calendar.add_component(_event(day, time(11, 0), time(15, 0), "B"))  # overlaps A
    path = tmp_path / "overlap.ics"
    path.write_bytes(calendar.to_ical())
    windows = free_windows(RunContext(scenario="test"), path, day)
    assert [w.label for w in windows] == ["06:00-09:00", "15:00-22:00"]
