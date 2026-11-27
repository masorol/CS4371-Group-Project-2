from pathlib import Path
import argparse
import json
import os
import time

import requests

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# 1. PROJECT CONFIGURATION

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORT_DIR = PROJECT_ROOT / "reports"

API_URL = "https://data.cityofnewyork.us/resource/qgea-i56i.json"

START_DATE = "2022-01-01T00:00:00"
END_DATE = "2025-01-01T00:00:00"

PAGE_SIZE = 2000

FIELDS = [
    "cmplnt_num",
    "cmplnt_fr_dt",
    "addr_pct_cd",
    "boro_nm",
    "law_cat_cd",
    "ofns_desc",
    "latitude",
    "longitude",
]

OFFENSE_MAPPING = {
    # Crimes against persons
    "HARRASSMENT 2": "crimes against persons",
    "ASSAULT 3 & RELATED OFFENSES": "crimes against persons",
    "FELONY ASSAULT": "crimes against persons",
    "ROBBERY": "crimes against persons",
    "SEX CRIMES": "crimes against persons",
    "OFFENSES AGAINST THE PERSON": "crimes against persons",
    "RAPE": "crimes against persons",
    "MURDER & NON-NEGL. MANSLAUGHTER": "crimes against persons",
    "KIDNAPPING & RELATED OFFENSES": "crimes against persons",
    "KIDNAPPING": "crimes against persons",
    "FELONY SEX CRIMES": "crimes against persons",
    "HOMICIDE-NEGLIGENT,UNCLASSIFIE": "crimes against persons",
    "HOMICIDE-NEGLIGENT-VEHICLE": "crimes against persons",
    "CHILD ABANDONMENT/NON SUPPORT": "crimes against persons",
    "CHILD ABANDONMENT/NON SUPPORT 1": "crimes against persons",
    "OFFENSES RELATED TO CHILDREN": "crimes against persons",
    "ENDAN WELFARE INCOMP": "crimes against persons",

    # Crimes against property
    "PETIT LARCENY": "crimes against property",
    "GRAND LARCENY": "crimes against property",
    "CRIMINAL MISCHIEF & RELATED OF": "crimes against property",
    "GRAND LARCENY OF MOTOR VEHICLE": "crimes against property",
    "BURGLARY": "crimes against property",
    "FORGERY": "crimes against property",
    "OTHER OFFENSES RELATED TO THEFT": "crimes against property",
    "THEFT-FRAUD": "crimes against property",
    "OFFENSES INVOLVING FRAUD": "crimes against property",
    "FRAUDS": "crimes against property",
    "POSSESSION OF STOLEN PROPERTY": "crimes against property",
    "UNAUTHORIZED USE OF A VEHICLE": "crimes against property",
    "OTHER OFFENSES RELATED TO THEF": "crimes against property",
    "ARSON": "crimes against property",
    "BURGLAR'S TOOLS": "crimes against property",
    "PETIT LARCENY OF MOTOR VEHICLE": "crimes against property",
    "THEFT OF SERVICES": "crimes against property",
    "JOSTLING": "crimes against property",
    "FRAUDULENT ACCOSTING": "crimes against property",
    "CRIMINAL TRESPASS": "crimes against property",

    # Other
    "VEHICLE AND TRAFFIC LAWS": "other",
    "OFF. AGNST PUB ORD SENSBLTY &": "other",
    "MISCELLANEOUS PENAL LAW": "other",
    "DANGEROUS DRUGS": "other",
    "DANGEROUS WEAPONS": "other",
    "OFFENSES AGAINST PUBLIC ADMINI": "other",
    "INTOXICATED & IMPAIRED DRIVING": "other",
    "ADMINISTRATIVE CODE": "other",
    "OTHER STATE LAWS": "other",
    "NYS LAWS-UNCLASSIFIED FELONY": "other",
    "OTHER STATE LAWS (NON PENAL LA": "other",
    "OTHER STATE LAWS (NON PENAL LAW)": "other",
    "CANNABIS RELATED OFFENSES": "other",
    "GAMBLING": "other",
    "PROSTITUTION & RELATED OFFENSES": "other",
    "OFFENSES AGAINST PUBLIC SAFETY": "other",
    "DISORDERLY CONDUCT": "other",
    "AGRICULTURE & MRKTS LAW-UNCLASSIFIED": "other",
    "ALCOHOLIC BEVERAGE CONTROL LAW": "other",
    "ESCAPE 3": "other",
    "UNLAWFUL POSS. WEAP. ON SCHOOL": "other",
    "ANTICIPATORY OFFENSES": "other",
    "INTOXICATED/IMPAIRED DRIVING": "other",
    "NEW YORK CITY HEALTH CODE": "other",
    "NYS LAWS-UNCLASSIFIED VIOLATION": "other",
    "LOITERING/GAMBLING (CARDS, DIC": "other",
    "DISRUPTION OF A RELIGIOUS SERV": "other",
    "OTHER TRAFFIC INFRACTION": "other",
    "FORTUNE TELLING": "other",
    "LOITERING": "other",
}

