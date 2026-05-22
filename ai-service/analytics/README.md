# Analytics on Render

PostgreSQL analytics aggregation runs on the **Render FastAPI backend** (`app/bi/analytics/`), not in this container.

This AI service receives **pre-summarized** tenant JSON only — never raw database rows.
