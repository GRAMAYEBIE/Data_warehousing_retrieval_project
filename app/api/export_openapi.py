"""Write the API's OpenAPI contract to openapi.json (no database or model needed).

    python export_openapi.py            # from app/api
The web interface generates its TypeScript types from this file (app/web: npm run types);
the CI regenerates both and fails if they differ from the committed ones.
"""

import json
import os
from pathlib import Path

# Settings are read lazily; these placeholders only let the module import without a .env.
for name in ("AI_READER_PASSWORD", "AI_AUDIT_WRITER_PASSWORD", "API_TOKEN"):
    os.environ.setdefault(name, "unused")
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")

from assistant.main import app  # noqa: E402

out = Path(__file__).resolve().parent / "openapi.json"
out.write_text(
    json.dumps(app.openapi(), indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
)
print(f"written {out.name}: {len(app.openapi()['paths'])} paths")
