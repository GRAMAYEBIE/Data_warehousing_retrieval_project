# Evaluation results (exam Q10)

Run 2026-11-20 13:07 UTC, prompt variant `default`, model `qwen2.5:3b`, output mode `free`, retrieval (RAG) `on`. **1 of 1 cases pass.** Median time of the cases that called the model: 4.0 s (1 cases).

| Case | Category | Question | Expected | Observed | Plan | Narrative check | Time | Result |
|---|---|---|---|---|---|---|---|---|
| X1 | model failure | How many trips did we have last month? | model_unavailable | model_unavailable (language model unavailable: ConnectError) | - | not_needed | 4.0 s | PASS |

## Expected behaviour per case

- **X1**: With Ollama stopped, a clear degraded answer and HTTP 200, no stack trace.

## Raw responses

```json
[
 {
  "id": "X1",
  "response": {
   "session_id": "f2cc80809546",
   "status": "model_unavailable",
   "question": "How many trips did we have last month?",
   "plan": null,
   "columns": [],
   "rows": [],
   "narrative": "The language model is not available right now. The dashboards and governed metrics are still available in Superset.",
   "narrative_check": "not_needed",
   "suggested_chart": null,
   "suggested_followup": null,
   "limitations": [],
   "reasons": [
    "language model unavailable: ConnectError"
   ],
   "provenance": null,
   "active_filters": [],
   "duration_ms": 3735,
   "step_ms": {
    "guards": 3,
    "plan": 3663
   },
   "trace_id": "9f66523634e78d122bb83d85877c112d",
   "llm_usage": {}
  }
 }
]
```
