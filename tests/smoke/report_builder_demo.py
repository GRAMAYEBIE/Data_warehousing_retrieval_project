"""Report builder walk-through (exam Q8 evidence), against the running API and Superset.

    docker compose --profile core --profile tools run --rm -T -v "$PWD:/repo" -w /repo \
        --entrypoint python ingestion tests/smoke/report_builder_demo.py --token "$API_TOKEN"

1. the exam's request -> a DRAFT dashboard with its specification, previews and summary;
2. publication without confirm=true -> refused;
3. publication with confirm=true -> published;
4. a request the data cannot answer -> rejected with the reason.
Writes docs/evidence/q08/report_builder.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

REQUEST = (
    "Create a weekly demand report for Manhattan and add a chart comparing airport trips "
    "this month with last month."
)
IMPOSSIBLE = "Create a dashboard of driver earnings per shift by borough."
OUT = Path("docs/evidence/q08/report_builder.md")


def block(title: str, payload) -> list[str]:
    return [f"### {title}", "", "```json", json.dumps(payload, indent=1, default=str)[:6000], "```", ""]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://api:8000")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    http = httpx.Client(
        base_url=args.api, timeout=1800, headers={"Authorization": f"Bearer {args.token}"}
    )
    lines = [
        "# Report and dashboard builder (exam Q8)",
        "",
        f"Run {datetime.now(UTC):%Y-%m-%d %H:%M} UTC against the running API and Superset.",
        "",
    ]
    ok = True

    draft = http.post("/reports", json={"request": REQUEST})
    body = draft.json()
    ok &= draft.status_code == 200 and body.get("status") == "draft"
    print("1. draft:", draft.status_code, body.get("status"), body.get("dashboard_title"))
    lines += [f"## 1. Request: \"{REQUEST}\"", "", f"HTTP {draft.status_code}.", ""]
    lines += block("Response (specification, previews, data summary)", body)
    report_id = body.get("report_id")

    if report_id:
        refused = http.post(f"/reports/{report_id}/confirm", json={"confirm": False})
        ok &= refused.status_code == 409
        print("2. publish without confirmation:", refused.status_code)
        lines += ["## 2. Publication without explicit confirmation", "",
                  f"HTTP {refused.status_code} (refused, the draft stays a draft).", ""]
        lines += block("Response", refused.json())

        published = http.post(f"/reports/{report_id}/confirm", json={"confirm": True})
        ok &= published.status_code == 200 and published.json().get("status") == "published"
        print("3. publish with confirm=true:", published.status_code, published.json().get("status"))
        lines += ["## 3. Publication with confirm=true", "", f"HTTP {published.status_code}.", ""]
        lines += block("Response", published.json())

    rejected = http.post("/reports", json={"request": IMPOSSIBLE})
    ok &= rejected.status_code == 422
    print("4. impossible request:", rejected.status_code, rejected.json())
    lines += [f"## 4. Rejected request: \"{IMPOSSIBLE}\"", "", f"HTTP {rejected.status_code}.", ""]
    lines += block("Response", rejected.json())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("written", OUT, "OK" if ok else "with failures")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
