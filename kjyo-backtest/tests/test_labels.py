import datetime as dt
import pytest

from kjyo_backtest.scoring.labels import (
    CONVECTIVE, NO_PRECIP, STRATIFORM, LightningHour, MrmsHour,
    hours_in_period, precip_class, precip_observed, thunder_observed,
)

H = lambda n, f5=0, f10=0, f20=0, complete=True: LightningHour(
    dt.datetime(2025, 7, 27, n, tzinfo=dt.timezone.utc), f5, f10, f20, complete)
M = lambda n, q=None, conv=0, strat=0, samples=6: MrmsHour(
    dt.datetime(2025, 7, 27, n, tzinfo=dt.timezone.utc), q, conv, strat, samples)


def test_thunder_detected_at_primary_radius():
    assert thunder_observed([H(3, f10=5), H(4)], radius_nm=10.0) is True


def test_thunder_radius_matters():
    # Flashes at 20 nm only: thunder at 20 nm, not at 10 nm. This is the
    # "LTG DSNT" case that GLM and METAR should agree on.
    hours = [H(21, f5=0, f10=0, f20=12)]
    assert thunder_observed(hours, radius_nm=20.0) is True
    assert thunder_observed(hours, radius_nm=10.0) is False
    assert thunder_observed(hours, radius_nm=5.0) is False


def test_no_thunder_when_all_hours_complete_and_empty():
    assert thunder_observed([H(1), H(2), H(3)]) is False


def test_incomplete_hours_cannot_prove_absence():
    assert thunder_observed([H(1), H(2, complete=False)]) is None


def test_incomplete_hour_can_still_prove_presence():
    assert thunder_observed([H(1, f10=3, complete=False)]) is True


def test_thunder_with_no_hours_is_unknown():
    assert thunder_observed([]) is None


def test_precip_threshold():
    assert precip_observed([M(1, 0.0), M(2, 0.02)]) is True
    assert precip_observed([M(1, 0.0), M(2, 0.005)]) is False
    assert precip_observed([M(1, 0.01)]) is True          # boundary is inclusive
    assert precip_observed([]) is None
    assert precip_observed([M(1, None)]) is None


def test_partial_precip_data_cannot_prove_absence():
    assert precip_observed([M(1, 0.0), M(2, None)]) is None


def test_precip_class_convective():
    assert precip_class([M(4, 0.9, conv=5)], [H(4, f10=600)]) == CONVECTIVE


def test_precip_class_stratiform_requires_no_convective_flag_and_no_lightning():
    assert precip_class([M(12, 0.15, conv=0, strat=6)], [H(12)]) == STRATIFORM


def test_precip_with_lightning_but_no_convective_flag_is_excluded():
    # Ambiguous: not convective by MRMS, not stratiform by definition.
    assert precip_class([M(12, 0.15, conv=0, strat=6)], [H(12, f10=4)]) is None


def test_precip_class_none():
    assert precip_class([M(12, 0.0)], [H(12)]) == NO_PRECIP


def test_precip_class_unknown_when_qpe_missing():
    assert precip_class([M(12, None)], [H(12)]) is None


def test_hours_in_period_is_half_open():
    hours = [H(n) for n in range(24)]
    start = dt.datetime(2025, 7, 27, 11, tzinfo=dt.timezone.utc)
    end = dt.datetime(2025, 7, 27, 23, tzinfo=dt.timezone.utc)
    got = hours_in_period(hours, start, end)
    assert len(got) == 12
    assert got[0].hour_utc.hour == 11 and got[-1].hour_utc.hour == 22
