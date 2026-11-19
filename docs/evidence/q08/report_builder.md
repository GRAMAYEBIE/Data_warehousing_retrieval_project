# Report and dashboard builder (exam Q8)

Run 2026-11-19 15:02 UTC against the running API and Superset.

## 1. Request: "Create a weekly demand report for Manhattan and add a chart comparing airport trips this month with last month."

HTTP 200.

### Response (specification, previews, data summary)

```json
{
 "report_id": "9df817b68806",
 "status": "draft",
 "dashboard_title": "Manhattan weekly demand comparison - airport trips",
 "dashboard_id": 7,
 "dashboard_url": "/superset/dashboard/7/",
 "chart_ids": [
  56,
  57
 ],
 "specification": {
  "request": {
   "intent": "compare",
   "metrics": [
    "airport_trips"
   ],
   "dimensions": [
    "pickup_borough"
   ],
   "filters": [
    {
     "dimension": "pickup_borough",
     "operator": "=",
     "values": [
      "Manhattan"
     ]
    }
   ],
   "date_range": {
    "period": "latest_month",
    "start_month": null,
    "end_month": null
   },
   "compare_to": "previous_period",
   "grain": null,
   "order": "desc",
   "limit": 10,
   "clarification_question": null,
   "unsupported_reason": null,
   "chart_recommendation": "line",
   "dashboard_title": "Manhattan weekly demand comparison - airport trips",
   "explanation": "Weekly airport trips in Manhattan compared between the latest month and the previous month",
   "extra_charts": [
    {
     "intent": "compare",
     "metrics": [
      "airport_trips"
     ],
     "dimensions": [],
     "filters": [
      {
       "dimension": "pickup_borough",
       "operator": "=",
       "values": [
        "Manhattan"
       ]
      }
     ],
     "date_range": {
      "period": "previous_month",
      "start_month": null,
      "end_month": null
     },
     "compare_to": "previous_period",
     "grain": null,
     "order": "desc",
     "limit": 10,
     "clarification_question": null,
     "unsupported_reason": null
    }
   ]
  },
  "charts": [
   {
    "chart_id": 56,
    "relation": "daily",
    "kind": "line",
    "months": [
     "2025-02",
     "2025-01"
    ]
   },
   {
    "chart_id": 57,
    "relation": "daily",
    "kind": "bar",
    "months": [
     "2025-01",
     "2024-12"
    ]
   }
  ]
 },
 "preview": [
  {
   "columns": [
    "pickup_borough",
    "airport_trips_previous",
    "airport_trips_current",
    "airport_trips_change",
    "airport_trips_change_pct"
   ],
   "rows": [
    [
     "Manhattan",
     "53258",
     "48737",
     "-4521",
     -8.49
    ]
   ],
   "row_count": 1,
   "sql": "SELECT a.pickup_borough AS pickup_borough, CASE WHEN a.month_start = ANY(ARRAY['2025-02-01']::date[]) THEN 'current' ELSE 'previous' END AS period_role, sum(airport_trip_count) filter (where quality_status = 'valid') AS airport_trips\nFROM analytics.mv_trips_daily AS a\nWHERE a.month_start IN (SELECT source_month FROM analytics.recon_bronze_silver) AND a.month_start = ANY(ARRAY['2025-02-01', '2025-01-01']::date[]) AND (a.pickup_borough)::text = ANY(ARRAY['Manhattan'])\nGROUP BY a.pickup_borough, CASE WHEN a.month_start = ANY(ARRAY['2025-02-01']::date[]) THEN 'current' ELSE 'previous' END\nLIMIT 5000"
  },
  {
   "columns": [
    "airport_trips_previous",
    "airport_trips_current",
    "airport_trips_change",
    "airport_trips_change_pct"
   ],
   "rows": [
    [
     "78648",
     "53258",
     "-25390",
     -32.28
    ]
   ],
   "row_count": 1,
   "sql": "SELECT CASE WHEN a.month_start = ANY(ARRAY['2025-01-01']::date[]) THEN 'current' ELSE 'previous' END AS period_role, sum(airport_trip_count) filter (where quality_status = 'valid') AS airport_trips\nFROM analytics.mv_trips_daily AS a\nWHERE a.month_start IN (SELECT source_month FROM analytics.recon_bronze_silver) AND a.month_start = ANY(ARRAY['2025-01-01', '2024-12-01']::date[]) AND (a.pickup_borough)::text = ANY(ARRAY['Manhattan'])\nGROUP BY CASE WHEN a.month_start = ANY(ARRAY['2025-01-01']::date[]) THEN 'current' ELSE 'previous' END\nLIMIT 5000"
  }
 ],
 "next_step": "Review the draft, then POST /reports/{id}/confirm with confirm=true to publish."
}
```

