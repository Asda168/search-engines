# Web Scraper Search

Lightweight scraper + fuzzy search tool. Fetches a webpage, splits it into
logical content blocks (articles, list items, cards, or heading+paragraph
pairs), and ranks those blocks against a search query.

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

### CLI

```bash
python -m webscraper.cli "<url>" "<query>" [--threshold N] [--timeout S]
```

Example:

```bash
python -m webscraper.cli "https://pythonbooks.org/free-books/" "data science" --threshold 60
```

Arguments:

| Flag | Default | Description |
|---|---|---|
| `url` | — | Target webpage URL (required) |
| `query` | — | Search keyword or phrase (required) |
| `--threshold` | `60` | Minimum fuzzy match score, 0-100 |
| `--timeout` | `10` | Request timeout in seconds |

Output is JSON on stdout:

```json
{
  "target_url": "https://pythonbooks.org/free-books/",
  "query": "data science",
  "total_matches": 1,
  "results": [
    {
      "title": "Geographic Data Science with Python",
      "url": "https://pythonbooks.org/geographic-data-science-with-python-chapman-hallcrc-texts-in-statistical-science",
      "snippet": "Geographic Data Science with Python",
      "score": 75.0
    }
  ]
}
```

On failure (network error, timeout, non-2xx response), the CLI exits with
status 1 and prints a JSON error object instead:

```json
{ "error": "'https://example.com/missing' returned HTTP 404", "target_url": "...", "query": "..." }
```

### API + Web UI

Start the server:

```bash
uvicorn webscraper.api:app --reload
```

Open **http://127.0.0.1:8000/** in a browser for a simple test UI — enter a URL, a query, and a threshold, and it renders ranked results as cards (title links out to the source, score badge, snippet).

Endpoints:

- `GET /` — the browser test UI (`webscraper/static/index.html`)
- `GET /search?url=<url>&q=<query>&threshold=<0-100>` — same JSON shape as the CLI. Returns HTTP 502 on scrape failure.
- `GET /health` — `{"status": "ok"}`

Example:

```bash
curl "http://127.0.0.1:8000/search?url=https://pythonbooks.org/free-books/&q=python&threshold=60"
```

Interactive API docs are available at `http://127.0.0.1:8000/docs` while the server is running.

### As a library

```python
from webscraper import scrape_and_search

result = scrape_and_search("https://pythonbooks.org/free-books/", "python", threshold=60)
```

## Deploying to Vercel

The project deploys with zero configuration on Vercel's native Python runtime,
which auto-detects a FastAPI app and routes every request to it directly (no
manual rewrites needed):

- `pyproject.toml`'s `[tool.vercel] entrypoint = "webscraper.api:app"` points Vercel at the app, since it lives inside the `webscraper` package rather than at one of the default root-level entrypoint filenames (`app.py`, `index.py`, `main.py`, etc.).
- `requirements.txt` supplies the runtime dependencies.

Deploy with:

```bash
vercel        # preview deployment
vercel --prod # production deployment
```

## Notes

- Requires the target page to expose content as static HTML — pages that render their listing purely via client-side JavaScript won't be fully captured.
- Block detection prioritizes heading tags (`h1`–`h4`) and walks up to the smallest enclosing container per heading; pages with no headings fall back to scanning `<article>`, `<li>`, `<section>`, and `<div>` elements.
