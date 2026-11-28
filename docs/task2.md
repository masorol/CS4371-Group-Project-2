# Task 2: Monthly Incident Outlook

Run all commands from the project root (`CS4371-Group-Project-2`), with Docker Desktop running.

## Environment Setup

### 1. Configure the Groq API key

Open `.env` and add your Groq API key:

```dotenv
GROQ_API_KEY=YOUR_ACTUAL_API_KEY
```

Do not commit your actual API key to Git.

## Monthly Incident Outlook

### 1. Run the default analysis

The script analyzes July and December by default:

```powershell
docker compose run --rm app python src/task2_outlook.py
```

### 2. Specify months (optional)

Use `--months` followed by month numbers (1–12).

For example, to analyze July and December:

```powershell
docker compose run --rm app python src/task2_outlook.py --months 7 12
```

To analyze only July:

```powershell
docker compose run --rm app python src/task2_outlook.py --months 7
```

## Analysis

The script uses the processed Task 1 Parquet dataset to calculate:

- Average monthly incidents per precinct across 2022–2024.
- Each precinct's percentage of the city's total incidents for the selected month.
- Seasonal ratios comparing the selected month's average with the precinct's average across all 36 months.
- Top-five lists for highest incidents, largest seasonal ratios, and fewest incidents.

Missing precinct/month combinations are filled with zero. Precinct 116 is excluded because it opened in December 2024 and does not have comparable historical coverage.

The 15 ranked entries are sent to the Groq API (`openai/gpt-oss-120b`) to generate a traveler-friendly summary. Responses are checked for unsupported numerical values and retried up to three times.

## Generated Files

| File                              | Description                             |
| --------------------------------- | --------------------------------------- |
| `outputs/t2_outlook_july.csv`     | July results for all 77 precincts       |
| `outputs/t2_outlook_december.csv` | December results for all 77 precincts   |
| `reports/t2_summary_july.md`      | July LLM summary and top-five lists     |
| `reports/t2_summary_december.md`  | December LLM summary and top-five lists |

## Important Notes

- Task 1 must be completed before running Task 2.
- Precinct 116 is excluded only from Task 2; the original Task 1 dataset is unchanged.
- A valid `GROQ_API_KEY` is required to generate the summaries.
- Incident counts represent reported incidents and should not be interpreted as direct measures of neighborhood safety.
