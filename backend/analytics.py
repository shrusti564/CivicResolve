
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATASET_PATH = (
    ROOT / "data" / "raw" /
    "bengaluru_icmc_complaints_2019_2022.csv"
)


_cached_df = None


def load_complaints():
    """Load and clean historical Bengaluru complaints with in-memory caching."""
    global _cached_df
    if _cached_df is not None:
        return _cached_df

    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Complaint dataset not found: {DATASET_PATH}"
        )

    df = pd.read_csv(DATASET_PATH)

    df["created_at"] = pd.to_datetime(
        df["created_at"], errors="coerce", utc=True
    )

    for column in ["category_title", "complaint_status_title",
                   "civic_agency_title", "ward_title"]:
        df[column] = df[column].fillna("Unknown").astype(str)

    df["latitude"] = pd.to_numeric(
        df["latitude"], errors="coerce"
    )
    df["longitude"] = pd.to_numeric(
        df["longitude"], errors="coerce"
    )

    _cached_df = df
    return _cached_df


def get_dashboard_kpis():
    df = load_complaints()

    total = len(df)
    resolved = int(
        df["complaint_status_title"].str.lower()
        .eq("resolved").sum()
    )
    open_count = int(
        df["complaint_status_title"].str.lower()
        .eq("open").sum()
    )
    in_progress = int(
        df["complaint_status_title"].str.lower()
        .eq("on-the-job").sum()
    )
    rejected = int(
        df["complaint_status_title"].str.lower()
        .eq("rejected").sum()
    )

    return {
        "data_type": "historical",
        "period": "2019-2022",
        "total_complaints": total,
        "resolved_complaints": resolved,
        "open_complaints": open_count,
        "in_progress_complaints": in_progress,
        "rejected_complaints": rejected,
        "resolution_rate_percent": round(
            resolved / total * 100, 2
        ) if total else 0,
        "records_with_gps": int(
            df[["latitude", "longitude"]].dropna().shape[0]
        )
    }


def get_category_statistics():
    df = load_complaints()

    return (
        df["category_title"]
        .value_counts()
        .rename_axis("category")
        .reset_index(name="complaints")
        .to_dict(orient="records")
    )


def get_status_statistics():
    df = load_complaints()

    return (
        df["complaint_status_title"]
        .value_counts()
        .rename_axis("status")
        .reset_index(name="complaints")
        .to_dict(orient="records")
    )


def get_monthly_statistics():
    df = load_complaints()

    df = df.dropna(subset=["created_at"]).copy()

    df["month"] = (
        df["created_at"].dt.strftime("%Y-%m")
    )

    return (
        df.groupby("month")
        .size()
        .reset_index(name="complaints")
        .to_dict(orient="records")
    )


def get_ward_statistics():
    df = load_complaints()

    return (
        df.groupby("ward_title")
        .size()
        .reset_index(name="complaints")
        .sort_values("complaints", ascending=False)
        .head(20)
        .to_dict(orient="records")
    )
