# Security and privacy

CivicResolve is an academic local prototype, not a public service. It has no authentication or role-based access control. Do not expose it to the public internet as configured.

- `.env`, SQLite database, downloaded datasets, and uploaded photos are excluded from Git. Confirm `git status` before committing.
- Photos are limited to 5 MB and JPG/JPEG/PNG/WEBP signatures are checked. The application generates UUID filenames and stores photos under `uploads/`. This is basic validation, not malware scanning.
- Coordinates, addresses, descriptions, and photo paths are stored in the local SQLite database. There is no automatic retention/deletion policy; remove the local database and upload files when no longer needed.
- The browser requests GPS only after the citizen clicks the GPS control. Selected coordinates are sent to the backend; reverse geocoding sends coordinates to Nominatim after location selection. Avoid entering sensitive personal details.
- Gemini is optional. When configured, complaint photos may be sent to the configured Gemini service for optional visual description. Complaint text is sent for answer generation. Review provider terms before use with real personal data.
- Restrict CORS, protect status updates and RAG ingestion, add rate limits, and define retention before any deployment beyond a trusted local environment.
