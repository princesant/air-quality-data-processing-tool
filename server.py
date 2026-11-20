# -*- coding: utf-8 -*-
"""Flask web app for the Air Quality Data Processing Tool.

Run with:  python server.py   then open http://127.0.0.1:5000
Uploaded and processed data is held in memory for this session only."""
import io
import json
import math
import os
import threading
import uuid
import zipfile
from collections import OrderedDict
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.offline
from flask import Flask, Response, abort, render_template, request, send_file
from werkzeug.exceptions import HTTPException

import aq_charts as charts
import aq_core as core

app = Flask(__name__)
# Limits can be lowered on small hosted instances through environment variables
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", 500)) * 1024 * 1024
# Keep the instrument order (DustTrak, weather station, C-12) in the options passed to the page
app.jinja_env.policies["json.dumps_kwargs"] = {"sort_keys": False}

# ===== IN-MEMORY STORE =====
STORE = OrderedDict()
STORE_LOCK = threading.Lock()
MAX_ITEMS = int(os.environ.get("MAX_STORED_ITEMS", 40))


def put(item):
    item_id = uuid.uuid4().hex[:12]
    with STORE_LOCK:
        STORE[item_id] = item
        while len(STORE) > MAX_ITEMS:
            STORE.popitem(last=False)
    return item_id


def get(item_id, kind):
    item = STORE.get(item_id)
    if item is None or item["kind"] != kind:
        abort(404, description=f"This {kind} is no longer available — please upload or process it again.")
    return item


# ===== JSON HELPERS =====
def clean_json(obj):
    """Make pandas/numpy values JSON-safe (NaN → null)"""
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, pd.Timestamp):
        return None if pd.isna(obj) else obj.strftime("%Y-%m-%d %H:%M:%S")
    if obj is pd.NaT:
        return None
    return obj


def jresp(obj, status=200):
    return Response(json.dumps(clean_json(obj)), status=status, mimetype="application/json")


def figure_response(fig, **extra):
    body = '{"figure":' + fig.to_json() + ',"extra":' + json.dumps(clean_json(extra)) + "}"
    return Response(body, mimetype="application/json")


def records(df, limit=None, offset=0):
    part = df.iloc[offset:offset + limit] if limit else df
    out = part.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d %H:%M:%S")
    out = out.astype(object).where(out.notna(), None)
    return {"columns": [str(c) for c in out.columns], "rows": out.values.tolist(), "total": len(df)}


def csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8-sig")


def download(data, filename, mimetype="text/csv"):
    return send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True, download_name=filename)


def build_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()


@app.errorhandler(Exception)
def handle_error(e):
    if isinstance(e, HTTPException):
        return jresp({"error": e.description}, e.code)
    app.logger.exception(e)
    return jresp({"error": str(e)}, 500)


