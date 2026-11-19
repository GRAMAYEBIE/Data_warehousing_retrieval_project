# Evaluation results (exam Q10)

Run 2026-11-19 14:47 UTC, prompt variant `v3_structured_examples`, model `qwen2.5:3b`, output mode `free`, retrieval (RAG) `on`. **2 of 2 cases pass.** Median time of the cases that called the model: 274.7 s (2 cases).

| Case | Category | Question | Expected | Observed | Plan | Narrative check | Time | Result |
|---|---|---|---|---|---|---|---|---|
| F1 | follow-up | What was the tip rate in Brooklyn last month? | answered | answered (plan adjusted: period set from the question: {'period': <Period.previous_month: 'previous_month'>} (the model planned {'period': <Period.latest_month: 'latest_month'>}); plan adjusted: exclusion removed, the question excludes nothing: pickup_borough != brooklyn) | lookup tip_rate by pickup_borough | passed | 274.7 s | PASS |
| F2 | follow-up | And for Queens? | answered | answered (plan adjusted: period kept from the previous question: {'period': <Period.previous_month: 'previous_month'>}; plan adjusted: filter removed, not named in the question: pickup_borough = Brooklyn) | breakdown tip_rate by pickup_borough | passed | 153.7 s | PASS |

## Expected behaviour per case

- **F1**: Starts a session; card trips only (tip rate definition).
- **F2**: Follow-up keeps the metric and the period, replaces the borough filter.

## Raw responses

