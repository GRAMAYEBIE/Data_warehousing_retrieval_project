# Q12 evidence: every service of the platform running and healthy

Lab machine (Mac mini M4, 16 GB), one Docker Compose project, all profiles:
`docker compose --profile core --profile ai --profile bi --profile ml --profile orchestration --profile stream --profile observability ps -a`

```
2026-11-27 14:14 UTC
SERVICE                 STATUS
airflow-apiserver       Up About an hour (healthy)
airflow-dag-processor   Up About an hour (healthy)
airflow-init            Exited (0) 5 days ago
airflow-scheduler       Up About an hour (healthy)
alertmanager            Up 30 hours
alloy                   Up 30 hours
api                     Up About an hour (healthy)
cadvisor                Up 30 hours (healthy)
forecast                Up 4 hours
grafana                 Up 30 hours
kafka                   Up 30 hours (healthy)
kafka-exporter          Up 21 hours
kafka-ui                Up 30 hours
loki                    Up 30 hours
mlflow                  Up 30 hours (healthy)
node-exporter           Up 30 hours
ollama                  Exited (0) 5 days ago
postgres                Up 30 hours (healthy)
postgres-exporter       Up About an hour
prometheus              Up 21 hours (healthy)
redis                   Up 30 hours (healthy)
redis-exporter          Up 30 hours
rustfs                  Up 30 hours (healthy)
speech                  Up 30 hours (healthy)
statsd-exporter         Up 30 hours (healthy)
stream-consumer         Up 30 hours
superset                Up 30 hours (healthy)
superset-init           Exited (0) 5 days ago
tempo                   Up 13 minutes
web                     Up 21 hours (healthy)
```

- The three `Exited (0)` are expected: `airflow-init` and `superset-init` are one-shot jobs (database migration, admin user, dbt manifest; Superset roles and datasets) that end once done; `ollama` is not used on this machine: the model runs in the host's Ollama, on the Apple GPU (README, "Windows and macOS"). The assistant reaches it, as its health shows below.
- `forecast` was running a replay of past months when this was taken.

Assistant health (`GET /health`, same time):

```json
{
  "status": "ok",
  "database": "ok",
  "model": "qwen2.5:7b",
  "model_available": true,
  "output_mode": "free",
  "retrieval": true,
  "prompt_cache_warm_up": {
    "state": "done",
    "step_ms": {
      "warm_up_data": 4422,
      "warm_up_planner": 255,
      "warm_up_narrator": 154,
      "warm_up_conversation": 67
    }
  },
  "complete_months": [
    "2024-12",
    "2025-01",
    "2025-02",
    "2025-03",
    "2025-04",
    "2025-05",
    "2025-06",
    "2025-07",
    "2025-08",
    "2025-09",
    "2025-10",
    "2025-11",
    "2025-12",
    "2026-01",
    "2026-02",
    "2026-03",
    "2026-04",
    "2026-05",
    "2026-06",
    "2026-07",
    "2026-08",
    "2026-09"
  ]
}
```
