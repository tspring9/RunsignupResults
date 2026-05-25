import os
from collections.abc import Mapping
from typing import Any

import pandas as pd
import requests
import streamlit as st


st.set_page_config(page_title="RunSignup Race Results", layout="wide")
st.title("RunSignup Race Results Puller")
st.caption("Enter a RunSignup race_id and event_id to pull available result data.")


def get_secret(name: str, default: str = "") -> str:
    """
    Reads from Streamlit secrets first, then environment variables.
    Recommended secrets:
      RUNSIGNUP_API_KEY
      RUNSIGNUP_API_SECRET
    """
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass

    return os.getenv(name, default)


def api_get(url: str, params: dict[str, Any], timeout: int = 45) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=timeout)

    if response.status_code != 200:
        raise RuntimeError(
            f"RunSignup returned HTTP {response.status_code}:\n\n{response.text[:3000]}"
        )

    try:
        return response.json()
    except Exception:
        raise RuntimeError(f"RunSignup did not return valid JSON:\n\n{response.text[:3000]}")


def flatten_dict(value: Any, prefix: str = "") -> dict[str, Any]:
    """
    Recursively flattens nested dicts/lists into one row.
    Lists of primitive values are joined.
    Lists of dicts are preserved as compact text unless handled elsewhere.
    """
    row = {}

    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            new_prefix = f"{prefix}_{key}" if prefix else str(key)
            row.update(flatten_dict(nested_value, new_prefix))
    elif isinstance(value, list):
        if all(not isinstance(x, (dict, list)) for x in value):
            row[prefix] = "; ".join("" if x is None else str(x) for x in value)
        else:
            row[prefix] = str(value)
    else:
        row[prefix] = value

    return row


def find_result_like_records(data: Any) -> list[dict[str, Any]]:
    """
    RunSignup result responses can vary by result set/race configuration.
    This searches recursively for likely result records and returns them.
    """
    records = []

    likely_result_keys = {
        "result_id",
        "place",
        "overall_place",
        "gender_place",
        "division_place",
        "bib_num",
        "bib",
        "chip_time",
        "clock_time",
        "gun_time",
        "finish_time",
        "first_name",
        "last_name",
        "registration_id",
    }

    def walk(obj: Any):
        if isinstance(obj, dict):
            keys = set(obj.keys())

            # Common wrapper format: {"result": {...}}
            if "result" in obj and isinstance(obj["result"], dict):
                records.append(obj["result"])
                return

            # Direct result-looking object
            if len(keys.intersection(likely_result_keys)) >= 2:
                records.append(obj)
                return

            for nested in obj.values():
                walk(nested)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    # De-duplicate records while preserving order.
    seen = set()
    unique_records = []
    for record in records:
        marker = repr(sorted(flatten_dict(record).items()))
        if marker not in seen:
            seen.add(marker)
            unique_records.append(record)

    return unique_records


def result_sets_to_dataframe(data: dict[str, Any]) -> pd.DataFrame:
    """
    Converts get-result-sets response into a dataframe.
    """
    candidates = []

    def walk(obj: Any):
        if isinstance(obj, dict):
            if "result_set_id" in obj or "individual_result_set_id" in obj:
                candidates.append(obj)
                return
            if "result_set" in obj and isinstance(obj["result_set"], dict):
                candidates.append(obj["result_set"])
                return
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    if not candidates:
        return pd.DataFrame()

    return pd.DataFrame([flatten_dict(item) for item in candidates])


def results_to_dataframe(data: dict[str, Any]) -> pd.DataFrame:
    records = find_result_like_records(data)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame([flatten_dict(record) for record in records])

    # Put the most useful fields first when present.
    preferred_cols = [
        "result_id",
        "registration_id",
        "bib_num",
        "bib",
        "first_name",
        "last_name",
        "gender",
        "age",
        "city",
        "state",
        "place",
        "overall_place",
        "gender_place",
        "division_place",
        "division",
        "clock_time",
        "chip_time",
        "gun_time",
        "finish_time",
        "pace",
    ]

    ordered = [col for col in preferred_cols if col in df.columns]
    remaining = [col for col in df.columns if col not in ordered]

    return df[ordered + remaining]


def get_result_sets(
    api_key: str,
    api_secret: str,
    race_id: str,
    event_id: str,
    include_ms: bool,
) -> pd.DataFrame:
    url = f"https://api.runsignup.com/rest/race/{race_id}/results/get-result-sets"
    params = {
        "format": "json",
        "api_key": api_key,
        "api_secret": api_secret,
        "event_id": event_id,
    }

    if include_ms:
        params["include_split_time_ms"] = "T"

    data = api_get(url, params)
    return result_sets_to_dataframe(data)