NULL_OFFENSE_VALUES = ("", "(NULL)", "NULL")


# 2. DOWNLOAD DATA

def download_data(output_file, sample_limit=None):

    output_file.parent.mkdir(parents=True, exist_ok=True)

    app_token = os.getenv("SOCRATA_APP_TOKEN", "").strip()
    if not app_token:
        raise RuntimeError(
            "Missing Socrata application token. Set the SOCRATA_APP_TOKEN "
            "environment variable before running the pipeline."
        )

    retry_strategy = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)

    session = requests.Session()
    session.mount("https://", adapter)
    session.headers.update({
        "X-App-Token": app_token,
        "Accept": "application/json"
    })

    where_clause = (
        "cmplnt_fr_dt IS NULL OR ("
        f"cmplnt_fr_dt >= '{START_DATE}' "
        f"AND cmplnt_fr_dt < '{END_DATE}'"
        ")"
    )

    params = {
        "$select": ",".join(FIELDS),
        "$where": where_clause,
        "$order": "cmplnt_num ASC",
        "$limit": PAGE_SIZE,
        "$offset": 0
    }

    downloaded = 0

    resume = (
        sample_limit is None
        and output_file.exists()
        and output_file.stat().st_size > 0
    )

    if resume:
        print("\nExisting download found. Checking progress...")

        with output_file.open("r", encoding="utf-8") as file:
            downloaded = sum(1 for line in file if line.strip())

        print(f"Existing records: {downloaded:,}")
        print(f"Resuming at API offset: {downloaded:,}")
        file_mode = "a"
    else:
        downloaded = 0
        file_mode = "w"

    offset = downloaded

    print("\nStarting NYC Open Data download...")
    print("Pagination method: $limit/$offset")
    print("Socrata application token: configured")

    with output_file.open(file_mode, encoding="utf-8") as file:
        while True:
            current_limit = PAGE_SIZE

            if sample_limit is not None:
                remaining = sample_limit - downloaded
                if remaining <= 0:
                    break
                current_limit = min(PAGE_SIZE, remaining)

            params["$limit"] = current_limit
            params["$offset"] = offset

            print(
                f"Requesting records with offset {offset:,} "
                f"(limit {current_limit:,})..."
            )

            response = session.get(
                API_URL,
                params=params,
                timeout=(15, 300)
            )
            response.raise_for_status()

            records = response.json()

            if not isinstance(records, list):
                raise RuntimeError(
                    "The Socrata API returned an unexpected response type: "
                    f"{type(records).__name__}. Response preview: "
                    f"{response.text[:500]}"
                )

            if not records:
                break

            for record in records:
                file.write(json.dumps(record) + "\n")

            file.flush()

            batch_count = len(records)
            downloaded += batch_count
            offset += batch_count

            print(
                f"Downloaded {downloaded:,} total records "
                f"(latest batch: {batch_count:,}; next offset: {offset:,})"
            )

            time.sleep(0.5)

    print(f"\nDownload complete: {downloaded:,} records")
    print(f"Saved to: {output_file}")

    if downloaded == 0:
        raise RuntimeError(
            "No records were returned. Check API availability, app token, "
            "field names, and the requested date range."
        )

    if sample_limit is not None and downloaded != sample_limit:
        raise RuntimeError(
            f"Sample download incomplete: requested {sample_limit:,} records, "
            f"but the API returned {downloaded:,}. Do not treat this as a "
            "successful sample or start the full pipeline until the API query "
            "has been investigated."
        )

    return downloaded



