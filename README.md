# DecisionOS AI

**From scattered data to confident decisions.**

DecisionOS AI addresses **PS-04 — AI Decision Engine for Business Data**. It profiles CSV and Excel datasets, answers natural-language questions with local Pandas calculations and evidence, and adds explainable business recommendations, what-if scenarios, and human approval for supported lead datasets.

## Solution

The prototype loads fictional business records or parses uploaded CSV and Excel workbooks (`.csv`, `.xlsx`, `.xls`), profiles arbitrary business datasets, and answers questions using deterministic Pandas calculations with source evidence. PS-04 lead datasets additionally support decision scoring, what-if scenarios, and human approval. Core analysis does not require an LLM.

## Key Features

- Demo dataset with 360 synthetic business records, duplicates, missing values, and varied sales profiles. No personal information is used.
- CSV and Excel parsing, dynamic profiling, data-quality checks, and numeric correlations in FastAPI/Pandas.
- Dataset-aware question answering through `POST /api/analytics/query`, with validated structured plans, Pandas results, evidence, follow-ups, and generated charts.
- Optional Gemini, OpenRouter, or Groq planning and explanation through one backend provider interface; deterministic analysis remains available without an API key.
- Lead scoring uses revenue potential, engagement, contact recency, purchase history, and lead status; each contribution is returned with the score.
- Intent-aware ranking for lead prioritization, revenue opportunity, and inactive customers.
- Evidence trace links displayed source fields to the underlying dataset.
- What-if simulation re-scores the full retrieved candidate set with adjusted weights.
- Human approval outcomes and decision records persist in SQLite.
- LLM prompts receive the schema or calculated results, not the full uploaded dataset; LLM failures fall back to deterministic analysis.
- Prototype evaluation cases and metrics are explicitly labeled as unmeasured demo values.

## Architecture

```text
React + TypeScript + Vite
  -> typed HTTP client
FastAPI API
  -> CSV / Excel validation and Pandas retrieval
  -> deterministic scoring and simulation
  -> evidence and trace assembly
  -> SQLite decision / approval persistence
  -> optional provider abstraction (Gemini / OpenRouter / Groq)
  -> structured query-plan validation
  -> evidence-only explanation service
```

Retrieval is isolated from scoring so a vector index can be added later. The current prototype uses Pandas filters and deterministic ranking; it does not require embeddings or an external database.

## Tech Stack

- Frontend: React, TypeScript, Vite, Tailwind CSS, Lucide React, Recharts
- Backend: Python, FastAPI, Pandas, NumPy
- Persistence: SQLite
- Optional AI: Google Gen AI SDK and OpenAI-compatible OpenRouter/Groq APIs

## Project Structure

```text
DecisionOS/
├── frontend/
│   ├── src/{components,pages,layouts,data,hooks,services,types}/
│   ├── src/App.tsx
│   └── src/main.tsx
├── backend/
│   ├── app/{main.py,routes,services,models,schemas,utils}/
│   ├── scripts/generate_demo_data.py
│   ├── tests/test_api.py
│   └── requirements.txt
├── data/demo_sales_data.csv
├── .env.example
└── README.md
```

## Installation

Prerequisites: Node.js 20.19+ or 22.12+, npm, and Python 3.10+.

From the repository root, create the backend environment file and optionally the frontend API URL override:

```powershell
Copy-Item .env.example backend/.env
Copy-Item frontend/.env.example frontend/.env.local
```

Put a key only for the provider you plan to use in `backend/.env`. Keys stay on the backend and must never be placed in frontend environment variables. Open two PowerShell terminals from the repository root.

### Backend Setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/generate_demo_data.py
uvicorn app.main:app --reload --port 8000
```

The checked-in root demo CSV is already generated. Regenerating it creates a new deterministic-shape synthetic dataset with fresh relative contact dates.

### Frontend Setup

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL printed in the frontend terminal (normally `http://127.0.0.1:5173`). The frontend API client uses one `VITE_API_BASE_URL` setting and defaults to `http://127.0.0.1:8000`.

