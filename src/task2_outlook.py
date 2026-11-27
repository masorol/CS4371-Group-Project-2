import argparse
import os
import re
from pathlib import Path
from decimal import Decimal, InvalidOperation
import hashlib, json, time
from datetime import datetime, timezone

import pandas as pd
import requests


# CONFIGURATION

PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "neighbourhood_month.parquet"
)

OUTPUT_DIR = PROJECT_ROOT / "outputs"
REPORT_DIR = PROJECT_ROOT / "reports"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"

YEARS = [2022, 2023, 2024]
MONTH_NAMES = {
    1: "January", 2: "February", 3: "March",
    4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September",
    10: "October", 11: "November", 12: "December"
}

REQUIRED_COLUMNS = [
    "precinct",
    "year",
    "month",
    "total_incidents",
    "crimes_against_persons",
    "crimes_against_property",
    "other",
]


CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "groq"
_last_call = 0.0

def call_groq(payload, headers):
    global _last_call
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        print("Using cached Groq response from", cached["retrieved_at_utc"])
        return cached["response"]
    gap = time.time() - _last_call
    if gap < 1.0:
        time.sleep(1.0 - gap)
    response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=90)
    _last_call = time.time()
    response.raise_for_status()
    data = response.json()
    path.write_text(json.dumps({
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "response": data}), encoding="utf-8")
    return data


# LOAD AND VALIDATE TASK 1 DATA

def load_data():
    print("\nReading Task 1 Parquet dataset...")

    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Task 1 Parquet file not found: {INPUT_PATH}"
        )

    df = pd.read_parquet(INPUT_PATH)

    missing = set(REQUIRED_COLUMNS) - set(df.columns)

    if missing:
        raise ValueError(
            f"Missing required columns: {sorted(missing)}"
        )

    for column in REQUIRED_COLUMNS:
        df[column] = pd.to_numeric(
            df[column], errors="raise"
        )

    df["precinct"] = df["precinct"].astype(int)
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)

    if df.duplicated(["precinct", "year", "month"]).any():
        raise ValueError(
            "Task 1 dataset contains duplicate precinct/year/month keys."
        )

    if not df["year"].isin(YEARS).all():
        raise ValueError("Unexpected year found in Task 1 data.")

    if not df["month"].between(1, 12).all():
        raise ValueError("Invalid month found in Task 1 data.")

    print(f"Rows loaded: {len(df):,}")
    print(f"Distinct precincts: {df['precinct'].nunique()}")

    return df



# CREATE COMPLETE PRECINCT-MONTH GRID

def complete_month_grid(df):

    precincts = sorted(df["precinct"].unique())

    complete_grid = pd.MultiIndex.from_product(
        [precincts, YEARS, range(1, 13)],
        names=["precinct", "year", "month"]
    ).to_frame(index=False)

    complete_df = complete_grid.merge(
        df,
        on=["precinct", "year", "month"],
        how="left"
    )

    count_columns = [
        "total_incidents",
        "crimes_against_persons",
        "crimes_against_property",
        "other",
    ]

    complete_df[count_columns] = (
        complete_df[count_columns].fillna(0)
    )

    print(
        f"Complete grid rows: {len(complete_df):,} "
        f"({len(precincts)} precincts x 36 months)"
    )

    return complete_df



# CALCULATE MONTHLY OUTLOOK

def calculate_outlook(df, selected_month):

    selected = (
        df[df["month"] == selected_month]
        .groupby("precinct", as_index=False)
        .agg(
            avg_monthly_incidents=("total_incidents", "mean"),
            avg_crimes_against_persons=(
                "crimes_against_persons", "mean"
            ),
            avg_crimes_against_property=(
                "crimes_against_property", "mean"
            ),
            avg_other=("other", "mean"),
        )
    )

    overall = (
        df.groupby("precinct", as_index=False)
        .agg(
            avg_all_months=("total_incidents", "mean")
        )
    )

    result = selected.merge(
        overall,
        on="precinct",
        how="inner"
    )

    city_average = result["avg_monthly_incidents"].sum()

    if city_average <= 0:
        raise ValueError(
            "The selected month has no incidents in the dataset."
        )

    result["city_share_pct"] = (
        result["avg_monthly_incidents"]
        / city_average
        * 100
    )

    result["seasonal_ratio"] = (
        result["avg_monthly_incidents"]
        / result["avg_all_months"]
    )

    result["month"] = selected_month

    return result



# CREATE THREE TOP-FIVE LISTS

