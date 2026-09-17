"""Metric tests against hand-computed answers.

Each contingency case states the table explicitly so the expected values can be
checked by hand rather than against the implementation.
"""

import math
import pytest

from kjyo_backtest.scoring.metrics import (
    Contingency, accuracy, brier_ci, brier_score, brier_skill_score,
    confusion_matrix, contingency, contingency_ci, ifr_or_worse, reliability,
)


def test_contingency_counts():
    f = [True, True, False, False, True]
    o = [True, False, True, False, True]
    c = contingency(f, o)
    assert (c.hits, c.false_alarms, c.misses, c.correct_negs) == (2, 1, 1, 1)
    assert c.n == 5


def test_contingency_metrics_hand_computed():
    # hits=8, false_alarms=2, misses=4, correct_negs=86
    c = Contingency(hits=8, false_alarms=2, misses=4, correct_negs=86)
    assert c.pod == pytest.approx(8 / 12)          # 0.6667
    assert c.far == pytest.approx(2 / 10)          # 0.20
    assert c.csi == pytest.approx(8 / 14)          # 0.5714
    assert c.bias == pytest.approx(10 / 12)        # 0.8333
    assert c.base_rate == pytest.approx(12 / 100)


def test_perfect_and_useless_forecasts():
    perfect = Contingency(hits=10, false_alarms=0, misses=0, correct_negs=90)
    assert (perfect.pod, perfect.far, perfect.csi, perfect.bias) == (1.0, 0.0, 1.0, 1.0)

    # Never forecasts the event: POD and CSI are 0, FAR is undefined (no yes fcsts).
    never = Contingency(hits=0, false_alarms=0, misses=10, correct_negs=90)
    assert never.pod == 0.0
    assert never.csi == 0.0
    assert never.far is None
    assert never.bias == 0.0


def test_undefined_metrics_return_none_not_zero():
    # No observed events: POD, bias and base-rate-dependent metrics are undefined.
    c = Contingency(hits=0, false_alarms=5, misses=0, correct_negs=95)
    assert c.pod is None
    assert c.bias is None
    assert c.far == 1.0
    assert c.csi == 0.0
    assert contingency([], []).n == 0


def test_contingency_length_mismatch_raises():
    with pytest.raises(ValueError):
        contingency([True], [True, False])


def test_brier_score_known_values():
    # Perfect deterministic forecasts.
    assert brier_score([1.0, 0.0, 1.0], [True, False, True]) == pytest.approx(0.0)
    # Always 50%: every term is 0.25.
    assert brier_score([0.5] * 4, [True, False, True, False]) == pytest.approx(0.25)
    # Worst possible.
    assert brier_score([0.0, 1.0], [True, False]) == pytest.approx(1.0)


def test_brier_accepts_percentages_and_fractions():
    assert brier_score([50, 50], [True, False]) == pytest.approx(0.25)
    assert brier_score([0.5, 0.5], [True, False]) == pytest.approx(0.25)


def test_brier_clamps_out_of_range():
    assert brier_score([150], [True]) == pytest.approx(0.0)
    assert brier_score([-10], [False]) == pytest.approx(0.0)


def test_brier_skill_vs_climatology():
    obs = [True] * 2 + [False] * 8          # climatological base rate 0.2
    # A forecast equal to climatology has zero skill.
    assert brier_skill_score([0.2] * 10, obs) == pytest.approx(0.0, abs=1e-12)
    # A perfect forecast has skill 1.
    assert brier_skill_score([1.0] * 2 + [0.0] * 8, obs) == pytest.approx(1.0)
    # An inverted forecast is worse than climatology.
    assert brier_skill_score([0.0] * 2 + [1.0] * 8, obs) < 0


def test_reliability_bins_are_calibrated_when_forecasts_are():
    # 100 samples at 30%, of which exactly 30 verify -> perfectly calibrated bin.
    probs = [0.3] * 100
    obs = [True] * 30 + [False] * 70
    bins = reliability(probs, obs, bins=10)
    hit = [b for b in bins if b.n][0]
    assert hit.n == 100
    assert hit.mean_forecast == pytest.approx(0.3)
    assert hit.observed_freq == pytest.approx(0.3)


def test_reliability_top_bin_includes_certainty():
    bins = reliability([1.0], [True], bins=10)
    assert bins[-1].n == 1
    assert sum(b.n for b in bins) == 1


def test_reliability_empty_bins_report_none_not_zero():
    bins = reliability([0.05], [False], bins=10)
    assert bins[0].n == 1
    assert all(b.observed_freq is None for b in bins[1:])


def test_bootstrap_ci_brackets_the_point_estimate():
    f = [True] * 30 + [False] * 70
    o = [True] * 20 + [False] * 10 + [True] * 10 + [False] * 60
    point = contingency(f, o).pod
    lo, hi = contingency_ci(f, o, "pod", n_boot=500)
    assert lo is not None and hi is not None
    assert lo <= point <= hi
    assert 0.0 <= lo <= hi <= 1.0


def test_bootstrap_ci_is_deterministic_for_a_seed():
    f, o = [True, False] * 25, [True, True, False, False] * 12 + [True, False]
    assert contingency_ci(f, o, "csi", n_boot=200, seed=7) == \
           contingency_ci(f, o, "csi", n_boot=200, seed=7)


def test_bootstrap_ci_empty_input():
    assert contingency_ci([], [], "pod") == (None, None)
    assert brier_ci([], []) == (None, None)


def test_brier_ci_brackets_point_estimate():
    probs = [0.2] * 50 + [0.8] * 50
    obs = [False] * 40 + [True] * 10 + [True] * 40 + [False] * 10
    point = brier_score(probs, obs)
    lo, hi = brier_ci(probs, obs, n_boot=500)
    assert lo <= point <= hi


def test_confusion_matrix_and_accuracy():
    f = ["VFR", "VFR", "MVFR", "IFR", "LIFR"]
    o = ["VFR", "MVFR", "MVFR", "LIFR", "LIFR"]
    m = confusion_matrix(f, o)
    assert m["VFR"]["VFR"] == 1
    assert m["MVFR"]["VFR"] == 1      # observed MVFR, forecast VFR
    assert m["MVFR"]["MVFR"] == 1
    assert m["LIFR"]["IFR"] == 1
    assert m["LIFR"]["LIFR"] == 1
    assert accuracy(m) == pytest.approx(3 / 5)


def test_confusion_matrix_ignores_unknown_labels():
    m = confusion_matrix(["VFR", "BOGUS"], ["VFR", "VFR"])
    assert sum(v for row in m.values() for v in row.values()) == 1


def test_accuracy_of_empty_matrix_is_none():
    assert accuracy(confusion_matrix([], [])) is None


def test_ifr_or_worse():
    assert ifr_or_worse("IFR") is True
    assert ifr_or_worse("LIFR") is True
    assert ifr_or_worse("MVFR") is False
    assert ifr_or_worse("VFR") is False
    assert ifr_or_worse(None) is None
