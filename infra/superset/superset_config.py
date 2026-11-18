"""Superset configuration for NYC Taxi Insight Hub (mounted as /app/pythonpath).

Every secret comes from the environment (.env), nothing is written here.
Superset keeps its own state in the `superset_meta` database; business data is read
only through the `superset_reader` role, which can SELECT the `analytics` schema only.
"""

import os

from cachelib.redis import RedisCache

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://superset:{os.environ['SUPERSET_DB_PASSWORD']}"
    f"@postgres:5432/superset_meta"
)

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

# Chart and dataset metadata caches: the published tables change once a month.
CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 3600,
    "CACHE_KEY_PREFIX": "superset_meta_",
    "CACHE_REDIS_URL": f"redis://{REDIS_HOST}:{REDIS_PORT}/0",
}
DATA_CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 3600,
    "CACHE_KEY_PREFIX": "superset_data_",
    "CACHE_REDIS_URL": f"redis://{REDIS_HOST}:{REDIS_PORT}/1",
}
FILTER_STATE_CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 86400,
    "CACHE_KEY_PREFIX": "superset_filter_",
    "CACHE_REDIS_URL": f"redis://{REDIS_HOST}:{REDIS_PORT}/2",
}
EXPLORE_FORM_DATA_CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 86400,
    "CACHE_KEY_PREFIX": "superset_explore_",
    "CACHE_REDIS_URL": f"redis://{REDIS_HOST}:{REDIS_PORT}/3",
}
RESULTS_BACKEND = RedisCache(host=REDIS_HOST, port=REDIS_PORT, key_prefix="superset_results_")

# One palette for every dashboard: distinct, colour-blind aware, readable on white.
EXTRA_CATEGORICAL_COLOR_SCHEMES = [
    {
        "id": "metromove",
        "description": "NYC Taxi Insight Hub categorical palette",
        "label": "MetroMove",
        "isDefault": True,
        "colors": [
            "#1F4E79",  # deep blue
            "#F2A900",  # taxi yellow
            "#2E8B57",  # green
            "#C0392B",  # red
            "#6C5B7B",  # purple
            "#17A2B8",  # teal
            "#E67E22",  # orange
            "#7F8C8D",  # grey
            "#8E44AD",
            "#16A085",
        ],
    }
]
EXTRA_SEQUENTIAL_COLOR_SCHEMES = [
    {
        "id": "metromove_seq",
        "description": "Light yellow to deep blue",
        "label": "MetroMove sequential",
        "isDiverging": False,
        "isDefault": True,
        "colors": ["#FFF7D6", "#F2A900", "#2E86C1", "#1F4E79"],
    }
]

FEATURE_FLAGS = {
    "DASHBOARD_RBAC": True,  # dashboards visible per role
    "DASHBOARD_CROSS_FILTERS": True,  # click a chart to filter the dashboard
    "TAGGING_SYSTEM": True,
}

# SQL Lab is for the data team only; dashboards never run free SQL from viewers.
SQLLAB_TIMEOUT = 30
SUPERSET_WEBSERVER_TIMEOUT = 120
ROW_LIMIT = 50000

# Small machine: one web worker.
SUPERSET_WEBSERVER_PROCESSES = 1

# Roles and row-level security are created by services/metrics_sync/superset_sync.py
# through the REST API.
FAB_ADD_SECURITY_API = True

WTF_CSRF_ENABLED = True
TALISMAN_ENABLED = False  # local deployment over plain HTTP