### Environment Variables

| Variable | Purpose |
| --- | --- |
| `LLM_PROVIDER` | Active provider: `gemini`, `openrouter`, or `groq`; defaults to Gemini. |
| `LLM_FALLBACK_ENABLED` | Set `true` to try another configured provider after a provider failure; defaults to `false`. |
| `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY` | Configure only the provider(s) you want to use. Keep keys in `backend/.env`. |
| `GEMINI_MODEL`, `OPENROUTER_MODEL`, `GROQ_MODEL` | Optional model overrides for each provider. |
| `DATABASE_URL` | Optional SQLite URL; blank uses `backend/data/decisionos.sqlite3`. |
| `VITE_API_BASE_URL` | Optional frontend API root, configured in `frontend/.env.local`; contains no secret. |

## Running Locally

Start the backend and frontend in separate terminals using the commands above. Check `http://localhost:8000/health` for API status and `http://localhost:8000/docs` for interactive API documentation.

## Demo Mode

1. Load demo data from the overview or Business Data page.
2. Ask: “Which 10 leads should our sales team contact first this week?”
3. Review the ranked results, open evidence for a lead, and inspect its five score contributions and trace.
4. Change scenario weights and run the simulator to compare rankings.
5. Approve, modify, or reject the decision. Rejection requires a reason.
6. Review prototype evaluation cases.

## API Endpoints

- `GET /health`
- `POST /api/data/demo`
- `POST /api/data/upload`
- `GET /api/data/summary`
- `GET /api/data/profile`
- `GET /api/data/preview`
- `GET /api/llm/providers`
- `POST /api/llm/provider`
- `POST /api/analytics/query`
- `POST /api/chat`
- `POST /api/decision/analyze`
- `GET /api/decision/{id}`
- `GET /api/decision/{id}/evidence`
- `POST /api/simulation/run`
- `POST /api/approval`
- `GET /api/evaluation`

## Evaluation

The evaluation page includes cases for prioritization, revenue opportunity, customer inactivity, ambiguity, missing data, duplicate data, and no-match behavior. Metrics are marked as demo placeholders, not measured accuracy or latency. The manual analysis baseline and sub-three-minute target are targets, not verified results.

Run backend tests with:

```powershell
cd backend
python -m pytest -q
```

Build the frontend with:

```powershell
cd frontend
npm run build
```

## AI Providers

Gemini uses Google's official `google-genai` SDK; OpenRouter and Groq use their OpenAI-compatible chat APIs through the existing OpenAI SDK. Choose the provider in Ask DecisionOS or set `LLM_PROVIDER` in `backend/.env`. The selected provider only plans questions and explains results. Numeric calculations, ranking, filtering, evidence selection, and simulation remain local Python/Pandas operations. Missing keys, invalid output, rate limits, and provider errors fall back to deterministic analysis. No provider receives the full uploaded dataset.

## Failure Handling

- Ambiguous questions return a clarification request.
- No matching records return an explicit no-match response.
- Records with no usable decision fields return “Insufficient evidence.”
- Missing individual fields remain null and receive conservative factor contributions; values are not fabricated.
- Invalid or unsupported CSV/Excel files are rejected with a useful error.
- Lead decision scoring is enabled only when the active dataset contains the supported PS-04 lead schema; general datasets remain available to analytics.
- Conflicting records are surfaced through duplicate counts for review; the prototype does not silently deduplicate source data.

## Future Improvements

- Add source-specific connectors for CRM, pipeline, customer, and transaction systems.
- Add authenticated users, approval audit history, and role-based access.
- Evaluate ranking and explanation quality on a labeled, human-reviewed benchmark.
- Add robust entity resolution and explicit conflict-resolution review.
- Add embeddings/vector retrieval when the dataset and retrieval needs justify it.
- Add database migrations and configurable SQLite/PostgreSQL persistence.