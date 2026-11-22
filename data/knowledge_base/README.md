# Official RAG knowledge sources

Add only official Bengaluru or Karnataka civic documents that can be redistributed for this use. Supported files are PDF, TXT and Markdown. Place source documents in `data/knowledge/`; the ingestion endpoint scans that folder. Keep this directory for the source registry and instructions.

For each document, record its filename, issuing authority, official source URL, jurisdiction, topic, publication/effective date, licence, and the date a person last verified the URL and document in `data/knowledge/sources.json`. Use the relative document path or unique filename in the `file` field. Do not add personal citizen information or treat an unverified mirror as an official source.

The current project does not ship a curated corpus of verified government procedures. Until one is added and checked, the assistant must say it cannot verify the procedure. Retrieval snippets are evidence for review, not proof that a rule is current.
