# -*- coding: utf-8 -*-
"""Data handling for the Air Quality Data Processing Tool: conversion of raw DustTrak, weather station (AWS)
and C-12 black carbon files, type detection, instrument-specific QC defaults and the logged cleaning pipeline. No web framework code lives here."""
import io
import re
import warnings

import numpy as np
import pandas as pd


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
    text = data.decode("utf-8-sig", errors="replace")
    return text.startswith("Instrument Name") and "Elapsed Time" in text


def load_table(data, dayfirst=True):
    """Read an uploaded file. Raw DustTrak, weather station and C-12 exports are converted automatically.

    Returns (DataFrame, instrument key of the raw format, or None for an ordinary table)."""
    kind = classify_file(data)
    if kind == "dusttrak":
        return convert_dusttrak_file(data)[0], "dusttrak"
    if kind == "aws":
        return convert_aws_file(data)[0], "aws"
    if kind == "c12_data":
        return convert_c12_file(data)[0], "c12"
    if kind != "table":
        raise ValueError("This is a C-12 support file (settings, alarm or diagnostic log), not a data file. "
                         "Upload Data.CSV instead.")
    text = decode_text(data)
    sep = "\t" if text.split("\n", 1)[0].count("\t") > text.split("\n", 1)[0].count(",") else ","
    df = pd.read_csv(io.StringIO(text), sep=sep)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, [c for c in df.columns if not (c.startswith("Unnamed") and df[c].isna().all())]]
    return detect_and_convert_types(df, dayfirst=dayfirst), None


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


def merge_frames(frames, dedupe=True):
    """Concatenate converted files, sort by time and optionally drop repeated timestamps"""
    merged = pd.concat(frames, ignore_index=True).sort_values("Timestamp", kind="stable")
    duplicates = 0
    if dedupe:
        dup_mask = merged.duplicated(subset=["Timestamp"], keep="first")
        duplicates = int(dup_mask.sum())
        merged = merged[~dup_mask]
    return merged.reset_index(drop=True), duplicates


# -------------------------------
# INSTRUMENTS
# -------------------------------
INSTRUMENTS = {
    "dusttrak": {
        "label": "DustTrak",
        "name": "DustTrak aerosol monitor",
        "sub": "PM mass concentrations",
        "convert_title": "Convert raw DustTrak files",
        "convert_desc": "Timestamps are rebuilt from each test's start time, rows with flow errors are dropped, "
                        "and mg/m³ is converted to µg/m³.",
        "files_hint": "DustTrak .csv exports, one per test",
        "extra_label": "Also include PM4 and TOTAL columns",
        "folders": False,
    },
    "aws": {
        "label": "Weather station",
        "name": "Automatic Weather Station (AWS)",
        "sub": "Temperature, humidity, wind, rain",
        "convert_title": "Convert weather station exports",
        "convert_desc": "Reads tab-separated station exports with two-row headers: joins date and time, drops "
                        "impossible calendar dates, turns compass wind directions into degrees and marks '---' as missing.",
        "files_hint": "Station export .txt or .csv files",
        "extra_label": "Also include indoor console, comfort-index and transmitter columns",
        "folders": False,
    },
    "c12": {
        "label": "C-12 Black Carbon",
        "name": "C-12 Black Carbon Monitor",
        "sub": "BC (880 nm) and UV (370 nm)",
        "convert_title": "Convert C-12 black carbon downloads",
        "convert_desc": "Drop the folder(s) downloaded from the C-12. Data.CSV is read together with the Settings, "
                        "Alarm and Diagnostic files from the same folder, and every Status code is decoded.",
        "files_hint": "Whole download folders, or Data.CSV with its Settings/Alarm/Diagnostic files",
        "extra_label": "Also add filter attenuation (ATN) from Diagnostic.CSV",
        "folders": True,
    },
}
GENERIC = {"label": "Other / generic", "name": "Generic time series", "sub": "Any tidy CSV"}


def instrument_info(key):
    return INSTRUMENTS.get(key, GENERIC)


