# court-edge-agent

An end-to-end NBA player prop intelligence system. Given a player, game date, stat market, and optional sportsbook line, it returns a projection, edge, confidence score, and a short narrative explanation — powered by a `HistGradientBoosting` model anchored to live context from GPT-4o.

> **Disclaimer:** For educational and portfolio purposes only. Projections are statistical estimates, not betting advice.

---

## What it does

- Ingests historical NBA player game logs via `nba_api` + `stats.nba.com`
- Engineers rolling features with strict no-leakage guarantees (shift-then-roll)
- Trains per-market `HistGradientBoostingRegressor` models (points, rebounds, assists, threes)
- Pulls live context at prediction time: recent games, opponent defense, injury report
- Calls GPT-4o to synthesize a projection + narrative grounded in the HGB estimate
- Fetches sportsbook prop lines (The Odds API) and computes over/under edges
- Runs a full slate analysis workflow: fetch today's games → expand to player candidates → rank edges → enrich top picks with LLM explanations
- Exposes five MCP tools for Cursor chat integration
- Serves everything through a FastAPI backend + Next.js frontend

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          court-edge-agent                           │
│                                                                     │
│  Data Layer                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐   │
│  │  nba_api /   │  │  ESPN        │  │  The Odds API          │   │
│  │  stats.nba   │  │  (injuries / │  │  (player prop lines)   │   │
│  │  (game logs, │  │   scoreboard)│  │                        │   │
│  │   defense)   │  └──────┬───────┘  └──────────┬────────────┘   │
│  └──────┬───────┘         │                     │                 │
│         │           ┌─────▼─────────────────────▼──────┐         │
│         │           │        SQLite  court_edge.db       │         │
│         └──────────▶│  player_game_logs · player_features│         │
│                     │  prop_lines                        │         │
│                     └──────────────────┬────────────────┘         │
│                                        │                           │
│  ML Layer                              │                           │
│  ┌─────────────────────────────────────▼──────────────┐           │
│  │  Feature Builder  (rolling 3/5/10, B2B, opp-drtg)  │           │
│  └─────────────────────────────────────┬──────────────┘           │
│                                        │                           │
│  ┌─────────────────────────────────────▼──────────────┐           │
│  │  HGB Models (one per market) + Ridge fallback       │           │
│  └─────────────────────────────────────┬──────────────┘           │
│                                        │                           │
│  Agent Layer                           │                           │
│  ┌─────────────────────────────────────▼──────────────┐           │
│  │  live_predict: asyncio.gather(recent games,         │           │
│  │    opponent defense, injuries) → GPT-4o prompt      │           │
│  └────────────────┬────────────────────────────────────┘          │
│                   │                                                 │
│  ┌────────────────▼────────────────────────────────────┐          │
│  │  slate_agent: today's slate → player candidates →   │          │
│  │    batch HGB scoring → rank edges → LLM top picks   │          │
│  └────────────────┬────────────────────────────────────┘          │
│                   │                                                 │
│  ┌────────────────▼──────┐  ┌─────────────────────────┐           │
│  │  FastAPI  /predict    │  │  MCP Server (5 tools)    │           │
│  │           /slate      │  │  Cursor chat integration │           │
│  │           /health     │  └─────────────────────────┘           │
│  └────────────────┬──────┘                                         │
│                   │                                                 │
│  ┌────────────────▼──────┐                                         │
│  │  Next.js UI            │                                        │
│  │  /predict · /slate     │                                        │
│  └───────────────────────┘                                         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Quickstart

### 1. Install

```bash
cd court-edge-agent
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env
# Add your keys:
#   OPENAI_API_KEY=sk-...
#   ODDS_API_KEY=...          (optional — only needed for live prop lines)
```

### 3. Ingest game logs

```bash
# A few specific players
python scripts/ingest_player_logs.py --players "Jalen Brunson" "Stephen Curry" "Nikola Jokic"

# Or the top N active players
python scripts/ingest_player_logs.py --top-n 50 --season 2024-25
```

> Uses `stats.nba.com` directly via `requests.Session` with browser-like headers and automatic retries. No API key required.

### 4. Build features

```bash
python scripts/build_features.py --season 2024-25
```

### 5. Train models

