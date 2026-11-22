# CivicResolve — Bengaluru civic assistance & grievance intelligence

A VS Code-ready starter application built from scratch. It combines citizen complaint intake, browser GPS, ward-boundary lookup, public Bengaluru dataset ingestion, a hybrid local retrieval pipeline (TF-IDF + BM25-style lexical scoring), source-cited guidance, complaint tracking, and an admin dashboard with KPI cards and charts.

> **Data and accuracy note:** the repository includes a reproducible downloader for public datasets, but the build environment used to create this ZIP had no outbound network access. Therefore the full third-party CSV/GeoJSON files are **not bundled**. Run `python scripts/download_datasets.py` on your computer to fetch them. A small clearly-labelled synthetic demo dataset is included for testing the UI. Do not treat demo rows as real complaints or official statistics.
>
> Bengaluru's administrative boundaries have changed. The current GBA 2025 ward layer (369 wards across five corporations) is configured as the preferred GPS boundary layer. Historical BBMP grievance / Fix My Street datasets may use older ward structures; the app keeps them as historical analytics and does not silently map old ward IDs to new ones.

## Features

### Citizen portal
- Submit civic issues: pothole/road, garbage, streetlight, drainage/flooding, water, other.
- Capture browser GPS (permission-based), show coordinates and map marker; allow manual map selection.
- Reverse-geocode coordinates using Nominatim (internet required; user-triggered).
- Point-in-polygon ward/corporation lookup from the downloaded GeoJSON boundary file (Shapely).
- Attach a photo; store complaint and image locally.
- View complaint status and a generated complaint reference.
- Ask CivicResolve a question and receive retrieved source snippets/citations from the local knowledge base.

### Admin dashboard
- KPI cards: total complaints, open complaints, resolved complaints, resolution rate, complaints this month, geo-tagged complaints.
- Charts: category distribution, status distribution, monthly complaint trend.
- Complaint table with search and status update.
- Map of submitted complaints.
- Dataset inventory and RAG document ingestion status.

### Backend / data
- FastAPI + SQLite.
- Local document ingestion for PDF, TXT and Markdown files.
- Hybrid retrieval: TF-IDF cosine similarity + BM25-style token scoring; citations point to document names and chunk IDs.
- Optional Gemini generation via `GEMINI_API_KEY`. Without a key, the app returns an extractive grounded answer based on retrieved chunks.
- Dataset downloader for OpenCity public datasets and GBA ward GeoJSON.
- CSV import for public complaint/infrastructure datasets; source metadata is retained.

## Project structure

```text
CivicResolve/
├── backend/
│   ├── main.py                 # FastAPI routes
│   ├── database.py             # SQLite setup and queries
│   ├── geo.py                  # GPS → ward/corporation polygon lookup
│   ├── rag.py                  # ingestion + hybrid retrieval + citations
│   └── datasets.py             # dataset inventory and CSV summary
├── frontend/
│   ├── index.html              # citizen portal
│   ├── admin.html              # KPI/admin dashboard
│   ├── styles.css
│   └── app.js
├── data/
│   ├── raw/                    # downloaded public datasets land here
│   ├── knowledge/              # add official PDFs/TXT/MD here for RAG
│   ├── processed/
│   └── demo/                   # synthetic demo complaint rows
├── uploads/                    # submitted images
├── scripts/
│   └── download_datasets.py
├── .env.example
├── requirements.txt
└── README.md
```

## Run in VS Code (Windows)

1. Extract the ZIP and open the `CivicResolve` folder in VS Code.
2. Open Terminal → PowerShell.
3. Create and activate a virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate again. To exit later, run `deactivate`.

4. Install dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

5. Copy `.env.example` to `.env`. Gemini is optional. Add a Gemini API key only if you want LLM-generated responses; local retrieval works without it.
6. Download Bengaluru datasets:

```powershell
python scripts/download_datasets.py
```

7. Start the application from the project root:

```powershell
uvicorn backend.main:app --reload
```

8. Open:
- Citizen portal: http://127.0.0.1:8000
- Admin dashboard: http://127.0.0.1:8000/admin
- API docs: http://127.0.0.1:8000/docs

