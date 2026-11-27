# Task 3 — LLM Crime Accuracy Comparison

## Overview

Task 3 evaluates how accurately two Large Language Models (LLMs) estimate reported crime incident levels across New York City police precincts compared to actual NYPD incident data from 2022–2024.

**Models Used:**
- Groq: `openai/gpt-oss-120b`
- Google: `gemini-3.5-flash-lite`

**4 Experiments are Conducted:**
1. Groq without actual incident data
2. Gemini without actual incident data
3. Groq with actual incident data
4. Gemini with actual incident data

## Required Files

**Input:**
- `data/processed/neighbourhood_month.parquet`

**Implementation:**
- `src/task3_llm_comparison.py`

**Generated Outputs:**
- `outputs/t3_llm_answers.json`
- `outputs/t3_comparison.csv`
- `outputs/t3_metrics.txt`

**Cached API Responses:**
- `cache/t3/`

## Setup Instructions

Run all commands from the project's root directory.

### 1. Create a Virtual Environment

**Windows:**
```bash
python -m venv .venv
```

**macOS / Linux:**
```bash
python3 -m venv .venv
```

### 2. Activate the Virtual Environment

**Windows:**
```bash
.venv\Scripts\activate
```

**macOS / Linux:**
```bash
source .venv/bin/activate
```

### 3. Install Dependencies

**Windows / macOS / Linux:**
```bash
python -m pip install -r requirements.txt
```

### 4. Configure API Keys

Copy `.env.example` to `.env`.

**Windows:**
```bash
copy .env.example .env
```

**macOS / Linux:**
```bash
cp .env.example .env
```

Open `.env` and add your API keys:

```dotenv
GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_gemini_api_key
```

API keys remain private (are not committed to GitHub).

### 5. Add the Incident Dataset

Place the processed Parquet file at:

```text
data/processed/neighbourhood_month.parquet
```

The dataset contains aggregated monthly NYPD incident counts by precinct for 2022–2024.

#### Handling Missing Months

`load_actual()` requires exactly 36 monthly rows (2022–2024) per precinct. If the dataset 
has an incomplete precinct, it raises `ValueError: Incomplete precinct coverage`.

**Root cause:** Some months may have no data points in the source dataset — either because 
there were truly zero reported incidents during that month, or due to data collection issues 
on the source end. The distinction cannot be determined from the parquet file alone.

**Resolution:** Treat missing months as zero incidents (the conservative assumption). 
This allows the analysis to proceed while making the assumption explicit:
- Precinct 116 has 13 months with no data points (2022–2024); these are treated as 0 incidents each.
- When running against `data/processed/neighbourhood_month.parquet`, the code will raise the error and 
  flag exactly which precinct/month combinations are missing, so the assumption can be reviewed.

## Running Task 3

### 1. Run the LLM Comparison

**Windows / macOS / Linux:**
```bash
python -m src.task3_llm_comparison
```

This script:
- Loads and validates the processed NYPD incident data.
- Calculates actual monthly incident averages by precinct.
- Queries Groq and Gemini with and without actual data.
- Validates the returned JSON predictions.
- Calculates evaluation metrics.
- Generates the three required output files.

### 2. Run the Self-Test

Tests the validation and metric calculations without making API calls.

**Windows / macOS / Linux:**
```bash
python -m src.task3_llm_comparison --self-test
```

### 3. Run Using Cached API Responses

Regenerates the outputs using previously cached responses without making new API requests.

**Windows / macOS / Linux:**
```bash
python -m src.task3_llm_comparison --offline
```

**Note:** The offline command requires cached responses from a previous successful run with the same models and prompts.

## Evaluation Metrics

Each of the 4 experiments is evaluated using:

1. **Spearman Rank Correlation:** Measures the relationship between the LLM's incident-level ratings and actual monthly incident averages.
2. **Top-5 Overlap:** Counts how many of the actual five highest-incident precincts appear in the LLM's predicted top five.
3. **Median Percentage Error:** Measures the median relative error between estimated and actual monthly incident counts.
4. **Missing/Invented Precincts:** Identifies precincts omitted, invented, duplicated, or returned with invalid predictions.

## Output Files

All generated results are saved to `outputs/`.

| File | Description |
|---|---|
| `t3_llm_answers.json` | LLM responses, prompts, experiment metadata, and validation diagnostics |
| `t3_comparison.csv` | Actual vs. estimated incident counts, ratings, and percentage errors for each experiment |
| `t3_metrics.txt` | Evaluation metrics and overall comparison summary |

## Notes

- The NYPD dataset uses **police precincts** rather than named neighbourhoods.
- LLM-generated incident counts are estimates unless grounded in actual data.
- API responses are cached to avoid unnecessary repeated requests.
- Each precinct should have complete monthly records for 2022–2024; incomplete data must be investigated before analysis.
- Reported incident counts should not be interpreted as direct measures of individual visitor safety.
- The final conclusions must be written based on the actual experimental results.
