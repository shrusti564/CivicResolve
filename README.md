# CivicResolve

CivicResolve is a local Bengaluru civic assistance prototype. Citizens can record an issue, attach supporting photo evidence, select GPS/manual/map coordinates, check a ward boundary when data is installed, and browse local submissions. The admin dashboard presents historical 2019–2022 analytics separately from live local submissions. No complaint is filed with a government agency.

Photos are evidence attachments. With `GEMINI_API_KEY` configured, the app may request an optional visual description from Gemini; this is not a validated civic issue classifier and must not be presented as automated pothole/garbage/streetlight diagnosis.

## Requirements and setup (Windows PowerShell)

Python 3.11 or newer is recommended. From the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` only if needed. `GEMINI_API_KEY` and `GEMINI_MODEL` are optional. Without a key, the assistant returns retrieved passages from the local knowledge index. Install datasets when desired:

```powershell
python scripts/download_datasets.py
```

Start from the repository root:

```powershell
uvicorn backend.main:app --reload
```

Open `http://127.0.0.1:8000` (citizen portal), `/admin` (dashboard), and `/docs` (API docs). First startup creates a local SQLite database and adds synthetic rows only when that database is empty. These rows use `DEMO-` references and are not real complaints.

## API routes

See [docs/API.md](docs/API.md) for request fields, response behavior, and error codes. Main routes include `GET /api/health`, `POST/GET /api/complaints`, `PATCH /api/complaints/{id}/status`, `GET /api/dashboard/historical`, `GET /api/dashboard/historical/geo`, `GET /api/geo/ward`, `GET /api/geo/wards`, `GET /api/datasets`, `POST /api/rag/ingest`, and `POST /api/ask`.

## Data and provenance

Downloaded public files go in `data/raw/`; `data/dataset_manifest.json` records per-source availability and download details. Some OpenCity resources have returned HTTP 403 and remain unavailable. The inventory distinguishes locally present files from failed or missing resources. Review licences and attribution before redistribution. See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

The historical I Change My City research mirror covers 2019–2022 and is not live data. Historical complaint ward labels are not mapped to current GBA 2025 wards. The GBA layer is only available after a successful download. GPS coordinates remain usable when ward boundaries are missing, but lookup will report no match/unavailable.

## RAG knowledge base

Put official, redistributable civic PDFs, TXT, or Markdown files under `data/knowledge/`, then click **Re-index knowledge base** or call `POST /api/rag/ingest`. The starter uses local BM25-style lexical scoring blended with TF-IDF cosine ranking and persists chunks in SQLite. It does not create dense embeddings or a separate vector store. Retrieved citations identify the source file and chunk; add verifiable authority and URL metadata using `data/knowledge_base/sources.json`. No curated official corpus ships with the project, so unsupported procedures must be treated as unverified. See [data/knowledge_base/README.md](data/knowledge_base/README.md).

## Tests and validation

Install `pytest` to run the automated suite when present:

```powershell
python -m pytest
```

Manual checks: submit complaints with and without images; try an invalid/oversized image; select GPS/manual/map location; inspect an outside-boundary result; update a live complaint status and refresh; verify historical charts and live table remain distinct; confirm dataset availability in the inventory; ingest an official source and inspect citations/no-evidence response. Browser map tiles and reverse geocoding require internet access.

## Privacy and limitations

Photos, descriptions, addresses, and coordinates remain in local files/database without a configured retention policy. GPS is user-triggered. Reverse geocoding sends selected coordinates to Nominatim. If Gemini is enabled, image and question content may be sent to Google's service. There is no authentication protecting admin, status, or ingestion operations. Do not deploy publicly without access control, retention rules, and security review. See [docs/SECURITY_AND_PRIVACY.md](docs/SECURITY_AND_PRIVACY.md).