def get_results(
    api_key: str,
    api_secret: str,
    race_id: str,
    event_id: str,
    individual_result_set_id: str,
    include_total_finishers: bool,
    include_ms: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = f"https://api.runsignup.com/rest/race/{race_id}/results/get-results"

    params = {
        "format": "json",
        "api_key": api_key,
        "api_secret": api_secret,
        "event_id": event_id,
    }

    if individual_result_set_id.strip():
        params["individual_result_set_id"] = individual_result_set_id.strip()

    if include_total_finishers:
        params["include_total_finishers"] = "T"

    if include_ms:
        params["include_split_time_ms"] = "T"

    data = api_get(url, params)
    return results_to_dataframe(data), data


with st.sidebar:
    st.header("API Credentials")

    api_key = st.text_input(
        "RunSignup API Key",
        value=get_secret("RUNSIGNUP_API_KEY"),
        type="password",
    )
    api_secret = st.text_input(
        "RunSignup API Secret",
        value=get_secret("RUNSIGNUP_API_SECRET"),
        type="password",
    )

    st.divider()
    st.header("Required IDs")

    race_id = st.text_input("Race ID", value="")
    event_id = st.text_input("Event ID", value="")

    st.divider()
    st.header("Optional")

    individual_result_set_id = st.text_input(
        "Individual Result Set ID",
        value="",
        help="Optional. Use this if the event has multiple result sets.",
    )

    include_total_finishers = st.checkbox("Include total finishers metadata", value=True)
    include_ms = st.checkbox("Include split milliseconds", value=False)

    st.divider()
    show_raw_json = st.checkbox("Show raw JSON response", value=False)


if not api_key or not api_secret:
    st.warning("Enter your RunSignup API credentials in the sidebar, or store them in Streamlit secrets.")
    st.code(
        """
# .streamlit/secrets.toml
RUNSIGNUP_API_KEY = "your_api_key_here"
RUNSIGNUP_API_SECRET = "your_api_secret_here"
""".strip(),
        language="toml",
    )
    st.stop()


if not race_id or not event_id:
    st.info("Enter both a Race ID and Event ID to pull results.")
    st.stop()


col1, col2 = st.columns(2)

with col1:
    lookup_sets = st.button("1. Check available result sets")

with col2:
    pull_results = st.button("2. Pull race results", type="primary")


if lookup_sets:
    with st.spinner("Checking result sets..."):
        try:
            sets_df = get_result_sets(
                api_key=api_key,
                api_secret=api_secret,
                race_id=race_id,
                event_id=event_id,
                include_ms=include_ms,
            )
        except Exception as exc:
            st.error("Result set lookup failed.")
            st.code(str(exc))
            st.stop()

    if sets_df.empty:
        st.info("No result sets were found or the response format did not include recognizable result set records.")
    else:
        st.success(f"Found {len(sets_df):,} result set row(s).")
        st.dataframe(sets_df, use_container_width=True, hide_index=True)

        st.download_button(
            "Download result sets CSV",
            data=sets_df.to_csv(index=False).encode("utf-8"),
            file_name=f"runsignup_result_sets_race_{race_id}_event_{event_id}.csv",
            mime="text/csv",
        )


if pull_results:
    with st.spinner("Pulling results from RunSignup..."):
        try:
            results_df, raw_data = get_results(
                api_key=api_key,
                api_secret=api_secret,
                race_id=race_id,
                event_id=event_id,
                individual_result_set_id=individual_result_set_id,
                include_total_finishers=include_total_finishers,
                include_ms=include_ms,
            )
        except Exception as exc:
            st.error("Results pull failed.")
            st.code(str(exc))
            st.stop()

    if results_df.empty:
        st.warning(
            "The API call succeeded, but I could not find recognizable result rows in the response. "
            "Turn on 'Show raw JSON response' to inspect the structure."
        )
    else:
        st.success(f"Pulled {len(results_df):,} result row(s).")
        st.dataframe(results_df, use_container_width=True, hide_index=True)

        st.download_button(
            "Download results CSV",
            data=results_df.to_csv(index=False).encode("utf-8"),
            file_name=f"runsignup_results_race_{race_id}_event_{event_id}.csv",
            mime="text/csv",
        )

    if show_raw_json:
        st.subheader("Raw JSON")
        st.json(raw_data)
