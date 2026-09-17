"""Verification metrics for the backtest.

Pure functions over plain sequences: no database, no config, no I/O. That keeps
them testable against hand-built tables with known answers, which is what the
brief's Phase 3 acceptance asks for.

Every metric returns None rather than raising when its denominator is zero. A
lead time with no observed thunder has an undefined POD; reporting None and a
sample count is honest, reporting 0.0 is not.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, asdict

Number = float | int


@dataclass(frozen=True)
class Contingency:
    """A 2x2 verification table.

    hits            forecast yes, observed yes
    false_alarms    forecast yes, observed no
    misses          forecast no,  observed yes
    correct_negs    forecast no,  observed no
    """

    hits: int = 0
    false_alarms: int = 0
    misses: int = 0
    correct_negs: int = 0

    @property
    def n(self) -> int:
        return self.hits + self.false_alarms + self.misses + self.correct_negs

    @property
    def observed_yes(self) -> int:
        return self.hits + self.misses

    @property
    def forecast_yes(self) -> int:
        return self.hits + self.false_alarms

    @property
    def pod(self) -> float | None:
        """Probability of detection: of the events that happened, how many were forecast."""
        d = self.observed_yes
        return self.hits / d if d else None

    @property
    def far(self) -> float | None:
        """False alarm ratio: of the yes forecasts, how many did not verify."""
        d = self.forecast_yes
        return self.false_alarms / d if d else None

    @property
    def csi(self) -> float | None:
        """Critical success index -- hits over everything except correct negatives."""
        d = self.hits + self.misses + self.false_alarms
        return self.hits / d if d else None

    @property
    def bias(self) -> float | None:
        """Frequency bias: >1 over-forecasts the event, <1 under-forecasts it."""
        d = self.observed_yes
        return self.forecast_yes / d if d else None

    @property
    def base_rate(self) -> float | None:
        return self.observed_yes / self.n if self.n else None

    def as_dict(self) -> dict:
        d = asdict(self)
        d.update(n=self.n, pod=self.pod, far=self.far, csi=self.csi,
                 bias=self.bias, base_rate=self.base_rate)
        return d


def contingency(forecast: Sequence[bool], observed: Sequence[bool]) -> Contingency:
    if len(forecast) != len(observed):
        raise ValueError(f"length mismatch: {len(forecast)} forecasts, {len(observed)} obs")
    h = fa = m = cn = 0
    for f, o in zip(forecast, observed):
        if f and o:
            h += 1
        elif f and not o:
            fa += 1
        elif (not f) and o:
            m += 1
        else:
            cn += 1
    return Contingency(h, fa, m, cn)


def brier_score(probs: Sequence[Number], observed: Sequence[bool]) -> float | None:
    """Mean squared error of probability forecasts. Lower is better; 0 is perfect.

    `probs` may be given as percentages (0-100) or fractions (0-1); values above
    1 are treated as percentages.
    """
    if len(probs) != len(observed):
        raise ValueError("length mismatch")
    if not probs:
        return None
    total = 0.0
    for p, o in zip(probs, observed):
        pf = _as_fraction(p)
        total += (pf - (1.0 if o else 0.0)) ** 2
    return total / len(probs)


def _as_fraction(p: Number) -> float:
    pf = float(p)
    if pf > 1.0:
        pf /= 100.0
    return min(max(pf, 0.0), 1.0)


def brier_skill_score(probs: Sequence[Number], observed: Sequence[bool],
                      reference: Sequence[Number] | None = None) -> float | None:
    """Skill against a reference forecast; climatology is used when none is given.

    1.0 is perfect, 0.0 is no better than the reference, negative is worse.
    """
    bs = brier_score(probs, observed)
    if bs is None:
        return None
    if reference is None:
        base = sum(1 for o in observed if o) / len(observed)
        ref_bs = brier_score([base] * len(observed), observed)
    else:
        ref_bs = brier_score(reference, observed)
    if not ref_bs:
        return None
    return 1.0 - bs / ref_bs


@dataclass(frozen=True)
class ReliabilityBin:
    lower: float
    upper: float
    n: int
    mean_forecast: float | None
    observed_freq: float | None


def reliability(probs: Sequence[Number], observed: Sequence[bool],
                bins: int = 10) -> list[ReliabilityBin]:
    """Bin probability forecasts and report the observed frequency in each bin.

    A well-calibrated forecast has observed_freq ~= mean_forecast in every bin.
    The top bin is closed on the right so a 100% forecast lands in it.
    """
    edges = [i / bins for i in range(bins + 1)]
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for p, o in zip(probs, observed):
        pf = _as_fraction(p)
        idx = min(int(pf * bins), bins - 1)
        buckets[idx].append((pf, bool(o)))
    out = []
    for i, bucket in enumerate(buckets):
        n = len(bucket)
        out.append(ReliabilityBin(
            lower=edges[i], upper=edges[i + 1], n=n,
            mean_forecast=(sum(p for p, _ in bucket) / n) if n else None,
            observed_freq=(sum(1 for _, o in bucket if o) / n) if n else None,
        ))
    return out


def bootstrap_ci(values: Sequence, statistic, n_boot: int = 2000,
                 alpha: float = 0.05, seed: int = 20260917
                 ) -> tuple[float | None, float | None]:
    """Percentile bootstrap CI for a statistic over paired samples.

    `values` is a sequence of samples (usually (forecast, observed) tuples) and
    `statistic` maps a resample to a number or None. Resamples where the
    statistic is undefined are skipped rather than counted as zero, so a CI is
    only reported when enough resamples were computable.
    """
    n = len(values)
    if n == 0:
        return (None, None)
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        s = statistic(sample)
        if s is not None and not (isinstance(s, float) and math.isnan(s)):
            stats.append(float(s))
    if len(stats) < max(20, n_boot // 20):
        return (None, None)
    stats.sort()
    lo = stats[max(int(alpha / 2 * len(stats)) - 1, 0)]
    hi = stats[min(int((1 - alpha / 2) * len(stats)), len(stats) - 1)]
    return (lo, hi)


def contingency_ci(forecast: Sequence[bool], observed: Sequence[bool], metric: str,
                   n_boot: int = 2000, alpha: float = 0.05, seed: int = 20260917):
    """Bootstrap CI for one contingency metric ('pod', 'far', 'csi', 'bias')."""
    pairs = list(zip(forecast, observed))

    def stat(sample):
        c = contingency([f for f, _ in sample], [o for _, o in sample])
        return getattr(c, metric)

    return bootstrap_ci(pairs, stat, n_boot=n_boot, alpha=alpha, seed=seed)


def brier_ci(probs: Sequence[Number], observed: Sequence[bool],
             n_boot: int = 2000, alpha: float = 0.05, seed: int = 20260917):
    pairs = list(zip(probs, observed))

    def stat(sample):
        return brier_score([p for p, _ in sample], [o for _, o in sample])

    return bootstrap_ci(pairs, stat, n_boot=n_boot, alpha=alpha, seed=seed)


# ------------------------------------------------------ multi-class -------

CATEGORY_ORDER = ("VFR", "MVFR", "IFR", "LIFR")


def confusion_matrix(forecast: Sequence[str], observed: Sequence[str],
                     labels: Sequence[str] = CATEGORY_ORDER) -> dict[str, dict[str, int]]:
    """Counts indexed [observed][forecast]. Unknown labels are ignored."""
    idx = set(labels)
    m = {o: {f: 0 for f in labels} for o in labels}
    for f, o in zip(forecast, observed):
        if f in idx and o in idx:
            m[o][f] += 1
    return m


def accuracy(matrix: dict[str, dict[str, int]]) -> float | None:
    total = sum(v for row in matrix.values() for v in row.values())
    if not total:
        return None
    correct = sum(matrix[k][k] for k in matrix)
    return correct / total


def ifr_or_worse(category: str | None) -> bool | None:
    """True when the category is IFR or LIFR -- the operationally decisive split."""
    if category is None:
        return None
    return category in ("IFR", "LIFR")