```json
[
 {
  "id": "F1",
  "response": {
   "session_id": "65974de71364",
   "status": "answered",
   "question": "What was the tip rate in Brooklyn last month?",
   "plan": {
    "intent": "lookup",
    "metrics": [
     "tip_rate"
    ],
    "dimensions": [
     "pickup_borough"
    ],
    "filters": [
     {
      "dimension": "pickup_borough",
      "operator": "=",
      "values": [
       "Brooklyn"
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
   },
   "columns": [
    "pickup_borough",
    "tip_rate_previous",
    "tip_rate_current",
    "tip_rate_change",
    "tip_rate_change_pct"
   ],
   "rows": [
    [
     "Brooklyn",
     "0.20883855187826495546",
     "0.20769182867668636468",
     "-0.00114672320157859078",
     -0.55
    ]
   ],
   "narrative": "The tip rate in Brooklyn last month was 20.7692%, with a change of -0.55% from the previous month.",
   "narrative_check": "passed",
   "suggested_chart": "bar",
   "suggested_followup": "Compare with the previous month by pickup_borough.",
   "limitations": [
    "Trip volume is a proxy for demand: unserved demand is not visible.",
    "Data is reported by vendors; TLC does not guarantee its accuracy.",
    "Tips are recorded for card payments only."
   ],
   "reasons": [
    "plan adjusted: period set from the question: {'period': <Period.previous_month: 'previous_month'>} (the model planned {'period': <Period.latest_month: 'latest_month'>})",
    "plan adjusted: exclusion removed, the question excludes nothing: pickup_borough != brooklyn"
   ],
   "provenance": {
    "metrics": [
     {
      "name": "tip_rate",
      "label": "Tip rate (card trips)",
      "definition": "Tips divided by metered fare, valid card trips only.",
      "sql_expression": "sum(sum_tip_amount_recorded) filter (where quality_status = 'valid') / nullif(sum(sum_fare_amount_tip_recorded) filter (where quality_status = 'valid'), 0)",
      "unit": "ratio",
      "filters": "valid trips paid by card only",
      "is_estimate": false
     }
    ],
    "source_months": [
     "2024-12",
     "2025-01"
    ],
    "period_resolved": {
     "period": "2025-01",
     "compared_with": "2024-12"
    },
    "published_run": "load_2025_02",
    "published_at": "2026-11-18 11:58:25.22717+00",
    "valid_trip_rate": 0.9258,
    "active_filters": [
     {
      "dimension": "pickup_borough",
      "operator": "=",
      "values": [
       "Brooklyn"
      ]
     }
    ],
    "rendered_sql": "SELECT a.pickup_borough AS pickup_borough, CASE WHEN a.month_start = ANY(ARRAY['2025-01-01']::date[]) THEN 'current' ELSE 'previous' END AS period_role, sum(sum_tip_amount_recorded) filter (where quality_status = 'valid') / nullif(sum(sum_fare_amount_tip_recorded) filter (where quality_status = 'valid'), 0) AS tip_rate\nFROM analytics.mv_trips_daily AS a\nWHERE a.month_start IN (SELECT source_month FROM analytics.recon_bronze_silver) AND a.month_start = ANY(ARRAY['2025-01-01', '2024-12-01']::date[]) AND (a.pickup_borough)::text = ANY(ARRAY['Brooklyn'])\nGROUP BY a.pickup_borough, CASE WHEN a.month_start = ANY(ARRAY['2025-01-01']::date[]) THEN 'current' ELSE 'previous' END\nLIMIT 5000",
    "row_count": 1,
    "data_layer": "analytics (published layer, read-only role ai_reader)"
   },
   "active_filters": [
    {
     "dimension": "pickup_borough",
     "operator": "=",
     "values": [
      "Brooklyn"
     ]
    }
   ],
   "duration_ms": 273798,
   "step_ms": {
    "guards": 34,
    "plan": 114057,
    "validate": 727,
    "execute": 5450,
    "provenance": 120,
    "narrate": 153346
   },
   "trace_id": "50136fa9bfd8fe2c3e9a74127e863fa4",
   "llm_usage": {
    "plan": {
     "calls": 1,
     "prompt_tokens": 2122,
     "prompt_ms": 49815,
     "output_tokens": 114,
     "output_ms": 62931,
     "load_ms": 25
    },
    "narrate": {
     "calls": 1,
     "prompt_tokens": 354,
     "prompt_ms": 104292,
     "output_tokens": 33,
     "output_ms": 30302,
     "load_ms": 5
    }
   }
  }
 },
 {
  "id": "F2",
  "response": {
   "session_id": "65974de71364",
   "status": "answered",
   "question": "And for Queens?",
   "plan": {
    "intent": "breakdown",
    "metrics": [
     "tip_rate"
    ],
    "dimensions": [
     "pickup_borough"
    ],
    "filters": [
     {
      "dimension": "pickup_borough",
      "operator": "in",
      "values": [
       "Queens"
      ]
     }
    ],
    "date_range": {
     "period": "previous_month",
     "start_month": null,
     "end_month": null
    },
    "compare_to": "none",
    "grain": null,
    "order": "desc",
    "limit": 10,
    "clarification_question": null,
    "unsupported_reason": null
   },
   "columns": [
    "pickup_borough",
    "tip_rate"
   ],
   "rows": [
    [
     "Queens",
     "0.20996305094687712703"
    ]
   ],
   "narrative": "In January 2025, the tip rate for trips in Queens was 21.0%.",
   "narrative_check": "passed",
   "suggested_chart": "bar",
   "suggested_followup": "Compare with the previous month by pickup_borough.",
   "limitations": [
    "Trip volume is a proxy for demand: unserved demand is not visible.",
    "Data is reported by vendors; TLC does not guarantee its accuracy.",
    "Tips are recorded for card payments only."
   ],
   "reasons": [
    "plan adjusted: period kept from the previous question: {'period': <Period.previous_month: 'previous_month'>}",
    "plan adjusted: filter removed, not named in the question: pickup_borough = Brooklyn"
   ],
   "provenance": {
    "metrics": [
     {
      "name": "tip_rate",
      "label": "Tip rate (card trips)",
      "definition": "Tips divided by metered fare, valid card trips only.",
      "sql_expression": "sum(sum_tip_amount_recorded) filter (where quality_status = 'valid') / nullif(sum(sum_fare_amount_tip_recorded) filter (where quality_status = 'valid'), 0)",
      "unit": "ratio",
      "filters": "valid trips paid by card only",
      "is_estimate": false
     }
    ],
    "source_months": [
     "2025-01"
    ],
    "period_resolved": {
     "period": "2025-01",
     "compared_with": ""
    },
    "published_run": "load_2025_02",
    "published_at": "2026-11-18 11:58:25.22717+00",
    "valid_trip_rate": 0.9144,
    "active_filters": [
     {
      "dimension": "pickup_borough",
      "operator": "in",
      "values": [
       "Queens"
      ]
     }
    ],
    "rendered_sql": "SELECT a.pickup_borough AS pickup_borough, sum(sum_tip_amount_recorded) filter (where quality_status = 'valid') / nullif(sum(sum_fare_amount_tip_recorded) filter (where quality_status = 'valid'), 0) AS tip_rate\nFROM analytics.mv_trips_daily AS a\nWHERE a.month_start IN (SELECT source_month FROM analytics.recon_bronze_silver) AND a.month_start = ANY(ARRAY['2025-01-01']::date[]) AND (a.pickup_borough)::text = ANY(ARRAY['Queens'])\nGROUP BY a.pickup_borough\nORDER BY tip_rate DESC NULLS LAST\nLIMIT 10",
    "row_count": 1,
    "data_layer": "analytics (published layer, read-only role ai_reader)"
   },
   "active_filters": [
    {
     "dimension": "pickup_borough",
     "operator": "in",
     "values": [
      "Queens"
     ]
    }
   ],
   "duration_ms": 153374,
   "step_ms": {
    "guards": 9,
    "plan": 121631,
    "validate": 137,
    "execute": 7953,
    "provenance": 145,
    "narrate": 23445
   },
   "trace_id": "2ee98810465d490733d0a58c43dd19df",
   "llm_usage": {
    "plan": {
     "calls": 1,
     "prompt_tokens": 2183,
     "prompt_ms": 71548,
     "output_tokens": 90,
     "output_ms": 47391,
     "load_ms": 117
    },
    "narrate": {
     "calls": 1,
     "prompt_tokens": 253,
     "prompt_ms": 7573,
     "output_tokens": 23,
     "output_ms": 11059,
     "load_ms": 26
    }
   }
  }
 }
]
```