```bash
python scripts/train_baseline.py --season 2024-25 --cutoff 2025-01-01
```

Trains one `HistGradientBoostingRegressor` and one `Ridge` model per market (`points`, `rebounds`, `assists`, `threes_made`). Models are saved to `data/models/`.

### 6. (Optional) Fetch prop lines

```bash
python scripts/fetch_odds.py --markets points assists rebounds threes_made
```

Requires `ODDS_API_KEY` in `.env`.

### 7. Start the API

```bash
uvicorn court_edge_agent.api.main:app --reload
```

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### 8. Start the UI

```bash
cd ui && npm install && npm run dev
```

UI: [http://localhost:3000](http://localhost:3000)

### 9. Run tests

```bash
pytest --tb=short
```

---

## API Reference

### `GET /health`

```json
{ "status": "ok", "version": "0.1.0" }
```

### `POST /predict`

**Request:**
```json
{
  "player_name": "Jalen Brunson",
  "game_date": "2025-04-10",
  "market": "points",
  "prop_line": 26.5,
  "opponent": "BOS",
  "home_away": "HOME"
}
```

**Response:**
```json
{
  "player_name": "Jalen Brunson",
  "game_date": "2025-04-10",
  "market": "points",
  "projection": 27.8,
  "prop_line": 26.5,
  "edge": 1.3,
  "lean": "over",
  "confidence": "medium",
  "explanation": "Brunson is averaging 28.4 over his last 5 games...",
  "source": "llm"
}
```

**Markets:** `points` · `rebounds` · `assists` · `threes_made`

**Confidence thresholds:**
| Confidence | Absolute Edge |
|-----------|--------------|
| high      | ≥ 3.0        |
| medium    | ≥ 1.5        |
| low       | < 1.5        |

**`source` values:**
| Value | Meaning |
|-------|---------|
| `llm` | GPT-4o projection with live context |
| `hgb` | HGB model only (no OpenAI key / API error) |
| `ridge` | Ridge fallback |
| `rolling_avg` | Simple rolling mean |

### `POST /slate`

**Request:**
```json
{
  "game_date": "2025-04-10",
  "markets": ["points", "assists"],
  "min_edge": 2.0,
  "top_n": 10
}
```

**Response:**
```json
{
  "game_date": "2025-04-10",
  "picks": [
    {
      "player_name": "Jalen Brunson",
      "market": "points",
      "projection": 29.1,
      "prop_line": 26.5,
      "edge": 2.6,
      "lean": "over",
      "confidence": "medium",
      "explanation": "..."
    }
  ],
  "generated_at": "2025-04-10T10:30:00"
}
```

---

## MCP Server (Cursor Integration)

Five tools are exposed for use directly in Cursor chat:

| Tool | Description |
|------|-------------|
| `get_player_recent_games` | Last N game logs from the local DB |
| `get_player_projection` | Full projection via GPT-4o + HGB fallback |
| `get_prop_edges` | Batch edge ranking vs stored lines (HGB only, no API burn) |
| `run_backtest` | MAE/RMSE report across all markets |
| `explain_projection` | Verbose breakdown: trend, matchup, injuries, B2B |

### Wire into Cursor

Merge into `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "court-edge-agent": {
      "command": "/path/to/court-edge-agent/.venv/bin/python",
      "args": ["-m", "court_edge_agent.mcp_server"],
      "cwd": "/path/to/court-edge-agent",
      "env": {
        "PYTHONPATH": "/path/to/court-edge-agent/src"
      }
    }
  }
}
```

Replace `/path/to/court-edge-agent` with your local path, then restart Cursor. The `cursor_mcp_config.json` file in the repo root has a filled-in template.

**Example prompt:**
> "Use court-edge-agent tools to project Joel Embiid's points for a home game vs NYK on 2025-04-10 with a line of 28.5"

---

## Project Structure

```
court-edge-agent/
├── src/court_edge_agent/
│   ├── config.py                  # Pydantic settings, absolute path resolution
│   ├── __main__.py                # MCP server entrypoint alias
│   ├── mcp_server.py              # FastMCP server (5 tools)
│   ├── common/
│   │   └── logging.py
│   ├── data/
│   │   ├── nba_client.py          # stats.nba.com + ESPN + reference file loader
│   │   ├── odds_client.py         # The Odds API client
│   │   ├── storage.py             # SQLite: game logs, features, prop lines
│   │   └── schemas.py             # Pydantic data models
│   ├── features/
│   │   └── build_features.py      # Rolling features, opponent defense, B2B
│   ├── models/
│   │   ├── baseline.py            # RollingAvg, Ridge, HGB model classes
│   │   ├── train.py               # Date-split training + time-series CV
│   │   ├── evaluate.py            # MAE/RMSE + baseline comparison
│   │   └── predict.py             # Offline single-game prediction
│   ├── agents/
│   │   ├── live_predict.py        # Async GPT-4o agent (primary path)
│   │   └── slate_agent.py         # Full slate analysis workflow
│   └── api/
│       ├── main.py                # FastAPI app (/predict, /slate, /health)
│       └── schemas.py             # Request/response schemas
├── ui/                            # Next.js + Tailwind + shadcn/ui frontend
│   ├── app/
│   │   ├── predict/               # Single-player projection page
│   │   └── slate/                 # Slate leaderboard page
│   └── ...
├── scripts/
│   ├── ingest_player_logs.py
│   ├── build_features.py
│   ├── train_baseline.py
│   ├── run_backtest.py
│   ├── fetch_odds.py
│   ├── run_slate.py               # CLI slate runner
│   └── update_pipeline.py         # Incremental refresh (ingest → features → train)
├── tests/
│   ├── test_features.py
│   ├── test_baseline.py
│   ├── test_api.py
│   ├── test_injury_client.py
│   ├── test_odds_client.py
│   ├── test_live_predict.py
│   ├── test_mcp_server.py
│   └── test_slate_agent.py
├── notebooks/
│   └── 01_eda.ipynb
├── data/
│   ├── raw/                       # Game log exports (gitignored)
│   ├── processed/                 # Feature tables (gitignored)
│   ├── models/                    # Trained .pkl files (gitignored)
│   └── reference/                 # Static reference files (tracked)
│       └── nba_net_ratings.xlsx   # Basketball Reference 2025-26 net ratings
├── cursor_mcp_config.json         # MCP server config template
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

---

## Feature Engineering

All features for a game on date **D** are computed using only data strictly before **D**:

```python
series.shift(1).rolling(window=N, min_periods=1).mean()
```

| Feature group | Columns |
|--------------|---------|
| Short-term rolling | `rolling_{3,5,10}_{points,rebounds,assists,threes,minutes}` |
| Season average to date | `season_avg_{stat}_to_date` (expanding mean, pre-game) |
| Schedule | `days_rest`, `back_to_back_flag` |
| Opponent defense | `opponent_drtg_rank`, `opp_pts_allowed`, `opp_reb_allowed`, `opp_ast_allowed` |
| Game context | `home_away` |

Opponent defensive ratings are sourced from the local `data/reference/nba_net_ratings.xlsx` (Basketball Reference 2025-26 season data) with a live `stats.nba.com` fallback.

---

## Models

| Model | Description |
|-------|-------------|
| `HistGradientBoostingRegressor` | Primary model. Handles NaNs natively, captures non-linear interactions. One per market. |
| `Ridge` | Secondary fallback. `SimpleImputer → StandardScaler → Ridge` pipeline. |
| `RollingAverageBaseline` | Last-resort fallback. 10-game rolling mean. |

Training uses an 80/20 chronological date split. Evaluation uses `TimeSeriesSplit(n_splits=5)` to avoid lookahead bias.

---

## Docker

```bash
cp .env.example .env
docker compose up --build
# API: http://localhost:8000
```

---

## Development

```bash
# Linting
ruff check src/ tests/ scripts/

# Type checking
pyright src/

# Tests with coverage
pytest --tb=short
```

---

## Current Limitations

- Opponent `pts_allowed` / `reb_allowed` / `ast_allowed` from the reference file are `null`; those fields come from the live `stats.nba.com` fallback only
- No lineup, pace, or usage-rate context
- Single-season ingestion (multi-season transfer learning is not implemented)
- The Odds API free tier is limited to a small number of daily requests
- GPT-4o projections are bounded to `[0, 60]` by system prompt; extreme outlier games will hit this cap