def decode_text(data):
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def classify_file(data):
    """Identify a raw instrument file from its content (file names are not reliable)"""
    text = data[:8192].decode("utf-8-sig", errors="replace").lstrip("﻿")
    lines = text.splitlines()
    first = lines[0] if lines else ""
    second = lines[1] if len(lines) > 1 else ""
    if first.startswith("Instrument Name") and is_raw_dusttrak(data):
        return "dusttrak"
    if first.startswith("C-12 Settings Report"):
        return "c12_settings"
    if first.startswith("Alarm Report"):
        return "c12_alarm"
    if re.search(r"880\s*nm", first):
        return "c12_diagnostic" if "ATN" in first else "c12_data"
    if re.match(r"^\d{2}:\d{2}:\d{2} - \w+", first):
        return "c12_joblog"
    head2 = [c.strip() for c in re.split(r"[\t,]", second)[:2]]
    head1 = [c.strip() for c in re.split(r"[\t,]", first)[:2]]
    if head2 == ["Date", "Time"] or (head1 == ["Date", "Time"] and re.search(r"Temp|Hum|Wind|Bar", first)):
        return "aws"
    return "table"


FILE_INSTRUMENT = {"dusttrak": "dusttrak", "aws": "aws", "c12_data": "c12", "c12_settings": "c12",
                   "c12_alarm": "c12", "c12_diagnostic": "c12", "c12_joblog": "c12"}


def instrument_from_columns(columns):
    """Guess the instrument behind an already-converted table"""
    text = " | ".join(map(str, columns))
    if re.search(r"880\s*nm", text):
        return "c12"
    if re.search(r"Temp Out|Out Hum|Wind Speed|Wind Dir|Rain Rate", text):
        return "aws"
    if any(pm_size(str(c)) is not None for c in columns):
        return "dusttrak"
    return "generic"


def _unique_names(names):
    seen, out = {}, []
    for n in names:
        n = n or "Column"
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n} ({seen[n]})")
    return out


def _parse_times(values, dayfirst=True):
    """Parse timestamps written either as ISO (2026-04-08 12:06:00) or day-first (08-04-2026 12:06)"""
    s = pd.Series(values).astype(str).str.strip()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if s.str.match(r"^\d{4}-\d{2}-\d{2}").mean() > 0.5:
            return pd.to_datetime(s, errors="coerce", format="ISO8601")
        return pd.to_datetime(s, errors="coerce", dayfirst=dayfirst)


