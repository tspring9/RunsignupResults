import json
from datetime import datetime, timedelta, timezone
from typing import Any
from collections.abc import Mapping

import pandas as pd
import requests
import streamlit as st


# Hard-coded for quick testing, per request.
# WARNING: Do not keep API secrets in a public GitHub repo long-term.
API_KEY = "b5joqX8Ur02116FakymNv5N8wlsCoNhO"
API_SECRET = "rllMlmau5DQjlfFcVF0HUJ0ILzfi27gp"

BASE_URL = "https://api.runsignup.com/rest"


st.set_page_config(page_title="RunSignup Results API Diagnostic", layout="wide")
st.title("RunSignup Results API Diagnostic")
st.caption(
    "Tests multiple RunSignup results-related endpoints to determine where a race's result data is exposed."
)


def api_get(label: str, url: str, params: dict[str, Any], timeout: int = 45) -> dict[str, Any]:
    """
    Makes one GET request and returns a diagnostic package.
    This keeps errors visible inside the Streamlit app rather than crashing the whole page.
    """
    clean_params = dict(params)

    try:
        response = requests.get(url, params=clean_params, timeout=timeout)

        try:
            payload = response.json()
        except Exception:
            payload = response.text

        return {
            "label": label,
            "url": url,
            "status_code": response.status_code,
            "ok": response.ok,
            "params_used": clean_params,
            "payload": payload,
        }

    except Exception as exc:
        return {
            "label": label,
            "url": url,
            "status_code": None,
            "ok": False,
            "params_used": clean_params,
            "payload": {"error": str(exc)},
        }


def flatten_dict(value: Any, prefix: str = "") -> dict[str, Any]:
    row = {}

    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            new_prefix = f"{prefix}_{key}" if prefix else str(key)
            row.update(flatten_dict(nested_value, new_prefix))
    elif isinstance(value, list):
        if all(not isinstance(x, (dict, list)) for x in value):
            row[prefix] = "; ".join("" if x is None else str(x) for x in value)
        else:
            row[prefix] = json.dumps(value, default=str)
    else:
        row[prefix] = value

    return row


