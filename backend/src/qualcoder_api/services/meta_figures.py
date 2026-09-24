"""Pillow-only figures for the meta-analysis report (PRISMA flow, forest plot).

Pure drawing with ``PIL.ImageDraw`` (no matplotlib): a black-and-white PRISMA
2020 flow diagram from the ``meta_prisma`` counts and a forest plot from the
``meta_analysis.forest`` data. Both return PNG bytes and stay legible at a
~1200 px width.
"""

from __future__ import annotations

import io
import math
from typing import Any

from PIL import Image, ImageDraw

_WIDTH = 1220


def _font(size: int):
    from PIL import ImageFont

    for name in ("DejaVuSans.ttf", "arial.ttf", "segoeui.ttf", "calibri.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _png_bytes(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    return buffer.getvalue()


def _wrap(draw: ImageDraw.ImageDraw, text: Any, font: Any, max_width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def _arrow(draw: ImageDraw.ImageDraw, x1: float, y1: float, x2: float, y2: float) -> None:
    draw.line([x1, y1, x2, y2], fill="black", width=2)
    angle = math.atan2(y2 - y1, x2 - x1)
    length, half = 12.0, 5.0
    p2 = (x2 - length * math.cos(angle) + half * math.sin(angle),
          y2 - length * math.sin(angle) - half * math.cos(angle))
    p3 = (x2 - length * math.cos(angle) - half * math.sin(angle),
          y2 - length * math.sin(angle) + half * math.cos(angle))
    draw.polygon([(x2, y2), p2, p3], fill="black")


def prisma_png(counts: dict[str, Any]) -> bytes:
    """Draw a simple two-column PRISMA 2020 flow diagram from the counts."""
    img = Image.new("RGB", (_WIDTH, 1500), "white")
    draw = ImageDraw.Draw(img)
    f_title = _font(26)
    f_head = _font(18)
    f_box = _font(17)
    f_small = _font(15)
    f_phase = _font(16)

    def arrow(x1: float, y1: float, x2: float, y2: float) -> None:
        _arrow(draw, x1, y1, x2, y2)

    def box(x: float, y: float, w: float, h: float, text: str, thick: bool = False) -> None:
        draw.rectangle([x, y, x + w, y + h], outline="black", width=3 if thick else 2, fill="white")
        lines = _wrap(draw, text, f_box, w - 18)
        line_h = f_box.size + 5
        cy = y + (h - len(lines) * line_h) / 2
        for line in lines:
            tw = draw.textlength(line, font=f_box)
            draw.text((x + (w - tw) / 2, cy), line, font=f_box, fill="black")
            cy += line_h

    def panel(x: float, y: float, w: float, title: str, items: list[tuple[str, int]]) -> float:
        lines: list[str] = []
        for label, n in items:
            if n:
                lines += _wrap(draw, f"{label} (n = {n:,})", f_small, w - 30)
        if not lines:
            lines = ["None reported"]
        h = 14 + (f_head.size + 6) + len(lines) * (f_small.size + 6)
        draw.rectangle([x, y, x + w, y + h], outline="black", width=2, fill="white")
        draw.text((x + 12, y + 8), title, font=f_head, fill="black")
        cy = y + 12 + f_head.size + 6
        for line in lines:
            draw.text((x + 22, cy), line, font=f_small, fill="black")
            cy += f_small.size + 6
        return h

    def reasons(key: str) -> list[tuple[str, int]]:
        entries = counts.get(key) or []
        return [
            (str(entry.get("reason") or "Unspecified"), int(entry.get("n") or 0))
            for entry in entries
            if isinstance(entry, dict)
        ]

    ident = counts.get("identification") or {}
    screening = counts.get("screening") or {}
    fulltext = counts.get("fulltext") or {}
    inclusion = counts.get("inclusion") or {}

    draw.text((30, 16), "PRISMA 2020 flow diagram", font=f_title, fill="black")

    lx, bw = 90, 250
    px, pw = 360, 430
    ox, ow = 810, 370
    cx = lx + bw // 2
    box_h = 74
    title_y = 60

    y_ident = 130
    box(lx, y_ident, bw, box_h,
        f"Records identified\n(n = {int(ident.get('total', 0)):,})")
    y_screen = y_ident + box_h + 46
    box(lx, y_screen, bw, box_h,
        f"Records screened\n(n = {int(screening.get('screened', 0)):,})")
    h_screen = panel(px, y_screen, pw, "Records excluded", reasons("screening"))
    arrow(lx + bw, y_screen + box_h / 2, px, y_screen + box_h / 2)
    arrow(cx, y_ident + box_h, cx, y_screen)

    y_assess = y_screen + max(box_h, h_screen) + 46
    box(lx, y_assess, bw, box_h,
        f"Reports assessed for eligibility\n(n = {int(fulltext.get('assessed', 0)):,})")
    h_assess = panel(px, y_assess, pw, "Reports excluded", reasons("fulltext"))
    arrow(lx + bw, y_assess + box_h / 2, px, y_assess + box_h / 2)
    arrow(cx, y_screen + max(box_h, h_screen), cx, y_assess)

    y_inc = y_assess + max(box_h, h_assess) + 46
    box(lx, y_inc, bw, box_h,
        f"Studies included\n(n = {int(inclusion.get('studies', 0)):,})",
        thick=True)
    arrow(cx, y_assess + max(box_h, h_assess), cx, y_inc)

    # ── "identified via other methods" track (right column) ──
    other = int(ident.get("other") or 0)
    if other:
        oy = y_ident
        box(ox, oy, ow, box_h, f"Records identified via\nother methods\n(n = {other:,})")
        draw.line([ox + ow / 2, oy + box_h, ox + ow / 2, y_inc - 30], fill="black", width=2)
        draw.line([ox + ow / 2, y_inc - 30, cx, y_inc - 30], fill="black", width=2)
        arrow(cx, y_inc - 30, cx, y_inc)
    else:
        # Right-track header is still shown so the diagram keeps two columns.
        title_lines = _wrap(
            draw, "Identification of studies via other methods", f_head, ow - 24
        )
        title_line_h = f_head.size + 4
        title_h = max(42, len(title_lines) * title_line_h + 14)
        draw.rectangle([ox, title_y, ox + ow, title_y + title_h], outline="black", width=2)
        for i, line in enumerate(title_lines):
            tw = draw.textlength(line, font=f_head)
            draw.text(
                (ox + (ow - tw) / 2, title_y + 7 + i * title_line_h),
                line,
                font=f_head,
                fill="black",
            )

    # ── phase labels ──
    for label, y0, y1 in (
        ("Identification", y_ident, y_ident + box_h),
        ("Screening", y_screen, y_assess + box_h),
        ("Included", y_inc, y_inc + box_h),
    ):
        tmp = Image.new("RGBA", (1, 1))
        text_w = int(ImageDraw.Draw(tmp).textlength(label, font=f_phase)) + 8
        text_h = f_phase.size + 8
        timg = Image.new("RGBA", (text_w, text_h), (255, 255, 255, 0))
        ImageDraw.Draw(timg).text((4, 4), label, font=f_phase, fill="black")
        timg = timg.rotate(90, expand=True)
        img.paste(timg, (14, int((y0 + y1 - timg.height) / 2)), timg)

    used = y_inc + box_h + 30
    return _png_bytes(img.crop((0, 0, _WIDTH, min(1500, used))))


def forest_png(forest: dict[str, Any]) -> bytes:
    """Draw a forest plot (labels, effect points, CI lines and a pooled diamond)."""
    rows = [row for row in (forest.get("rows") or []) if isinstance(row, dict)]
    pooled = forest.get("pooled") or {}
    label_w = 500
    plot_left = label_w + 30
    plot_right = _WIDTH - 110
    plot_w = plot_right - plot_left
    header_h = 92
    row_h = 28
    footer_h = 120
    height = header_h + max(1, len(rows)) * row_h + footer_h
    img = Image.new("RGB", (_WIDTH, height), "white")
    draw = ImageDraw.Draw(img)
    f_title = _font(22)
    f_label = _font(15)
    f_small = _font(13)

    draw.text((30, 18), "Forest plot — individual effects and pooled estimate",
              font=f_title, fill="black")

    values: list[float] = [0.0]
    for row in rows:
        for key in ("effect", "ci_low", "ci_high"):
            value = row.get(key)
            if isinstance(value, (int, float)) and math.isfinite(value):
                values.append(float(value))
    for key in ("estimate", "ci_low", "ci_high"):
        value = pooled.get(key)
        if isinstance(value, (int, float)) and math.isfinite(value):
            values.append(float(value))
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        lo, hi = lo - 1.0, hi + 1.0
    pad = 0.06 * (hi - lo)
    lo, hi = lo - pad, hi + pad

    def sx(value: float) -> float:
        return plot_left + (value - lo) / (hi - lo) * plot_w

    draw.line([sx(0.0), header_h - 14, sx(0.0), header_h + max(1, len(rows)) * row_h],
              fill="grey", width=1)
    draw.text((sx(0.0) - 8, header_h - 30), "0", font=f_small, fill="black")
    draw.text((plot_left, header_h - 30), f"{lo:.1f}", font=f_small, fill="black")
    draw.text((plot_right - 30, header_h - 30), f"{hi:.1f}", font=f_small, fill="black")

    y = header_h
    if not rows:
        draw.text((plot_left, y + 10), "No effects with a usable variance.",
                  font=f_label, fill="black")
        y += row_h
    for row in rows:
        label = str(row.get("label") or row.get("study_id") or "")
        draw.text((24, y + 5), label[:60], font=f_label, fill="black")
        effect = row.get("effect")
        ci_low = row.get("ci_low")
        ci_high = row.get("ci_high")
        weight = row.get("weight")
        if isinstance(ci_low, (int, float)) and isinstance(ci_high, (int, float)):
            draw.line([sx(float(ci_low)), y + 10, sx(float(ci_high)), y + 10],
                      fill="black", width=2)
            for edge in (float(ci_low), float(ci_high)):
                draw.line([sx(edge), y + 5, sx(edge), y + 15], fill="black", width=2)
        if isinstance(effect, (int, float)):
            radius = 5
            point = sx(float(effect))
            draw.rectangle([point - radius, y + 10 - radius, point + radius, y + 10 + radius],
                           fill="black")
        if isinstance(weight, (int, float)):
            draw.text((plot_right + 12, y + 4), f"{float(weight):.1f}%", font=f_small, fill="black")
        y += row_h

    # ── pooled diamond ──
    estimate = pooled.get("estimate")
    ci_low = pooled.get("ci_low")
    ci_high = pooled.get("ci_high")
    y += 16
    draw.line([20, y, _WIDTH - 20, y], fill="black", width=2)
    y += 12
    draw.text((24, y - 4), f"Pooled (DL)  k = {forest.get('k', 0)}", font=f_label, fill="black")
    if (
        isinstance(estimate, (int, float))
        and isinstance(ci_low, (int, float))
        and isinstance(ci_high, (int, float))
    ):
        d_lo, d_hi, d_mid = sx(float(ci_low)), sx(float(ci_high)), sx(float(estimate))
        draw.polygon(
            [(d_lo, y + 10), (d_mid, y), (d_hi, y + 10), (d_mid, y + 20)],
            fill="black",
        )
        draw.text((plot_right + 12, y + 2), f"{float(estimate):.2f}", font=f_small, fill="black")
    return _png_bytes(img)


def _effect_se(row: dict[str, Any]) -> tuple[float, float] | None:
    """``(effect, standard error)`` for an effect row when both are usable."""
    effect = row.get("effect")
    se = row.get("se")
    if not isinstance(se, (int, float)) or not math.isfinite(float(se)):
        variance = row.get("variance")
        se = math.sqrt(variance) if isinstance(variance, (int, float)) and variance > 0 else None
    if (
        isinstance(effect, (int, float))
        and math.isfinite(float(effect))
        and isinstance(se, (int, float))
        and math.isfinite(float(se))
        and se > 0
    ):
        return float(effect), float(se)
    return None


def funnel_png(rows: list[dict[str, Any]]) -> bytes:
    """Funnel plot: effect size versus standard error with a pseudo-95% funnel.

    The pooled DL estimate is drawn as a vertical line and the funnel is the
    ``estimate ± 1.96 * SE`` interval widening with the standard error.
    """
    from qualcoder_api.services.meta_analysis import pool_dl

    clean = [row for row in (rows if isinstance(rows, list) else []) if isinstance(row, dict)]
    points = [pair for row in clean for pair in [_effect_se(row)] if pair is not None]
    pooled = pool_dl(clean)
    estimate = pooled.get("estimate")

    img = Image.new("RGB", (_WIDTH, 720), "white")
    draw = ImageDraw.Draw(img)
    f_title = _font(22)
    f_label = _font(14)
    f_small = _font(12)
    draw.text(
        (30, 18), "Funnel plot — effect size versus standard error",
        font=f_title, fill="black",
    )

    left, right = 130, _WIDTH - 240
    top, bottom = 92, 720 - 86

    if not points or estimate is None:
        draw.text((left, top + 60), "No effects with a usable variance.", font=f_label, fill="black")
        return _png_bytes(img)

    estimate = float(estimate)
    max_se = max(max(se for _e, se in points), float(pooled.get("se") or 0.0), 1e-6)
    values = [estimate, *(e for e, _se in points), *(estimate - 1.96 * max_se, estimate + 1.96 * max_se)]
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        lo, hi = lo - 1.0, hi + 1.0
    pad = 0.08 * (hi - lo)
    lo, hi = lo - pad, hi + pad

    def sx(value: float) -> float:
        return left + (value - lo) / (hi - lo) * (right - left)

    def sy(se: float) -> float:
        return top + se / max_se * (bottom - top)

    draw.line([left, top, left, bottom], fill="black", width=2)
    draw.line([left, bottom, right, bottom], fill="black", width=2)
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        xv = lo + frac * (hi - lo)
        x = sx(xv)
        draw.line([x, bottom, x, bottom + 5], fill="black", width=1)
        draw.text((x - 16, bottom + 9), f"{xv:.1f}", font=f_small, fill="black")
    for frac in (0.0, 0.5, 1.0):
        yv = frac * max_se
        y = sy(yv)
        draw.line([left - 5, y, left, y], fill="black", width=1)
        draw.text((left - 66, y - 7), f"{yv:.2f}", font=f_small, fill="black")
    draw.text((left - 72, top - 26), "SE", font=f_small, fill="black")
    draw.text((right - 40, bottom + 30), "Effect", font=f_small, fill="black")

    # Pseudo-95% funnel (widening with SE) and the pooled estimate.
    draw.line([sx(estimate - 1.96 * max_se), sy(max_se), sx(estimate), sy(0.0)],
              fill=(120, 120, 120), width=2)
    draw.line([sx(estimate + 1.96 * max_se), sy(max_se), sx(estimate), sy(0.0)],
              fill=(120, 120, 120), width=2)
    pooled_x = sx(estimate)
    draw.line([pooled_x, top, pooled_x, bottom], fill="black", width=2)
    draw.text((pooled_x + 5, top + 4), f"Pooled {estimate:.2f}", font=f_small, fill="black")

    for effect, se in points:
        x, y = sx(effect), sy(se)
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill="black")
    return _png_bytes(img)


_SPEC_BAND_COLOURS = {
    "dl": (222, 235, 247),
    "two_level": (226, 240, 217),
    "fixed": (252, 228, 214),
}


def spec_curve_png(multiverse: dict[str, Any]) -> bytes:
    """Specification curve: specs sorted by estimate, with CI bars and a median line.

    The background band of each row is coloured by the ``estimator`` dimension so
    the analytic choice behind every estimate stays visible.
    """
    specs = [
        spec
        for spec in (multiverse.get("specs") or [])
        if isinstance(spec, dict)
        and isinstance(spec.get("estimate"), (int, float))
        and math.isfinite(float(spec["estimate"]))
    ]
    header_h = 118
    row_h = 22
    footer_h = 86
    height = header_h + max(1, len(specs)) * row_h + footer_h
    img = Image.new("RGB", (_WIDTH, height), "white")
    draw = ImageDraw.Draw(img)
    f_title = _font(22)
    f_label = _font(13)
    f_small = _font(12)
    draw.text(
        (30, 18), "Specification curve — pooled estimate by analytic choice",
        font=f_title, fill="black",
    )
    if not specs:
        draw.text((60, header_h + 20), "No specification produced a pooled estimate.",
                  font=f_label, fill="black")
        return _png_bytes(img)

    label_w = 250
    plot_left = label_w + 30
    plot_right = _WIDTH - 120

    specs.sort(key=lambda spec: float(spec["estimate"]))
    values: list[float] = []
    for spec in specs:
        values.append(float(spec["estimate"]))
        for key in ("ci_low", "ci_high"):
            value = spec.get(key)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                values.append(float(value))
    summary = multiverse.get("summary") or {}
    median = summary.get("median")
    if isinstance(median, (int, float)):
        values.append(float(median))
    values.append(0.0)
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        lo, hi = lo - 1.0, hi + 1.0
    pad = 0.06 * (hi - lo)
    lo, hi = lo - pad, hi + pad

    def sx(value: float) -> float:
        return plot_left + (value - lo) / (hi - lo) * (plot_right - plot_left)

    # Dimension bands (coloured by estimator) + per-spec labels.
    y: float = float(header_h)
    for spec in specs:
        estimator = str((spec.get("choices") or {}).get("estimator") or "")
        draw.rectangle(
            [plot_left, y, plot_right, y + row_h - 1],
            fill=_SPEC_BAND_COLOURS.get(estimator, (245, 245, 245)),
        )
        draw.text((24, y + 3), f"#{spec.get('id')}  k={spec.get('k')}", font=f_small, fill="black")
        y += row_h

    zero_x = sx(0.0)
    draw.line([zero_x, header_h, zero_x, y], fill="grey", width=1)
    if isinstance(median, (int, float)):
        med_x = sx(float(median))
        draw.line([med_x, header_h - 10, med_x, y], fill=(200, 60, 60), width=2)
        draw.text((med_x + 4, header_h - 30), f"median {float(median):.2f}",
                  font=f_small, fill=(200, 60, 60))

    y = header_h + row_h / 2
    for spec in specs:
        estimate = float(spec["estimate"])
        ci_low = spec.get("ci_low")
        ci_high = spec.get("ci_high")
        if isinstance(ci_low, (int, float)) and isinstance(ci_high, (int, float)):
            draw.line([sx(float(ci_low)), y, sx(float(ci_high)), y], fill="black", width=2)
            for edge in (float(ci_low), float(ci_high)):
                draw.line([sx(edge), y - 5, sx(edge), y + 5], fill="black", width=1)
        x = sx(estimate)
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill="black")
        y += row_h

    # Legend for the estimator bands.
    legend_x = plot_left
    for estimator, colour in _SPEC_BAND_COLOURS.items():
        draw.rectangle([legend_x, 78, legend_x + 14, 92], fill=colour, outline="grey")
        draw.text((legend_x + 19, 79), estimator, font=f_small, fill="black")
        legend_x += 110
    draw.text((24, header_h - 30), f"{lo:.2f}", font=f_small, fill="black")
    draw.text((plot_right - 20, header_h - 30), f"{hi:.2f}", font=f_small, fill="black")

    pct = summary.get("pct_positive")
    footer = f"{summary.get('n_specs', len(specs))} specifications"
    if isinstance(median, (int, float)):
        footer += f"; median {float(median):.2f}"
    if isinstance(summary.get("min"), (int, float)) and isinstance(summary.get("max"), (int, float)):
        footer += f"; range [{float(summary['min']):.2f}, {float(summary['max']):.2f}]"
    if isinstance(pct, (int, float)):
        footer += f"; {float(pct):.0f}% positive"
    draw.text((24, y + 18), footer, font=f_label, fill="black")
    return _png_bytes(img)