# 3. START SPARK

def create_spark_session():

    spark = (
        SparkSession.builder
        .appName("SafeStayIncidentPipeline")
        .master("local[*]")
        .config("spark.hadoop.fs.permissions.umask-mode", "000")
        .getOrCreate()
    )

    spark.sparkContext.setLogLevel("WARN")

    return spark



# 4. CLEAN AND TRANSFORM

def clean_data(spark, raw_file, raw_parquet_path):

    print("\nReading raw JSON data...")

    raw_df = (
        spark.read
        .option("inferSchema", "false")
        .json(str(raw_file))
    ).cache()

    required_raw_columns = {
        "cmplnt_num", "cmplnt_fr_dt", "addr_pct_cd", "boro_nm",
        "law_cat_cd", "ofns_desc", "latitude", "longitude"
    }
    missing_columns = required_raw_columns - set(raw_df.columns)
    if missing_columns:
        raise ValueError(
            "The downloaded raw data is missing required fields: "
            + ", ".join(sorted(missing_columns))
            + ". Re-download using the updated field list; do not reuse the older "
                "JSONL file that did not include coordinates."
        )

    raw_count = raw_df.count()
    print(f"Raw records read by Spark: {raw_count:,}")

    raw_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving uncleaned raw data as Parquet: {raw_parquet_path}")
    raw_df.coalesce(4).write.mode("overwrite").parquet(
        str(raw_parquet_path)
    )

    nyc_boroughs = ["BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"]
    NYC_LAT_MIN, NYC_LAT_MAX = 40.4774, 40.9176
    NYC_LON_MIN, NYC_LON_MAX = -74.2591, -73.7004

    cleaned = (
        raw_df
        .withColumn("cmplnt_num", F.trim(F.col("cmplnt_num")))
        .withColumn("ofns_desc", F.upper(F.trim(F.col("ofns_desc"))))
        .withColumn("boro_nm", F.upper(F.trim(F.col("boro_nm"))))
        .withColumn("addr_pct_cd", F.trim(F.col("addr_pct_cd")).cast("int"))
        .withColumn("latitude", F.trim(F.col("latitude")).cast("double"))
        .withColumn("longitude", F.trim(F.col("longitude")).cast("double"))
        .withColumn(
            "incident_date",
            F.coalesce(
                F.to_date(F.col("cmplnt_fr_dt"), "yyyy-MM-dd'T'HH:mm:ss.SSS"),
                F.to_date(F.col("cmplnt_fr_dt"), "yyyy-MM-dd'T'HH:mm:ss"),
                F.to_date(F.col("cmplnt_fr_dt"), "yyyy-MM-dd"),
                F.to_date(F.col("cmplnt_fr_dt"), "MM/dd/yyyy")
            )
        )
    )

    with_id = cleaned.filter(
        F.col("cmplnt_num").isNotNull() & (F.col("cmplnt_num") != "")
    )
    after_missing_id = with_id.count()
    removed_missing_id = raw_count - after_missing_id

    deduplicated = with_id.dropDuplicates(["cmplnt_num"]).cache()
    after_deduplication = deduplicated.count()
    removed_duplicates = after_missing_id - after_deduplication

    with_date = deduplicated.filter(F.col("incident_date").isNotNull())
    after_date = with_date.count()
    removed_missing_date = after_deduplication - after_date

    with_precinct = with_date.filter(F.col("addr_pct_cd").between(1, 123))
    after_precinct = with_precinct.count()
    removed_invalid_precinct = after_date - after_precinct

    valid_coordinate_condition = (
        F.col("latitude").isNotNull()
        & F.col("longitude").isNotNull()
        & (~F.isnan(F.col("latitude")))
        & (~F.isnan(F.col("longitude")))
        & F.col("latitude").between(-90.0, 90.0)
        & F.col("longitude").between(-180.0, 180.0)
    )
    with_coordinates = with_precinct.filter(valid_coordinate_condition)
    after_coordinates = with_coordinates.count()
    removed_invalid_coordinates = after_precinct - after_coordinates

    inside_city_condition = (
        F.col("boro_nm").isin(*nyc_boroughs)
        & F.col("latitude").between(NYC_LAT_MIN, NYC_LAT_MAX)
        & F.col("longitude").between(NYC_LON_MIN, NYC_LON_MAX)
    )
    inside_city = with_coordinates.filter(inside_city_condition)
    after_city = inside_city.count()
    removed_outside_city = after_coordinates - after_city

    valid = inside_city.filter(
        (F.col("incident_date") >= F.lit("2022-01-01"))
        & (F.col("incident_date") < F.lit("2025-01-01"))
    ).cache()
    valid_count = valid.count()
    removed_outside_date_range = after_city - valid_count

    cleaning_counts = {
        "raw_count": raw_count,
        "removed_missing_id": removed_missing_id,
        "after_missing_id": after_missing_id,
        "removed_duplicates": removed_duplicates,
        "after_deduplication": after_deduplication,
        "removed_missing_date": removed_missing_date,
        "after_date": after_date,
        "removed_invalid_precinct": removed_invalid_precinct,
        "after_precinct": after_precinct,
        "removed_invalid_coordinates": removed_invalid_coordinates,
        "after_coordinates": after_coordinates,
        "removed_outside_city": removed_outside_city,
        "after_city": after_city,
        "removed_outside_date_range": removed_outside_date_range,
        "valid_count": valid_count,
        "raw_jsonl_path": str(raw_file),
        "raw_parquet_path": str(raw_parquet_path),
        "nyc_boroughs": nyc_boroughs,
        "nyc_lat_min": NYC_LAT_MIN,
        "nyc_lat_max": NYC_LAT_MAX,
        "nyc_lon_min": NYC_LON_MIN,
        "nyc_lon_max": NYC_LON_MAX,
    }

    print("\nCLEANING RESULTS")
    print("-" * 55)
    print(f"Starting records:                  {raw_count:,}")
    print(f"Removed missing IDs:               {removed_missing_id:,}")
    print(f"Removed duplicate reports:         {removed_duplicates:,}")
    print(f"Removed missing dates:             {removed_missing_date:,}")
    print(f"Removed missing/invalid precincts: {removed_invalid_precinct:,}")
    print(f"Removed invalid coordinates:       {removed_invalid_coordinates:,}")
    print(f"Removed outside NYC:               {removed_outside_city:,}")
    print(f"Removed outside date range:        {removed_outside_date_range:,}")
    print(f"Final valid incidents:             {valid_count:,}")

    valid = (
        valid
        .withColumn("year", F.year("incident_date"))
        .withColumn("month", F.month("incident_date"))
    )

    print(f"\nValid unique incidents: {valid_count:,}")
    return valid, cleaning_counts



