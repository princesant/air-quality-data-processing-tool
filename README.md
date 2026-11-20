# Air Quality Data Processing Tool

A local web app for converting, merging, cleaning and exploring data from three air-quality and weather instruments:

| Instrument | What the tool reads |
|---|---|
| **DustTrak** aerosol monitor | Raw `.csv` exports, one per test |
| **Automatic Weather Station (AWS)** | Tab-separated station exports with a two-row header (`.txt` / `.csv`) |
| **C-12 Black Carbon Monitor** | Whole download folders: `Data.CSV` plus `Settings.TXT`, `Alarm.TXT` and `Diagnostic.CSV` |

It is built with Flask and plain JavaScript (no build step). Charts are drawn with Plotly. Every cleaning step is logged, so each change to the data can be traced and downloaded.

## Workflow

1. **Convert**: choose the instrument in the sidebar and drop in raw files.
   - DustTrak: timestamps are rebuilt from the test start time, rows flagged with flow errors are removed, and mg/m³ is converted to µg/m³.
   - AWS: date and time are joined, impossible calendar dates are dropped, compass wind directions become degrees, and a barometer recorded in inHg can be converted to hPa. All other units are kept as the station logs them.
   - C-12: each `Data.CSV` is paired with the other files from its folder. Status codes are decoded into a readable *Alarms* column, and the alarm log is collected.
2. **Merge**: combine converted files into one time-sorted dataset, with optional removal of duplicate timestamps.
3. **Clean**: build a quality-control pipeline. The instrument profile sets sensible starting values, and every one of them can be edited.
   - Columns and time window
   - Duplicates
   - **Instrument QC**: for the C-12, status codes, off-nominal flow and all-zero readings; for the AWS, weak radio reception
   - Range limits
   - Consistency checks (PM size fractions; low ≤ average ≤ high temperature)
   - Stuck sensor
   - Outliers (k-sigma, IQR, Hampel, percentile)
   - Missing values
   - Time averaging with a completeness threshold. Averaging is instrument-aware: rain is summed, highs and lows are kept, and wind direction is vector-averaged.
4. **Results**: explore the cleaned data and download it.
   - Charts: time series with trendlines, before/after comparison, distribution, diurnal pattern, relationships, and a summary of removed rows.
   - An instrument-specific view: a wind rose for the AWS and a status-code summary for the C-12.
   - Downloads: the cleaned CSV, the cleaning report and the removed rows.

Long pauses in monitoring are collapsed on time-series charts and marked with two red dashed lines, so series and trendlines read continuously.

## Running it

Tested with Python 3.13, pandas 2.3 and Plotly 6.6.

```bash
pip install -r requirements.txt
python server.py
```

The app opens at <http://127.0.0.1:5000>. Use `python server.py --no-browser` to start it without opening a browser. Uploaded data is held in memory only while the app runs; nothing is sent elsewhere.

## Project layout

```
server.py          Flask routes and API
aq_core.py         Instrument parsers, QC defaults and the cleaning pipeline
aq_charts.py       Plotly figures (gap-aware time axis, wind rose, status codes)
templates/         Page template
static/            CSS and JavaScript
legacy/            Earlier Streamlit version, kept for reference
```

## Sources for instrument rules

- **C-12:** status-code meanings, the nominal 1 lpm flow and its 10% flow-failure threshold, and the box temperature and pressure sensor limits come from the Met One *C-12 Portable Carbon Monitor Operation Manual*, C-12-9800 Rev A, section 7 ([PDF](https://metone.com/wp-content/uploads/2022/01/C-12-9800-Rev-A.pdf)).
- **AWS:** the default range limits are general plausibility checks, not instrument specifications. Adjust them for your site and the units your station logs.

Please verify these sources against the manual for your own instrument and firmware before relying on the defaults.

## Data

No monitoring data is included in this repository. Place your own instrument files anywhere on your computer and upload them through the app.