def assign_rankings(df):

    result = df.copy()

    highest = (
        result.sort_values(
            ["avg_monthly_incidents", "precinct"],
            ascending=[False, True]
        )
        .head(5)
    )

    result["top_incidents_rank"] = pd.NA

    for rank, index in enumerate(highest.index, start=1):
        result.loc[index, "top_incidents_rank"] = rank

    seasonal = (
        result.sort_values(
            ["seasonal_ratio", "precinct"],
            ascending=[False, True]
        )
        .head(5)
    )

    result["seasonal_increase_rank"] = pd.NA

    for rank, index in enumerate(seasonal.index, start=1):
        result.loc[index, "seasonal_increase_rank"] = rank

    lowest = (
        result.sort_values(
            ["avg_monthly_incidents", "precinct"],
            ascending=[True, True]
        )
        .head(5)
    )

    result["fewest_incidents_rank"] = pd.NA

    for rank, index in enumerate(lowest.index, start=1):
        result.loc[index, "fewest_incidents_rank"] = rank

    return result



# PREPARE THE 15 ROWS FOR THE MAIN LLM

def prepare_llm_rows(df):

    lists = [
        ("Highest incidents", "top_incidents_rank"),
        ("Largest seasonal ratio", "seasonal_increase_rank"),
        ("Fewest incidents", "fewest_incidents_rank"),
    ]

    frames = []

    for list_name, rank_column in lists:

        subset = df[df[rank_column].notna()].copy()

        subset["list_type"] = list_name
        subset["rank"] = subset[rank_column].astype(int)

        frames.append(subset)

    llm_df = pd.concat(frames, ignore_index=True)

    llm_columns = [
        "list_type",
        "rank",
        "precinct",
        "avg_monthly_incidents",
        "city_share_pct",
        "avg_crimes_against_persons",
        "avg_crimes_against_property",
        "seasonal_ratio",
    ]

    llm_df = llm_df[llm_columns]

    list_order = {
        "Highest incidents": 1,
        "Largest seasonal ratio": 2,
        "Fewest incidents": 3,
    }

    llm_df["_list_order"] = llm_df["list_type"].map(list_order)

    llm_df = (
        llm_df.sort_values(
            ["_list_order", "rank"]
        )
        .drop(columns="_list_order")
        .reset_index(drop=True)
    )

    decimal_columns = [
        "avg_monthly_incidents",
        "city_share_pct",
        "avg_crimes_against_persons",
        "avg_crimes_against_property",
        "seasonal_ratio",
    ]

    llm_df[decimal_columns] = (
        llm_df[decimal_columns].round(2)
    )

    return llm_df



# NUMBER VALIDATION

def extract_numbers(text):

    return re.findall(
        r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?",
        text
    )


def normalize_number(number):
    try:
        return Decimal(number.replace(",", "")).normalize()
    except InvalidOperation:
        return None


def validate_summary(summary, llm_df):

    numeric_columns = llm_df.select_dtypes(
        include="number"
    ).columns

    allowed_numbers = {
        normalize_number(str(value))
        for column in numeric_columns
        for value in llm_df[column].dropna()
    }

    allowed_numbers.discard(None)

    allowed_numbers.add(Decimal("1"))

    summary_numbers = {
        normalize_number(value)
        for value in extract_numbers(summary)
    }

    summary_numbers.discard(None)

    unsupported = summary_numbers - allowed_numbers

    if unsupported:
        print(
            "Summary contains unsupported numbers:",
            sorted(str(value) for value in unsupported)
        )
        return False

    return bool(summary.strip())



# GENERATE GROQ SUMMARY