def find_records_by_keys(data: Any, key_names: set[str]) -> list[dict[str, Any]]:
    """
    Recursively finds dicts that contain any of the target keys.
    Useful because RunSignup responses vary by endpoint.
    """
    records = []

    def walk(obj: Any):
        if isinstance(obj, dict):
            if set(obj.keys()).intersection(key_names):
                records.append(obj)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    seen = set()
    unique = []

    for record in records:
        marker = json.dumps(flatten_dict(record), sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            unique.append(record)

    return unique


def payload_to_dataframe(payload: Any, mode: str) -> pd.DataFrame:
    """
    Attempts to extract useful table rows from known RunSignup payloads.
    """
    if not isinstance(payload, dict):
        return pd.DataFrame()

    if mode == "result_sets":
        records = payload.get("individual_results_sets", [])
        return pd.DataFrame([flatten_dict(r) for r in records]) if records else pd.DataFrame()

    if mode == "results":
        rows = []
        result_sets = payload.get("individual_results_sets", [])

        for result_set in result_sets:
            result_set_id = result_set.get("individual_result_set_id")
            result_set_name = result_set.get("individual_result_set_name")

            result_rows = (
                result_set.get("individual_results")
                or result_set.get("results")
                or []
            )

            for result in result_rows:
                flat = flatten_dict(result)
                flat["individual_result_set_id"] = result_set_id
                flat["individual_result_set_name"] = result_set_name
                rows.append(flat)

        return pd.DataFrame(rows) if rows else pd.DataFrame()

    if mode == "timing":
        records = find_records_by_keys(
            payload,
            {
                "timing_data_id",
                "finish_time",
                "chip_time",
                "clock_time",
                "bib_num",
                "registration_id",
                "event_id",
            },
        )
        return pd.DataFrame([flatten_dict(r) for r in records]) if records else pd.DataFrame()

    if mode == "updated_sets":
        records = find_records_by_keys(
            payload,
            {
                "individual_result_set_id",
                "result_set_id",
                "race_id",
                "event_id",
                "last_modified",
                "modified_timestamp",
            },
        )
        return pd.DataFrame([flatten_dict(r) for r in records]) if records else pd.DataFrame()

    if mode == "generic":
        records = find_records_by_keys(payload, {"has_result_sets", "result_sets", "individual_results_sets"})
        return pd.DataFrame([flatten_dict(r) for r in records]) if records else pd.DataFrame()

    return pd.DataFrame()


def reorder_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    preferred = [
        "race_id",
        "event_id",
        "individual_result_set_id",
        "individual_result_set_name",
        "result_set_id",
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
        "clock_time",
        "chip_time",
        "gun_time",
        "finish_time",
        "pace",
        "last_modified",
        "modified_timestamp",
    ]

    ordered = [c for c in preferred if c in df.columns]
    remaining = [c for c in df.columns if c not in ordered]
    return df[ordered + remaining]


def display_diagnostic_result(result: dict[str, Any], mode: str):
    label = result["label"]
    status_code = result["status_code"]
    ok = result["ok"]
    payload = result["payload"]

    st.subheader(label)

    if ok:
        st.success(f"HTTP {status_code}")
    else:
        st.error(f"HTTP {status_code}" if status_code else "Request failed")

    with st.expander("Request details"):
        st.write(result["url"])
        safe_params = dict(result["params_used"])
        if "api_secret" in safe_params:
            safe_params["api_secret"] = "***hidden***"
        if "api_key" in safe_params:
            safe_params["api_key"] = "***hidden***"
        st.json(safe_params)

    df = reorder_columns(payload_to_dataframe(payload, mode))

    if df.empty:
        st.warning("No recognizable table rows found in this response.")
    else:
        st.write(f"Detected **{len(df):,}** row(s).")
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button(
            f"Download {label} CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name=f"{label.lower().replace(' ', '_').replace('/', '_')}.csv",
            mime="text/csv",
            key=f"download_{label}",
        )

    with st.expander("Raw JSON response"):
        st.json(payload)


with st.sidebar:
    st.header("Race / Event IDs")

    race_id = st.text_input("Race ID", value="")
    event_id = st.text_input("Event ID", value="")

    st.divider()
    st.header("Optional IDs / Filters")

    individual_result_set_id = st.text_input(
        "Individual Result Set ID",
        value="",
        help="Optional. If you know the specific result set, enter it here.",
    )

    result_search = st.text_input(
        "Search term",
        value="",
        help="Optional. Some result endpoints support searching by name/bib/etc.",
    )

    st.divider()
    st.header("Pagination")

    page = st.number_input("Page", min_value=1, max_value=1000, value=1)
    results_per_page = st.number_input("Results per page", min_value=1, max_value=1000, value=100)

    st.divider()
    st.header("Updated public result sets")

    days_back = st.number_input(
        "Look back this many days",
        min_value=1,
        max_value=3650,
        value=365,
        help="Used for the public updated-result-sets endpoint.",
    )

    st.divider()
    include_ms = st.checkbox("Include split milliseconds", value=False)
    include_total_finishers = st.checkbox("Include total finishers", value=True)
    include_division_finishers = st.checkbox("Include division finishers", value=False)


st.info(
    "This app intentionally tests several endpoints. If public results are visible on the website but "
    "these API calls return empty, the results may be hosted on a public page but not exposed through "
    "your API access scope."
)

if not race_id or not event_id:
    st.warning("Enter a Race ID and Event ID in the sidebar.")
    st.stop()


common_params = {
    "format": "json",
    "api_key": API_KEY,
    "api_secret": API_SECRET,
    "event_id": event_id,
}

if include_total_finishers:
    common_params["include_total_finishers"] = "T"

if include_division_finishers:
    common_params["include_division_finishers"] = "T"

if include_ms:
    common_params["include_split_time_ms"] = "T"

if result_search.strip():
    common_params["search"] = result_search.strip()


run_all = st.button("Run diagnostic calls", type="primary")

if run_all:
    diagnostics = []

    diagnostics.append(
        api_get(
            "Has Result Sets",
            f"{BASE_URL}/race/{race_id}/results/has-result-sets",
            {
                "format": "json",
                "api_key": API_KEY,
                "api_secret": API_SECRET,
                "event_id": event_id,
            },
        )
    )

    diagnostics.append(
        api_get(
            "Get Result Sets",
            f"{BASE_URL}/race/{race_id}/results/get-result-sets",
            common_params,
        )
    )

    get_results_params = dict(common_params)
    get_results_params["page"] = page
    get_results_params["results_per_page"] = results_per_page

    if individual_result_set_id.strip():
        get_results_params["individual_result_set_id"] = individual_result_set_id.strip()

    diagnostics.append(
        api_get(
            "Get Results",
            f"{BASE_URL}/race/{race_id}/results/get-results",
            get_results_params,
        )
    )

    timing_params = {
        "format": "json",
        "api_key": API_KEY,
        "api_secret": API_SECRET,
        "event_id": event_id,
        "page": page,
        "results_per_page": results_per_page,
    }

    diagnostics.append(
        api_get(
            "Get Timing Data",
            f"{BASE_URL}/race/{race_id}/results/get-timing-data",
            timing_params,
        )
    )

    modified_after = int((datetime.now(timezone.utc) - timedelta(days=int(days_back))).timestamp())

    diagnostics.append(
        api_get(
            "Public Updated Result Sets",
            "https://api.runsignup.com/rest/v2/results/updated-result-sets.json",
            {
                "format": "json",
                "api_key": API_KEY,
                "api_secret": API_SECRET,
                "modified_after_timestamp": modified_after,
                "page": page,
                "results_per_page": results_per_page,
            },
        )
    )

    st.divider()

    for result in diagnostics:
        label = result["label"]

        if label == "Get Result Sets":
            mode = "result_sets"
        elif label == "Get Results":
            mode = "results"
        elif label == "Get Timing Data":
            mode = "timing"
        elif label == "Public Updated Result Sets":
            mode = "updated_sets"
        else:
            mode = "generic"

        display_diagnostic_result(result, mode)
        st.divider()

    st.subheader("Quick interpretation")

    get_sets = next((r for r in diagnostics if r["label"] == "Get Result Sets"), None)
    get_results = next((r for r in diagnostics if r["label"] == "Get Results"), None)
    timing = next((r for r in diagnostics if r["label"] == "Get Timing Data"), None)

    sets_df = payload_to_dataframe(get_sets["payload"], "result_sets") if get_sets else pd.DataFrame()
    results_df = payload_to_dataframe(get_results["payload"], "results") if get_results else pd.DataFrame()
    timing_df = payload_to_dataframe(timing["payload"], "timing") if timing else pd.DataFrame()

    if not sets_df.empty:
        st.success(
            "Result sets were found. Use the displayed individual_result_set_id in the optional field, "
            "then rerun the diagnostic."
        )
    elif not results_df.empty:
        st.success("Results were found directly from Get Results.")
    elif not timing_df.empty:
        st.success("Timing data was found. The race may expose timing records but not normal published result sets.")
    else:
        st.warning(
            "No result rows were found from the standard result endpoints. "
            "If the public website shows results, they may be coming from a custom/public page, "
            "a different event_id, or a result source not exposed to your current API credentials."
        )
else:
    st.write("Enter IDs in the sidebar, then click **Run diagnostic calls**.")
