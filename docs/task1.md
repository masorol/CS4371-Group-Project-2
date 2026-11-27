# Task 1: NYPD Data Collection and Processing

Run all commands from the project root (`CS4371-Group-Project-2`), with Docker Desktop running.

## Environment Setup

### 1. Configure the Socrata API token

Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

Open `.env` and replace the placeholder with your Socrata application token:

```dotenv
SOCRATA_APP_TOKEN=YOUR_ACTUAL_TOKEN
```

### 2. Build the Docker image

```powershell
docker compose build
```

The Docker environment provides Python, Java, and PySpark, so a local Python virtual environment is not required to run the pipeline.

## NYPD Data Pipeline

### 1. Run the full pipeline

```powershell
docker compose run --rm app python src/build_pipeline.py
```

This runs the complete Task 1 workflow.

### 2. Run a smaller sample (optional)

To test the pipeline with 1,000 records:

```powershell
docker compose run --rm app python src/build_pipeline.py --limit 1000
```

This generates sample outputs rather than the full production outputs.

## Generated Files

| File                                                        | Description                                                        |
| ----------------------------------------------------------- | ------------------------------------------------------------------ |
| `data/raw/nypd_complaints_2022_2024_with_coordinates.jsonl` | Downloaded raw API records                                         |
| `data/raw/nypd_complaints_2022_2024.parquet`                | Raw, uncleaned data in Parquet format                              |
| `data/processed/neighbourhood_month.parquet`                | Cleaned and aggregated monthly data                                |
| `reports/t1_summary.txt`                                    | Data collection, cleaning, classification, and aggregation summary |

The monthly Parquet output contains one row per precinct, year, and month with at least one reported incident. It includes total incidents, offense category counts, and the three most frequent offense descriptions.

## Important Notes

- **Resuming downloads:** If the full JSONL download file already exists, the pipeline checks its current record count and resumes API pagination from that offset. Keep the existing file if you want to reuse the downloaded data.
- **Duplicate records:** Duplicate complaint IDs are removed during Spark cleaning.
- **Sample vs. full runs:** Sample runs use separate output filenames and should not replace the full production outputs.
- **Docker:** Docker Desktop must be running before executing the pipeline.
- **Output directories:** Generated files are saved under `data/raw/`, `data/processed/`, and `reports/`.