## Public datasets configured

The downloader queries OpenCity's CKAN API for these public catalogue entries and downloads available CSV/KML/GeoJSON resources where accessible:

- BBMP Grievances Data — historical ward-level grievance categories.
- BBMP Fix My Street Data — pothole-related data (catalogue description identifies May–June 2022 and aggregate data).
- BBMP Ward Information.
- Bengaluru Streetlights.
- BBMP Solid Waste Management Data.
- Flooding Locations in Bengaluru Urban.
- BBMP Work Orders (historical).
- BDA Jurisdiction and Boundary.
- Greater Bengaluru Authority 2025 ward boundaries — 369 wards, GeoJSON, CC0 listing via Bharatlas/OpenCity.

Catalogue entry points:
- https://data.opencity.in/
- https://data.opencity.in/api/3/action/package_search?q=BBMP%20Grievances%20Data
- https://bharatlas.com/layers (search “Greater Bengaluru Wards (2025)”).

The script records source URL, retrieval timestamp, licence/notes when available in `data/dataset_manifest.json`. Check each dataset's licence and source notes before redistribution or publication. OpenCity catalogue pages may occasionally block automated downloads; if so, download the resource manually from the linked catalogue and place it in `data/raw/`.

## GPS and ward mapping

- Browser GPS requires the user to grant location permission and generally works on `localhost` or HTTPS.
- GPS is never requested automatically on page load; the citizen clicks **Use my GPS**.
- The backend uses `data/raw/gba_wards_2025.geojson` if present. It uses Shapely to find the polygon containing the supplied longitude/latitude.
- If the boundary file is missing, GPS coordinates are still stored and displayed, but ward lookup reports “boundary dataset not installed”.
- Reverse geocoding is a separate request to Nominatim. Follow its usage policy; do not bulk-geocode or send personal information.
- Authority recommendations are labelled as guidance and should be verified against the current corporation/department jurisdiction before real-world use.

## Add official knowledge sources for RAG

Place official circulars, grievance procedures, service-level documents, department contacts, and government PDFs in `data/knowledge/`. Then call:

```powershell
curl -X POST http://127.0.0.1:8000/api/rag/ingest
```

or use the “Re-index knowledge base” button in the admin page. The app will extract text, chunk it, index it locally and return citations. Only ingest material you have permission to use. Keep source URLs and dates in the documents or filenames.

## Environment variables

See `.env.example`. The Gemini integration is optional. If configured, the server uses the Google GenAI SDK; otherwise it returns a grounded extractive answer. Never commit `.env` or API keys.

## Demo data and KPIs

`data/demo/demo_complaints.csv` contains synthetic sample rows to make the dashboard usable immediately. The dashboard shows a **DEMO DATA** notice until real submissions are recorded. Historical public datasets are shown in the dataset inventory and can be analysed separately; they are not mixed into live complaint counts.

## Known limitations / next validation steps

- Public catalogue resource URLs and schemas can change; inspect downloaded CSV headers before relying on them.
- Historical BBMP ward IDs do not automatically map to the 2025 GBA ward IDs. A verified official crosswalk is required for longitudinal ward-level comparisons.
- The starter's category classification is keyword-based. Add a validated image classifier / vision model before claiming automated visual diagnosis.
- No real government complaint is submitted to BBMP/GBA. CivicResolve records and guides; actual filing remains a citizen action unless an authorised official integration is added.
- The included authority map is intentionally conservative. Add verified, dated official department/ward contact data before showing a definitive “responsible officer”.

### Included historical complaint dataset download

The downloader also fetches the public research mirror of the I Change My City Bengaluru complaint log (January 2019–December 2022; the repository README reports 16,071 records), saved as `data/raw/bengaluru_icmc_complaints_2019_2022.csv`. This is useful for historical category, agency, ward and status analysis, but it is not live complaint data and its historical ward labels must not be joined to 2025 GBA ward polygons without an authoritative crosswalk. Source: https://github.com/Vaibhav-code15/Bengaluru-Municipality-Issue-Analysis (original dataset attribution in that repository points to OpenCity / I Change My City / Janaagraha).
