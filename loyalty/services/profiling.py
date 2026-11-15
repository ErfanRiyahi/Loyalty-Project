"""Dataset inspection without modifying source column names or source data."""

import numpy as np
import pandas as pd
from ..progress import stage as track_stage


# Build the profile and time series without modifying input data or column names.
@track_stage("Inspect dataset")
def profile_dataset(
    frame, date_column=None, usage_column=None, frequency="day", user_column=None
):
    if bool(date_column) != bool(usage_column):
        raise ValueError(
            "Provide both the date column and usage column, or leave both empty."
        )
    for column in [date_column, usage_column, user_column]:
        if column and column not in frame.columns:
            raise ValueError(f"Column not found: {column}")
    if frequency not in ["day", "week", "month"]:
        raise ValueError("Frequency must be day, week or month.")
    summary = {
        "rows": len(frame),
        "columns": len(frame.columns),
        "null_values": int(frame.isna().sum().sum()),
        "rows_with_nulls": int(frame.isna().any(axis=1).sum()),
        "duplicate_rows": int(frame.duplicated().sum()),
        "memory_bytes": int(frame.memory_usage(deep=True).sum()),
        "column_info": [
            {
                "name": str(column),
                "dtype": str(frame[column].dtype),
                "nulls": int(frame[column].isna().sum()),
                "null_percentage": (
                    round(float(frame[column].isna().mean() * 100), 2)
                    if len(frame)
                    else 0
                ),
                "unique": int(frame[column].nunique(dropna=True)),
            }
            for column in frame.columns
        ],
        "preview": frame.head(5)
        .astype(object)
        .where(pd.notna(frame.head(5)), None)
        .to_dict(orient="records"),
    }
    if user_column:
        summary["unique_users"] = int(frame[user_column].nunique(dropna=True))
    chart = None
    if date_column:
        # Treat dates as text to avoid interpreting integer date labels as epoch nanoseconds.
        dates = pd.to_datetime(
            frame[date_column].astype("string"),
            errors="coerce",
            utc=True,
            format="mixed",
        )
        usage = pd.to_numeric(frame[usage_column], errors="coerce")
        finite = usage.notna() & np.isfinite(usage)
        valid = dates.notna() & finite
        summary["invalid_dates"] = int(
            (frame[date_column].notna() & dates.isna()).sum()
        )
        summary["invalid_usage"] = int((frame[usage_column].notna() & ~finite).sum())
        summary["rows_used_in_chart"] = int(valid.sum())
        summary["rows_excluded_from_chart"] = int((~valid).sum())
        summary["date_range"] = {
            "start": dates.min().isoformat() if dates.notna().any() else None,
            "end": dates.max().isoformat() if dates.notna().any() else None,
        }
        series = pd.Series(
            usage.loc[valid].to_numpy(dtype=float),
            index=pd.DatetimeIndex(dates.loc[valid]),
        )
        # Sum every valid row. Coarsen bins, rather than dropping observations, for long histories.
        frequencies = {
            "day": ["D", "MS", "YS"],
            "week": ["W-MON", "MS", "YS"],
            "month": ["MS", "YS"],
        }
        grouped = pd.Series(dtype=float)
        actual_frequency = frequencies[frequency][0]
        if not series.empty:
            for actual_frequency in frequencies[frequency]:
                grouped = series.resample(actual_frequency).sum(min_count=1).dropna()
                if len(grouped) <= 1000:
                    break
            if not np.isfinite(grouped.to_numpy()).all():
                raise ValueError("Usage totals overflowed. Check the selected values.")
        chart = {
            "date_column": date_column,
            "usage_column": usage_column,
            "requested_frequency": frequency,
            "frequency": {"D": "day", "W-MON": "week", "MS": "month", "YS": "year"}[
                actual_frequency
            ],
            "aggregation": "sum",
            "timezone": "UTC",
            "points": [
                {"date": date.isoformat(), "usage": float(value)}
                for date, value in grouped.items()
            ],
        }
    return {"dataset_overview": summary, "time_series": chart}
