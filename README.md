# SafeStay NYC (CS4371 Group Project 2)

An LLM-assisted trip planner for New York City built on NYPD complaint data,
Xotelo hotel prices, OpenStreetMap attractions and the Homework 2/4 temperatures.

## Install

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

## API keys

Copy `.env.example` to `.env` and fill in your keys. `.env` is git-ignored; never commit it.

| Variable | Used for | Where to get it |
|---|---|---|
| `GROQ_API_KEY` | main LLM (gpt-oss-120b), Tasks 2, 3, 5, 8 | console.groq.com |
| `GEMINI_API_KEY` | second model, Task 3 | Google AI Studio |
| `OPENROUTER_API_KEY` | backup LLM if Groq is down | openrouter.ai |
| `SOCRATA_APP_TOKEN` | NYC Open Data downloads, Task 1 | data.cityofnewyork.us |
| `SERPAPI_KEY` | backup hotel prices, Task 4 | serpapi.com |

## Run the web app (Task 5)

```bash
streamlit run app.py
```

It opens at http://localhost:8501 and has two pages:
- **Chat**: type a request in plain English. The assistant asks a follow-up question when
  details are missing and declines cities other than New York.
- **Map**: pick a month and budget to see hotels (blue) and attractions (orange), with the
  top 10 places and top 5 neighbourhoods below.

The sidebar shows which task modules are real and which still use placeholder data.

## Project layout

```
app.py                    Streamlit web app (Task 5)
src/utils.py              LLM client, cache, throttle, call counter, number check
src/task5_assistant.py    request parsing, validation, follow-ups, grounded answers
src/data_api.py           single entry point to Tasks 2/4/6/8 (falls back to placeholders)
src/placeholders.py       fake data with the agreed columns (until real modules exist)
INTERFACES.md             the functions and columns each task must provide
cache/                    saved API responses with retrieval times
outputs/                  all t1_... to t8_... output files
```

## How the assistant works (Task 5)

1. The main LLM turns the message into JSON (`city, check_in, nights, guests,
   max_price_per_night, month, preferences`, plus `intents`).
2. Code validates every field: the city must be New York, check-in must be in the future
   and within about 11 months, nights 1-30, guests 1-10, budget $1-$5,000, month 1-12.
   Invalid values are dropped and asked for again. A message that names no city is taken
   as New York, because the app covers only New York and says so on screen.
3. Required fields depend on the request (hotels need check-in, nights, guests and budget;
   outlook and places need a month; the best month needs nothing). Missing ones lead to a
   follow-up question. Collected details are kept across messages in `st.session_state`.
4. The Task 2/4/6/8 functions run, and only their results go to the LLM, as JSON.
5. Every number in the reply must appear in that JSON (or be one the user gave). If not,
   the LLM gets one retry; after that the app shows the tables without the summary.

## Run each task

<!-- Each owner: add the command for your task here. -->
- Task 1: _TODO (Person 1)_
- Task 2: _TODO (Person 1)_
- Task 3: _TODO (Person 2)_
- Task 4: _TODO (Person 3)_
- Task 6: _TODO (Person 3)_
- Task 7: _TODO (Person 4)_
- Task 8: _TODO (Person 2)_

## Integration checklist (after each real module is added)

1. Start the app and check that the sidebar shows ✅ for the new functions.
2. Ask a few chat questions that use that module and check the tables and sources.
3. Rerun the Task 7 evaluation and regenerate `t5_transcripts.md` with real data.

## Task Documentation

Detailed implementation and testing instructions
for each task are available in the `docs/` folder.

| Task | Description | Documentation |
|------|-------------|---------------|
| 1 | Incident Data Pipeline | [Task 1](docs/task1.md) |
| 2 | Monthly Incident Outlook | [Task 2](docs/task2.md) |
| 3 | LLM Crime Accuracy Comparison | [Task 3](docs/task3.md) |
| 4 | Hotel Search | [Task 4](docs/task4.md) |
| 5 | Natural-Language Assistant | [Task 5](docs/task5.md) |
| 6 | Best Month to Visit | [Task 6](docs/task6.md) |
| 7 | System Evaluation | [Task 7](docs/task7.md) |
| 8 | Attractions and Neighbourhoods | [Task 8](docs/task8.md) |
