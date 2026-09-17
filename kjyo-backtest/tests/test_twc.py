import datetime as dt
import json
import pathlib

import pytest

from kjyo_backtest.collect.twc import (
    build_url, parse_daily, parse_hourly, response_schema_hash, thunder_from_phrase, _redact,
)

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "twc_daily_sample.json"
TZ = "America/New_York"
PULLED = dt.datetime(2025, 7, 27, 21, 15, tzinfo=dt.timezone.utc)   # 5:15pm EDT


@pytest.fixture
def daily():
    return json.loads(FIXTURE.read_text())


def test_thunder_phrase_detection():
    assert thunder_from_phrase("Scattered Thunderstorms") is True
    assert thunder_from_phrase("Strong Storms") is True
    assert thunder_from_phrase("Isolated T-Storms") is True
    assert thunder_from_phrase("Partly Cloudy") is False
    assert thunder_from_phrase("Rain Showers") is False
    # "Storm" alone must not trigger: snow and wind storms are not thunder.
    assert thunder_from_phrase("Snow Storm") is False
    assert thunder_from_phrase(None) is None
    assert thunder_from_phrase("") is None


def test_parse_daily_skips_null_daypart(daily):
    rows, diag = parse_daily(daily, PULLED, TZ)
    # 6 slots, first is null (after 3pm local) -> 5 parsed.
    assert diag["n_dayparts"] == 6
    assert diag["n_null_dayparts"] == 1
    assert len(rows) == 5
    assert not diag["missing_fields"]


def test_parse_daily_alternates_day_night(daily):
    rows, _ = parse_daily(daily, PULLED, TZ)
    assert [r.daypart for r in rows] == ["night", "day", "night", "day", "night"]


def test_parse_daily_target_dates_advance(daily):
    rows, _ = parse_daily(daily, PULLED, TZ)
    # The nulled slot was today's day period; tonight still belongs to today.
    assert rows[0].local_date == dt.date(2025, 7, 27)
    assert rows[1].local_date == dt.date(2025, 7, 28)
    assert rows[2].local_date == dt.date(2025, 7, 28)


def test_parse_daily_lead_times(daily):
    rows, _ = parse_daily(daily, PULLED, TZ)
    tonight = rows[0]
    # Pulled 21:15Z, night starts 19:00 EDT = 23:00Z -> 1.75 h lead.
    assert tonight.lead_hours == pytest.approx(1.75)
    assert tonight.lead_day == 0
    assert rows[1].lead_day == 1


def test_parse_daily_thunder_signals_scored_separately(daily):
    rows, _ = parse_daily(daily, PULLED, TZ)
    tonight = rows[0]
    assert tonight.thunder_index == 2
    assert tonight.thunder_by_index is True
    assert tonight.thunder_by_phrase is True
    clear = rows[-1]
    assert clear.thunder_by_index is False
    assert clear.thunder_by_phrase is False


def test_parse_daily_records_icon_phrase_pairs(daily):
    _, diag = parse_daily(daily, PULLED, TZ)
    # Mapping is learned from data, not hard-coded.
    assert diag["icon_phrase_pairs"]["47"] == "Scattered Thunderstorms"
    assert diag["icon_phrase_pairs"]["31"] == "Clear"


def test_parse_daily_tolerates_missing_fields():
    payload = {"daypart": [{"dayOrNight": ["D", "N"], "wxPhraseLong": ["Sunny", "Clear"]}]}
    rows, diag = parse_daily(payload, PULLED, TZ)
    assert len(rows) == 2
    assert "thunderIndex" in diag["missing_fields"]
    assert rows[0].thunder_index is None
    assert rows[0].thunder_by_index is None      # unknown, not False


def test_parse_daily_empty_payload():
    rows, diag = parse_daily({}, PULLED, TZ)
    assert rows == [] and diag["n_dayparts"] == 0


def test_parse_hourly_basic():
    payload = {
        "validTimeUtc": [1753650000, 1753653600],
        "iconCode": [47, 30],
        "wxPhraseLong": ["Thunderstorms", "Partly Cloudy"],
        "precipChance": [70, 10],
        "temperature": [78, 75],
        "visibility": [4.0, 10.0],
    }
    rows, diag = parse_hourly(payload, PULLED)
    assert len(rows) == 2
    assert rows[0].thunder_by_phrase is True
    assert rows[0].visibility_sm == 4.0
    # TWC v3 hourly has no ceiling; the parser must report that rather than guess.
    assert diag["ceiling_key"] is None
    assert rows[0].ceiling_ft is None
    assert "temperatureDewPoint" in diag["missing_fields"]


def test_api_key_is_redacted_from_stored_url():
    url = build_url("/v3/wx/forecast/daily/15day", 39.078, -77.5575, "SECRET123")
    assert "SECRET123" in url                    # the real request carries it
    assert "SECRET123" not in _redact(url)       # what we store does not
    assert "apiKey=REDACTED" in _redact(url)


def test_schema_hash_ignores_values_but_catches_shape_changes(daily):
    h1 = response_schema_hash(daily)
    changed_values = json.loads(FIXTURE.read_text())
    changed_values["daypart"][0]["precipChance"] = [None, 99, 99, 99, 99, 99]
    assert response_schema_hash(changed_values) == h1

    changed_shape = json.loads(FIXTURE.read_text())
    changed_shape["daypart"][0]["newThunderField"] = [1, 2, 3]
    assert response_schema_hash(changed_shape) != h1