# 5. CLASSIFY OFFENSES AND AGGREGATE BY PRECINCT/MONTH

def aggregate_monthly(valid):

    print("\nClassifying offenses and aggregating by precinct/month...")

    observed_offenses = {
        row["ofns_desc"]
        for row in valid.select("ofns_desc").distinct().collect()
        if row["ofns_desc"] is not None
        and row["ofns_desc"].strip().upper() not in NULL_OFFENSE_VALUES
    }

    unmapped_offenses = observed_offenses - set(OFFENSE_MAPPING)

    if unmapped_offenses:
        raise ValueError(
            "The following offense descriptions are not mapped:\\n"
            + "\n".join(sorted(unmapped_offenses))
        )

    print(
        f"All {len(observed_offenses)} non-null offense descriptions "
        "have been mapped."
    )

    mapping_expression = F.create_map(
        *[
            item
            for offense, category in OFFENSE_MAPPING.items()
            for item in (F.lit(offense), F.lit(category))
        ]
    )

    classified = valid.withColumn(
        "offense_category",
        F.when(
            F.col("ofns_desc").isNull()
            | F.upper(F.trim(F.col("ofns_desc"))).isin(*NULL_OFFENSE_VALUES),
            F.lit("other")
        ).otherwise(
            F.coalesce(
                F.element_at(mapping_expression, F.col("ofns_desc")),
                F.lit("other")
            )
        )
    ).cache()

    group_columns = ["addr_pct_cd", "year", "month"]

    monthly = (
        classified
        .groupBy(*group_columns)
        .agg(
            F.count("*").alias("total_incidents"),
            F.sum(
                F.when(
                    F.col("offense_category") == "crimes against persons", 1
                ).otherwise(0)
            ).alias("crimes_against_persons"),
            F.sum(
                F.when(
                    F.col("offense_category") == "crimes against property", 1
                ).otherwise(0)
            ).alias("crimes_against_property"),
            F.sum(
                F.when(F.col("offense_category") == "other", 1).otherwise(0)
            ).alias("other")
        )
        .withColumnRenamed("addr_pct_cd", "precinct")
    )

    offense_counts = (
        classified
        .filter(
            F.col("ofns_desc").isNotNull()
            & (~F.upper(F.trim(F.col("ofns_desc"))).isin(*NULL_OFFENSE_VALUES))
        )
        .groupBy(*group_columns, "ofns_desc")
        .agg(F.count("*").alias("offense_count"))
    )

    ranking_window = (
        Window
        .partitionBy(*group_columns)
        .orderBy(F.desc("offense_count"), F.asc("ofns_desc"))
    )

    ranked = (
        offense_counts
        .withColumn("offense_rank", F.row_number().over(ranking_window))
        .filter(F.col("offense_rank") <= 3)
    )

    top_three = (
        ranked
        .groupBy(*group_columns)
        .agg(
            F.max(F.when(F.col("offense_rank") == 1, F.col("ofns_desc")))
            .alias("top_1_offense"),
            F.max(F.when(F.col("offense_rank") == 1, F.col("offense_count")))
            .alias("top_1_offense_count"),
            F.max(F.when(F.col("offense_rank") == 2, F.col("ofns_desc")))
            .alias("top_2_offense"),
            F.max(F.when(F.col("offense_rank") == 2, F.col("offense_count")))
            .alias("top_2_offense_count"),
            F.max(F.when(F.col("offense_rank") == 3, F.col("ofns_desc")))
            .alias("top_3_offense"),
            F.max(F.when(F.col("offense_rank") == 3, F.col("offense_count")))
            .alias("top_3_offense_count")
        )
    )

    final_columns = [
        "precinct",
        "year",
        "month",
        "total_incidents",
        "crimes_against_persons",
        "crimes_against_property",
        "other",
        "top_1_offense",
        "top_1_offense_count",
        "top_2_offense",
        "top_2_offense_count",
        "top_3_offense",
        "top_3_offense_count",
    ]

    monthly_output = (
        monthly
        .join(
            top_three.withColumnRenamed("addr_pct_cd", "precinct"),
            on=["precinct", "year", "month"],
            how="left"
        )
        .select(*final_columns)
        .orderBy("precinct", "year", "month")
    )

    return monthly_output, classified