# ----- Automatic Weather Station -----
AWS_COMPASS = {d: i * 22.5 for i, d in enumerate("N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split())}
AWS_EXTRA = {"Wind Chill", "Heat Index", "THW Index", "THSW Index", "Heat D-D", "Cool D-D", "In Temp", "In Hum",
             "In Dew", "In Heat", "In EMC", "In Air Density", "Wind Samp", "Wind Tx", "Arc. Int."}
AWS_DIRECTIONS = {"Wind Dir", "Hi Dir"}
AWS_UNITS = {"Out Hum": "%", "In Hum": "%", "ISS Recept": "%", "Wind Dir": "°", "Hi Dir": "°"}
INHG_TO_HPA = 33.8639

_DATE_PARTS_DAYFIRST = ["%d-%m-%y", "%d/%m/%y", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d.%m.%y"]
_DATE_PARTS_MONTHFIRST = ["%m-%d-%y", "%m/%d/%y", "%m-%d-%Y", "%m/%d/%Y"]
_TIME_PARTS = ["%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p"]


def _best_datetime(stamps):
    """Try day-first formats before month-first and keep the one that reads the most rows"""
    best, best_count = None, -1
    candidates = [f"{d} {t}" for d in _DATE_PARTS_DAYFIRST + _DATE_PARTS_MONTHFIRST for t in _TIME_PARTS]
    candidates.insert(0, "ISO8601")
    sample = stamps.head(500)
    for fmt in candidates:
        n = pd.to_datetime(sample, format=fmt, errors="coerce").notna().sum()
        if n > best_count:
            best, best_count = fmt, n
    return pd.to_datetime(stamps, format=best, errors="coerce")


def convert_aws_file(data, include_extra=False, bar_to_hpa=True):
    """Convert a weather station text export (two-row header, tab-separated) to a tidy table.

    Units are kept as logged by the station, except that a barometer recorded in inHg can be converted to hPa."""
    lines = [line for line in decode_text(data).splitlines() if line.strip()]
    if len(lines) < 3:
        raise ValueError("File is too short to be a station export")
    sep = "\t" if lines[1].count("\t") >= lines[1].count(",") else ","
    top = [c.strip() for c in lines[0].split(sep)]
    second = [c.strip() for c in lines[1].split(sep)]
    if second[:2] == ["Date", "Time"]:
        n = max(len(top), len(second))
        top += [""] * (n - len(top))
        second += [""] * (n - len(second))
        names, body = [" ".join(p for p in pair if p) for pair in zip(top, second)], lines[2:]
    elif top[:2] == ["Date", "Time"]:
        names, body = top, lines[1:]
    else:
        raise ValueError("No 'Date' and 'Time' header found")
    names = _unique_names(names)

    df = pd.read_csv(io.StringIO("\n".join(body)), sep=sep, header=None, names=names, dtype=str, index_col=False)
    stamps = (df["Date"].str.strip() + " " + df["Time"].str.strip()).str.replace(
        r"(\d)\s*([ap])m?$", lambda m: f"{m.group(1)} {m.group(2).upper()}M", regex=True, case=False)
    df.insert(0, "Timestamp", _best_datetime(stamps))
    invalid = int(df["Timestamp"].isna().sum())
    df = df[df["Timestamp"].notna()].drop(columns=["Date", "Time"])

    for col in df.columns[1:]:
        text = df[col].astype(str).str.strip()
        if col in AWS_DIRECTIONS:
            df[col] = text.str.upper().map(AWS_COMPASS).fillna(pd.to_numeric(text, errors="coerce"))
        else:
            df[col] = pd.to_numeric(text, errors="coerce")

    if not include_extra:
        df = df.drop(columns=[c for c in df.columns if c in AWS_EXTRA])

    renames, bar_note = {c: f"{c} [{u}]" for c, u in AWS_UNITS.items() if c in df.columns}, "–"
    if "Bar" in df.columns:
        median = df["Bar"].median()
        if 25 < median < 32.5:
            if bar_to_hpa:
                df["Bar"] = (df["Bar"] * INHG_TO_HPA).round(1)
                renames["Bar"], bar_note = "Bar [hPa]", "inHg → hPa"
            else:
                renames["Bar"], bar_note = "Bar [inHg]", "inHg (as logged)"
        elif 850 < median < 1100:
            renames["Bar"], bar_note = "Bar [hPa]", "hPa (as logged)"
        elif 600 < median < 830:
            renames["Bar"], bar_note = "Bar [mmHg]", "mmHg (as logged)"
    df = df.rename(columns=renames).sort_values("Timestamp", kind="stable").reset_index(drop=True)

    if df.empty:
        raise ValueError("No rows with a readable date and time")
    _, step = find_gaps(df["Timestamp"])
    info = {
        "Start": df["Timestamp"].min(),
        "End": df["Timestamp"].max(),
        "Rows": len(df),
        "Interval": format_timedelta(step),
        "Invalid dates dropped": invalid,
        "Duplicate timestamps": int(df["Timestamp"].duplicated().sum()),
        "Barometer": bar_note,
    }
    return df, info


# ----- C-12 Black Carbon Monitor -----
# Status codes from the Met One C-12 operation manual (C-12-9800 Rev A), Table 7-1. The Status value is the
# sum of all alarm codes raised during the sample, so each code is tested as a bit.
C12_ALARMS = {
    1: "Power failure",
    4: "Tape move failure",
    8: "Maintenance / stop",
    16: "Flow failure",
    32: "Automatic tape advance",
    64: "Detector failure",
    256: "Sensor out of range",
    512: "Nozzle move failure",
    2048: "Calibration audit",
    65536: "Tape move",
}
C12_INFO_ONLY = {32, 65536}   # the manual describes these as "not an error condition"
C12_NOMINAL_FLOW = 1.0        # lpm (manual section 7)
C12_FLOW_TOLERANCE = 10.0     # %: the manual's flow-failure threshold for out-of-regulation flow
C12_SETTINGS_KEYS = {"Serial Number": "Serial no.", "Firmware": "Firmware", "Sample Period": "Sample period",
                     "Time Zone": "Time zone", "Location": "Location"}


def decode_c12_status(value):
    if value is None or pd.isna(value) or int(value) == 0:
        return ""
    v = int(value)
    names = [label for code, label in C12_ALARMS.items() if v & code]
    unknown = v & ~sum(C12_ALARMS)
    if unknown:
        names.append(f"Code {unknown}")
    return "; ".join(names)


def _read_c12_table(data):
    df = pd.read_csv(io.StringIO(decode_text(data)), sep=None, engine="python")
    df.columns = [str(c).strip() for c in df.columns]
    return df.loc[:, [c for c in df.columns if not (c.startswith("Unnamed") and df[c].isna().all())]]


def parse_c12_settings(data):
    meta = {}
    for line in decode_text(data).splitlines():
        if line.strip().startswith("Factory Settings"):
            break
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0] in C12_SETTINGS_KEYS:
            meta[C12_SETTINGS_KEYS[parts[0]]] = ", ".join(parts[1:])
    return meta


def parse_c12_alarms(data):
    rows = []
    for line in decode_text(data).splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and re.match(r"^\d{4}-\d{2}-\d{2} \d", parts[0]):
            rows.append({"Time": pd.Timestamp(parts[0]), "Alarm": parts[1], "Details": ", ".join(p for p in parts[2:] if p)})
    return pd.DataFrame(rows, columns=["Time", "Alarm", "Details"])


def convert_c12_file(data, settings=None, diagnostic=None, unit="ng/m3", alarms=None):
    """Convert a C-12 Data.CSV (comma- or tab-separated) to Timestamp + concentration, flow and status columns"""
    df = _read_c12_table(data)
    if "Time" not in df.columns:
        raise ValueError("No 'Time' column found in the C-12 data file")
    out = pd.DataFrame({"Timestamp": _parse_times(df["Time"])})
    factor = 0.001 if unit == "µg/m3" else 1.0
    for col in df.columns:
        nm = re.search(r"(\d+)\s*nm", col)
        if nm:
            label = {"880": "BC 880nm", "370": "UV 370nm"}.get(nm.group(1), f"{nm.group(1)}nm")
            out[f"{label} [{unit}]"] = (pd.to_numeric(df[col], errors="coerce") * factor).round(4)
    if len(out.columns) == 1:
        raise ValueError("No 370nm/880nm concentration columns found")
    for prefix, name in (("Flow", "Flow [lpm]"), ("BT", "Box temp [°C]"), ("BP", "Box pressure [mmHg]")):
        col = next((c for c in df.columns if c.split(" ")[0] == prefix), None)
        if col:
            out[name] = pd.to_numeric(df[col], errors="coerce")
    if "Status" in df.columns:
        out["Status"] = pd.to_numeric(df["Status"], errors="coerce").fillna(0).astype("int64")
        out["Alarms"] = out["Status"].map(decode_c12_status)

    if diagnostic is not None:
        diag = _read_c12_table(diagnostic)
        atn = {"ATN1": "ATN 370nm", "ATN2": "ATN 880nm"}
        if "Time" in diag.columns and set(atn) & set(diag.columns):
            diag = diag[["Time"] + [c for c in atn if c in diag.columns]].rename(columns=atn)
            diag["Timestamp"] = _parse_times(diag.pop("Time"))
            out = out.merge(diag.dropna(subset=["Timestamp"]).drop_duplicates("Timestamp"), on="Timestamp", how="left")

    invalid = int(out["Timestamp"].isna().sum())
    out = out[out["Timestamp"].notna()].sort_values("Timestamp", kind="stable").reset_index(drop=True)
    if out.empty:
        raise ValueError("No rows with a readable timestamp")

    bc = [c for c in out.columns if "nm [" in c]
    settings = settings or {}
    start, end = out["Timestamp"].min(), out["Timestamp"].max()
    info = {
        "Serial no.": settings.get("Serial no.", "–"),
        "Sample period": settings.get("Sample period", "–"),
        "Time zone": settings.get("Time zone", "–"),
        "Start": start,
        "End": end,
        "Rows": len(out),
        "Rows with alarm codes": int((out["Status"] != 0).sum()) if "Status" in out else 0,
        "All-zero readings": int((out[bc] == 0).all(axis=1).sum()),
        "Alarm log events": int(alarms["Time"].between(start, end).sum()) if alarms is not None and len(alarms) else 0,
    }
    if invalid:
        info["Unreadable timestamps dropped"] = invalid
    return out, info


# ----- Batch conversion -----
def _output_name(instrument, df, info):
    start, end = df["Timestamp"].min(), df["Timestamp"].max()
    if instrument == "dusttrak":
        return f"{info['File timestamp']}.csv"
    if instrument == "aws":
        return f"AWS_{start:%Y-%m-%d}_to_{end:%Y-%m-%d}.csv"
    serial = re.sub(r"\W+", "", str(info.get("Serial no.", ""))) or "C12"
    return f"C12_{serial}_{start:%Y-%m-%d_%H-%M}.csv"


def convert_files(files, instrument, include_extra=False, options=None):
    """Convert raw files for one instrument.

    files: list of (name, bytes); C-12 names may include their folder ("13 12-24-08/Data.CSV") so each
    Data.CSV is paired with the Settings, Alarm and Diagnostic files from the same download.
    Returns {"converted": [{source, output, df, info}], "failures": [{file, reason}], "alarms": DataFrame}."""
    options = options or {}
    converted, failures, alarm_frames, groups = [], [], [], {}
    label = instrument_info(instrument)["label"]

    for name, data in files:
        kind = classify_file(data)
        owner = FILE_INSTRUMENT.get(kind)
        if kind == "c12_joblog":
            continue
        if owner is None:
            failures.append({"file": name, "reason": f"Not a recognised raw {label} file"})
            continue
        if owner != instrument:
            failures.append({"file": name, "reason": f"Looks like a {instrument_info(owner)['label']} file. "
                                                     f"Switch the instrument to convert it."})
            continue
        if instrument == "c12":
            folder = name.replace("\\", "/").rsplit("/", 1)[0] if "/" in name.replace("\\", "/") else ""
            group = groups.setdefault(folder, {"data": [], "settings": None, "alarm": None, "diagnostic": None})
            if kind == "c12_data":
                group["data"].append((name, data))
            else:
                group[kind.split("_", 1)[1]] = data
            continue
        try:
            if instrument == "dusttrak":
                df, info = convert_dusttrak_file(data, include_extra)
            else:
                df, info = convert_aws_file(data, include_extra, options.get("bar_to_hpa", True))
            converted.append({"source": name, "df": df, "info": info})
        except Exception as e:
            failures.append({"file": name, "reason": str(e)})

    for folder, group in groups.items():
        settings = parse_c12_settings(group["settings"]) if group["settings"] else {}
        alarms = parse_c12_alarms(group["alarm"]) if group["alarm"] else None
        if alarms is not None and len(alarms):
            alarm_frames.append(alarms.assign(**{"Serial no.": settings.get("Serial no.", "–")}))
        if not group["data"]:
            failures.append({"file": folder or "(selected files)", "reason": "No Data.CSV found alongside these files"})
            continue
        for name, data in group["data"]:
            try:
                df, info = convert_c12_file(data, settings, group["diagnostic"] if include_extra else None,
                                            options.get("unit", "ng/m3"), alarms)
                converted.append({"source": name, "df": df, "info": info})
            except Exception as e:
                failures.append({"file": name, "reason": str(e)})

    used = set()
    for c in converted:
        base = _output_name(instrument, c["df"], c["info"])
        name, n = base, 2
        while name in used:
            name = base.replace(".csv", f"_{n}.csv")
            n += 1
        used.add(name)
        c["output"] = name

    alarms = pd.concat(alarm_frames).drop_duplicates().sort_values("Time") if alarm_frames else pd.DataFrame()
    return {"converted": converted, "failures": failures, "alarms": alarms}


def read_converted_table(name, data):
    """Read a tidy CSV produced by this tool (or similar) for merging"""
    df, _ = load_table(data)
    if "Timestamp" not in df.columns:
        dt_cols = df.select_dtypes(include=["datetime64"]).columns
        if not len(dt_cols):
            raise ValueError("no timestamp column found")
        df = df.rename(columns={dt_cols[0]: "Timestamp"})
    return df


# ----- Instrument-specific cleaning defaults -----
def instrument_defaults(instrument, df):
    """Suggested settings for the cleaning pipeline. Range limits are plausibility checks the user can edit."""
    numeric = df.select_dtypes(include=[np.number]).columns.tolist()
    find = lambda pattern: [c for c in numeric if re.search(pattern, c, re.I)]
    first = lambda pattern: next(iter(find(pattern)), None)
    d = {"plot_cols": default_pm_columns(numeric), "ranges": {}, "flat_cols": numeric,
         "consistency": [], "consistency_label": "Size-fraction consistency",
         "consistency_desc": "Flag rows where a finer fraction exceeds a coarser one (e.g. PM2.5 > PM10)",
         "avg_special": {}, "qc": None}

    if instrument == "aws":
        temp = first(r"^Temp Out")
        fahrenheit = temp is not None and df[temp].median() > 50
        temp_limits = (-40, 140) if fahrenheit else (-40, 60)
        bar = first(r"^Bar")
        bar_limits = {"hPa": (870, 1085), "inHg": (25.7, 32.1), "mmHg": (650, 815)}
        for c in numeric:
            if re.search(r"Temp|Dew|Chill|Heat Index|THW|In Heat", c) and "D-D" not in c:
                d["ranges"][c] = [*temp_limits, True]
            elif re.search(r"Hum|Recept", c):
                d["ranges"][c] = [0, 100, True]
            elif re.search(r"Dir", c):
                d["ranges"][c] = [0, 360, True]
            elif re.search(r"Speed|Run|Rain", c):
                d["ranges"][c] = [0, None, True]
            elif c == bar:
                unit = re.search(r"\[(\w+)\]", c)
                if unit and unit.group(1) in bar_limits:
                    d["ranges"][c] = [*bar_limits[unit.group(1)], True]
        d["plot_cols"] = [c for c in (temp, first(r"^Out Hum")) if c] or numeric[:2]
        d["flat_cols"] = [c for c in (temp, first(r"^Out Hum"), bar) if c]
        pairs = [(r"^Low Temp", r"^Temp Out"), (r"^Temp Out", r"^Hi Temp"), (r"^Dew Pt", r"^Temp Out"),
                 (r"^Wind Speed", r"^Hi Speed")]
        d["consistency"] = [(first(a), first(b)) for a, b in pairs if first(a) and first(b)]
        d["consistency_label"] = "Internal consistency"
        d["consistency_desc"] = "Low ≤ average ≤ high temperature, dew point ≤ air temperature, mean wind ≤ gust"
        special = {r"^Hi Temp": "max", r"^Low Temp": "min", r"^Hi Speed": "max", r"^Rain Rate": "max",
                   r"^Rain(?! Rate)": "sum", r"^Wind Run": "sum", r"^Wind Dir": "circular", r"^Hi Dir": "circular"}
        d["avg_special"] = {first(p): how for p, how in special.items() if first(p)}
        d["qc"] = {"reception_col": first(r"Recept")}

    elif instrument == "c12":
        conc = find(r"\d+\s*nm \[")
        bc = sorted(conc, key=lambda c: "880" not in c)
        d["plot_cols"] = bc[:2]
        d["flat_cols"] = bc
        d["ranges"] = {c: [0, None, True] for c in conc}
        # Sensor limits from the manual's Table 7-3: BT −40 to 60 °C, BP 304–1090.6 mbar (≈ 228–818 mmHg)
        if first(r"^Box temp"):
            d["ranges"][first(r"^Box temp")] = [-40, 60, True]
        if first(r"^Box pressure"):
            d["ranges"][first(r"^Box pressure")] = [228, 818, True]
        status, flow = first(r"^Status$"), first(r"^Flow")
        if status:
            d["avg_special"][status] = "bitor"
        codes = {}
        if status:
            values = df[status].fillna(0).astype("int64")
            codes = {code: int(((values & code) != 0).sum()) for code in C12_ALARMS}
        d["qc"] = {
            "status_col": status,
            "codes": [{"code": code, "label": label, "count": codes.get(code, 0),
                       "default": code not in C12_INFO_ONLY} for code, label in C12_ALARMS.items()],
            "flow_col": flow,
            "flow_nominal": C12_NOMINAL_FLOW,
            "flow_tol": C12_FLOW_TOLERANCE,
            "flow_off": int(((df[flow] - C12_NOMINAL_FLOW).abs() > C12_NOMINAL_FLOW * C12_FLOW_TOLERANCE / 100).sum()) if flow else 0,
            "zero_cols": conc,
            "zero_count": int((df[conc] == 0).all(axis=1).sum()) if conc else 0,
        }

    else:
        d["ranges"] = {c: [0, None, True] for c in numeric}
        d["consistency"] = consistency_rules(numeric)
    return d


# -------------------------------
# HELPERS
# -------------------------------
def format_timedelta(td):
    if td is None or pd.isna(td):
        return "–"
    seconds = int(pd.Timedelta(td).total_seconds())
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


def default_pm_columns(numeric_cols, limit=2):
    preferred = [c for c in numeric_cols if re.search(r"PM\s*2\.5|PM\s*10", c, re.I)]
    return (preferred or numeric_cols)[:limit]


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


def find_gaps(times, threshold=None):
    """Pauses in sampling: returns ([(last reading before, first reading after)], typical interval).

    By default a pause counts as a gap when it is longer than both 10 sampling intervals and 1 hour."""
    t = pd.Series(pd.to_datetime(times)).dropna().sort_values().to_numpy()
    if len(t) < 3:
        return [], None
    diffs = np.diff(t)
    positive = diffs[diffs > np.timedelta64(0)]
    if len(positive) == 0:
        return [], None
    step = pd.Timedelta(np.median(positive))
    if threshold is None:
        threshold = max(step * 10, pd.Timedelta(hours=1))
    idx = np.where(diffs > np.timedelta64(threshold))[0]
    return [(pd.Timestamp(t[i]), pd.Timestamp(t[i + 1])) for i in idx], step


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
        window = int(params["window"])
        median = s.rolling(window, center=True, min_periods=1).median()
        mad = (s - median).abs().rolling(window, center=True, min_periods=1).median()
        scale = (1.4826 * mad).replace(0, np.nan)  # flat stretches are not flagged
        return median - params["k"] * scale, median + params["k"] * scale
    lower_pct, upper_pct = params["pct_range"]
    return s.quantile(lower_pct / 100), s.quantile(upper_pct / 100)


def outlier_description(method, params):
    if method == OUTLIER_SIGMA:
        return f"Mean ± {params['k']:g}·SD"
    if method == OUTLIER_IQR:
        return f"Q1/Q3 ± {params['iqr_mult']:g}·IQR"
    if method == OUTLIER_HAMPEL:
        return f"Hampel, window {int(params['window'])}, k = {params['k']:g}"
    return f"Outside P{params['pct_range'][0]:g}–P{params['pct_range'][1]:g}"


def instrument_qc(run, qc):
    """Remove readings the instrument itself marked as invalid"""
    status = qc.get("status_col")
    if status in run.df.columns:
        for code in qc.get("codes", []):
            values = pd.to_numeric(run.df[status], errors="coerce").fillna(0).astype("int64")
            label = C12_ALARMS.get(int(code), f"code {code}")
            run.remove_rows((values & int(code)) != 0, "Instrument QC", f"Status code {code}: {label}")

    flow = qc.get("flow_col")
    if qc.get("flow_on") and flow in run.df.columns:
        nominal, tol = float(qc.get("flow_nominal", C12_NOMINAL_FLOW)), float(qc.get("flow_tol", C12_FLOW_TOLERANCE))
        off = (run.df[flow] - nominal).abs() > nominal * tol / 100
        run.remove_rows(off, "Instrument QC", f"Flow outside {nominal:g} lpm ± {tol:g}%")

    zero_cols = [c for c in qc.get("zero_cols", []) if c in run.df.columns]
    if qc.get("zero_on") and zero_cols:
        run.remove_rows((run.df[zero_cols] == 0).all(axis=1), "Instrument QC",
                        "Exactly zero in every channel (instrument not measuring)")

    reception = qc.get("reception_col")
    if qc.get("reception_on") and reception in run.df.columns:
        minimum = float(qc.get("reception_min", 50))
        run.remove_rows(run.df[reception] < minimum, "Instrument QC", f"Station radio reception below {minimum:g}%")


def _circular_mean(series, rule):
    """Vector-average wind direction in degrees, so 350° and 10° average to 0° rather than 180°"""
    rad = np.deg2rad(series)
    sin, cos = np.sin(rad).resample(rule).mean(), np.cos(rad).resample(rule).mean()
    return (np.rad2deg(np.arctan2(sin, cos)) % 360).round(1)


def _bitwise_or(values):
    values = values.dropna()
    return float(np.bitwise_or.reduce(values.astype("int64").to_numpy())) if len(values) else np.nan


def aggregate_periods(numeric, rule, how, special=None):
    """Resample with `how`, except columns in `special` ({col: sum|max|min|circular|bitor})"""
    special = special or {}
    plain = [c for c in numeric.columns if c not in special]
    parts = [numeric[plain].resample(rule).agg(how)] if plain else []
    for col, kind in special.items():
        if kind == "circular":
            parts.append(_circular_mean(numeric[col], rule).rename(col))
        elif kind == "bitor":
            parts.append(numeric[col].resample(rule).apply(_bitwise_or).rename(col))
        elif kind == "sum":
            parts.append(numeric[col].resample(rule).sum(min_count=1))
        else:
            parts.append(numeric[col].resample(rule).agg(kind))
    return pd.concat(parts, axis=1)[list(numeric.columns)]


def run_cleaning(df, cfg):
    run = CleaningRun(df.copy())
    dt = cfg["dt_col"]

    # Step 1: Columns
    keep = [c for c in cfg["keep_cols"] if c in run.df.columns] or list(run.df.columns)
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
            start, end = (pd.Timestamp(v) for v in cfg["time_window"])
            outside = (run.df[dt] < start) | (run.df[dt] > end)
            run.remove_rows(outside, "Time window", f"Outside {start:%d %b %Y %H:%M} – {end:%d %b %Y %H:%M}")

    # Step 3: Duplicates
    if cfg["dedupe"]:
        subset = [dt] if (cfg["dedupe_by_time"] and dt) else None
        run.remove_rows(run.df.duplicated(subset=subset, keep="first"), "Duplicates",
                        "Duplicate timestamp (kept first)" if subset else "Exact duplicate row")

    # Step 3b: Instrument QC flags (C-12 status codes and flow; AWS radio reception)
    if cfg.get("qc_on"):
        instrument_qc(run, cfg.get("qc") or {})

    # Step 4: Valid range limits
    if cfg["range_on"]:
        masks, bounds, parts = {}, {}, []
        for rule in cfg["range_rules"]:
            col, lo, hi = rule["Column"], rule.get("Min"), rule.get("Max")
            if col not in run.df.columns:
                continue
            lo = None if lo is None or pd.isna(lo) else float(lo)
            hi = None if hi is None or pd.isna(hi) else float(hi)
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
                run.remove_rows(violated, "Consistency",
                                f"{small} > {large}" + (f" (+{cfg['consistency_tol']:g}% tolerance)" if tol else ""))

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
        run.apply_action(masks, cfg["flat_action"], "Stuck sensor", f"≥ {cfg['flat_n']} identical consecutive readings")

    # Step 7: Outliers
    if cfg["outlier_on"]:
        masks, bounds = {}, {}
        for col in cfg["outlier_cols"]:
            if col not in run.df.columns:
                continue
            lower, upper = outlier_bounds(run.df[col], cfg["outlier_method"], cfg["outlier_params"])
            masks[col] = (run.df[col] < lower) | (run.df[col] > upper)
            bounds[col] = (lower, upper)
        run.apply_action(masks, cfg["outlier_action"], "Outliers",
                         outlier_description(cfg["outlier_method"], cfg["outlier_params"]), bounds)

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
                filled = run.df.set_index(dt)[cols].interpolate(method="time", limit=limit, limit_area="inside")
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
        special = {c: how for c, how in (cfg.get("avg_special") or {}).items() if c in numeric.columns} \
            if cfg.get("avg_smart", True) else {}
        averaged = aggregate_periods(numeric, rule, cfg["avg_how"], special)
        completeness = numeric.resample(rule).count() / expected
        incomplete = (completeness < cfg["avg_completeness"] / 100) & averaged.notna()
        averaged = averaged.where(~incomplete)
        if cfg["avg_drop_empty"]:
            averaged = averaged.dropna(how="all")
        averaged.index.name = dt
        run.df = averaged.reset_index().round(3)
        resampled = True
        how_text = {"sum": "summed", "max": "maximum", "min": "minimum", "circular": "vector-averaged direction",
                    "bitor": "all alarm codes kept"}
        special_text = "; ".join(f"{c}: {how_text[h]}" for c, h in special.items())
        run.note("Time averaging",
                 f"{cfg['avg_how'].title()} over {cfg['avg_rule']} → {len(run.df):,} periods; "
                 f"{int(incomplete.sum().sum()):,} value(s) blanked below {cfg['avg_completeness']}% completeness"
                 + (f" (instrument-aware: {special_text})" if special_text else ""))
        for c, h in special.items():
            if h == "bitor":   # text columns are dropped by averaging; rebuild the decoded alarm list
                run.df["Alarms"] = run.df[c].map(decode_c12_status)

    removed = pd.concat(run.removed) if run.removed else pd.DataFrame()
    return {
        "cleaned": run.df,
        "pre_resample": pre_resample,
        "log": pd.DataFrame(run.log, columns=["Step", "Details", "Rows removed", "Values changed"]),
        "removed": removed,
        "resampled": resampled,
    }
