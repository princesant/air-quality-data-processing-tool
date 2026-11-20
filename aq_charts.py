# -*- coding: utf-8 -*-
"""Plotly figures for the Air Quality Data Processing Tool.

Time series use a gap-aware axis: long pauses in sampling are collapsed so the record reads
as one continuous series, and each pause is marked with two red dashed lines and its length."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from aq_core import find_gaps, format_timedelta

PRIMARY = "#0F766E"
COLORWAY = ["#0F766E", "#2563EB", "#D97706", "#7C3AED", "#DB2777", "#0891B2", "#65A30D", "#475569"]
RAW_GREY = "#94A3B8"
GAP_RED = "#E11D48"
REMOVED_RED = "#DC2626"
CHANGED_AMBER = "#F59E0B"
FONT = "Inter, Segoe UI, system-ui, sans-serif"

TREND_OPTIONS = ["None", "Rolling average", "Linear trend", "Rolling average + linear trend"]
WINDOWS = {"15 min": "15min", "1 hour": "1h", "3 hours": "3h", "8 hours": "8h", "24 hours": "24h"}
WINDOW_POINTS = {"15 min": 15, "1 hour": 60, "3 hours": 180, "8 hours": 480, "24 hours": 1440}
MAX_LINE_POINTS = 4000


def hex_to_rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def styled(fig, title, height=480, **layout):
    settings = dict(
        title=dict(text=title, x=0.01, xanchor="left", y=0.97, yanchor="top",
                   font=dict(size=15, color="#0F172A", family=FONT)),
        template="plotly_white",
        font=dict(family=FONT, size=12.5, color="#334155"),
        colorway=COLORWAY,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        height=height,
        margin=dict(l=64, r=24, t=100, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.03, xanchor="left", x=0, font=dict(size=11.5)),
        hoverlabel=dict(bgcolor="#0F172A", bordercolor="#0F172A", font=dict(color="#FFFFFF", family=FONT, size=12)),
    )
    settings.update(layout)
    fig.update_layout(**settings)
    fig.update_xaxes(gridcolor="#EEF2F6", linecolor="#CBD5E1", zeroline=False, ticks="outside", tickcolor="#CBD5E1")
    fig.update_yaxes(gridcolor="#EEF2F6", linecolor="#CBD5E1", zeroline=False)
    return fig


# ===== SAMPLING HELPERS =====
def downsample(x, y, max_points=MAX_LINE_POINTS):
    """Keep the min and max of each bucket so spikes survive thinning"""
    n = len(y)
    if n <= max_points:
        return x, y
    values = y.to_numpy(dtype=float)
    edges = np.linspace(0, n, max_points // 2 + 1).astype(int)
    keep = {0, n - 1}
    for a, b in zip(edges[:-1], edges[1:]):
        segment = values[a:b]
        if b <= a:
            continue
        if np.all(np.isnan(segment)):
            keep.add(a)
            continue
        keep.add(a + int(np.nanargmin(segment)))
        keep.add(a + int(np.nanargmax(segment)))
    idx = sorted(keep)
    return x.iloc[idx], y.iloc[idx]


def stride(x, y, max_points=MAX_LINE_POINTS):
    if len(y) <= max_points:
        return x, y
    idx = np.unique(np.linspace(0, len(y) - 1, max_points).astype(int))
    return x.iloc[idx], y.iloc[idx]


# ===== GAP-AWARE TIME AXIS =====
class TimeAxis:
    """Finds sampling gaps; when collapsing, hides most of each gap with a Plotly rangebreak
    and leaves a narrow marked strip, so lines and trends run continuously across it."""

    def __init__(self, times, collapse=True):
        t = pd.Series(pd.to_datetime(times)).dropna().sort_values()
        self.collapse = collapse
        self.gaps, self.step = find_gaps(t)
        self.t0 = t.iloc[0] if len(t) else None
        self.pad = pd.Timedelta(0)
        if self.gaps:
            span = t.iloc[-1] - t.iloc[0]
            active = span - sum((b - a for a, b in self.gaps), pd.Timedelta(0))
            # Each collapsed gap keeps a strip ~2.4% of the plot wide, whatever the sampling interval
            self.pad = max(active * 0.012, pd.Timedelta(seconds=1))

    def hidden(self, a, b):
        """Length of the part of a gap that is cut out of the axis"""
        if not self.collapse:
            return pd.Timedelta(0)
        return max(b - a - 2 * self.pad, pd.Timedelta(0))

    def effective_seconds(self, x):
        """Seconds along the drawn axis (real time minus hidden parts of gaps)"""
        values = pd.to_datetime(x).to_numpy()
        t = (values - np.datetime64(self.t0)) / np.timedelta64(1, "s")
        for a, b in self.gaps:
            cut = self.hidden(a, b).total_seconds()
            if cut > 0:
                t = t - np.where(values >= np.datetime64(b), cut, 0.0)
        return t

    def prepare(self, xs, ys):
        """Break lines at gaps when they are shown at full length"""
        if self.collapse or not self.gaps:
            return xs, ys
        frame = pd.DataFrame({"x": pd.to_datetime(xs).to_numpy(), "y": np.asarray(ys, dtype=float)})
        breaks = pd.DataFrame({"x": [a + (b - a) / 2 for a, b in self.gaps], "y": np.nan})
        frame = pd.concat([frame, breaks], ignore_index=True).sort_values("x", kind="stable")
        return frame["x"], frame["y"]

    def decorate(self, fig):
        rangebreaks = []
        for a, b in self.gaps:
            cut = self.hidden(a, b) > pd.Timedelta(0)
            if cut:
                rangebreaks.append(dict(bounds=[(a + self.pad).strftime("%Y-%m-%d %H:%M:%S"),
                                                (b - self.pad).strftime("%Y-%m-%d %H:%M:%S")]))
            fig.add_shape(type="rect", xref="x", yref="paper", x0=a, x1=b, y0=0, y1=1,
                          fillcolor=hex_to_rgba(GAP_RED, 0.07), line_width=0, layer="below")
            for edge in (a, b):
                fig.add_shape(type="line", xref="x", yref="paper", x0=edge, x1=edge, y0=0, y1=1,
                              line=dict(color=GAP_RED, width=1.8, dash="dash"))
            fig.add_annotation(
                x=a + self.pad if cut else a + (b - a) / 2, y=0.99, xref="x", yref="paper", yanchor="top",
                text=f"<b>{format_timedelta(b - a)}</b><br>no data", showarrow=False,
                font=dict(color=GAP_RED, size=10.5), bgcolor="rgba(255,255,255,0.9)",
                bordercolor=hex_to_rgba(GAP_RED, 0.4), borderwidth=1, borderpad=3
            )
        if rangebreaks:
            fig.update_xaxes(rangebreaks=rangebreaks)
        return fig

    def gap_summary(self):
        return [{"start": a.strftime("%d %b %Y %H:%M"), "end": b.strftime("%d %b %Y %H:%M"),
                 "length": format_timedelta(b - a)} for a, b in self.gaps]


def add_range_buttons(fig):
    fig.update_xaxes(rangeselector=dict(
        buttons=[
            dict(count=1, label="1 h", step="hour", stepmode="backward"),
            dict(count=6, label="6 h", step="hour", stepmode="backward"),
            dict(count=1, label="1 d", step="day", stepmode="backward"),
            dict(count=7, label="1 w", step="day", stepmode="backward"),
            dict(step="all", label="All"),
        ],
        bgcolor="#F1F5F9", activecolor="#CCEBE6", font=dict(size=11),
        x=1, xanchor="right", y=1.03, yanchor="bottom"
    ))


# ===== TRENDLINES =====
def rolling_mean(x, y, is_time, window_label):
    if is_time:
        s = pd.Series(y.to_numpy(dtype=float), index=pd.DatetimeIndex(x))
        return pd.Series(s.rolling(WINDOWS[window_label], center=True, min_periods=1).mean().to_numpy(), index=y.index)
    return y.rolling(WINDOW_POINTS[window_label], center=True, min_periods=1).mean()


def linear_trend(x, y, axis):
    """Least-squares line. On a collapsed axis it is fitted on monitoring time (gaps removed),
    so it is drawn as one continuous straight line across gaps."""
    mask = (x.notna() & y.notna()).to_numpy()
    if mask.sum() < 2:
        return None
    t = axis.effective_seconds(x) if axis else np.arange(len(x), dtype=float)
    if np.ptp(t[mask]) == 0:
        return None
    slope, intercept = np.polyfit(t[mask], y.to_numpy(dtype=float)[mask], 1)
    idx = np.unique(np.concatenate([np.linspace(0, len(x) - 1, 400).astype(int), [len(x) - 1]]))
    xs, ys = x.iloc[idx], intercept + slope * t[idx]
    if axis:
        span_days = np.ptp(t[mask]) / 86400
        unit, factor = ("day", 86400) if span_days >= 2 else ("hour", 3600)
        label = f"{slope * factor:+.2f} per {unit}" + (" of monitoring" if axis.collapse and axis.gaps else "")
        if not axis.collapse:
            xs, ys = axis.prepare(xs, ys)
    else:
        label = f"slope {slope:+.3g} per row"
    return xs, ys, label


# ===== FIGURES =====
def timeseries_figure(df, datetime_col, cols, trend="Rolling average", window="1 hour", ref_value=0.0,
                      ref_label="", log_y=False, collapse=True, fade=True, title="Time series"):
    valid_cols = [c for c in cols if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]
    is_time = bool(datetime_col) and datetime_col in df.columns
    if is_time:
        data = df.dropna(subset=[datetime_col]).sort_values(datetime_col, kind="stable").reset_index(drop=True)
        x = data[datetime_col]
        axis = TimeAxis(x, collapse)
    else:
        data = df.reset_index(drop=True)
        x = pd.Series(np.arange(len(data)), index=data.index)
        axis = None

    show_rolling = trend in ("Rolling average", "Rolling average + linear trend")
    show_linear = trend in ("Linear trend", "Rolling average + linear trend")
    faded = (show_rolling or show_linear) and fade

    fig = go.Figure()
    for i, col in enumerate(valid_cols):
        color = COLORWAY[i % len(COLORWAY)]
        y = data[col]
        xs, ys = downsample(x, y)
        if axis:
            xs, ys = axis.prepare(xs, ys)
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", name=col, legendgroup=col,
            line=dict(width=1.4, color=color), opacity=0.32 if faded else 1,
            hovertemplate=f"<b>{col}</b>: %{{y:.2f}}<extra></extra>"
        ))
        if show_rolling:
            xs, rs = stride(x, rolling_mean(x, y, is_time, window))
            if axis:
                xs, rs = axis.prepare(xs, rs)
            fig.add_trace(go.Scatter(
                x=xs, y=rs, mode="lines", name=f"{col} · {window} rolling mean", legendgroup=col,
                line=dict(width=3, color=color, shape="spline", smoothing=0.6),
                hovertemplate=f"<b>{col} ({window} mean)</b>: %{{y:.2f}}<extra></extra>"
            ))
        if show_linear:
            fit = linear_trend(x, y, axis)
            if fit:
                xs, ys, label = fit
                fig.add_trace(go.Scatter(
                    x=xs, y=ys, mode="lines", name=f"{col} · linear trend ({label})", legendgroup=col,
                    line=dict(width=2.6, color=color, dash="dash"), hoverinfo="skip"
                ))

    if ref_value and ref_value > 0:
        fig.add_hline(y=ref_value, line_dash="dot", line_color=REMOVED_RED, line_width=2,
                      annotation_text=ref_label or f"Reference: {ref_value:g}", annotation_position="top left",
                      annotation_font_color=REMOVED_RED)

    styled(fig, title, height=540, hovermode="x unified",
           xaxis_title="Time" if is_time else "Row", yaxis_title="Concentration / value")
    if axis:
        axis.decorate(fig)
        add_range_buttons(fig)
    if log_y:
        fig.update_yaxes(type="log")
    return fig, (axis.gap_summary() if axis else [])


def before_after_figure(raw, cleaned_pre, cleaned_final, datetime_col, col, resampled, collapse=True):
    """Raw vs cleaned for one variable, marking removed rows and changed values"""
    is_time = bool(datetime_col) and datetime_col in raw.columns
    if is_time:
        raw = raw.sort_values(datetime_col, kind="stable")
        axis = TimeAxis(raw[datetime_col], collapse)
    else:
        axis = None

    def xy(frame):
        frame_x = frame[datetime_col] if is_time else pd.Series(frame.index, index=frame.index)
        return frame_x, frame[col]

    def line(frame):
        lx, ly = downsample(*xy(frame))
        return axis.prepare(lx, ly) if axis else (lx, ly)

    fig = go.Figure()
    lx, ly = line(raw)
    fig.add_trace(go.Scatter(x=lx, y=ly, mode="lines", name="Original", line=dict(color=RAW_GREY, width=1.3)))

    if resampled:
        lx, ly = line(cleaned_final.sort_values(datetime_col))
        fig.add_trace(go.Scatter(x=lx, y=ly, mode="lines", name="Cleaned (averaged)",
                                 line=dict(color=PRIMARY, width=2.6, shape="hv")))
    elif col in cleaned_pre.columns:
        lx, ly = line(cleaned_pre.sort_values(datetime_col) if is_time else cleaned_pre)
        fig.add_trace(go.Scatter(x=lx, y=ly, mode="lines", name="Cleaned", line=dict(color=PRIMARY, width=1.8)))

    raw_x, raw_y = xy(raw)
    removed_idx = raw.index.difference(cleaned_pre.index)
    if len(removed_idx):
        fig.add_trace(go.Scatter(x=raw_x.loc[removed_idx], y=raw_y.loc[removed_idx], mode="markers",
                                 name=f"Row removed ({len(removed_idx):,})",
                                 marker=dict(color=REMOVED_RED, symbol="x", size=7)))

    if col in cleaned_pre.columns:
        common = raw.index.intersection(cleaned_pre.index)
        before, after = raw.loc[common, col], cleaned_pre.loc[common, col]
        changed = ~((before == after) | (before.isna() & after.isna()))
        changed_idx = changed[changed].index
        if len(changed_idx):
            fig.add_trace(go.Scatter(x=raw_x.loc[changed_idx], y=before.loc[changed_idx], mode="markers",
                                     name=f"Value changed ({len(changed_idx):,})",
                                     marker=dict(color=CHANGED_AMBER, size=7, line=dict(color="#fff", width=1))))

    styled(fig, f"Before vs after cleaning · {col}", height=500, hovermode="x unified",
           xaxis_title="Time" if is_time else "Row", yaxis_title=col)
    if axis:
        axis.decorate(fig)
        add_range_buttons(fig)
    return fig


def distribution_figure(raw, cleaned, col, nbins=50):
    """Overlaid histograms, binned on the server so large datasets stay light"""
    values = pd.concat([raw[col], cleaned[col]]).dropna()
    fig = go.Figure()
    if values.empty:
        return styled(fig, f"Distribution · {col}", height=430)
    edges = np.histogram_bin_edges(values, bins=nbins)
    centres = (edges[:-1] + edges[1:]) / 2
    width = edges[1] - edges[0] if len(edges) > 1 else 1
    for name, series, color, opacity in (("Original", raw[col], RAW_GREY, 0.55), ("Cleaned", cleaned[col], PRIMARY, 0.75)):
        counts, _ = np.histogram(series.dropna(), bins=edges)
        fig.add_trace(go.Bar(x=centres, y=counts, width=width, name=name, marker_color=color, opacity=opacity,
                             hovertemplate=f"<b>{name}</b><br>%{{x:.1f}}: %{{y}} readings<extra></extra>"))
    styled(fig, f"Distribution · {col}", height=430, barmode="overlay", bargap=0.02,
           xaxis_title=col, yaxis_title="Count")
    return fig


def box_figure(raw, cleaned, col):
    """Box plots from precomputed quartiles (Tukey whiskers)"""
    fig = go.Figure()
    for name, series, color in (("Original", raw[col].dropna(), RAW_GREY), ("Cleaned", cleaned[col].dropna(), PRIMARY)):
        if series.empty:
            continue
        q1, med, q3 = series.quantile([0.25, 0.5, 0.75])
        iqr = q3 - q1
        lower = series[series >= q1 - 1.5 * iqr].min()
        upper = series[series <= q3 + 1.5 * iqr].max()
        fig.add_trace(go.Box(name=name, q1=[q1], median=[med], q3=[q3], lowerfence=[lower], upperfence=[upper],
                             mean=[series.mean()], marker_color=color, fillcolor=hex_to_rgba(color, 0.25),
                             line=dict(width=2)))
    styled(fig, "Spread (box plot)", height=430, showlegend=False, yaxis_title=col)
    return fig


def diurnal_figure(df, datetime_col, cols, split_weekend):
    """Mean by hour of day with interquartile band"""
    data = df.dropna(subset=[datetime_col])
    fig = go.Figure()
    groups = [("All days", data)]
    if split_weekend:
        weekend = data[datetime_col].dt.dayofweek >= 5
        groups = [("Weekdays", data[~weekend]), ("Weekends", data[weekend])]

    trace_idx = 0
    for col in cols:
        for group_name, part in groups:
            if part.empty:
                continue
            color = COLORWAY[trace_idx % len(COLORWAY)]
            trace_idx += 1
            grouped = part.groupby(part[datetime_col].dt.hour)[col]
            mean, q25, q75 = grouped.mean(), grouped.quantile(0.25), grouped.quantile(0.75)
            name = col if not split_weekend else f"{col} · {group_name}"
            hours = mean.index.tolist()
            fig.add_trace(go.Scatter(
                x=hours + hours[::-1], y=q75.tolist() + q25.tolist()[::-1], fill="toself",
                fillcolor=hex_to_rgba(color, 0.14), line=dict(width=0), hoverinfo="skip",
                showlegend=False, legendgroup=name
            ))
            fig.add_trace(go.Scatter(
                x=hours, y=mean, mode="lines+markers", name=name, legendgroup=name,
                line=dict(color=color, width=2.6, shape="spline", smoothing=0.5), marker=dict(size=6),
                hovertemplate=f"<b>{name}</b><br>%{{x}}:00 · mean %{{y:.2f}}<extra></extra>"
            ))

    styled(fig, "Diurnal profile · mean with 25th–75th percentile band", height=470,
           xaxis=dict(title="Hour of day", tickmode="linear", dtick=2, range=[-0.5, 23.5]),
           yaxis_title="Concentration / value")
    return fig


def relationship_figure(df, x_col, y_col):
    data = df[[x_col, y_col]].dropna()
    shown = data.sample(5000, random_state=0) if len(data) > 5000 else data
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=shown[x_col], y=shown[y_col], mode="markers", name="Observations",
                             marker=dict(color=hex_to_rgba(PRIMARY, 0.45), size=6)))
    stats = None
    if len(data) >= 2 and data[x_col].nunique() > 1:
        slope, intercept = np.polyfit(data[x_col], data[y_col], 1)
        r = np.corrcoef(data[x_col], data[y_col])[0, 1]
        xs = np.array([data[x_col].min(), data[x_col].max()])
        fig.add_trace(go.Scatter(x=xs, y=intercept + slope * xs, mode="lines",
                                 line=dict(color=COLORWAY[2], width=3),
                                 name=f"Fit: y = {slope:.3f}x {intercept:+.2f}  (R² = {r ** 2:.3f})"))
        ratio = (data[y_col] / data[x_col].replace(0, np.nan)).dropna()
        stats = {"r2": float(r ** 2), "slope": float(slope), "intercept": float(intercept), "n": int(len(data)),
                 "median_ratio": float(ratio.median()) if len(ratio) else None}
    styled(fig, f"{y_col} vs {x_col}", height=480, xaxis_title=x_col, yaxis_title=y_col)
    return fig, stats


def correlation_figure(df):
    corr = df.select_dtypes(include=[np.number]).corr().round(2)
    fig = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index, zmin=-1, zmax=1,
                               colorscale="RdBu", text=corr.values, texttemplate="%{text:.2f}",
                               hovertemplate="%{y} × %{x}: %{z:.2f}<extra></extra>"))
    styled(fig, "Correlation matrix", height=480)
    fig.update_yaxes(autorange="reversed")
    return fig


def removed_reasons_figure(removed):
    counts = removed["Removal reason"].value_counts().sort_values()
    fig = go.Figure(go.Bar(x=counts.values, y=counts.index, orientation="h", marker_color=REMOVED_RED,
                           hovertemplate="%{y}: %{x} rows<extra></extra>"))
    styled(fig, "Rows removed by reason", height=max(260, 60 + 46 * len(counts)), margin=dict(l=20, r=24, t=60, b=40))
    fig.update_yaxes(automargin=True)
    return fig


# ===== INSTRUMENT-SPECIFIC FIGURES =====
SPEED_EDGES = [0, 0.5, 1.5, 3, 5, 8, np.inf]
SPEED_COLORS = ["#CCFBF1", "#5EEAD4", "#14B8A6", "#0F766E", "#134E4A", "#0B2F2C"]


def windrose_figure(df, speed_col, dir_col, title="Wind rose"):
    """Frequency of wind by direction (16 sectors) and speed class, as % of readings with a direction"""
    data = df[[speed_col, dir_col]].dropna()
    total = len(df[[speed_col]].dropna())
    calm = total - len(data)
    sector = ((data[dir_col] + 11.25) % 360 // 22.5 * 22.5).astype(float)
    names = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()
    fig = go.Figure()
    for i, (lo, hi) in enumerate(zip(SPEED_EDGES[:-1], SPEED_EDGES[1:])):
        in_bin = (data[speed_col] >= lo) & (data[speed_col] < hi)
        counts = sector[in_bin].value_counts().reindex(np.arange(16) * 22.5, fill_value=0)
        label = f"{lo:g}–{hi:g}" if np.isfinite(hi) else f"≥ {lo:g}"
        fig.add_trace(go.Barpolar(r=(counts / max(total, 1) * 100).round(2).tolist(), theta=names, name=label,
                                  marker_color=SPEED_COLORS[i], marker_line_color="#FFFFFF", marker_line_width=0.6,
                                  hovertemplate=f"%{{theta}} · {label}: %{{r:.1f}}%<extra></extra>"))
    styled(fig, title, height=520, margin=dict(l=40, r=40, t=90, b=40),
           legend=dict(title=dict(text=f"{speed_col}"), orientation="v", x=1.02, y=0.5, yanchor="middle"),
           polar=dict(bgcolor="#FFFFFF", angularaxis=dict(direction="clockwise", rotation=90, gridcolor="#E2E8F0"),
                      radialaxis=dict(ticksuffix="%", angle=90, gridcolor="#E2E8F0", tickfont=dict(size=10))))
    calm_pct = calm / max(total, 1) * 100
    return fig, {"calm_pct": calm_pct, "readings": total}


def alarm_codes_figure(df, status_col, alarms, info_only):
    """Readings carrying each C-12 status code (a reading can carry several)"""
    values = pd.to_numeric(df[status_col], errors="coerce").fillna(0).astype("int64")
    rows = [(label, int(((values & code) != 0).sum()), code in info_only) for code, label in alarms.items()]
    rows = [r for r in rows if r[1]] or [("No status codes", 0, True)]
    rows.sort(key=lambda r: r[1])
    fig = go.Figure(go.Bar(
        x=[r[1] for r in rows], y=[r[0] for r in rows], orientation="h",
        marker_color=[CHANGED_AMBER if r[2] else REMOVED_RED for r in rows],
        text=[f"{r[1]:,}" for r in rows], textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: %{x:,} readings<extra></extra>"))
    styled(fig, "Status codes in the original data", height=max(260, 70 + 46 * len(rows)),
           margin=dict(l=20, r=60, t=60, b=40))
    fig.update_yaxes(automargin=True)
    fig.update_xaxes(title_text="Readings")
    return fig