# 6. VALIDATE THE AGGREGATED DATA

def validate_data(monthly, valid_count, classified):

    print("\nRunning output validation...")

    output_count = monthly.count()

    incident_total = (
        monthly.agg(F.sum("total_incidents").alias("total"))
        .first()["total"]
    )

    distinct_months = monthly.select("year", "month").distinct().count()

    null_keys = monthly.filter(
        F.col("precinct").isNull()
        | F.col("year").isNull()
        | F.col("month").isNull()
    ).count()

    invalid_months = monthly.filter(
        (F.col("month") < 1) | (F.col("month") > 12)
    ).count()

    duplicate_keys = (
        monthly
        .groupBy("precinct", "year", "month")
        .count()
        .filter(F.col("count") > 1)
        .count()
    )

    invalid_coordinates = classified.filter(
        F.col("latitude").isNull()
        | F.col("longitude").isNull()
        | F.isnan(F.col("latitude"))
        | F.isnan(F.col("longitude"))
        | (~F.col("latitude").between(-90.0, 90.0))
        | (~F.col("longitude").between(-180.0, 180.0))
    ).count()

    outside_city = classified.filter(
        (~F.col("boro_nm").isin("BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"))
        | (~F.col("latitude").between(40.4774, 40.9176))
        | (~F.col("longitude").between(-74.2591, -73.7004))
    ).count()

    category_total = (
        monthly
        .agg(
            F.sum(
                F.col("crimes_against_persons")
                + F.col("crimes_against_property")
                + F.col("other")
            ).alias("total")
        )
        .first()["total"]
    )

    print(f"Output rows:                  {output_count:,}")
    print(f"Incident total:               {incident_total:,}")
    print(f"Category count total:         {category_total:,}")
    print(f"Distinct year/month combinations: {distinct_months}")
    print(f"Null grouping keys:            {null_keys}")
    print(f"Invalid month values:          {invalid_months}")
    print(f"Duplicate precinct/month keys: {duplicate_keys}")
    print(f"Invalid coordinates in cleaned incidents: {invalid_coordinates}")
    print(f"Incidents outside NYC screen after cleaning: {outside_city}")

    assert output_count > 0, "Output is empty"
    assert incident_total == valid_count, (
        "Incident total does not match cleaned input count"
    )
    assert category_total == incident_total, (
        "The three offense-category counts do not sum to total incidents"
    )
    assert null_keys == 0, "Null grouping keys found"
    assert invalid_months == 0, "Invalid month values found"
    assert duplicate_keys == 0, "Duplicate precinct/year/month keys found"
    assert invalid_coordinates == 0, "Invalid coordinates remain after cleaning"
    assert outside_city == 0, "Incidents outside NYC remain after cleaning"

    print("\nMonthly coverage:")
    (
        monthly
        .select("year", "month")
        .distinct()
        .orderBy("year", "month")
        .show(50, truncate=False)
    )

    if distinct_months != 36:
        print(
            "WARNING: Expected 36 calendar months for 2022-2024, "
            f"but found {distinct_months}. Investigate source coverage."
        )

    print("Core validation checks passed.")