## 2. Publication without explicit confirmation

HTTP 409 (refused, the draft stays a draft).

### Response

```json
{
 "detail": "publication needs explicit confirmation (confirm=true)"
}
```

## 3. Publication with confirm=true

HTTP 200.

### Response

```json
{
 "report_id": "9df817b68806",
 "status": "published",
 "dashboard_title": "Manhattan weekly demand comparison - airport trips",
 "dashboard_id": 7,
 "dashboard_url": "/superset/dashboard/7/",
 "chart_ids": [
  56,
  57
 ],
 "specification": {
  "request": {
   "intent": "compare",
   "metrics": [
    "airport_trips"
   ],
   "dimensions": [
    "pickup_borough"
   ],
   "filters": [
    {
     "dimension": "pickup_borough",
     "operator": "=",
     "values": [
      "Manhattan"
     ]
    }
   ],
   "date_range": {
    "period": "latest_month",
    "start_month": null,
    "end_month": null
   },
   "compare_to": "previous_period",
   "grain": null,
   "order": "desc",
   "limit": 10,
   "clarification_question": null,
   "unsupported_reason": null,
   "chart_recommendation": "line",
   "dashboard_title": "Manhattan weekly demand comparison - airport trips",
   "explanation": "Weekly airport trips in Manhattan compared between the latest month and the previous month",
   "extra_charts": [
    {
     "intent": "compare",
     "metrics": [
      "airport_trips"
     ],
     "dimensions": [],
     "filters": [
      {
       "dimension": "pickup_borough",
       "operator": "=",
       "values": [
        "Manhattan"
       ]
      }
     ],
     "date_range": {
      "period": "previous_month",
      "start_month": null,
      "end_month": null
     },
     "compare_to": "previous_period",
     "grain": null,
     "order": "desc",
     "limit": 10,
     "clarification_question": null,
     "unsupported_reason": null
    }
   ]
  },
  "charts": [
   {
    "chart_id": 56,
    "relation": "daily",
    "kind": "line",
    "months": [
     "2025-02",
     "2025-01"
    ]
   },
   {
    "chart_id": 57,
    "relation": "daily",
    "kind": "bar",
    "months": [
     "2025-01",
     "2024-12"
    ]
   }
  ]
 },
 "preview": [
  {
   "columns": [
    "pickup_borough",
    "airport_trips_previous",
    "airport_trips_current",
    "airport_trips_change",
    "airport_trips_change_pct"
   ],
   "rows": [
    [
     "Manhattan",
     "53258",
     "48737",
     "-4521",
     -8.49
    ]
   ],
   "row_count": 1,
   "sql": "SELECT a.pickup_borough AS pickup_borough, CASE WHEN a.month_start = ANY(ARRAY['2025-02-01']::date[]) THEN 'current' ELSE 'previous' END AS period_role, sum(airport_trip_count) filter (where quality_status = 'valid') AS airport_trips\nFROM analytics.mv_trips_daily AS a\nWHERE a.month_start IN (SELECT source_month FROM analytics.recon_bronze_silver) AND a.month_start = ANY(ARRAY['2025-02-01', '2025-01-01']::date[]) AND (a.pickup_borough)::text = ANY(ARRAY['Manhattan'])\nGROUP BY a.pickup_borough, CASE WHEN a.month_start = ANY(ARRAY['2025-02-01']::date[]) THEN 'current' ELSE 'previous' END\nLIMIT 5000"
  },
  {
   "columns": [
    "airport_trips_previous",
    "airport_trips_current",
    "airport_trips_change",
    "airport_trips_change_pct"
   ],
   "rows": [
    [
     "78648",
     "53258",
     "-25390",
     -32.28
    ]
   ],
   "row_count": 1,
   "sql": "SELECT CASE WHEN a.month_start = ANY(ARRAY['2025-01-01']::date[]) THEN 'current' ELSE 'previous' END AS period_role, sum(airport_trip_count) filter (where quality_status = 'valid') AS airport_trips\nFROM analytics.mv_trips_daily AS a\nWHERE a.month_start IN (SELECT source_month FROM analytics.recon_bronze_silver) AND a.month_start = ANY(ARRAY['2025-01-01', '2024-12-01']::date[]) AND (a.pickup_borough)::text = ANY(ARRAY['Manhattan'])\nGROUP BY CASE WHEN a.month_start = ANY(ARRAY['2025-01-01']::date[]) THEN 'current' ELSE 'previous' END\nLIMIT 5000"
  }
 ],
 "next_step": "Published."
}
```

## 4. Rejected request: "Create a dashboard of driver earnings per shift by borough."

HTTP 422.

### Response

```json
{
 "detail": {
  "status": "rejected",
  "reasons": [
   "driver earnings are not in the data"
  ]
 }
}
```