def generate_summary(month, llm_df):

    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY is missing. Add it to your .env file."
        )

    month_name = MONTH_NAMES[month]
    csv_data = llm_df.to_csv(index=False)

    
    prompt = f"""
        You are writing a concise, traveler-friendly incident outlook for New York City.

        The user selected {month_name}.

        Use ONLY the information in the CSV below.

        The CSV contains three ranked lists:
        1. Highest incidents
        2. Largest seasonal ratio
        3. Fewest incidents

        Requirements:
        - Include all five precincts in each of the three lists.
        - Preserve the rankings shown in the CSV.
        - Explain the persons/property split using the supplied values.
        - Include relevant average incident counts and seasonal ratios.
        - Explain seasonal ratios correctly:
        - A ratio above 1 means the selected month's average incidents are higher than that precinct's average
            across all 36 months.
        - A ratio below 1 means the selected month's average incidents are lower than that precinct's average
            across all 36 months.
        - A ratio of 1 represents that precinct's typical monthly average.
        - Do not confuse a precinct's seasonal ratio with the city-wide average.
        - Do not describe any precinct as safe, unsafe, safest, or most dangerous.
        - Do not make claims about causes, crime trends, or individual risk that are not supported by the data.
        - Do not introduce numerical values that do not appear exactly in the CSV, except for 1 when explaining
            the seasonal-ratio baseline.
        - Do not calculate additional percentages or ratios.
        - Do not round values or replace precise values with approximations.
        - Do not express numerical values in words.
        - Organize the explanation into three sections: highest incidents, largest seasonal ratios, and
            fewest incidents.
        - Finish with a short traveler-friendly takeaway that summarizes the reported incident patterns without
            making safety recommendations.
        - Keep the explanation concise.

        CSV DATA:
        {csv_data}
    """


    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    
    for attempt in range(1, 4):

        print(f"Requesting LLM summary (attempt {attempt}/3)...")

        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": "You are a careful data analyst. Never invent or calculate numbers."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_completion_tokens": 2048,
            "reasoning_effort": "low",
            "include_reasoning": False,
        }
        try:
            response_data = call_groq(payload, headers)
        except requests.RequestException as e:
            print(f"Groq request failed: {e}")
            return None
        choice = response_data["choices"][0]
        message = choice["message"]

        summary = message.get("content") or ""
        finish_reason = choice.get("finish_reason")

        print("Model:", response_data.get("model"))
        print("Finish reason:", finish_reason)
        print(
            "Completion tokens:",
            response_data.get("usage", {}).get("completion_tokens")
        )

        if not summary.strip():
            print("LLM returned an empty response.")
            continue

        if finish_reason == "length":
            print("LLM response was truncated.")
            continue

        print("\nLLM response:")
        print(summary)

        if validate_summary(summary, llm_df):
            print("LLM summary passed number validation.")
            return summary

        unsupported_numbers = (
            {
                normalize_number(value)
                for value in extract_numbers(summary)
            }
            - {
                normalize_number(str(value))
                for column in llm_df.select_dtypes(
                    include="number"
                ).columns
                for value in llm_df[column].dropna()
            }
            - {Decimal("1")}
        )

        unsupported_numbers.discard(None)

        print(
            "Retrying because of unsupported numbers:",
            sorted(str(value) for value in unsupported_numbers)
        )

        prompt += f"""

        Your previous response contained numerical values that
        were not present in the supplied CSV:
        {sorted(str(value) for value in unsupported_numbers)}

        Rewrite the explanation.

        Use only numerical values exactly as they appear in the CSV.
        Do not round, estimate, or calculate additional numbers.
        You may use 1 to explain the seasonal ratio baseline.
        """

    print("LLM summary failed validation after 3 attempts.")
    return None




# SAVE OUTPUTS

def save_outputs(month, outlook, llm_df, summary):

    month_name = MONTH_NAMES[month].lower()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = (
        OUTPUT_DIR / f"t2_outlook_{month_name}.csv"
    )

    md_path = (
        REPORT_DIR / f"t2_summary_{month_name}.md"
    )

    outlook.to_csv(csv_path, index=False)

    with open(md_path, "w", encoding="utf-8") as file:

        file.write(
            f"# Task 2: {MONTH_NAMES[month]} Incident Outlook\n\n"
        )

        if summary:
            file.write("## Traveler-Friendly Summary\n\n")
            file.write(summary + "\n\n")
        else:
            file.write(
                "## Traveler-Friendly Summary\n\n"
                "No summary was saved because a response did not "
                "pass validation after three attempts.\n\n"
            )

        file.write("## Top-Five Lists\n\n")
        file.write(llm_df.to_markdown(index=False))
        file.write("\n## Notes\n\n")
        file.write("- Figures are reported incidents (NYPD complaints by occurrence date, 2022-2024), averaged over the three years. They are not a measure of personal safety or individual risk.\n")
        file.write("- Neighbourhood = NYPD precinct. Seasonal ratio = chosen-month average / average over all 36 months.\n")
        file.write(f"- Summary written by {GROQ_MODEL}; every number in it was checked in code against the table above.\n")
        file.write("- Precinct 116 is excluded from this analysis: <state your reason and how many incidents it had>.\n")
        file.write("\n")

    print(f"\nSaved CSV: {csv_path}")
    print(f"Saved summary: {md_path}")



def main():

    parser = argparse.ArgumentParser(
        description="Generate Task 2 monthly incident outlooks."
    )

    parser.add_argument(
        "--months",
        nargs="+",
        type=int,
        default=[7, 12],
        help="Months to analyze (1-12). Default: 7 12",
    )

    args = parser.parse_args()

    for month in args.months:
        if month not in range(1, 13):
            parser.error("Months must be between 1 and 12.")

    df = load_data()
    
    df = df[df["precinct"] != 116].copy()

    print("Excluded precinct 116 from Task 2 analysis.")
    print(f"Remaining precincts: {df['precinct'].nunique()}")

    df = complete_month_grid(df)

    for month in args.months:

        print("\n" + "=" * 60)
        print(f"PROCESSING {MONTH_NAMES[month].upper()}")
        print("=" * 60)

        outlook = calculate_outlook(df, month)
        outlook = assign_rankings(outlook)

        llm_df = prepare_llm_rows(outlook)

        print("\nThree top-five lists:")
        print(llm_df.to_string(index=False))

        summary = generate_summary(month, llm_df)

        save_outputs(
            month,
            outlook,
            llm_df,
            summary
        )

    print("\nTASK 2 PROCESSING COMPLETED.")


if __name__ == "__main__":
    main()