# 7. SAVE PARQUET AND WRITE A REPORT

def save_outputs(
    monthly,
    classified,
    output_path,
    report_path,
    cleaning_counts
):

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\nWriting Parquet to: {output_path}")
    monthly.write.mode("overwrite").parquet(str(output_path))

    date_range = classified.agg(
        F.min("incident_date").alias("min_date"),
        F.max("incident_date").alias("max_date")
    ).first()

    number_of_precincts = classified.select("addr_pct_cd").distinct().count()
    category_counts = {
        row["offense_category"]: row["count"]
        for row in classified.groupBy("offense_category").count().collect()
    }
    c = cleaning_counts

    report_lines = [
        "SAFESTAY TASK 1 - DATA SUMMARY",
        "=" * 60,
        "",
        "SOURCE DATA",
        "NYC Open Data - NYPD Complaint Data Historic",
        "Dataset ID: qgea-i56i",
        "Downloaded API staging file: " + c["raw_jsonl_path"],
        "Raw, uncleaned Parquet: " + c["raw_parquet_path"],
        "",
        "CLEANING RESULTS (SEQUENTIAL COUNTS)",
        f"Starting records: {c['raw_count']:,}",
        f"Missing complaint IDs removed: {c['removed_missing_id']:,}",
        f"Rows after missing-ID removal: {c['after_missing_id']:,}",
        f"Duplicate reports removed: {c['removed_duplicates']:,}",
        f"Rows after deduplication: {c['after_deduplication']:,}",
        f"Missing/unparseable dates removed: {c['removed_missing_date']:,}",
        f"Rows after date removal: {c['after_date']:,}",
        f"Missing/invalid precincts removed: {c['removed_invalid_precinct']:,}",
        f"Rows after precinct validation: {c['after_precinct']:,}",
        f"Missing/invalid coordinates removed: {c['removed_invalid_coordinates']:,}",
        f"Rows after coordinate validation: {c['after_coordinates']:,}",
        f"Outside NYC removed: {c['removed_outside_city']:,}",
        f"Rows after NYC filter: {c['after_city']:,}",
        f"Outside date range removed: {c['removed_outside_date_range']:,}",
        f"Final valid incidents: {c['valid_count']:,}",
        "",
        "COORDINATE AND CITY VALIDATION",
        "Coordinates were cast to numeric latitude/longitude values.",
        "Rows with null, non-finite, or globally out-of-range coordinates were removed.",
        "City membership required a recognized NYC borough and coordinates within",
        "the broad NYC coordinate envelope (latitude 40.4774–40.9176, longitude",
        "-74.2591–-73.7004). The borough field is the primary city-membership check.",
        "Recognized boroughs: Bronx, Brooklyn, Manhattan, Queens, Staten Island.",
        "",
        "DATE COVERAGE",
        "The API query includes 2022-2024 dated records plus undated rows so",
        "Spark can explicitly count and remove rows with missing dates.",
        f"First occurrence date: {date_range['min_date']}",
        f"Last occurrence date: {date_range['max_date']}",
        "Requested date range: 2022-01-01 through 2024-12-31",
        "",
        "GEOGRAPHIC COVERAGE",
        f"Number of precincts: {number_of_precincts}",
        "Geographic unit: NYPD precinct (addr_pct_cd), as approved for this project.",
        "",
        "OFFENSE CATEGORY COUNTS",
        f"Crimes against persons: {category_counts.get('crimes against persons', 0):,}",
        f"Crimes against property: {category_counts.get('crimes against property', 0):,}",
        f"Other: {category_counts.get('other', 0):,}",
        "",
        "OFFENSE CLASSIFICATION MAPPING",
        "The source dataset does not provide a direct person/property/other field.",
        "Each observed ofns_desc value was explicitly assigned to one category.",
        "NULL, (NULL), and empty offense descriptions are assigned to other.",
        "",
        "Crimes against persons:",
    ]

    for offense, category in OFFENSE_MAPPING.items():
        if category == "crimes against persons":
            report_lines.append(f"  - {offense}")

    report_lines.extend(["", "Crimes against property:"])
    for offense, category in OFFENSE_MAPPING.items():
        if category == "crimes against property":
            report_lines.append(f"  - {offense}")

    report_lines.extend(["", "Other:"])
    for offense, category in OFFENSE_MAPPING.items():
        if category == "other":
            report_lines.append(f"  - {offense}")

    report_lines.extend([
        "",
        "MONTHLY AGGREGATION",
        "One row per precinct, year, and month with at least one reported incident.",
        "Includes total incidents, incidents in each category, and the three most",
        "frequent individual ofns_desc values with counts.",
        "Ties in offense counts are broken alphabetically by offense description.",
        "",
        "OUTPUT COLUMNS",
        "precinct, year, month, total_incidents, crimes_against_persons,",
        "crimes_against_property, other, top_1_offense, top_1_offense_count,",
        "top_2_offense, top_2_offense_count, top_3_offense, top_3_offense_count",
        "",
        "OUTPUT",
        f"Rows in output: {monthly.count():,}",
        f"Monthly summary Parquet: {output_path}",
        f"Raw Parquet: {c['raw_parquet_path']}",
        "",
        "NOTE",
        "The pipeline uses NYPD precincts as the geographic unit, as approved",
        "for this project. Offense categories are an analytical mapping created",
        "for this assignment, not official NYPD category labels.",
    ])

    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"Task 1 summary saved to: {report_path}")



