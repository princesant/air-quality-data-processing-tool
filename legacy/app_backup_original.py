# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import timedelta
import zipfile
import io
import numpy as np
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# ===== PAGE CONFIG =====
st.set_page_config(
    page_title="Air Quality Data Processing Tool",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===== CUSTOM STYLING =====
st.markdown("""
    <style>
    .main {
        padding: 20px;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    .stTabs [data-baseweb="tab-list"] button {
        font-size: 16px;
        font-weight: 600;
        padding: 12px 24px;
    }
    
    .stMetric {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 8px;
        border-left: 4px solid #1f77b4;
    }
    
    .stDataFrame {
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    h1 {
        color: #0d47a1;
        font-weight: 700;
        font-weight: 700;
        margin-bottom: 30px;
    }
    
    h2 {
        color: #1565c0;
        font-weight: 600;
        margin-top: 25px;
        margin-bottom: 15px;
    }
    
    .success-box {
        background-color: #e8f5e9;
        border-left: 4px solid #4caf50;
        padding: 12px;
        border-radius: 4px;
        margin: 10px 0;
    }
    
    .info-box {
        background-color: #e3f2fd;
        border-left: 4px solid #2196f3;
        padding: 12px;
        border-radius: 4px;
        margin: 10px 0;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🌍 Air Quality Data Processing Tool")

# ===== TYPE CONVERSION FUNCTIONS =====
def detect_and_convert_types(df):
    """Automatically detect and convert column types"""
    df_converted = df.copy()
    
    for col in df_converted.columns:
        # Try to convert to datetime
        if df_converted[col].dtype == 'object':
            try:
                df_converted[col] = pd.to_datetime(df_converted[col])
                continue
            except:
                pass
        
        # Try to convert to numeric
        try:
            df_converted[col] = pd.to_numeric(df_converted[col], errors='coerce')
            # If all values became NaN, revert
            if df_converted[col].isna().all():
                df_converted[col] = df[col]
        except:
            pass
    
    return df_converted


# ===== VISUALIZATION FUNCTIONS =====
def plot_timeseries(df, datetime_col, numeric_cols):
    """Create interactive time series line plot"""
    if datetime_col not in df.columns:
        st.error(f"❌ Column '{datetime_col}' not found")
        return None
    
    # Filter only numeric columns that exist
    valid_cols = [col for col in numeric_cols if col in df.columns and pd.api.types.is_numeric_dtype(df[col])]
    
    if not valid_cols:
        st.error("❌ No numeric columns selected")
        return None
    
    # Create figure
    fig = go.Figure()
    
    # Add traces for each numeric column
    colors = px.colors.qualitative.Set1
    for idx, col in enumerate(valid_cols):
        color = colors[idx % len(colors)]
        fig.add_trace(go.Scatter(
            x=df[datetime_col],
            y=df[col],
            mode='lines',
            name=col,
            line=dict(width=2, color=color),
            hovertemplate=f"<b>{col}</b><br>Time: %{{x}}<br>Value: %{{y:.2f}}<extra></extra>"
        ))
    
    # Update layout
    fig.update_layout(
        title=f"📈 Time Series Analysis",
        xaxis_title="Time",
        yaxis_title="Value",
        hovermode='x unified',
        height=500,
        template='plotly_white',
        font=dict(size=12),
        margin=dict(l=50, r=50, t=50, b=50)
    )
    
    return fig


# -------------------------------
# FUNCTION: CONVERTER
# -------------------------------
def convert_dusttrak_file(uploaded_file):
    lines = uploaded_file.getvalue().decode("utf-8").splitlines()

    start_date = None
    start_time = None

    for line in lines:
        parts = line.strip().split(",")
        if parts[0] == "Test Start Date":
            start_date = parts[1].strip()
        if parts[0] == "Test Start Time":
            start_time = parts[1].strip()

    if not start_date or not start_time:
        return None, None

    start_timestamp = pd.to_datetime(start_date + " " + start_time, dayfirst=True)
    file_timestamp = start_timestamp.strftime("%Y-%m-%d_%H-%M-%S")

    header_index = None
    for i, line in enumerate(lines):
        if line.startswith("Elapsed Time"):
            header_index = i
            break

    if header_index is None:
        return None, None

    df = pd.read_csv(uploaded_file, skiprows=header_index)
    df.columns = [c.strip() for c in df.columns]

    # REMOVE FLOW ERRORS
    if "Error" in df.columns:
        df = df[~df["Error"].str.contains("Flow", case=False, na=False)]

    # Timestamp creation
    df["Timestamp"] = [
        start_timestamp + timedelta(seconds=int(s))
        for s in df["Elapsed Time [s]"]
    ]

    # Convert mg/m3 → µg/m3
    pm_map = {
        "PM1 [mg/m3]": "PM1 [µg/m3]",
        "PM2.5 [mg/m3]": "PM2.5 [µg/m3]",
        "PM10 [mg/m3]": "PM10 [µg/m3]"
    }

    for old_col, new_col in pm_map.items():
        if old_col in df.columns:
            df[new_col] = df[old_col] * 1000

    final_df = df[[
        "Timestamp",
        "PM1 [µg/m3]",
        "PM2.5 [µg/m3]",
        "PM10 [µg/m3]"
    ]]

    return final_df, file_timestamp


# -------------------------------
# FUNCTIONS: DATA CLEANING
# -------------------------------
def remove_na_rows(df, columns):
    """Remove rows with NA/NaN/empty values in specified columns"""
    if not columns:
        return df.copy()
    initial_rows = len(df)
    df_clean = df.dropna(subset=columns, how='any')
    removed_rows = initial_rows - len(df_clean)
    return df_clean, removed_rows


def remove_outliers_3sigma(df, columns):
    """Remove outliers using 3-sigma method"""
    df_clean = df.copy()
    removed_count = 0
    
    for col in columns:
        if pd.api.types.is_numeric_dtype(df_clean[col]):
            mean = df_clean[col].mean()
            std = df_clean[col].std()
            lower_bound = mean - 3 * std
            upper_bound = mean + 3 * std
            
            mask = (df_clean[col] >= lower_bound) & (df_clean[col] <= upper_bound)
            removed_count += (~mask).sum()
            df_clean = df_clean[mask]
    
    return df_clean, removed_count


def remove_outliers_iqr(df, columns):
    """Remove outliers using Interquartile Range (IQR) method"""
    df_clean = df.copy()
    removed_count = 0
    
    for col in columns:
        if pd.api.types.is_numeric_dtype(df_clean[col]):
            Q1 = df_clean[col].quantile(0.25)
            Q3 = df_clean[col].quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            
            mask = (df_clean[col] >= lower_bound) & (df_clean[col] <= upper_bound)
            removed_count += (~mask).sum()
            df_clean = df_clean[mask]
    
    return df_clean, removed_count


# -------------------------------
# TABS
# -------------------------------
tab1, tab2 = st.tabs(["📂 DustTrak Data Processing", "🧹 Data Cleaning"])

# -------------------------------
# TAB 1: DUSTTRAK PROCESSING (Converter + Merger Combined)
# -------------------------------
with tab1:
    st.header("📂 DustTrak Data Processing")
    
    # ===== SECTION 1: CONVERTER =====
    with st.expander("🔄 Step 1: Convert Raw DustTrak Files", expanded=True):
        st.subheader("Convert Raw DustTrak Instrument Files")
        st.caption("Upload raw CSV files from DustTrak instruments and convert them to standardized format")
        
        uploaded_files = st.file_uploader(
            "📥 Upload DustTrak CSV file(s)",
            type=["csv"],
            accept_multiple_files=True,
            key="dusttrak_converter"
        )

        if uploaded_files:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔄 Convert Files", use_container_width=True, key="convert_btn"):
                    zip_buffer = io.BytesIO()
                    zip_file = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)

                    success_count = 0

                    for file in uploaded_files:
                        cleaned_df, file_timestamp = convert_dusttrak_file(file)

                        if cleaned_df is not None:
                            success_count += 1

                            output_name = f"{file_timestamp}.csv"
                            csv_bytes = cleaned_df.to_csv(index=False).encode("utf-8")

                            zip_file.writestr(output_name, csv_bytes)

                    zip_file.close()

                    if success_count > 0:
                        st.success(f"✅ {success_count} file(s) converted successfully!")
                        
                        st.download_button(
                            label="⬇️ Download All as ZIP",
                            data=zip_buffer.getvalue(),
                            file_name="dusttrak_converted_files.zip",
                            mime="application/zip",
                            use_container_width=True,
                            key="download_converted"
                        )
                    else:
                        st.error("❌ No valid files were processed.")
    
    st.markdown("---")
    
    # ===== SECTION 2: MERGER =====
    with st.expander("🔗 Step 2: Merge Converted Files", expanded=False):
        st.subheader("Merge Multiple Converted Files")
        st.caption("Combine multiple converted DustTrak files into a single dataset")
        
        merge_files = st.file_uploader(
            "📥 Upload converted CSV file(s) to merge",
            type=["csv"],
            accept_multiple_files=True,
            key="dusttrak_merger"
        )

        if merge_files:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔗 Merge Files", use_container_width=True, key="merge_btn"):
                    merged_df = pd.DataFrame()

                    for file in merge_files:
                        try:
                            df = pd.read_csv(file)

                            # Ensure Timestamp is datetime
                            df["Timestamp"] = pd.to_datetime(df["Timestamp"])

                            merged_df = pd.concat([merged_df, df], ignore_index=True)

                        except Exception as e:
                            st.warning(f"⚠️ Skipping file {file.name}: {e}")

                    if not merged_df.empty:
                        # Sort by time
                        merged_df = merged_df.sort_values("Timestamp")

                        st.success(f"✅ {len(merge_files)} file(s) merged successfully!")
                        
                        # Display info
                        col_info1, col_info2, col_info3 = st.columns(3)
                        with col_info1:
                            st.metric("📊 Total Rows", len(merged_df))
                        with col_info2:
                            st.metric("⏱️ Time Range", f"{merged_df['Timestamp'].min().date()} to {merged_df['Timestamp'].max().date()}")
                        with col_info3:
                            duration = (merged_df['Timestamp'].max() - merged_df['Timestamp'].min()).days
                            st.metric("📅 Duration", f"{duration} days")

                        st.subheader("📋 Merged Data Preview")
                        st.dataframe(merged_df.head(15), use_container_width=True)

                        # ===== TIME SERIES VISUALIZATION FOR MERGED DATA =====
                        st.subheader("📊 Time Series Visualization")
                        
                        numeric_cols_merged = merged_df.select_dtypes(include=[np.number]).columns.tolist()
                        
                        if numeric_cols_merged:
                            selected_numeric_merged = st.multiselect(
                                "📈 Select PM columns to visualize:",
                                options=numeric_cols_merged,
                                default=numeric_cols_merged,
                                key="merged_ts_cols"
                            )
                            
                            if st.button("📉 Generate Merged Time Series Plot", use_container_width=True, key="plot_merged_btn"):
                                fig = plot_timeseries(merged_df, "Timestamp", selected_numeric_merged)
                                if fig:
                                    st.plotly_chart(fig, use_container_width=True)
                        
                        st.markdown("---")

                        csv = merged_df.to_csv(index=False).encode("utf-8")

                        st.download_button(
                            label="⬇️ Download Merged CSV",
                            data=csv,
                            file_name="merged_dusttrak_data.csv",
                            mime="text/csv",
                            use_container_width=True,
                            key="download_merged"
                        )
                    else:
                        st.error("❌ No valid files to merge.")


# -------------------------------
# TAB 2: DATA CLEANING
# -------------------------------
with tab2:
    st.header("🧹 Data Cleaning & Preprocessing")
    
    # File uploader
    clean_file = st.file_uploader(
        "📥 Upload CSV file for cleaning",
        type=["csv"],
        key="clean_uploader"
    )
    
    if clean_file is not None:
        try:
            # Read file and convert types
            df = pd.read_csv(clean_file)
            df = detect_and_convert_types(df)
            
            # Display original data info
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📊 Total Rows", len(df))
            with col2:
                st.metric("📋 Total Columns", len(df.columns))
            with col3:
                st.metric("🔢 Numeric Cols", len(df.select_dtypes(include=[np.number]).columns))
            with col4:
                st.metric("📅 DateTime Cols", len(df.select_dtypes(include=['datetime64']).columns))
            
            # Display original data preview
            st.subheader("📋 Original Data Preview")
            st.dataframe(df.head(10), use_container_width=True)
            
            st.markdown("---")
            
            # ===== CLEANING OPTIONS IN EXPANDERS =====
            st.subheader("🛠️ Cleaning Options")
            
            # ===== SECTION 1: COLUMN SELECTION =====
            with st.expander("1️⃣ Select Columns to Keep", expanded=True):
                all_cols = df.columns.tolist()
                selected_cols = st.multiselect(
                    "Choose which columns to keep in the final output:",
                    options=all_cols,
                    default=all_cols,
                    key="column_selection"
                )
            
            # ===== SECTION 2: REMOVE NA/EMPTY ROWS =====
            with st.expander("2️⃣ Remove Missing Values (NA/Empty)", expanded=True):
                remove_na = st.checkbox("Remove rows with missing values", key="remove_na_check", value=False)
                
                if remove_na:
                    all_cols = df.columns.tolist()
                    na_columns = st.multiselect(
                        "Select columns to check for missing values:",
                        options=all_cols,
                        default=all_cols[:min(3, len(all_cols))],
                        key="na_columns"
                    )
                else:
                    na_columns = []
            
            # ===== SECTION 3: OUTLIER REMOVAL =====
            with st.expander("3️⃣ Remove Outliers (Optional)", expanded=True):
                remove_outliers = st.checkbox("Enable outlier removal", key="outlier_check", value=False)
                
                if remove_outliers:
                    col_left, col_right = st.columns(2)
                    
                    with col_left:
                        outlier_method = st.selectbox(
                            "🎯 Choose outlier removal method:",
                            options=["None", "3-Sigma Method", "IQR Method"],
                            index=0,
                            key="outlier_method"
                        )
                    
                    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
                    
                    outlier_columns = st.multiselect(
                        "Select numeric columns for outlier removal:",
                        options=numeric_cols,
                        default=numeric_cols[:min(3, len(numeric_cols))] if numeric_cols else [],
                        key="outlier_columns"
                    )
                else:
                    outlier_method = "None"
                    outlier_columns = []
            
            st.markdown("---")
            
            # ===== APPLY CLEANING BUTTON =====
            if st.button("🔄 Apply All Cleaning Operations", key="apply_cleaning", use_container_width=True):
                df_cleaned = df.copy()
                stats = {
                    "initial_rows": len(df),
                    "na_removed": 0,
                    "outlier_removed": 0,
                    "final_rows": 0
                }
                
                # Step 1: Select columns
                if selected_cols:
                    df_cleaned = df_cleaned[selected_cols]
                
                # Step 2: Remove NA
                if remove_na and na_columns:
                    initial_rows = len(df_cleaned)
                    df_cleaned = df_cleaned.dropna(subset=na_columns, how='any')
                    stats["na_removed"] = initial_rows - len(df_cleaned)
                
                # Step 3: Remove Outliers (only one method)
                if remove_outliers and outlier_method != "None" and outlier_columns:
                    initial_rows = len(df_cleaned)
                    
                    if outlier_method == "3-Sigma Method":
                        for col in outlier_columns:
                            if col in df_cleaned.columns and pd.api.types.is_numeric_dtype(df_cleaned[col]):
                                mean = df_cleaned[col].mean()
                                std = df_cleaned[col].std()
                                lower_bound = mean - 3 * std
                                upper_bound = mean + 3 * std
                                df_cleaned = df_cleaned[(df_cleaned[col] >= lower_bound) & (df_cleaned[col] <= upper_bound)]
                    
                    elif outlier_method == "IQR Method":
                        for col in outlier_columns:
                            if col in df_cleaned.columns and pd.api.types.is_numeric_dtype(df_cleaned[col]):
                                Q1 = df_cleaned[col].quantile(0.25)
                                Q3 = df_cleaned[col].quantile(0.75)
                                IQR = Q3 - Q1
                                lower_bound = Q1 - 1.5 * IQR
                                upper_bound = Q3 + 1.5 * IQR
                                df_cleaned = df_cleaned[(df_cleaned[col] >= lower_bound) & (df_cleaned[col] <= upper_bound)]
                    
                    stats["outlier_removed"] = initial_rows - len(df_cleaned)
                
                stats["final_rows"] = len(df_cleaned)
                
                # Display success message
                st.success("✅ Cleaning completed successfully!")
                
                # Display summary metrics
                st.subheader("📊 Cleaning Summary")
                col1, col2, col3, col4, col5 = st.columns(5)
                
                with col1:
                    st.metric("Initial Rows", stats["initial_rows"])
                with col2:
                    st.metric("NA Removed", stats["na_removed"])
                with col3:
                    st.metric("Outliers Removed", stats["outlier_removed"])
                with col4:
                    st.metric("Final Rows", stats["final_rows"])
                with col5:
                    retained_pct = (stats["final_rows"] / stats["initial_rows"] * 100) if stats["initial_rows"] > 0 else 0
                    st.metric("Data Retained", f"{retained_pct:.1f}%")
                
                st.markdown("---")
                
                # Display cleaned data
                st.subheader("✨ Cleaned Data Preview")
                st.dataframe(df_cleaned.head(15), use_container_width=True)
                
                # Display data types info
                st.subheader("🔍 Data Types (Auto-Converted)")
                type_info = pd.DataFrame({
                    'Column': df_cleaned.columns,
                    'Data Type': df_cleaned.dtypes.astype(str)
                })
                st.dataframe(type_info, use_container_width=True)
                
                # Display statistics
                st.subheader("📈 Data Statistics (Cleaned)")
                st.dataframe(df_cleaned.describe(), use_container_width=True)
                
                st.markdown("---")
                
                # ===== TIME SERIES VISUALIZATION =====
                st.subheader("📊 Time Series Visualization")
                
                # Find datetime columns
                datetime_cols = df_cleaned.select_dtypes(include=['datetime64']).columns.tolist()
                numeric_cols = df_cleaned.select_dtypes(include=[np.number]).columns.tolist()
                
                if datetime_cols and numeric_cols:
                    col_viz1, col_viz2 = st.columns(2)
                    
                    with col_viz1:
                        selected_datetime = st.selectbox(
                            "📅 Select datetime column (X-axis):",
                            options=datetime_cols,
                            key="ts_datetime_col"
                        )
                    
                    with col_viz2:
                        selected_numeric = st.multiselect(
                            "📈 Select numeric columns to plot (Y-axis):",
                            options=numeric_cols,
                            default=numeric_cols[:min(2, len(numeric_cols))],
                            key="ts_numeric_cols"
                        )
                    
                    if st.button("📉 Generate Time Series Plot", use_container_width=True, key="plot_btn"):
                        if selected_numeric:
                            fig = plot_timeseries(df_cleaned, selected_datetime, selected_numeric)
                            if fig:
                                st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.warning("⚠️ Please select at least one numeric column")
                else:
                    st.info("💡 No datetime or numeric columns found for visualization")
                
                st.markdown("---")
                
                # Download cleaned data
                csv_cleaned = df_cleaned.to_csv(index=False).encode("utf-8")
                
                st.download_button(
                    label="⬇️ Download Cleaned CSV",
                    data=csv_cleaned,
                    file_name=f"cleaned_{clean_file.name}",
                    mime="text/csv",
                    use_container_width=True
                )
        
        except Exception as e:
            st.error(f"❌ Error processing file: {str(e)}")