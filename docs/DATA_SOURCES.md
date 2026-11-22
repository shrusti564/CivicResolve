# Data sources and provenance

The downloader writes retrieval time, URL, availability, and SHA-256 for successful downloads to `data/dataset_manifest.json`. The admin inventory marks whether a manifest file is present locally. A failed download is an unavailable source, not a local dataset. Results can change as publishers move or restrict resources; inspect the manifest and local file before use.

## Configured sources

- OpenCity CKAN catalogue searches: https://data.opencity.in/ — BBMP grievances, Fix My Street, ward information, streetlights, solid waste, flooding, work orders, and BDA boundary packages. Each package/resource carries its own licence and terms; check those before redistribution. Some sources in the checked-in manifest returned HTTP 403 and are marked failed.
- GBA 2025 ward GeoJSON: https://pub-0429b8e3b5a946e69ea007df844a6f1c.r2.dev/admin/wards-bengaluru-gba/wards_bengaluru_gba.geojson — downloader records CC0-1.0 as listed by the source. Verify before redistribution.
- I Change My City Bengaluru complaints, 2019–2022 research mirror: https://github.com/Vaibhav-code15/Bengaluru-Municipality-Issue-Analysis — historical dataset attribution points to OpenCity / I Change My City / Janaagraha. Licence is unverified; source terms must be checked. It is historical and must not be represented as current citizen complaints or joined to 2025 ward IDs without an authoritative crosswalk.

The checked-in manifest records the previous run's retrieval data and failures. Re-run `python scripts/download_datasets.py` to refresh availability. No external source is guaranteed to remain accessible.