# ===== DATASET SUMMARY =====
def sparkline(series, points=60):
    s = series.dropna()
    if s.empty:
        return []
    step = max(1, len(s) // points)
    return s.groupby(np.arange(len(s)) // step).mean().round(2).tolist()


def dataset_summary(dataset_id):
    item = get(dataset_id, "dataset")
    df = item["df"]
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    datetime_cols = df.select_dtypes(include=["datetime64"]).columns.tolist()
    dt = datetime_cols[0] if datetime_cols else None
    instrument = item["meta"].get("instrument") or core.instrument_from_columns(df.columns)
    defaults = core.instrument_defaults(instrument, df)

    summary = {
        "id": dataset_id,
        "name": item["name"],
        "rows": len(df),
        "columns": [str(c) for c in df.columns],
        "numeric_cols": numeric_cols,
        "datetime_cols": datetime_cols,
        "instrument": instrument,
        "instrument_label": core.instrument_info(instrument)["label"],
        "default_plot_cols": defaults["plot_cols"],
        "missing_pct": float(df.isna().mean().mean() * 100) if len(df) else 0.0,
        "consistency_rules": defaults["consistency"],
        "defaults": {k: v for k, v in defaults.items() if k not in ("plot_cols", "consistency")},
        "meta": item.get("meta", {}),
        "preview": records(df, limit=15),
    }

    if dt:
        t = df[dt].dropna().sort_values()
        gaps, step = core.find_gaps(t)
        summary.update({
            "start": t.min(), "end": t.max(),
            "span": core.format_timedelta(t.max() - t.min()) if len(t) else "–",
            "interval": core.format_timedelta(step),
            "gaps": [{"start": a, "end": b, "length": core.format_timedelta(b - a)} for a, b in gaps],
        })

    sorted_df = df.sort_values(dt) if dt else df
    card_cols = defaults["plot_cols"] + [c for c in numeric_cols if c not in defaults["plot_cols"]
                                         and c not in defaults["avg_special"] and c != "Status"]
    summary["pm_cards"] = [{
        "column": c, "mean": df[c].mean(), "max": df[c].max(), "spark": sparkline(sorted_df[c])
    } for c in card_cols[:6]]

    profile = []
    for c in df.columns:
        s = df[c]
        row = {"Column": str(c), "Type": str(s.dtype), "Non-missing": int(s.notna().sum()),
               "Missing %": round(float(s.isna().mean() * 100), 2), "Unique": int(s.nunique())}
        if c in numeric_cols:
            row.update({"Min": s.min(), "Mean": round(float(s.mean()), 3) if s.notna().any() else None, "Max": s.max()})
        profile.append(row)
    summary["profile"] = profile
    return summary


def register_dataset(df, name, meta=None):
    meta = meta or {}
    meta.setdefault("instrument", core.instrument_from_columns(df.columns))
    return put({"kind": "dataset", "df": df.reset_index(drop=True), "name": name, "meta": meta})


def convert_options():
    return {"unit": request.form.get("unit", "ng/m3"), "bar_to_hpa": request.form.get("bar_to_hpa", "true") == "true"}


def requested_instrument():
    instrument = request.form.get("instrument", "dusttrak")
    if instrument not in core.INSTRUMENTS:
        abort(400, description=f"Unknown instrument '{instrument}'.")
    return instrument


# -------------------------------
# PAGES
# -------------------------------
@app.route("/")
def index():
    return render_template("index.html", options={
        "instruments": core.INSTRUMENTS,
        "trend_options": charts.TREND_OPTIONS,
        "windows": list(charts.WINDOWS),
        "outlier_methods": [core.OUTLIER_SIGMA, core.OUTLIER_IQR, core.OUTLIER_HAMPEL, core.OUTLIER_PCT],
        "missing_methods": core.MISSING_METHODS,
        "averaging_rules": list(core.AVERAGING_RULES),
        "actions": [core.ACTION_REMOVE, core.ACTION_BLANK, core.ACTION_CAP],
    })


_PLOTLY_JS = None


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.route("/vendor/plotly.min.js")
def plotly_js():
    """Serve Plotly.js from the installed Python package, so charts work offline"""
    global _PLOTLY_JS
    if _PLOTLY_JS is None:
        _PLOTLY_JS = plotly.offline.get_plotlyjs()
    resp = Response(_PLOTLY_JS, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


# -------------------------------
# API: CONVERT & MERGE
# -------------------------------
def convert_stats(instrument, files, alarms):
    """Headline numbers for the Convert page, specific to each instrument"""
    total = lambda key: sum(f["info"].get(key, 0) for f in files)
    stats = [{"label": "Files converted", "value": len(files)},
             {"label": "Rows produced", "value": total("Rows"), "sub": "1 row per logged reading", "tone": "blue"}]
    if instrument == "dusttrak":
        n = total("Flow-error rows removed")
        stats.append({"label": "Flow-error rows removed", "value": n, "sub": "Flagged 'Flow Error' by the instrument",
                      "tone": "red" if n else ""})
    elif instrument == "aws":
        n, d = total("Invalid dates dropped"), total("Duplicate timestamps")
        stats.append({"label": "Invalid dates dropped", "value": n, "sub": "e.g. 31 April from the logger clock",
                      "tone": "red" if n else ""})
        stats.append({"label": "Duplicate timestamps", "value": d, "sub": "handled in Merge and Clean",
                      "tone": "amber" if d else ""})
    else:
        n, z = total("Rows with alarm codes"), total("All-zero readings")
        stats.append({"label": "Rows with status codes", "value": n, "sub": "decoded in the Alarms column",
                      "tone": "amber" if n else ""})
        stats.append({"label": "All-zero readings", "value": z, "sub": "instrument not measuring", "tone": "amber" if z else ""})
        stats.append({"label": "Alarm log events", "value": len(alarms), "sub": "from Alarm.TXT"})
    return stats


@app.post("/api/convert")
def api_convert():
    instrument = requested_instrument()
    include_extra = request.form.get("include_extra") == "true"
    uploads = [(f.filename, f.read()) for f in request.files.getlist("files")]
    res = core.convert_files(uploads, instrument, include_extra, convert_options())
    converted, alarms = res["converted"], res["alarms"]

    batch_id = put({"kind": "batch", "instrument": instrument, "files": converted, "alarms": alarms}) if converted else None
    columns = []
    for c in converted:
        columns += [k for k in c["info"] if k not in columns and k != "File timestamp"]
    return jresp({
        "batch_id": batch_id,
        "instrument": instrument,
        "failures": res["failures"],
        "stats": convert_stats(instrument, converted, alarms),
        "info_columns": columns,
        "files": [{"source": c["source"], "output": c["output"], **c["info"]} for c in converted],
        "preview": {c["output"]: records(c["df"], limit=10) for c in converted},
        "alarms": records(alarms, limit=300) if len(alarms) else None,
    })


@app.get("/api/batch/<batch_id>/zip")
def api_batch_zip(batch_id):
    batch = get(batch_id, "batch")
    files = {c["output"]: csv_bytes(c["df"]) for c in batch["files"]}
    if len(batch.get("alarms", [])):
        files["alarm_log.csv"] = csv_bytes(batch["alarms"])
    return download(build_zip(files), f"{batch['instrument']}_converted_files.zip", "application/zip")


@app.post("/api/merge")
def api_merge():
    dedupe = request.form.get("dedupe", "true") == "true"
    add_source = request.form.get("add_source") == "true"
    include_extra = request.form.get("include_extra") == "true"
    instrument = requested_instrument()
    frames, warnings_ = [], []

    def add(df, source):
        df = df.copy()
        if add_source:
            df["Source file"] = source
        frames.append(df)

    batch_id = request.form.get("batch_id")
    if batch_id:
        batch = get(batch_id, "batch")
        instrument = batch["instrument"]
        for c in batch["files"]:
            add(c["df"], c["source"])

    uploads = [(f.filename, f.read()) for f in request.files.getlist("files")]
    is_raw = [core.classify_file(d) != "table" for _, d in uploads]
    raw = [u for u, r in zip(uploads, is_raw) if r]
    if raw:
        res = core.convert_files(raw, instrument, include_extra, convert_options())
        warnings_ += [f"Skipped {f['file']}: {f['reason']}" for f in res["failures"]]
        for c in res["converted"]:
            add(c["df"], c["source"])
    for (name, data), r in zip(uploads, is_raw):
        if r:
            continue
        try:
            df = core.read_converted_table(name, data)
            found = core.instrument_from_columns(df.columns)
            if found not in (instrument, "generic"):
                warnings_.append(f"Skipped {name}: it looks like {core.instrument_info(found)['label']} data, "
                                 f"not {core.instrument_info(instrument)['label']}")
                continue
            add(df, name)
        except Exception as e:
            warnings_.append(f"Skipped {name}: {e}")

    if not frames:
        abort(400, description="No valid files to merge. " + " ".join(warnings_))

    merged, duplicates = core.merge_frames(frames, dedupe)
    dataset_id = register_dataset(merged, f"merged_{instrument}_data.csv",
                                  {"files": len(frames), "duplicates": duplicates, "instrument": instrument})
    return jresp({"dataset": dataset_summary(dataset_id), "warnings": warnings_})


# -------------------------------
# API: DATASETS
# -------------------------------
@app.post("/api/upload")
def api_upload():
    file = request.files.get("file")
    if file is None:
        abort(400, description="No file received.")
    dayfirst = request.form.get("dayfirst", "true") == "true"
    df, raw_instrument = core.load_table(file.read(), dayfirst)
    meta = {"converted_from_raw": raw_instrument}
    if raw_instrument:
        meta["instrument"] = raw_instrument
    dataset_id = register_dataset(df, file.filename, meta)
    return jresp({"dataset": dataset_summary(dataset_id)})


@app.get("/api/dataset/<dataset_id>")
def api_dataset(dataset_id):
    instrument = request.args.get("instrument")
    if instrument:
        if instrument not in core.INSTRUMENTS and instrument != "generic":
            abort(400, description=f"Unknown instrument '{instrument}'.")
        get(dataset_id, "dataset")["meta"]["instrument"] = instrument
    return jresp({"dataset": dataset_summary(dataset_id)})


@app.get("/api/dataset/<dataset_id>/csv")
def api_dataset_csv(dataset_id):
    item = get(dataset_id, "dataset")
    return download(csv_bytes(item["df"]), item["name"])


def timeseries_from_request(df, dt_col, default_title):
    p = request.get_json(force=True)
    fig, gaps = charts.timeseries_figure(
        df, dt_col, p.get("cols", []), p.get("trend", "Rolling average"), p.get("window", "1 hour"),
        float(p.get("ref_value") or 0), p.get("ref_label", ""), bool(p.get("log_y")),
        bool(p.get("collapse_gaps", True)), bool(p.get("fade", True)), default_title)
    return figure_response(fig, gaps=gaps)


@app.post("/api/dataset/<dataset_id>/timeseries")
def api_dataset_timeseries(dataset_id):
    df = get(dataset_id, "dataset")["df"]
    datetime_cols = df.select_dtypes(include=["datetime64"]).columns.tolist()
    return timeseries_from_request(df, datetime_cols[0] if datetime_cols else None, "Time series")


@app.post("/api/dataset/<dataset_id>/outlier-preview")
def api_outlier_preview(dataset_id):
    df = get(dataset_id, "dataset")["df"]
    p = request.get_json(force=True)
    dt = p.get("dt_col")
    if dt in df.columns:
        df = df.sort_values(dt, kind="stable")
    rows = []
    for col in p.get("cols", []):
        if col not in df.columns:
            continue
        s = df[col]
        lo, hi = core.outlier_bounds(s, p["method"], p["params"])
        flagged = int(((s < lo) | (s > hi)).sum())
        rows.append({"Column": col, "Flagged": flagged,
                     "% of readings": round(flagged / max(int(s.notna().sum()), 1) * 100, 2)})
    return jresp({"rows": rows})


# -------------------------------
# API: CLEANING
# -------------------------------
DEFAULT_CONFIG = {
    "dt_col": None, "keep_cols": [], "time_window": None,
    "dedupe": True, "dedupe_by_time": True,
    "range_on": True, "range_rules": [], "range_action": core.ACTION_BLANK,
    "consistency_on": False, "consistency_rules": [], "consistency_tol": 0.0,
    "flat_on": False, "flat_cols": [], "flat_n": 10, "flat_action": core.ACTION_BLANK,
    "outlier_on": False, "outlier_cols": [], "outlier_method": core.OUTLIER_SIGMA,
    "outlier_params": {"k": 3.0, "iqr_mult": 1.5, "window": 31, "pct_range": [1.0, 99.0]},
    "outlier_action": core.ACTION_REMOVE,
    "missing_method": "Leave as is", "missing_cols": [], "missing_limit": 5,
    "avg_on": False, "avg_rule": "1 hour", "avg_how": "mean", "avg_completeness": 75, "avg_drop_empty": True,
    "avg_smart": True, "avg_special": {},
    "qc_on": False, "qc": {},
}


@app.post("/api/clean")
def api_clean():
    p = request.get_json(force=True)
    dataset_id = p["dataset_id"]
    item = get(dataset_id, "dataset")
    df = item["df"]

    cfg = {**DEFAULT_CONFIG, **(p.get("config") or {})}
    if cfg["dt_col"] not in df.columns:
        cfg["dt_col"] = None
    cfg["consistency_rules"] = [tuple(r) for r in cfg["consistency_rules"]]
    cfg["flat_n"] = int(cfg["flat_n"])
    cfg["missing_limit"] = int(cfg["missing_limit"] or 0)
    cfg["outlier_params"] = {**DEFAULT_CONFIG["outlier_params"], **cfg["outlier_params"]}
    if cfg["time_window"] and not all(cfg["time_window"]):
        cfg["time_window"] = None

    instrument = item["meta"].get("instrument") or core.instrument_from_columns(df.columns)
    defaults = core.instrument_defaults(instrument, df)
    if not p.get("config", {}).get("avg_special"):
        cfg["avg_special"] = defaults["avg_special"]

    result = core.run_cleaning(df, cfg)
    log = result["log"]
    result.update({"kind": "result", "dataset_id": dataset_id, "dt_col": cfg["dt_col"], "instrument": instrument,
                   "source_name": item["name"], "applied_at": datetime.now()})
    result_id = put(result)

    cleaned, removed = result["cleaned"], result["removed"]
    numeric_cols = cleaned.select_dtypes(include=[np.number]).columns.tolist()
    plot_cols = [c for c in defaults["plot_cols"] if c in numeric_cols] or core.default_pm_columns(numeric_cols)
    instrument_tab = None
    if instrument == "aws" and instrument_wind_cols(cleaned):
        instrument_tab = "Wind rose"
    elif instrument == "c12" and "Status" in df.columns:
        instrument_tab = "Status codes"
    return jresp({
        "instrument": instrument,
        "instrument_label": core.instrument_info(instrument)["label"],
        "instrument_tab": instrument_tab,
        "result_id": result_id,
        "applied_at": result["applied_at"].strftime("%H:%M:%S"),
        "initial_rows": len(df),
        "rows_removed": int(log["Rows removed"].sum()),
        "values_changed": int(log["Values changed"].sum()),
        "final_rows": len(cleaned),
        "retained_pct": len(result["pre_resample"]) / len(df) * 100 if len(df) else 0,
        "resampled": result["resampled"],
        "log": log.to_dict("records"),
        "numeric_cols": numeric_cols,
        "default_plot_cols": plot_cols,
        "dt_col": cfg["dt_col"],
        "removed_count": len(removed),
    })


def instrument_wind_cols(df):
    """(speed column, direction column) for a wind rose, or None"""
    speed = next((c for c in df.columns if c.startswith("Wind Speed")), None)
    direction = next((c for c in df.columns if c.startswith("Wind Dir")), None)
    return (speed, direction) if speed and direction else None


@app.post("/api/result/<result_id>/chart")
def api_result_chart(result_id):
    r = get(result_id, "result")
    p = request.get_json(force=True)
    kind = p.get("type")
    cleaned, pre, dt = r["cleaned"], r["pre_resample"], r["dt_col"]
    raw_df = get(r["dataset_id"], "dataset")["df"]
    raw = raw_df.loc[:, [c for c in raw_df.columns if c in pre.columns]]

    if kind == "timeseries":
        return timeseries_from_request(cleaned, dt, "Cleaned time series")

    col = p.get("col")
    if kind == "before_after":
        fig = charts.before_after_figure(raw, pre, cleaned, dt, col, r["resampled"], bool(p.get("collapse_gaps", True)))
        before, after = raw[col], cleaned[col]
        stats = {name: {"value": getattr(after, fn)(), "delta": getattr(after, fn)() - getattr(before, fn)()}
                 for name, fn in (("Mean", "mean"), ("Median", "median"), ("Std. deviation", "std"), ("Maximum", "max"))}
        return figure_response(fig, stats=stats)
    if kind == "distribution":
        return figure_response(charts.distribution_figure(raw, cleaned, col, int(p.get("bins", 50))))
    if kind == "box":
        return figure_response(charts.box_figure(raw, cleaned, col))
    if kind == "diurnal":
        if not dt:
            abort(400, description="A timestamp column is needed for the diurnal profile.")
        return figure_response(charts.diurnal_figure(cleaned, dt, p.get("cols", []), bool(p.get("split"))))
    if kind == "relationship":
        fig, stats = charts.relationship_figure(cleaned, p["x"], p["y"])
        return figure_response(fig, stats=stats)
    if kind == "correlation":
        return figure_response(charts.correlation_figure(cleaned))
    if kind == "removed":
        if r["removed"].empty:
            abort(400, description="No rows were removed.")
        return figure_response(charts.removed_reasons_figure(r["removed"]))
    if kind == "windrose":
        cols = instrument_wind_cols(pre)
        if not cols:
            abort(400, description="Wind speed and wind direction columns are needed for a wind rose.")
        which = pre if p.get("stage") != "raw" else raw_df
        fig, stats = charts.windrose_figure(which, *cols, title="Wind rose (cleaned)" if which is pre else "Wind rose (original)")
        return figure_response(fig, stats=stats)
    if kind == "alarms":
        if "Status" not in raw_df.columns:
            abort(400, description="No Status column in this dataset.")
        return figure_response(charts.alarm_codes_figure(raw_df, "Status", core.C12_ALARMS, core.C12_INFO_ONLY))
    abort(400, description=f"Unknown chart type '{kind}'.")


@app.get("/api/result/<result_id>/table/<which>")
def api_result_table(result_id, which):
    r = get(result_id, "result")
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 100))
    if which == "cleaned":
        return jresp(records(r["cleaned"], limit, offset))
    if which == "removed":
        return jresp(records(r["removed"], limit, offset))
    if which == "stats":
        numeric = r["cleaned"].select_dtypes(include=[np.number])
        stats = numeric.describe().T.round(3).reset_index().rename(columns={"index": "Column"}) if not numeric.empty \
            else pd.DataFrame()
        return jresp(records(stats))
    abort(404)


@app.get("/api/result/<result_id>/download/<kind>")
def api_result_download(result_id, kind):
    r = get(result_id, "result")
    base = r["source_name"].rsplit(".", 1)[0]
    files = {
        f"cleaned_{base}.csv": csv_bytes(r["cleaned"]),
        f"cleaning_report_{base}.csv": csv_bytes(r["log"]),
        f"removed_rows_{base}.csv": csv_bytes(r["removed"]),
    }
    if kind == "cleaned":
        return download(files[f"cleaned_{base}.csv"], f"cleaned_{base}.csv")
    if kind == "report":
        return download(files[f"cleaning_report_{base}.csv"], f"cleaning_report_{base}.csv")
    if kind == "removed":
        return download(files[f"removed_rows_{base}.csv"], f"removed_rows_{base}.csv")
    if kind == "zip":
        return download(build_zip(files), f"cleaning_bundle_{base}.zip", "application/zip")
    abort(404)


if __name__ == "__main__":
    import sys
    import webbrowser

    url = "http://127.0.0.1:5000"
    print(f"\n  Air Quality Data Processing Tool running at {url}  (press Ctrl+C to stop)\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