def bayes_png(bayes: dict[str, Any]) -> bytes:
    """Marginal posterior density of the pooled effect ``mu``.

    The 95% credible interval is shaded, the posterior mean and the point null
    ``mu = 0`` are marked.
    """
    posterior = bayes.get("posterior") or {}
    mu = [float(x) for x in (posterior.get("mu") or []) if isinstance(x, (int, float))]
    density = [
        float(d) for d in (posterior.get("density") or []) if isinstance(d, (int, float))
    ]
    img = Image.new("RGB", (_WIDTH, 720), "white")
    draw = ImageDraw.Draw(img)
    f_title = _font(22)
    f_label = _font(14)
    f_small = _font(12)
    draw.text(
        (30, 18), "Bayesian posterior density of the pooled effect (mu)",
        font=f_title, fill="black",
    )

    left, right = 120, _WIDTH - 120
    top, bottom = 100, 720 - 96
    draw.line([left, top, left, bottom], fill="black", width=2)
    draw.line([left, bottom, right, bottom], fill="black", width=2)

    if len(mu) < 2 or len(density) != len(mu) or max(density) <= 0:
        draw.text((left, top + 60), "No posterior density available.", font=f_label, fill="black")
        return _png_bytes(img)

    lo, hi = min(mu), max(mu)
    if hi - lo < 1e-9:
        lo, hi = lo - 1.0, hi + 1.0
    peak = max(density)

    def sx(value: float) -> float:
        return left + (value - lo) / (hi - lo) * (right - left)

    def sy(value: float) -> float:
        return bottom - value / peak * (bottom - top)

    model_mu = bayes.get("mu") or {}
    ci_low = model_mu.get("ci_low")
    ci_high = model_mu.get("ci_high")
    if isinstance(ci_low, (int, float)) and isinstance(ci_high, (int, float)):
        idx = [i for i, x in enumerate(mu) if float(ci_low) <= x <= float(ci_high)]
        if len(idx) >= 2:
            polygon = [(sx(mu[i]), sy(density[i])) for i in range(idx[0], idx[-1] + 1)]
            polygon += [(sx(mu[idx[-1]]), sy(0.0)), (sx(mu[idx[0]]), sy(0.0))]
            draw.polygon(polygon, fill=(198, 219, 239))
            draw.text((sx(float(ci_low)), bottom + 12), f"{float(ci_low):.2f}",
                      font=f_small, fill="black")
            draw.text((sx(float(ci_high)) - 22, bottom + 12), f"{float(ci_high):.2f}",
                      font=f_small, fill="black")

    draw.line(
        [(sx(x), sy(d)) for x, d in zip(mu, density, strict=True)],
        fill=(31, 78, 121), width=2,
    )
    zero_x = sx(0.0)
    draw.line([zero_x, top, zero_x, bottom], fill="black", width=2)
    draw.text((zero_x + 4, top - 22), "mu = 0", font=f_small, fill="black")

    mean = model_mu.get("mean")
    if isinstance(mean, (int, float)):
        mean_x = sx(float(mean))
        draw.line([mean_x, top + 20, mean_x, bottom], fill=(200, 60, 60), width=2)
        draw.text((mean_x + 4, top + 22), f"mean {float(mean):.2f}",
                  font=f_small, fill=(200, 60, 60))
        draw.text((mean_x - 8, bottom + 30), f"{float(mean):.2f}", font=f_small, fill="black")
    draw.text((left - 80, top - 26), "Density", font=f_small, fill="black")
    return _png_bytes(img)
