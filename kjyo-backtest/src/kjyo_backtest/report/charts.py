"""Inline SVG charts.

Hand-rolled rather than matplotlib: the report is a single self-contained HTML
file with no image assets, and the two chart types needed here are simple.
"""

from __future__ import annotations

from html import escape

AXIS = "#8a8f98"
GRID = "#e3e6ea"
INK = "#1b1f24"
SERIES = ["#2f6fb5", "#c8642a", "#4a8b5c", "#8a5fa8", "#b03a48"]


def _fmt(v: float) -> str:
    return f"{v:.4g}"


def reliability_diagram(bins, width=380, height=300, title="Reliability") -> str:
    """Forecast probability against observed frequency, with a 1:1 diagonal."""
    pad_l, pad_b, pad_t, pad_r = 48, 40, 28, 12
    pw, ph = width - pad_l - pad_r, height - pad_t - pad_b

    def px(x): return pad_l + x * pw
    def py(y): return pad_t + (1 - y) * ph

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}" '
        f'style="max-width:100%;height:auto">',
        f'<text x="{pad_l}" y="18" font-size="12" font-weight="600" fill="{INK}">{escape(title)}</text>',
    ]
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        parts.append(f'<line x1="{px(0):.1f}" y1="{py(t):.1f}" x2="{px(1):.1f}" y2="{py(t):.1f}" stroke="{GRID}"/>')
        parts.append(f'<text x="{pad_l-6}" y="{py(t)+4:.1f}" font-size="10" text-anchor="end" fill="{AXIS}">{t:.2f}</text>')
        parts.append(f'<text x="{px(t):.1f}" y="{height-pad_b+14:.1f}" font-size="10" text-anchor="middle" fill="{AXIS}">{t:.2f}</text>')
    # Perfect-calibration diagonal.
    parts.append(f'<line x1="{px(0):.1f}" y1="{py(0):.1f}" x2="{px(1):.1f}" y2="{py(1):.1f}" '
                 f'stroke="{AXIS}" stroke-dasharray="4 3"/>')

    pts = [(b.mean_forecast, b.observed_freq, b.n) for b in bins
           if b.n and b.mean_forecast is not None and b.observed_freq is not None]
    if pts:
        path = " ".join(f"{'M' if i == 0 else 'L'}{px(x):.1f},{py(y):.1f}"
                        for i, (x, y, _) in enumerate(pts))
        parts.append(f'<path d="{path}" fill="none" stroke="{SERIES[0]}" stroke-width="2"/>')
        maxn = max(n for _, _, n in pts)
        for x, y, n in pts:
            r = 3 + 4 * (n / maxn) ** 0.5
            parts.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="{r:.1f}" '
                         f'fill="{SERIES[0]}" fill-opacity="0.75"><title>forecast {_fmt(x)}, '
                         f'observed {_fmt(y)}, n={n}</title></circle>')
    else:
        parts.append(f'<text x="{width/2:.0f}" y="{height/2:.0f}" font-size="11" '
                     f'text-anchor="middle" fill="{AXIS}">no data yet</text>')

    parts.append(f'<text x="{pad_l+pw/2:.0f}" y="{height-4}" font-size="10" '
                 f'text-anchor="middle" fill="{AXIS}">forecast probability</text>')
    parts.append(f'<text transform="translate(12,{pad_t+ph/2:.0f}) rotate(-90)" font-size="10" '
                 f'text-anchor="middle" fill="{AXIS}">observed frequency</text>')
    parts.append("</svg>")
    return "".join(parts)


def lead_time_chart(series: dict[str, list[tuple[int, float | None]]],
                    width=560, height=300, title="Skill by lead day",
                    ylabel="metric", ymax: float | None = None) -> str:
    """One line per series: metric against lead day."""
    pad_l, pad_b, pad_t, pad_r = 48, 44, 28, 110
    pw, ph = width - pad_l - pad_r, height - pad_t - pad_b
    xs = sorted({x for pts in series.values() for x, y in pts if y is not None})
    ys = [y for pts in series.values() for _, y in pts if y is not None]
    if not xs or not ys:
        return (f'<svg viewBox="0 0 {width} {height}" style="max-width:100%;height:auto">'
                f'<text x="{width/2:.0f}" y="{height/2:.0f}" font-size="11" '
                f'text-anchor="middle" fill="{AXIS}">no data yet</text></svg>')
    xmin, xmax = min(xs), max(xs)
    top = ymax if ymax is not None else max(1.0, max(ys) * 1.1)

    def px(x): return pad_l + ((x - xmin) / max(xmax - xmin, 1)) * pw
    def py(y): return pad_t + (1 - y / top) * ph

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}" '
        f'style="max-width:100%;height:auto">',
        f'<text x="{pad_l}" y="18" font-size="12" font-weight="600" fill="{INK}">{escape(title)}</text>',
    ]
    for i in range(5):
        t = top * i / 4
        parts.append(f'<line x1="{px(xmin):.1f}" y1="{py(t):.1f}" x2="{px(xmax):.1f}" y2="{py(t):.1f}" stroke="{GRID}"/>')
        parts.append(f'<text x="{pad_l-6}" y="{py(t)+4:.1f}" font-size="10" text-anchor="end" fill="{AXIS}">{_fmt(t)}</text>')
    for x in xs:
        parts.append(f'<text x="{px(x):.1f}" y="{height-pad_b+14:.1f}" font-size="10" '
                     f'text-anchor="middle" fill="{AXIS}">{x}</text>')

    for i, (name, pts) in enumerate(sorted(series.items())):
        color = SERIES[i % len(SERIES)]
        good = [(x, y) for x, y in sorted(pts) if y is not None]
        if not good:
            continue
        path = " ".join(f"{'M' if j == 0 else 'L'}{px(x):.1f},{py(y):.1f}"
                        for j, (x, y) in enumerate(good))
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"/>')
        for x, y in good:
            parts.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="3" fill="{color}">'
                         f'<title>{escape(name)} lead {x}: {_fmt(y)}</title></circle>')
        ly = pad_t + 14 * i + 6
        parts.append(f'<line x1="{width-pad_r+6}" y1="{ly}" x2="{width-pad_r+22}" y2="{ly}" stroke="{color}" stroke-width="2"/>')
        parts.append(f'<text x="{width-pad_r+26}" y="{ly+4}" font-size="10" fill="{INK}">{escape(name)}</text>')

    parts.append(f'<text x="{pad_l+pw/2:.0f}" y="{height-6}" font-size="10" '
                 f'text-anchor="middle" fill="{AXIS}">lead day</text>')
    parts.append(f'<text transform="translate(12,{pad_t+ph/2:.0f}) rotate(-90)" font-size="10" '
                 f'text-anchor="middle" fill="{AXIS}">{escape(ylabel)}</text>')
    parts.append("</svg>")
    return "".join(parts)
