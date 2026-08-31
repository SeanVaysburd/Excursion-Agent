"""Weather gate over synthetic hourly payloads, the rain logic is proven
here regardless of what the live forecast does on demo day."""

from __future__ import annotations

from datetime import datetime

from src import config
from src.tools.weather import WxHour, gate_outdoor


def hour(h: int, temp=70.0, prob=10, precip=0.0, wind=5.0) -> WxHour:
    return WxHour(
        dt=datetime(2026, 9, 5, h, tzinfo=config.TZ),
        temp_f=temp,
        precip_prob=prob,
        precip_in=precip,
        wind_mph=wind,
        evidence_id=f"wx:20260905T{h:02d}",
    )


def test_clean_window_is_not_gated():
    gated, reasons, evidence = gate_outdoor([hour(h) for h in range(6, 14)])
    assert not gated and not reasons and not evidence


def test_rain_probability_gates_and_cites_the_offending_hour():
    hours = [hour(h) for h in range(6, 10)] + [hour(10, prob=config.PRECIP_PROB_GATE)]
    gated, reasons, evidence = gate_outdoor(hours)
    assert gated
    assert "10:00" in reasons[0]
    assert evidence == ["wx:20260905T10"]


def test_each_threshold_gates_independently():
    assert gate_outdoor([hour(7, precip=config.PRECIP_IN_GATE)])[0]
    assert gate_outdoor([hour(7, temp=config.TEMP_MIN_F - 1)])[0]
    assert gate_outdoor([hour(7, temp=config.TEMP_MAX_F + 1)])[0]
    assert gate_outdoor([hour(7, wind=config.WIND_GATE_MPH)])[0]


def test_missing_data_never_gates():
    """An absent forecast is a fallback situation, not evidence of rain."""
    blank = WxHour(
        dt=datetime(2026, 9, 5, 7, tzinfo=config.TZ),
        temp_f=None,
        precip_prob=None,
        precip_in=None,
        wind_mph=None,
        evidence_id="wx:20260905T07",
    )
    gated, _, _ = gate_outdoor([blank])
    assert not gated