# 8. RUN THE PIPELINE

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional small record limit for a test run."
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    if args.limit:
        raw_file = RAW_DIR / "nypd_sample_with_coordinates.jsonl"
        raw_parquet_path = RAW_DIR / "nypd_sample.parquet"
        output_path = PROCESSED_DIR / "neighbourhood_month_sample.parquet"
        report_path = REPORT_DIR / "sample_t1_summary.txt"
    else:
        raw_file = RAW_DIR / "nypd_complaints_2022_2024_with_coordinates.jsonl"
        raw_parquet_path = RAW_DIR / "nypd_complaints_2022_2024.parquet"
        output_path = PROCESSED_DIR / "neighbourhood_month.parquet"
        report_path = REPORT_DIR / "t1_summary.txt"

    downloaded_count = download_data(raw_file, sample_limit=args.limit)
    spark = create_spark_session()

    try:
        valid, cleaning_counts = clean_data(
            spark,
            raw_file,
            raw_parquet_path
        )

        monthly, classified = aggregate_monthly(valid)
        validate_data(monthly, cleaning_counts["valid_count"], classified)

        save_outputs(
            monthly,
            classified,
            output_path,
            report_path,
            cleaning_counts
        )

        print("\nPIPELINE COMPLETED SUCCESSFULLY")
        print(f"Downloaded: {downloaded_count:,}")
        print(f"Valid incidents: {cleaning_counts['valid_count']:,}")
        print(f"Raw Parquet: {raw_parquet_path}")
        print(f"Monthly Parquet: {output_path}")
        print(f"Task 1 summary: {report_path}")

    finally:
        spark.stop()


if __name__ == "__main__":
    main()