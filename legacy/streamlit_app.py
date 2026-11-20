# -*- coding: utf-8 -*-
import hashlib
import io
import re
import warnings
import zipfile
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ===== PAGE CONFIG =====
st.set_page_config(
    page_title="Air Quality Data Processing Tool",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===== THEME CONSTANTS =====
PRIMARY = "#0F766E"
COLORWAY = ["#0F766E", "#2563EB", "#D97706", "#7C3AED", "#DC2626", "#0891B2", "#65A30D", "#DB2777"]
RAW_GREY = "#94A3B8"
REMOVED_RED = "#DC2626"
CHANGED_AMBER = "#F59E0B"

pio.templates["aq"] = go.layout.Template(layout=dict(
    font=dict(family="Inter, Segoe UI, sans-serif", size=13, color="#1E293B"),
    colorway=COLORWAY,
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="#FFFFFF",
    xaxis=dict(gridcolor="#EEF2F6", linecolor="#CBD5E1", zeroline=False),
    yaxis=dict(gridcolor="#EEF2F6", linecolor="#CBD5E1", zeroline=False),
    hoverlabel=dict(bgcolor="white", font_size=12),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    margin=dict(l=50, r=20, t=110, b=40),
    title=dict(font=dict(size=16, color="#0F172A"), x=0, xanchor="left", xref="paper",
               y=0.98, yanchor="top", yref="container"),
))
pio.templates.default = "plotly_white+aq"

# ===== CUSTOM STYLING =====
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    .stApp, .stApp p, .stApp label, .stApp li, .stApp h1, .stApp h2, .stApp h3, .stApp h4 {
        font-family: 'Inter', 'Segoe UI', sans-serif;
    }
    .block-container { padding-top: 2rem; max-width: 1400px; }

    /* Hero banner */
    .hero {
        background: linear-gradient(120deg, #0F766E 0%, #0E7490 45%, #1D4ED8 100%);
        color: #fff;
        padding: 28px 34px;
        border-radius: 18px;
        box-shadow: 0 10px 30px -12px rgba(15, 118, 110, .55);
        margin-bottom: 22px;
        position: relative;
        overflow: hidden;
    }
    .hero::after {
        content: ""; position: absolute; right: -60px; top: -60px;
        width: 260px; height: 260px; border-radius: 50%;
        background: radial-gradient(circle, rgba(255,255,255,.18), rgba(255,255,255,0) 70%);
    }
    .hero-badge {
        display: inline-block; font-size: .75rem; font-weight: 600; letter-spacing: .06em;
        text-transform: uppercase; background: rgba(255,255,255,.16);
        padding: 4px 12px; border-radius: 999px; margin-bottom: 10px;
    }
    .hero-title { font-size: 2rem; font-weight: 800; line-height: 1.2; margin: 0 0 6px 0; }
    .hero-sub { font-size: 1rem; opacity: .9; max-width: 780px; margin: 0; }

    /* Section headers */
    .section-head { display: flex; gap: 14px; align-items: center; margin: 6px 0 14px 0; }
    .section-icon {
        width: 44px; height: 44px; border-radius: 12px; display: flex; align-items: center;
        justify-content: center; font-size: 22px; background: #E6F4F1; flex-shrink: 0;
    }
    .section-title { font-size: 1.3rem; font-weight: 700; color: #0F172A; line-height: 1.2; }
    .section-sub { font-size: .9rem; color: #64748B; }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 14px 18px;
        box-shadow: 0 1px 2px rgba(15, 23, 42, .04);
    }
    [data-testid="stMetricLabel"] p {
        font-size: .76rem; text-transform: uppercase; letter-spacing: .05em;
        color: #64748B; font-weight: 600;
    }
    [data-testid="stMetricValue"] { font-weight: 700; color: #0F172A; font-size: 1.6rem; }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px; background: #FFFFFF; padding: 6px; border-radius: 12px;
        border: 1px solid #E2E8F0; flex-wrap: wrap;
    }
    .stTabs [data-baseweb="tab"] {
        height: 42px; padding: 0 18px; border-radius: 9px; font-weight: 600; color: #475569;
    }
    .stTabs [aria-selected="true"] { background: #E6F4F1; color: #0F766E; }
    .stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none; }

    /* Expanders as cards */
    [data-testid="stExpander"] details {
        background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 14px;
    }
    [data-testid="stExpander"] summary p { font-weight: 600; font-size: 1rem; }

    /* Buttons */
    .stButton button, .stDownloadButton button { border-radius: 10px; font-weight: 600; }
    .stButton button[kind="primary"] { box-shadow: 0 6px 16px -8px rgba(15,118,110,.8); }

    /* Charts as cards */
    [data-testid="stPlotlyChart"] {
        background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 14px;
        padding: 8px 6px 4px 6px; box-shadow: 0 1px 2px rgba(15, 23, 42, .04);
    }

    /* Data frames */
    [data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; border: 1px solid #E2E8F0; }

    /* Pipeline chips */
    .chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 12px 0; }
    .chip {
        font-size: .82rem; font-weight: 600; padding: 5px 12px; border-radius: 999px;
        background: #E6F4F1; color: #0F766E; border: 1px solid #B7E1D9;
    }
    .chip.off { background: #F1F5F9; color: #94A3B8; border-color: #E2E8F0; text-decoration: line-through; }

    /* Sidebar */
    [data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid #E2E8F0; }
    .side-brand { font-weight: 800; font-size: 1.1rem; color: #0F172A; }
    .side-step { display: flex; gap: 10px; margin: 8px 0; font-size: .9rem; color: #334155; }
    .side-num {
        width: 22px; height: 22px; border-radius: 50%; background: #0F766E; color: #fff;
        font-size: .75rem; font-weight: 700; display: flex; align-items: center;
        justify-content: center; flex-shrink: 0;
    }
    </style>
""", unsafe_allow_html=True)


def section_header(icon, title, subtitle=""):
    st.markdown(
        f'<div class="section-head"><div class="section-icon">{icon}</div>'
        f'<div><div class="section-title">{title}</div>'
        f'<div class="section-sub">{subtitle}</div></div></div>',
        unsafe_allow_html=True
    )


def show_chart(fig, key):
    # Streamlit fills in its own theme colours unless they are set on the figure itself
    fig.update_layout(template="plotly_white+aq", plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF")
    st.plotly_chart(fig, width="stretch", theme=None, key=key)


def hex_to_rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def format_timedelta(td):
    if td is None or pd.isna(td):
        return "–"
    seconds = int(td.total_seconds())
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min" + (f" {secs} s" if secs else "")
    return f"{secs} s"


# ===== TYPE CONVERSION FUNCTIONS =====
def detect_and_convert_types(df, dayfirst=False):
    """Convert text columns to numeric or datetime when at least 90% of values parse"""
    df_converted = df.copy()

    for col in df_converted.columns:
        series = df_converted[col]
        if series.dtype != object:
            continue

        stripped = series.astype(str).str.strip()
        non_blank = series.notna() & (stripped != "") & (stripped.str.lower() != "nan")
        if non_blank.sum() == 0:
            continue

        # Numeric first, so strings like "12.5" are never read as dates
        as_numeric = pd.to_numeric(stripped, errors="coerce")
        if as_numeric[non_blank].notna().mean() >= 0.9:
            df_converted[col] = as_numeric
            continue

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            as_datetime = pd.to_datetime(series, errors="coerce", dayfirst=dayfirst)
        if as_datetime[non_blank].notna().mean() >= 0.9:
            df_converted[col] = as_datetime

    return df_converted


def is_raw_dusttrak(data):
    head = data[:2000].decode("utf-8-sig", errors="replace")
    return head.startswith("Instrument Name") and "Elapsed Time" in data.decode("utf-8-sig", errors="replace")


@st.cache_data(show_spinner=False)
def load_table(data, dayfirst):
    """Read an uploaded CSV (raw DustTrak exports are converted automatically)"""
    if is_raw_dusttrak(data):
        df, _ = convert_dusttrak_file(data)
        return df, True
    try:
        df = pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(io.BytesIO(data), encoding="latin-1")
    df.columns = [str(c).strip() for c in df.columns]
    return detect_and_convert_types(df, dayfirst=dayfirst), False


# -------------------------------
# FUNCTION: CONVERTER
# -------------------------------
PM_SIZES = ["PM1", "PM2.5", "PM4", "PM10", "TOTAL"]


def convert_dusttrak_file(data, include_extra=False):
    """Convert a raw DustTrak export (bytes) to Timestamp + PM columns in µg/m³.

    Returns (DataFrame, info dict). Raises ValueError for files that cannot be read.
    """
    lines = data.decode("utf-8-sig", errors="replace").splitlines()

    meta = {}
    header_index = None
    for i, line in enumerate(lines):
        if line.startswith("Elapsed Time"):
            header_index = i
            break
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0]:
            meta[parts[0]] = parts[1]

    if header_index is None:
        raise ValueError("No 'Elapsed Time' data header found")

    start_date = meta.get("Test Start Date")
    start_time = meta.get("Test Start Time")
    if not start_date or not start_time:
        raise ValueError("Test start date/time missing from file header")

    start_timestamp = pd.to_datetime(start_date + " " + start_time, dayfirst=True)

    df = pd.read_csv(io.StringIO("\n".join(lines[header_index:])))
    df.columns = [c.strip() for c in df.columns]

    # REMOVE FLOW ERRORS (DustTrak names this column "Errors")
    flow_removed = 0
    error_col = next((c for c in ("Errors", "Error") if c in df.columns), None)
    if error_col:
        flow_mask = df[error_col].astype(str).str.contains("Flow", case=False, na=False)
        flow_removed = int(flow_mask.sum())
        df = df[~flow_mask]

    # Timestamp creation
    df["Timestamp"] = start_timestamp + pd.to_timedelta(df["Elapsed Time [s]"], unit="s")

    # Convert mg/m3 → µg/m3
    wanted = PM_SIZES if include_extra else ["PM1", "PM2.5", "PM10"]
    out_cols = ["Timestamp"]
    for size in wanted:
        old_col = f"{size} [mg/m3]"
        if old_col in df.columns:
            new_col = f"{size} [µg/m3]"
            df[new_col] = (pd.to_numeric(df[old_col], errors="coerce") * 1000).round(4)
            out_cols.append(new_col)

    if len(out_cols) == 1:
        raise ValueError("No PM [mg/m3] columns found")

    final_df = df[out_cols].reset_index(drop=True)
    info = {
        "Test name": meta.get("Test Name", "–"),
        "Serial no.": meta.get("Serial Number", "–"),
        "Start": final_df["Timestamp"].min(),
        "End": final_df["Timestamp"].max(),
        "Rows": len(final_df),
        "Flow-error rows removed": flow_removed,
        "File timestamp": start_timestamp.strftime("%Y-%m-%d_%H-%M-%S"),
    }
    return final_df, info


# ===== VISUALIZATION FUNCTIONS =====
TREND_OPTIONS = ["None", "Rolling average", "Linear trend", "Rolling average + linear trend"]
WINDOWS = {"15 min": "15min", "1 hour": "1h", "3 hours": "3h", "8 hours": "8h", "24 hours": "24h"}
WINDOW_POINTS = {"15 min": 15, "1 hour": 60, "3 hours": 180, "8 hours": 480, "24 hours": 1440}


def scatter_trace(n_points):
    return go.Scattergl if n_points > 15000 else go.Scatter


def insert_gap_breaks(data, datetime_col):
    """Add empty rows where sampling stops for a while, so lines break instead of bridging the gap.

    Inserted rows are marked in the '__gap' column."""
    data = data.assign(__gap=False)
    diffs = data[datetime_col].diff()
    step = diffs.median()
    if pd.isna(step) or step <= pd.Timedelta(0):
        return data
    gap_rows = data.index[diffs > step * 5]
    if len(gap_rows) == 0:
        return data
    breaks = pd.DataFrame({datetime_col: data.loc[gap_rows, datetime_col] - step, "__gap": True})
    return pd.concat([data, breaks], ignore_index=True).sort_values(datetime_col, kind="stable").reset_index(drop=True)


def rolling_mean(x, y, is_time, window_label):
    if is_time:
        s = pd.Series(y.to_numpy(), index=pd.DatetimeIndex(x))
        return s.rolling(WINDOWS[window_label], center=True, min_periods=1).mean().to_numpy()
    return y.rolling(WINDOW_POINTS[window_label], center=True, min_periods=1).mean().to_numpy()


def linear_fit(x, y, is_time):
    """Least-squares straight line; returns (x_ends, y_ends, slope label) or None"""
    mask = pd.notna(x) & pd.notna(y)
    x, y = x[mask], y[mask]
    if len(x) < 2:
        return None
    if is_time:
        t = (x - x.min()).dt.total_seconds().to_numpy()
    else:
        t = np.asarray(x, dtype=float)
    if np.ptp(t) == 0:
        return None
    slope, intercept = np.polyfit(t, y.to_numpy(dtype=float), 1)
    if is_time:
        span_days = np.ptp(t) / 86400
        unit, factor = ("day", 86400) if span_days >= 2 else ("hour", 3600)
        label = f"{slope * factor:+.2f} per {unit}"
    else:
        label = f"slope {slope:+.3g}"
    x_ends = [x.min(), x.max()]
    y_ends = [intercept + slope * t.min(), intercept + slope * t.max()]
    return x_ends, y_ends, label


def plot_timeseries(df, datetime_col, numeric_cols, trend="None", window="1 hour",
                    ref_value=0.0, ref_label="", log_y=False, fade_raw=True, title="Time series"):
    """Interactive time series with optional rolling-mean and linear trendlines"""
    valid_cols = [col for col in numeric_cols if col in df.columns and pd.api.types.is_numeric_dtype(df[col])]
    if not valid_cols:
        return None

    is_time = datetime_col is not None and datetime_col in df.columns
    if is_time:
        data = insert_gap_breaks(df.dropna(subset=[datetime_col]).sort_values(datetime_col), datetime_col)
        x = data[datetime_col]
    else:
        data = df.reset_index(drop=True).assign(__gap=False)
        x = pd.Series(np.arange(len(data)), index=data.index)

    Trace = scatter_trace(len(data))
    show_rolling = trend in ("Rolling average", "Rolling average + linear trend")
    show_linear = trend in ("Linear trend", "Rolling average + linear trend")
    faded = (show_rolling or show_linear) and fade_raw

    fig = go.Figure()
    for idx, col in enumerate(valid_cols):
        color = COLORWAY[idx % len(COLORWAY)]
        y = data[col]
        fig.add_trace(Trace(
            x=x, y=y, mode="lines", name=col, legendgroup=col,
            line=dict(width=1.4, color=color), opacity=0.35 if faded else 1,
            hovertemplate=f"<b>{col}</b>: %{{y:.2f}}<extra></extra>"
        ))
        if show_rolling:
            smoothed = np.where(data["__gap"], np.nan, rolling_mean(x, y, is_time, window))
            fig.add_trace(Trace(
                x=x, y=smoothed, mode="lines",
                name=f"{col} · {window} rolling mean", legendgroup=col,
                line=dict(width=3, color=color),
                hovertemplate=f"<b>{col} ({window} mean)</b>: %{{y:.2f}}<extra></extra>"
            ))
        if show_linear:
            fit = linear_fit(x, y, is_time)
            if fit:
                x_ends, y_ends, label = fit
                fig.add_trace(go.Scatter(
                    x=x_ends, y=y_ends, mode="lines", name=f"{col} · linear trend ({label})",
                    legendgroup=col, line=dict(width=2.5, color=color, dash="dash"),
                    hoverinfo="skip"
                ))

    if ref_value and ref_value > 0:
        fig.add_hline(
            y=ref_value, line_dash="dot", line_color=REMOVED_RED, line_width=2,
            annotation_text=ref_label or f"Reference: {ref_value:g}",
            annotation_position="top left", annotation_font_color=REMOVED_RED
        )

    fig.update_layout(
        title=title,
        xaxis_title="Time" if is_time else "Row",
        yaxis_title="Concentration / value",
        hovermode="x unified",
        height=520,
    )
    if is_time:
        fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06), rangeselector=dict(
            buttons=[
                dict(count=1, label="1 h", step="hour", stepmode="backward"),
                dict(count=6, label="6 h", step="hour", stepmode="backward"),
                dict(count=1, label="1 d", step="day", stepmode="backward"),
                dict(count=7, label="1 w", step="day", stepmode="backward"),
                dict(step="all", label="All"),
            ],
            bgcolor="#F1F5F9", activecolor="#CDEBE5", y=1.0, yanchor="bottom", x=1, xanchor="right"
        ))
    if log_y:
        fig.update_yaxes(type="log")
    return fig


def default_pm_columns(numeric_cols, limit=2):
    preferred = [c for c in numeric_cols if re.search(r"PM\s*2\.5|PM\s*10", c, re.I)]
    return (preferred or numeric_cols)[:limit]


def render_timeseries_explorer(df, datetime_col, key, title="Time series"):
    """Widgets + chart for exploring a dataset over time. Safe across reruns."""
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if not numeric_cols:
        st.info("💡 No numeric columns available to plot.")
        return

    c1, c2, c3 = st.columns([2.2, 1.3, 1])
    with c1:
        cols = st.multiselect("📈 Variables to plot", numeric_cols,
                              default=default_pm_columns(numeric_cols), key=f"{key}_cols")
    with c2:
        trend = st.selectbox("📐 Trendline", TREND_OPTIONS, index=1, key=f"{key}_trend")
    with c3:
        window = st.selectbox("🪟 Smoothing window", list(WINDOWS), index=1, key=f"{key}_window",
                              disabled=trend not in ("Rolling average", "Rolling average + linear trend"))

    c4, c5, c6, c7 = st.columns([1, 1.4, 1, 1])
    with c4:
        ref_value = st.number_input("📏 Reference line (0 = off)", min_value=0.0, value=0.0,
                                    step=5.0, key=f"{key}_ref")
    with c5:
        ref_label = st.text_input("Reference label", value="", placeholder="e.g. Standard / guideline",
                                  key=f"{key}_ref_label")
    with c6:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        log_y = st.toggle("Log scale", key=f"{key}_log")
    with c7:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        fade = st.toggle("Fade raw lines", value=True, key=f"{key}_fade")

    if not cols:
        st.warning("⚠️ Please select at least one variable to plot.")
        return

    fig = plot_timeseries(df, datetime_col, cols, trend, window, ref_value, ref_label, log_y, fade, title)
    if fig:
        show_chart(fig, key=f"{key}_chart")


def plot_before_after(raw, cleaned_pre, cleaned_final, datetime_col, col, resampled):
    """Raw vs cleaned for one variable, marking removed rows and changed values"""
    is_time = datetime_col is not None and datetime_col in raw.columns
    raw_x = raw[datetime_col] if is_time else pd.Series(raw.index, index=raw.index)
    Trace = scatter_trace(len(raw))

    def line_xy(frame):
        if is_time:
            gapped = insert_gap_breaks(frame.sort_values(datetime_col), datetime_col)
            return gapped[datetime_col], gapped[col]
        return pd.Series(frame.index, index=frame.index), frame[col]

    fig = go.Figure()
    x_line, y_line = line_xy(raw)
    fig.add_trace(Trace(x=x_line, y=y_line, mode="lines", name="Original",
                        line=dict(color=RAW_GREY, width=1.2)))

    if resampled:
        x_line, y_line = line_xy(cleaned_final)
        fig.add_trace(go.Scatter(x=x_line, y=y_line, mode="lines",
                                 name="Cleaned (averaged)", line=dict(color=PRIMARY, width=2.6, shape="hv")))
    elif col in cleaned_pre.columns:
        x_line, y_line = line_xy(cleaned_pre)
        fig.add_trace(Trace(x=x_line, y=y_line, mode="lines", name="Cleaned",
                            line=dict(color=PRIMARY, width=1.8)))

    removed_idx = raw.index.difference(cleaned_pre.index)
    if len(removed_idx):
        r = raw.loc[removed_idx]
        fig.add_trace(Trace(x=raw_x.loc[removed_idx], y=r[col], mode="markers", name=f"Row removed ({len(r):,})",
                            marker=dict(color=REMOVED_RED, symbol="x", size=7)))

    if col in cleaned_pre.columns:
        common = raw.index.intersection(cleaned_pre.index)
        before, after = raw.loc[common, col], cleaned_pre.loc[common, col]
        changed = ~((before == after) | (before.isna() & after.isna()))
        changed_idx = changed[changed].index
        if len(changed_idx):
            fig.add_trace(Trace(x=raw_x.loc[changed_idx], y=before.loc[changed_idx], mode="markers",
                                name=f"Value changed ({len(changed_idx):,})",
                                marker=dict(color=CHANGED_AMBER, size=7, line=dict(color="#fff", width=1))))

    fig.update_layout(title=f"Before vs after cleaning · {col}", hovermode="x unified", height=480,
                      xaxis_title="Time" if is_time else "Row", yaxis_title=col)
    return fig


def plot_distribution(raw, cleaned, col, nbins):
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=raw[col], name="Original", nbinsx=nbins,
                               marker_color=RAW_GREY, opacity=0.55))
    fig.add_trace(go.Histogram(x=cleaned[col], name="Cleaned", nbinsx=nbins,
                               marker_color=PRIMARY, opacity=0.75))
    fig.update_layout(barmode="overlay", title=f"Distribution · {col}", height=420,
                      xaxis_title=col, yaxis_title="Count")
    return fig


def plot_box(raw, cleaned, col):
    fig = go.Figure()
    fig.add_trace(go.Box(y=raw[col], name="Original", marker_color=RAW_GREY, boxmean=True))
    fig.add_trace(go.Box(y=cleaned[col], name="Cleaned", marker_color=PRIMARY, boxmean=True))
    fig.update_layout(title="Spread (box plot)", height=420, showlegend=False, yaxis_title=col)
    return fig


def plot_diurnal(df, datetime_col, cols, split_weekend):
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
                fillcolor=hex_to_rgba(color, 0.15), line=dict(width=0), hoverinfo="skip",
                showlegend=False, legendgroup=name
            ))
            fig.add_trace(go.Scatter(
                x=hours, y=mean, mode="lines+markers", name=name, legendgroup=name,
                line=dict(color=color, width=2.6), marker=dict(size=6),
                hovertemplate=f"<b>{name}</b><br>Hour %{{x}}:00 · mean %{{y:.2f}}<extra></extra>"
            ))

    fig.update_layout(title="Diurnal profile (mean with 25th–75th percentile band)", height=460,
                      xaxis=dict(title="Hour of day", tickmode="linear", dtick=2, range=[-0.5, 23.5]),
                      yaxis_title="Concentration / value")
    return fig


def plot_relationship(df, x_col, y_col):
    data = df[[x_col, y_col]].dropna()
    fig = go.Figure()
    fig.add_trace(scatter_trace(len(data))(
        x=data[x_col], y=data[y_col], mode="markers", name="Observations",
        marker=dict(color=hex_to_rgba(PRIMARY, 0.45), size=6)
    ))
    stats = None
    if len(data) >= 2 and data[x_col].nunique() > 1:
        slope, intercept = np.polyfit(data[x_col], data[y_col], 1)
        r = np.corrcoef(data[x_col], data[y_col])[0, 1]
        xs = np.array([data[x_col].min(), data[x_col].max()])
        fig.add_trace(go.Scatter(
            x=xs, y=intercept + slope * xs, mode="lines", line=dict(color=COLORWAY[2], width=3),
            name=f"Fit: y = {slope:.3f}x {intercept:+.2f}  (R² = {r ** 2:.3f})"
        ))
        stats = {"slope": slope, "intercept": intercept, "r2": r ** 2, "n": len(data)}
    fig.update_layout(title=f"{y_col} vs {x_col}", height=480, xaxis_title=x_col, yaxis_title=y_col)
    return fig, stats


def plot_correlation(df):
    corr = df.select_dtypes(include=[np.number]).corr()
    fig = px.imshow(corr, text_auto=".2f", color_continuous_scale="RdBu", zmin=-1, zmax=1, aspect="auto")
    fig.update_layout(title="Correlation matrix", height=440)
    return fig


def sparkline_values(df, datetime_col, col, points=60):
    """Downsample a series to a handful of points for metric sparklines"""
    s = df.set_index(datetime_col)[col].dropna() if datetime_col else df[col].dropna()
    if s.empty:
        return None
    step = max(1, len(s) // points)
    return s.groupby(np.arange(len(s)) // step).mean().round(2).tolist()


def render_pm_metrics(df, datetime_col):
    pm_cols = [c for c in df.select_dtypes(include=[np.number]).columns if re.search(r"PM|TOTAL", c, re.I)]
    if not pm_cols:
        return
    cols = st.columns(len(pm_cols))
    for col_box, col in zip(cols, pm_cols):
        with col_box:
            st.metric(
                f"Mean {col}", f"{df[col].mean():,.1f}",
                delta=f"max {df[col].max():,.0f}", delta_color="off",
                chart_data=sparkline_values(df, datetime_col, col), chart_type="area"
            )


# -------------------------------
# FUNCTIONS: DATA CLEANING
# -------------------------------
ACTION_REMOVE = "Remove entire row"
ACTION_BLANK = "Set value to blank (NaN)"
ACTION_CAP = "Cap at limit"

OUTLIER_SIGMA = "k-Sigma (mean ± k·SD)"
OUTLIER_IQR = "IQR (Tukey fences)"
OUTLIER_HAMPEL = "Hampel filter (rolling median ± k·MAD)"
OUTLIER_PCT = "Percentile limits"

MISSING_METHODS = [
    "Leave as is",
    "Drop rows with missing values",
    "Linear interpolation",
    "Time-weighted interpolation",
    "Forward fill",
    "Backward fill",
    "Fill with column mean",
    "Fill with column median",
]

AVERAGING_RULES = {"15 minutes": "15min", "30 minutes": "30min", "1 hour": "1h", "8 hours": "8h", "24 hours (daily)": "1D"}


class CleaningRun:
    """Applies cleaning steps to a DataFrame while keeping an audit log"""

    def __init__(self, df):
        self.df = df
        self.log = []
        self.removed = []

    def note(self, step, detail, rows_removed=0, values_changed=0):
        self.log.append({"Step": step, "Details": detail,
                         "Rows removed": int(rows_removed), "Values changed": int(values_changed)})

    def remove_rows(self, mask, step, detail):
        mask = mask.reindex(self.df.index, fill_value=False).astype(bool)
        n = int(mask.sum())
        if n:
            dropped = self.df[mask].copy()
            dropped.insert(0, "Removal reason", f"{step}: {detail}")
            self.removed.append(dropped)
            self.df = self.df[~mask]
        self.note(step, detail, rows_removed=n)

    def apply_action(self, masks, action, step, detail, bounds=None):
        """masks: {column: bool Series}; bounds: {column: (lower, upper)} for capping"""
        if not masks:
            self.note(step, detail + " (no columns selected)")
            return
        if action == ACTION_REMOVE:
            combined = pd.concat(masks.values(), axis=1).any(axis=1)
            self.remove_rows(combined, step, detail)
            return

        changed = 0
        for col, mask in masks.items():
            mask = mask.reindex(self.df.index, fill_value=False) & self.df[col].notna()
            changed += int(mask.sum())
            if action == ACTION_BLANK:
                self.df.loc[mask, col] = np.nan
            elif action == ACTION_CAP and bounds:
                lower, upper = bounds[col]
                self.df[col] = self.df[col].clip(lower=lower, upper=upper)
        self.note(step, f"{detail} → {action}", values_changed=changed)


def outlier_bounds(s, method, params):
    if method == OUTLIER_SIGMA:
        k = params["k"]
        return s.mean() - k * s.std(), s.mean() + k * s.std()
    if method == OUTLIER_IQR:
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        return q1 - params["iqr_mult"] * iqr, q3 + params["iqr_mult"] * iqr
    if method == OUTLIER_HAMPEL:
        window = params["window"]
        median = s.rolling(window, center=True, min_periods=1).median()
        mad = (s - median).abs().rolling(window, center=True, min_periods=1).median()
        scale = (1.4826 * mad).replace(0, np.nan)  # flat stretches are not flagged
        return median - params["k"] * scale, median + params["k"] * scale
    lower_pct, upper_pct = params["pct_range"]
    return s.quantile(lower_pct / 100), s.quantile(upper_pct / 100)


def pm_size(col):
    match = re.search(r"PM\s*([0-9]+(?:\.[0-9]+)?)", col, re.I)
    return float(match.group(1)) if match else None


def consistency_rules(numeric_cols):
    """Pairs (smaller-size column, larger-size column), e.g. PM2.5 ≤ PM10"""
    sized = sorted([(pm_size(c), c) for c in numeric_cols if pm_size(c) is not None])
    rules = []
    for i, (size_a, col_a) in enumerate(sized):
        for size_b, col_b in sized[i + 1:]:
            if size_b > size_a:
                rules.append((col_a, col_b))
    return rules


def run_cleaning(df, cfg):
    run = CleaningRun(df.copy())
    dt = cfg["dt_col"]

    # Step 1: Columns
    keep = list(cfg["keep_cols"]) or list(run.df.columns)
    if dt and dt not in keep:
        keep.insert(0, dt)
    dropped = [c for c in run.df.columns if c not in keep]
    run.df = run.df[keep]
    if dropped:
        run.note("Columns", f"Dropped {len(dropped)} column(s): {', '.join(dropped)}")

    # Step 2: Timestamps and time window
    if dt:
        run.remove_rows(run.df[dt].isna(), "Timestamps", "Missing or unreadable timestamp")
        run.df = run.df.sort_values(dt, kind="stable")
        if cfg["time_window"]:
            start, end = cfg["time_window"]
            outside = (run.df[dt] < pd.Timestamp(start)) | (run.df[dt] > pd.Timestamp(end))
            run.remove_rows(outside, "Time window",
                            f"Outside {pd.Timestamp(start):%d %b %Y %H:%M} – {pd.Timestamp(end):%d %b %Y %H:%M}")

    # Step 3: Duplicates
    if cfg["dedupe"]:
        subset = [dt] if (cfg["dedupe_by_time"] and dt) else None
        run.remove_rows(run.df.duplicated(subset=subset, keep="first"), "Duplicates",
                        "Duplicate timestamp (kept first)" if subset else "Exact duplicate row")

    # Step 4: Valid range limits
    if cfg["range_on"]:
        masks, bounds, parts = {}, {}, []
        for rule in cfg["range_rules"]:
            col, lo, hi = rule["Column"], rule["Min"], rule["Max"]
            if col not in run.df.columns:
                continue
            lo = None if pd.isna(lo) else float(lo)
            hi = None if pd.isna(hi) else float(hi)
            mask = pd.Series(False, index=run.df.index)
            if lo is not None:
                mask |= run.df[col] < lo
            if hi is not None:
                mask |= run.df[col] > hi
            masks[col], bounds[col] = mask, (lo, hi)
            parts.append(f"{col} [{'–∞' if lo is None else f'{lo:g}'}, {'∞' if hi is None else f'{hi:g}'}]")
        run.apply_action(masks, cfg["range_action"], "Range limits", "; ".join(parts) or "No limits set", bounds)

    # Step 5: Size-fraction consistency (e.g. PM2.5 must not exceed PM10)
    if cfg["consistency_on"] and cfg["consistency_rules"]:
        tol = cfg["consistency_tol"] / 100
        for small, large in cfg["consistency_rules"]:
            if small in run.df.columns and large in run.df.columns:
                violated = run.df[small] > run.df[large] * (1 + tol)
                run.remove_rows(violated, "Consistency", f"{small} > {large}" + (f" (+{cfg['consistency_tol']:g}% tolerance)" if tol else ""))

    # Step 6: Stuck sensor / flatline
    if cfg["flat_on"]:
        masks = {}
        for col in cfg["flat_cols"]:
            if col not in run.df.columns:
                continue
            s = run.df[col]
            run_id = (s != s.shift()).cumsum()
            run_len = s.groupby(run_id).transform("size")
            masks[col] = (run_len >= cfg["flat_n"]) & s.notna()
        run.apply_action(masks, cfg["flat_action"], "Stuck sensor",
                         f"≥ {cfg['flat_n']} identical consecutive readings")

    # Step 7: Outliers
    if cfg["outlier_on"]:
        masks, bounds = {}, {}
        for col in cfg["outlier_cols"]:
            if col not in run.df.columns:
                continue
            lower, upper = outlier_bounds(run.df[col], cfg["outlier_method"], cfg["outlier_params"])
            masks[col] = (run.df[col] < lower) | (run.df[col] > upper)
            bounds[col] = (lower, upper)
        run.apply_action(masks, cfg["outlier_action"], "Outliers", cfg["outlier_desc"], bounds)

    # Step 8: Missing values
    method = cfg["missing_method"]
    cols = [c for c in cfg["missing_cols"] if c in run.df.columns]
    if method != "Leave as is" and cols:
        if method == "Drop rows with missing values":
            run.remove_rows(run.df[cols].isna().any(axis=1), "Missing values", f"Blank in {', '.join(cols)}")
        else:
            before = run.df[cols].isna()
            limit = cfg["missing_limit"] or None
            if method == "Linear interpolation":
                filled = run.df[cols].interpolate(method="linear", limit=limit, limit_area="inside")
            elif method == "Time-weighted interpolation" and dt:
                filled = (run.df.set_index(dt)[cols]
                          .interpolate(method="time", limit=limit, limit_area="inside"))
                filled.index = run.df.index
            elif method == "Forward fill":
                filled = run.df[cols].ffill(limit=limit)
            elif method == "Backward fill":
                filled = run.df[cols].bfill(limit=limit)
            elif method == "Fill with column mean":
                filled = run.df[cols].fillna(run.df[cols].mean())
            elif method == "Fill with column median":
                filled = run.df[cols].fillna(run.df[cols].median())
            else:
                filled = run.df[cols]
            run.df[cols] = filled
            n_filled = int((before & run.df[cols].notna()).sum().sum())
            run.note("Missing values", f"{method}" + (f" (max gap {limit})" if limit else ""), values_changed=n_filled)

    pre_resample = run.df.copy()

    # Step 9: Time averaging with completeness check
    resampled = False
    if cfg["avg_on"] and dt:
        rule = AVERAGING_RULES[cfg["avg_rule"]]
        indexed = run.df.set_index(dt)
        numeric = indexed.select_dtypes(include=[np.number])
        interval = indexed.index.to_series().diff().median()
        expected = pd.Timedelta(rule) / interval if pd.notna(interval) and interval > pd.Timedelta(0) else 1
        averaged = numeric.resample(rule).agg(cfg["avg_how"])
        completeness = numeric.resample(rule).count() / expected
        incomplete = (completeness < cfg["avg_completeness"] / 100) & averaged.notna()
        averaged = averaged.where(~incomplete)
        if cfg["avg_drop_empty"]:
            averaged = averaged.dropna(how="all")
        averaged.index.name = dt
        run.df = averaged.reset_index().round(3)
        resampled = True
        run.note("Time averaging",
                 f"{cfg['avg_how'].title()} over {cfg['avg_rule']} → {len(run.df):,} periods; "
                 f"{int(incomplete.sum().sum()):,} value(s) blanked below {cfg['avg_completeness']}% completeness")

    removed = pd.concat(run.removed) if run.removed else pd.DataFrame()
    return {
        "cleaned": run.df,
        "pre_resample": pre_resample,
        "log": pd.DataFrame(run.log, columns=["Step", "Details", "Rows removed", "Values changed"]),
        "removed": removed,
        "resampled": resampled,
    }


def build_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()


# -------------------------------
# HEADER & SIDEBAR
# -------------------------------
st.markdown("""
<div class="hero">
  <div class="hero-badge">DustTrak · QA/QC · Visual analytics</div>
  <div class="hero-title">🌍 Air Quality Data Processing Tool</div>
  <p class="hero-sub">Convert raw DustTrak exports, merge monitoring campaigns, clean and quality-check
  measurements with a full audit trail, and explore trends, diurnal patterns and relationships.</p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown('<div class="side-brand">🌍 AQ Processing Tool</div>', unsafe_allow_html=True)
    st.caption("Workflow")
    for num, text in enumerate([
        "Convert raw DustTrak CSVs (µg/m³, flow errors removed)",
        "Merge converted files into one dataset",
        "Clean: limits, consistency, outliers, gaps, averaging",
        "Explore charts & download cleaned data + report",
    ], start=1):
        st.markdown(f'<div class="side-step"><div class="side-num">{num}</div><div>{text}</div></div>',
                    unsafe_allow_html=True)
    st.divider()
    st.caption("Settings")
    dayfirst = st.toggle("Day-first dates (DD/MM/YYYY) in uploaded files", value=True, key="dayfirst",
                         help="Used when reading dates in CSVs uploaded to the Data Cleaning tab.")
    if st.button("♻️ Reset session", width="stretch"):
        st.session_state.clear()
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption("Every cleaning step is logged and can be downloaded as a report, so decisions remain traceable.")


# -------------------------------
# TABS
# -------------------------------
tab1, tab2 = st.tabs(["📂 DustTrak Data Processing", "🧹 Data Cleaning & Analysis"])

# -------------------------------
# TAB 1: DUSTTRAK PROCESSING (Converter + Merger Combined)
# -------------------------------
with tab1:
    section_header("📂", "DustTrak Data Processing",
                   "Convert raw instrument exports to a standard format, then merge them into one dataset.")

    # ===== SECTION 1: CONVERTER =====
    with st.expander("🔄 Step 1: Convert Raw DustTrak Files", expanded=True):
        st.caption("Upload raw CSV exports from DustTrak instruments. Timestamps are rebuilt from the test start time, "
                   "rows with flow errors are dropped, and mg/m³ is converted to µg/m³.")

        uploaded_files = st.file_uploader(
            "📥 Upload DustTrak CSV file(s)",
            type=["csv"],
            accept_multiple_files=True,
            key="dusttrak_converter"
        )
        include_extra = st.checkbox("Also include PM4 and TOTAL columns", value=False, key="include_extra")

        if uploaded_files and st.button("🔄 Convert Files", type="primary", key="convert_btn"):
            converted, failures = [], []
            used_names = set()
            for file in uploaded_files:
                try:
                    cleaned_df, info = convert_dusttrak_file(file.getvalue(), include_extra)
                except Exception as e:
                    failures.append((file.name, str(e)))
                    continue
                output_name = f"{info['File timestamp']}.csv"
                suffix = 2
                while output_name in used_names:
                    output_name = f"{info['File timestamp']}_{suffix}.csv"
                    suffix += 1
                used_names.add(output_name)
                converted.append({"source": file.name, "output": output_name, "df": cleaned_df, "info": info})
            st.session_state["converted"] = converted
            st.session_state["convert_failures"] = failures

        converted = st.session_state.get("converted", [])
        for name, reason in st.session_state.get("convert_failures", []):
            st.error(f"❌ {name}: {reason}")

        if converted:
            total_rows = sum(c["info"]["Rows"] for c in converted)
            total_flow = sum(c["info"]["Flow-error rows removed"] for c in converted)
            m1, m2, m3 = st.columns(3)
            m1.metric("✅ Files converted", len(converted))
            m2.metric("📊 Rows produced", f"{total_rows:,}")
            m3.metric("🚫 Flow-error rows removed", f"{total_flow:,}")

            summary = pd.DataFrame([{"Source file": c["source"], "Output file": c["output"], **{
                k: v for k, v in c["info"].items() if k != "File timestamp"}} for c in converted])
            st.dataframe(summary, width="stretch", hide_index=True)

            zip_bytes = build_zip({c["output"]: c["df"].to_csv(index=False).encode("utf-8") for c in converted})
            st.download_button(
                label="⬇️ Download All as ZIP",
                data=zip_bytes,
                file_name="dusttrak_converted_files.zip",
                mime="application/zip",
                key="download_converted"
            )

            preview_name = st.selectbox("🔍 Preview a converted file", [c["output"] for c in converted],
                                        key="convert_preview")
            preview = next(c for c in converted if c["output"] == preview_name)
            st.dataframe(preview["df"].head(10), width="stretch", hide_index=True)

    # ===== SECTION 2: MERGER =====
    with st.expander("🔗 Step 2: Merge Converted Files", expanded=True):
        st.caption("Combine converted files into a single, time-sorted dataset. "
                   "Raw DustTrak exports uploaded here are converted automatically.")

        merge_sources = ["Upload converted CSV files"]
        if converted:
            merge_sources.insert(0, f"Use the {len(converted)} file(s) converted in Step 1")
        # Key changes once files are converted, so the radio then defaults to those files
        merge_source = st.radio("Source", merge_sources, horizontal=True, key=f"merge_source_{bool(converted)}")

        merge_files = None
        if merge_source == "Upload converted CSV files":
            merge_files = st.file_uploader(
                "📥 Upload converted CSV file(s) to merge",
                type=["csv"],
                accept_multiple_files=True,
                key="dusttrak_merger"
            )

        o1, o2 = st.columns(2)
        dedupe_merge = o1.checkbox("Remove duplicate timestamps (overlapping files)", value=True, key="merge_dedupe")
        add_source = o2.checkbox("Add a 'Source file' column", value=False, key="merge_add_source")

        ready = bool(merge_files) or merge_source != "Upload converted CSV files"
        if ready and st.button("🔗 Merge Files", type="primary", key="merge_btn"):
            frames = []
            if merge_source == "Upload converted CSV files":
                for file in merge_files:
                    try:
                        data = file.getvalue()
                        if is_raw_dusttrak(data):
                            df, _ = convert_dusttrak_file(data, include_extra)
                        else:
                            df = pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")
                            df.columns = [c.strip() for c in df.columns]
                            # Ensure Timestamp is datetime
                            df["Timestamp"] = pd.to_datetime(df["Timestamp"])
                        if add_source:
                            df["Source file"] = file.name
                        frames.append(df)
                    except Exception as e:
                        st.warning(f"⚠️ Skipping file {file.name}: {e}")
            else:
                for c in converted:
                    df = c["df"].copy()
                    if add_source:
                        df["Source file"] = c["source"]
                    frames.append(df)

            if frames:
                merged_df = pd.concat(frames, ignore_index=True).sort_values("Timestamp", kind="stable")
                duplicates = 0
                if dedupe_merge:
                    dup_mask = merged_df.duplicated(subset=["Timestamp"], keep="first")
                    duplicates = int(dup_mask.sum())
                    merged_df = merged_df[~dup_mask]
                merged_df = merged_df.reset_index(drop=True)
                st.session_state["merged_df"] = merged_df
                st.session_state["merged_token"] = hashlib.md5(
                    pd.util.hash_pandas_object(merged_df, index=False).values.tobytes()).hexdigest()[:10]
                st.session_state["merged_info"] = {"files": len(frames), "duplicates": duplicates}
            else:
                st.error("❌ No valid files to merge.")

    # ===== MERGED RESULT (kept in session so charts survive reruns) =====
    merged_df = st.session_state.get("merged_df")
    if merged_df is not None:
        info = st.session_state["merged_info"]
        st.markdown("")
        section_header("📊", "Merged Dataset",
                       f"{info['files']} file(s) combined · {info['duplicates']:,} duplicate timestamp(s) removed")

        span = merged_df["Timestamp"].max() - merged_df["Timestamp"].min()
        interval = merged_df["Timestamp"].diff().median()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📊 Total rows", f"{len(merged_df):,}")
        c2.metric("📅 Start", f"{merged_df['Timestamp'].min():%d %b %Y}")
        c3.metric("⏱️ Duration", format_timedelta(span))
        c4.metric("🔁 Sampling interval", format_timedelta(interval))
        render_pm_metrics(merged_df, "Timestamp")

        view_ts, view_data = st.tabs(["📈 Time series", "📋 Data preview"])
        with view_ts:
            render_timeseries_explorer(merged_df, "Timestamp", key="merged_ts", title="Merged DustTrak time series")
        with view_data:
            st.dataframe(merged_df.head(200), width="stretch", hide_index=True)

        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                label="⬇️ Download Merged CSV",
                data=merged_df.to_csv(index=False).encode("utf-8"),
                file_name="merged_dusttrak_data.csv",
                mime="text/csv",
                width="stretch",
                key="download_merged"
            )
        with d2:
            if st.button("🧹 Send to Data Cleaning", width="stretch", key="send_to_clean"):
                st.session_state["clean_source"] = "Use merged DustTrak data"
                st.toast("Merged data is ready in the Data Cleaning tab", icon="✅")


# -------------------------------
# TAB 2: DATA CLEANING
# -------------------------------
with tab2:
    section_header("🧹", "Data Cleaning & Quality Control",
                   "Build a cleaning pipeline, apply it, then compare and explore the results.")

    source_options = ["Upload a CSV file"]
    if st.session_state.get("merged_df") is not None:
        source_options.append("Use merged DustTrak data")
    if st.session_state.get("clean_source") not in source_options:
        st.session_state["clean_source"] = source_options[0]
    source = st.radio("Data source", source_options, horizontal=True, key="clean_source")

    df = None
    if source == "Upload a CSV file":
        clean_file = st.file_uploader(
            "📥 Upload CSV file for cleaning",
            type=["csv"],
            key="clean_uploader"
        )
        if clean_file is not None:
            try:
                data = clean_file.getvalue()
                df, was_raw = load_table(data, dayfirst)
                if was_raw:
                    st.info("ℹ️ This looks like a raw DustTrak export — it was converted to µg/m³ automatically.")
                source_name = clean_file.name
                token = hashlib.md5(data).hexdigest()[:10] + ("d" if dayfirst else "m")
            except Exception as e:
                st.error(f"❌ Error reading file: {e}")
    else:
        df = st.session_state["merged_df"]
        source_name = "merged_dusttrak_data.csv"
        token = st.session_state["merged_token"]

    if df is None:
        st.info("💡 Upload a CSV file (or merge DustTrak files in the first tab) to start cleaning.")
    else:
        df = df.reset_index(drop=True)
        numeric_cols_all = df.select_dtypes(include=[np.number]).columns.tolist()
        datetime_cols_all = df.select_dtypes(include=["datetime64"]).columns.tolist()

        # ===== DATA OVERVIEW =====
        primary_dt = datetime_cols_all[0] if datetime_cols_all else None
        missing_pct = df.isna().mean().mean() * 100 if len(df) else 0
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("📊 Rows", f"{len(df):,}")
        c2.metric("📋 Columns", len(df.columns))
        c3.metric("🔢 Numeric cols", len(numeric_cols_all))
        c4.metric("⏱️ Time span", format_timedelta(df[primary_dt].max() - df[primary_dt].min()) if primary_dt else "–")
        c5.metric("🕳️ Missing cells", f"{missing_pct:.1f}%")

        ov_preview, ov_profile, ov_missing = st.tabs(["📋 Preview", "🔍 Column profile", "🕳️ Missing values"])
        with ov_preview:
            st.dataframe(df.head(15), width="stretch", hide_index=True)
        with ov_profile:
            profile = pd.DataFrame({
                "Column": df.columns,
                "Data type": df.dtypes.astype(str).values,
                "Non-missing": df.notna().sum().values,
                "Missing %": (df.isna().mean() * 100).round(2).values,
                "Unique values": df.nunique().values,
            })
            numeric_summary = df[numeric_cols_all].agg(["min", "mean", "max"]).T.round(3) if numeric_cols_all else None
            if numeric_summary is not None:
                profile = profile.merge(numeric_summary, left_on="Column", right_index=True, how="left")
            st.dataframe(profile, width="stretch", hide_index=True, column_config={
                "Missing %": st.column_config.ProgressColumn("Missing %", min_value=0, max_value=100, format="%.1f%%")
            })
        with ov_missing:
            miss = (df.isna().mean() * 100).sort_values()
            if miss.sum() == 0:
                st.success("✅ No missing values in this dataset.")
            else:
                fig = px.bar(miss, orientation="h", labels={"value": "Missing %", "index": ""},
                             color_discrete_sequence=[CHANGED_AMBER])
                fig.update_layout(title="Share of missing values by column", showlegend=False,
                                  height=max(260, 34 * len(miss)))
                show_chart(fig, key="missing_chart")

        st.markdown("")

        # ===== CLEANING OPTIONS =====
        section_header("🛠️", "Cleaning Pipeline",
                       "Steps run top to bottom. Enable the ones you need — nothing changes until you press Apply.")
        k = token  # widget keys are tied to the dataset, so switching files resets the options

        dt_choice = st.selectbox("⏱️ Timestamp column (used for sorting, time filters, interpolation & averaging)",
                                 datetime_cols_all + ["(none)"], key=f"dt_col_{k}")
        dt_col = None if dt_choice == "(none)" else dt_choice

        # ===== SECTION 1: COLUMNS & TIME WINDOW =====
        with st.expander("1️⃣ Columns & time window", expanded=False):
            keep_cols = st.multiselect("Columns to keep in the output", df.columns.tolist(),
                                       default=df.columns.tolist(), key=f"keep_{k}")
            time_window = None
            if dt_col:
                t_min, t_max = df[dt_col].min(), df[dt_col].max()
                if pd.notna(t_min) and pd.notna(t_max) and t_max > t_min:
                    use_window = st.toggle("Restrict to a time window", key=f"tw_on_{k}")
                    if use_window:
                        time_window = st.slider(
                            "Time window", min_value=t_min.to_pydatetime(), max_value=t_max.to_pydatetime(),
                            value=(t_min.to_pydatetime(), t_max.to_pydatetime()),
                            step=timedelta(minutes=1), format="DD MMM YYYY HH:mm", key=f"tw_{k}"
                        )

        # ===== SECTION 2: DUPLICATES =====
        with st.expander("2️⃣ Duplicate records", expanded=False):
            dedupe = st.toggle("Remove duplicates", value=True, key=f"dedupe_{k}")
            dedupe_by_time = st.radio("Treat rows as duplicates when they share…",
                                      ["the same timestamp", "identical values in every column"],
                                      horizontal=True, key=f"dedupe_by_{k}", disabled=not dedupe) == "the same timestamp"

        # ===== SECTION 3: VALID RANGE =====
        with st.expander("3️⃣ Valid range limits (physical / instrument limits)", expanded=False):
            range_on = st.toggle("Apply range limits", value=True, key=f"range_on_{k}",
                                 help="Concentrations below zero are physically impossible; "
                                      "set an upper limit to drop values above the instrument's measurable range.")
            range_table = pd.DataFrame({"Column": numeric_cols_all, "Apply": True,
                                        "Min": 0.0, "Max": np.nan})
            edited_range = st.data_editor(
                range_table, hide_index=True, width="stretch", key=f"range_tbl_{k}", disabled=["Column"],
                column_config={
                    "Apply": st.column_config.CheckboxColumn("Apply"),
                    "Min": st.column_config.NumberColumn("Min (blank = none)", format="%.3f"),
                    "Max": st.column_config.NumberColumn("Max (blank = none)", format="%.3f"),
                },
            )
            range_action = st.radio("Values outside the limits:", [ACTION_REMOVE, ACTION_BLANK, ACTION_CAP],
                                    index=1, horizontal=True, key=f"range_act_{k}")

        # ===== SECTION 4: CONSISTENCY =====
        rules = consistency_rules(numeric_cols_all)
        with st.expander("4️⃣ Size-fraction consistency (e.g. PM2.5 ≤ PM10)", expanded=False):
            if rules:
                consistency_on = st.toggle("Remove rows where a finer fraction exceeds a coarser one",
                                           value=True, key=f"cons_on_{k}")
                rule_labels = {f"{a}  ≤  {b}": (a, b) for a, b in rules}
                chosen_rules = st.multiselect("Rules", list(rule_labels), default=list(rule_labels),
                                              key=f"cons_rules_{k}")
                consistency_tol = st.slider("Tolerance (%)", 0.0, 20.0, 0.0, 0.5, key=f"cons_tol_{k}",
                                            help="Allow the finer fraction to exceed the coarser one by this much "
                                                 "before flagging (useful for instrument noise at low concentrations).")
                consistency_selected = [rule_labels[r] for r in chosen_rules]
            else:
                st.caption("No PM size columns (e.g. 'PM2.5', 'PM10') detected in this dataset.")
                consistency_on, consistency_selected, consistency_tol = False, [], 0.0

        # ===== SECTION 5: STUCK SENSOR =====
        with st.expander("5️⃣ Stuck sensor / flatline detection", expanded=False):
            flat_on = st.toggle("Detect repeated identical readings", value=False, key=f"flat_on_{k}")
            f1, f2 = st.columns([2, 1])
            flat_cols = f1.multiselect("Columns", numeric_cols_all, default=numeric_cols_all,
                                       key=f"flat_cols_{k}", disabled=not flat_on)
            flat_n = f2.number_input("Minimum run length", min_value=3, value=10, step=1,
                                     key=f"flat_n_{k}", disabled=not flat_on)
            flat_action = st.radio("Flagged readings:", [ACTION_BLANK, ACTION_REMOVE], horizontal=True,
                                   key=f"flat_act_{k}", disabled=not flat_on)

        # ===== SECTION 6: OUTLIERS =====
        with st.expander("6️⃣ Outlier detection", expanded=False):
            outlier_on = st.toggle("Enable outlier removal", value=False, key=f"out_on_{k}")
            col_left, col_right = st.columns([1.2, 2])
            with col_left:
                outlier_method = st.selectbox(
                    "🎯 Method", [OUTLIER_SIGMA, OUTLIER_IQR, OUTLIER_HAMPEL, OUTLIER_PCT],
                    key=f"out_method_{k}", disabled=not outlier_on,
                    help="Hampel compares each point with its local rolling median, so it catches short spikes "
                         "without removing genuine pollution episodes."
                )
            with col_right:
                outlier_cols = st.multiselect("Columns", numeric_cols_all,
                                              default=default_pm_columns(numeric_cols_all, limit=3),
                                              key=f"out_cols_{k}", disabled=not outlier_on)

            params = {}
            p1, p2 = st.columns(2)
            if outlier_method == OUTLIER_SIGMA:
                params["k"] = p1.slider("k (number of standard deviations)", 1.5, 6.0, 3.0, 0.5,
                                        key=f"out_k_{k}", disabled=not outlier_on)
                outlier_desc = f"Mean ± {params['k']:g}·SD"
            elif outlier_method == OUTLIER_IQR:
                params["iqr_mult"] = p1.slider("IQR multiplier", 1.0, 5.0, 1.5, 0.5,
                                               key=f"out_iqr_{k}", disabled=not outlier_on)
                outlier_desc = f"Q1/Q3 ± {params['iqr_mult']:g}·IQR"
            elif outlier_method == OUTLIER_HAMPEL:
                params["window"] = p1.slider("Window (number of readings)", 5, 241, 31, 2,
                                             key=f"out_win_{k}", disabled=not outlier_on)
                params["k"] = p2.slider("k (number of scaled MADs)", 2.0, 8.0, 3.0, 0.5,
                                        key=f"out_hk_{k}", disabled=not outlier_on)
                outlier_desc = f"Hampel, window {params['window']}, k = {params['k']:g}"
            else:
                params["pct_range"] = p1.slider("Keep values between percentiles", 0.0, 100.0, (1.0, 99.0), 0.5,
                                                key=f"out_pct_{k}", disabled=not outlier_on)
                outlier_desc = f"Outside P{params['pct_range'][0]:g}–P{params['pct_range'][1]:g}"
            outlier_action = st.radio("Outliers:", [ACTION_REMOVE, ACTION_BLANK, ACTION_CAP], horizontal=True,
                                      key=f"out_act_{k}", disabled=not outlier_on,
                                      help="'Set value to blank' keeps the rest of the row, e.g. PM2.5 is kept "
                                           "when only PM10 is an outlier.")

            if outlier_on and outlier_cols:
                preview_rows = []
                for col in outlier_cols:
                    s = df[col]
                    lo, hi = outlier_bounds(s, outlier_method, params)
                    flagged = int(((s < lo) | (s > hi)).sum())
                    preview_rows.append({"Column": col, "Flagged (on original data)": flagged,
                                         "% of readings": round(flagged / max(s.notna().sum(), 1) * 100, 2)})
                st.caption("Preview")
                st.dataframe(pd.DataFrame(preview_rows), hide_index=True, width="stretch")

        # ===== SECTION 7: MISSING VALUES =====
        with st.expander("7️⃣ Missing values (NA / empty)", expanded=False):
            m1, m2 = st.columns([1.3, 1])
            available_methods = [m for m in MISSING_METHODS if dt_col or m != "Time-weighted interpolation"]
            missing_method = m1.selectbox("Handling method", available_methods, key=f"miss_m_{k}",
                                          help="Runs after the steps above, so it also handles values blanked by them.")
            missing_limit = m2.number_input("Max consecutive gap to fill (0 = no limit)", min_value=0, value=5,
                                            step=1, key=f"miss_lim_{k}",
                                            disabled=missing_method in ("Leave as is", "Drop rows with missing values",
                                                                        "Fill with column mean", "Fill with column median"))
            default_missing_cols = numeric_cols_all if missing_method != "Drop rows with missing values" else df.columns.tolist()
            missing_cols = st.multiselect("Columns", df.columns.tolist(), default=default_missing_cols,
                                          key=f"miss_cols_{k}", disabled=missing_method == "Leave as is")

        # ===== SECTION 8: AVERAGING =====
        with st.expander("8️⃣ Time averaging (resample)", expanded=False):
            if dt_col:
                avg_on = st.toggle("Average to a coarser time resolution", value=False, key=f"avg_on_{k}")
                a1, a2, a3 = st.columns(3)
                avg_rule = a1.selectbox("Averaging period", list(AVERAGING_RULES), index=2,
                                        key=f"avg_rule_{k}", disabled=not avg_on)
                avg_how = a2.selectbox("Statistic", ["mean", "median", "max", "min"], key=f"avg_how_{k}",
                                       disabled=not avg_on)
                avg_completeness = a3.slider("Minimum data completeness (%)", 0, 100, 75, 5, key=f"avg_comp_{k}",
                                             disabled=not avg_on,
                                             help="Periods with fewer valid readings than this share of the expected "
                                                  "number are left blank instead of being averaged.")
                avg_drop_empty = st.checkbox("Drop periods with no valid data", value=True, key=f"avg_drop_{k}",
                                             disabled=not avg_on)
            else:
                st.caption("Select a timestamp column above to enable time averaging.")
                avg_on, avg_rule, avg_how, avg_completeness, avg_drop_empty = False, "1 hour", "mean", 75, True

        # ===== PIPELINE SUMMARY =====
        steps = [
            ("Columns", len(keep_cols) < len(df.columns) or bool(time_window)),
            ("Duplicates", dedupe),
            ("Range limits", range_on),
            ("Consistency", consistency_on and bool(consistency_selected)),
            ("Stuck sensor", flat_on),
            ("Outliers", outlier_on),
            ("Missing values", missing_method != "Leave as is"),
            ("Averaging", avg_on),
        ]
        chips = "".join(f'<span class="chip{"" if on else " off"}">{name}</span>' for name, on in steps)
        st.markdown(f'<div class="chip-row">{chips}</div>', unsafe_allow_html=True)

        # ===== APPLY CLEANING BUTTON =====
        if st.button("✨ Apply Cleaning Pipeline", key=f"apply_{k}", type="primary", width="stretch"):
            cfg = {
                "dt_col": dt_col,
                "keep_cols": keep_cols,
                "time_window": time_window,
                "dedupe": dedupe,
                "dedupe_by_time": dedupe_by_time,
                "range_on": range_on,
                "range_rules": edited_range[edited_range["Apply"]].to_dict("records"),
                "range_action": range_action,
                "consistency_on": consistency_on,
                "consistency_rules": consistency_selected,
                "consistency_tol": consistency_tol,
                "flat_on": flat_on,
                "flat_cols": flat_cols,
                "flat_n": int(flat_n),
                "flat_action": flat_action,
                "outlier_on": outlier_on,
                "outlier_cols": outlier_cols,
                "outlier_method": outlier_method,
                "outlier_params": params,
                "outlier_desc": outlier_desc,
                "outlier_action": outlier_action,
                "missing_method": missing_method,
                "missing_cols": missing_cols,
                "missing_limit": int(missing_limit),
                "avg_on": avg_on,
                "avg_rule": avg_rule,
                "avg_how": avg_how,
                "avg_completeness": avg_completeness,
                "avg_drop_empty": avg_drop_empty,
            }
            try:
                with st.spinner("Cleaning data…"):
                    result = run_cleaning(df, cfg)
                result.update({"token": token, "dt_col": dt_col, "source_name": source_name,
                               "applied_at": datetime.now()})
                st.session_state["clean_results"] = result
            except Exception as e:
                st.error(f"❌ Error while cleaning: {e}")

        # ===== RESULTS (rendered from session state, so charts work after any widget change) =====
        result = st.session_state.get("clean_results")
        if result and result["token"] == token:
            cleaned = result["cleaned"]
            pre = result["pre_resample"]
            res_dt = result["dt_col"]
            log = result["log"]
            initial_rows = len(df)
            rows_removed = int(log["Rows removed"].sum())
            values_changed = int(log["Values changed"].sum())

            st.markdown("")
            section_header("✅", "Cleaning Results",
                           f"Pipeline applied at {result['applied_at']:%H:%M:%S} · "
                           "change options above and press Apply again to update")

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Initial rows", f"{initial_rows:,}")
            c2.metric("Rows removed", f"{rows_removed:,}")
            c3.metric("Values changed", f"{values_changed:,}")
            c4.metric("Final rows", f"{len(cleaned):,}",
                      delta="averaged" if result["resampled"] else None, delta_color="off")
            retained_pct = (len(pre) / initial_rows * 100) if initial_rows else 0
            c5.metric("Rows retained", f"{retained_pct:.1f}%")

            st.dataframe(log, width="stretch", hide_index=True, column_config={
                "Rows removed": st.column_config.NumberColumn(format="%d"),
                "Values changed": st.column_config.NumberColumn(format="%d"),
            })

            numeric_clean = cleaned.select_dtypes(include=[np.number]).columns.tolist()
            raw_for_compare = df.loc[:, [c for c in df.columns if c in pre.columns]]

            r_ts, r_ba, r_dist, r_diurnal, r_rel, r_data, r_removed = st.tabs([
                "📈 Time series & trends", "⚖️ Before vs after", "📊 Distribution",
                "🕒 Diurnal pattern", "🔗 Relationships", "📋 Data & statistics", "🗑️ Removed rows"
            ])

            with r_ts:
                render_timeseries_explorer(cleaned, res_dt, key=f"clean_ts_{k}", title="Cleaned time series")

            with r_ba:
                if numeric_clean:
                    ba_col = st.selectbox("Variable", numeric_clean, key=f"ba_col_{k}",
                                          index=numeric_clean.index(default_pm_columns(numeric_clean, 1)[0]))
                    show_chart(plot_before_after(raw_for_compare, pre, cleaned, res_dt, ba_col, result["resampled"]),
                               key=f"ba_chart_{k}")
                    if res_dt and ba_col in raw_for_compare.columns:
                        before, after = raw_for_compare[ba_col], cleaned[ba_col]
                        s1, s2, s3, s4 = st.columns(4)
                        s1.metric("Mean", f"{after.mean():.2f}", help="Cleaned value; the delta is the change from the original data.",
                                  delta=f"{after.mean() - before.mean():+.2f}", delta_color="off")
                        s2.metric("Median", f"{after.median():.2f}",
                                  delta=f"{after.median() - before.median():+.2f}", delta_color="off")
                        s3.metric("Std. deviation", f"{after.std():.2f}",
                                  delta=f"{after.std() - before.std():+.2f}", delta_color="off")
                        s4.metric("Maximum", f"{after.max():.2f}",
                                  delta=f"{after.max() - before.max():+.2f}", delta_color="off")
                else:
                    st.info("💡 No numeric columns to compare.")

            with r_dist:
                if numeric_clean:
                    d1, d2 = st.columns([2, 1])
                    dist_col = d1.selectbox("Variable", numeric_clean, key=f"dist_col_{k}")
                    nbins = d2.slider("Bins", 10, 150, 50, 5, key=f"dist_bins_{k}")
                    g1, g2 = st.columns([2, 1])
                    with g1:
                        show_chart(plot_distribution(raw_for_compare, cleaned, dist_col, nbins), key=f"dist_chart_{k}")
                    with g2:
                        show_chart(plot_box(raw_for_compare, cleaned, dist_col), key=f"box_chart_{k}")

            with r_diurnal:
                if res_dt and numeric_clean:
                    d1, d2 = st.columns([3, 1])
                    diurnal_cols = d1.multiselect("Variables", numeric_clean,
                                                  default=default_pm_columns(numeric_clean), key=f"diu_cols_{k}")
                    d2.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                    split = d2.toggle("Weekdays vs weekends", key=f"diu_split_{k}")
                    if diurnal_cols:
                        show_chart(plot_diurnal(cleaned, res_dt, diurnal_cols, split), key=f"diu_chart_{k}")
                    st.caption("Shows how concentrations typically vary through the day. "
                               "Needs data covering several days for a meaningful pattern.")
                else:
                    st.info("💡 A timestamp column is needed for the diurnal profile.")

            with r_rel:
                if len(numeric_clean) >= 2:
                    pm_defaults = default_pm_columns(numeric_clean)
                    x_default = pm_defaults[0] if len(pm_defaults) > 0 else numeric_clean[0]
                    y_default = pm_defaults[1] if len(pm_defaults) > 1 else numeric_clean[1]
                    x1, x2 = st.columns(2)
                    x_col = x1.selectbox("X axis", numeric_clean, index=numeric_clean.index(y_default),
                                         key=f"rel_x_{k}")
                    y_col = x2.selectbox("Y axis", numeric_clean, index=numeric_clean.index(x_default),
                                         key=f"rel_y_{k}")
                    g1, g2 = st.columns([3, 2])
                    with g1:
                        fig, stats = plot_relationship(cleaned, x_col, y_col)
                        show_chart(fig, key=f"rel_chart_{k}")
                    with g2:
                        show_chart(plot_correlation(cleaned), key=f"corr_chart_{k}")
                    if stats:
                        ratio = (cleaned[y_col] / cleaned[x_col].replace(0, np.nan)).dropna()
                        s1, s2, s3 = st.columns(3)
                        s1.metric("R²", f"{stats['r2']:.3f}")
                        s2.metric("Slope", f"{stats['slope']:.3f}")
                        s3.metric(f"Median ratio {y_col} / {x_col}", f"{ratio.median():.2f}" if len(ratio) else "–")
                else:
                    st.info("💡 At least two numeric columns are needed.")

            with r_data:
                st.markdown("**Cleaned data**")
                st.dataframe(cleaned, width="stretch", hide_index=True, height=360)
                st.markdown("**Descriptive statistics (cleaned)**")
                if numeric_clean:
                    st.dataframe(cleaned[numeric_clean].describe().T.round(3), width="stretch")
                st.markdown("**Data types**")
                st.dataframe(pd.DataFrame({"Column": cleaned.columns, "Data type": cleaned.dtypes.astype(str).values}),
                             width="stretch", hide_index=True)

            with r_removed:
                removed = result["removed"]
                if removed.empty:
                    st.success("✅ No rows were removed.")
                else:
                    counts = removed["Removal reason"].value_counts().sort_values()
                    fig = px.bar(counts, orientation="h", labels={"value": "Rows", "index": ""},
                                 color_discrete_sequence=[REMOVED_RED])
                    fig.update_layout(title="Rows removed by reason", showlegend=False,
                                      height=max(240, 46 * len(counts)))
                    show_chart(fig, key=f"removed_chart_{k}")
                    st.dataframe(removed, width="stretch", hide_index=True, height=320)

            # ===== DOWNLOADS =====
            st.markdown("")
            section_header("⬇️", "Downloads", "Cleaned data plus an audit trail of every change.")
            base_name = source_name.rsplit(".", 1)[0]
            csv_cleaned = cleaned.to_csv(index=False).encode("utf-8")
            csv_log = log.to_csv(index=False).encode("utf-8")
            csv_removed = result["removed"].to_csv(index=False).encode("utf-8")
            dl1, dl2, dl3, dl4 = st.columns(4)
            dl1.download_button("⬇️ Cleaned CSV", csv_cleaned, f"cleaned_{base_name}.csv", "text/csv",
                                width="stretch", type="primary", key=f"dl_clean_{k}")
            dl2.download_button("📝 Cleaning report", csv_log, f"cleaning_report_{base_name}.csv", "text/csv",
                                width="stretch", key=f"dl_log_{k}")
            dl3.download_button("🗑️ Removed rows", csv_removed, f"removed_rows_{base_name}.csv", "text/csv",
                                width="stretch", key=f"dl_removed_{k}", disabled=result["removed"].empty)
            dl4.download_button("📦 Everything (ZIP)", build_zip({
                f"cleaned_{base_name}.csv": csv_cleaned,
                f"cleaning_report_{base_name}.csv": csv_log,
                f"removed_rows_{base_name}.csv": csv_removed,
            }), f"cleaning_bundle_{base_name}.zip", "application/zip", width="stretch", key=f"dl_zip_{k}")
