"""The training data: recorded valid trips per pickup zone and hour, from the published layer.

Only complete, published months are read (analytics.mv_trips_hourly keeps nothing else), as
the dashboards and the assistant see them. Hours without a trip are not stored there; they are
filled with zeros here, so every zone has the full 24 x days grid: a sparse zone's many empty
hours are part of what the model must learn and what its error is measured on.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

HOURLY_SQL = """
SELECT date_day, pickup_hour, pickup_zone_sk, sum(trip_count)::bigint AS trips
FROM analytics.mv_trips_hourly
WHERE quality_status = 'valid'
GROUP BY 1, 2, 3
"""
ZONES_SQL = "SELECT zone_sk, zone_name, borough FROM analytics.dim_zone"
CALENDAR_SQL = "SELECT date_day, is_holiday FROM analytics.dim_date WHERE date_day IS NOT NULL"
STATUS_SQL = "SELECT run_id FROM analytics.pipeline_status"


@dataclass
class History:
    """Trips as an array zones x days x 24 hours, with what describes each axis."""

    zone_sk: np.ndarray  # (Z,)
    zone_name: np.ndarray  # (Z,)
    borough: np.ndarray  # (Z,)
    days: pd.DatetimeIndex  # (D,) consecutive days of the complete months
    trips: np.ndarray  # (Z, D, 24) float64
    holidays: frozenset  # dates (Timestamp) that are public holidays, history and future
    data_run: str  # publication the data comes from (analytics.pipeline_status)

    @property
    def months(self) -> list[str]:
        return sorted({d.strftime("%Y-%m") for d in self.days})


def from_frames(
    hourly: pd.DataFrame, zones: pd.DataFrame, holidays: set, data_run: str = "test"
) -> History:
    """Dense array from the sparse rows (date_day, pickup_hour, pickup_zone_sk, trips)."""
    hourly = hourly.copy()
    hourly["date_day"] = pd.to_datetime(hourly["date_day"])
    days = pd.date_range(hourly["date_day"].min(), hourly["date_day"].max(), freq="D")
    zone_sk = np.sort(hourly["pickup_zone_sk"].unique())
    names = zones.set_index("zone_sk").reindex(zone_sk)
    trips = np.zeros((len(zone_sk), len(days), 24))
    z = np.searchsorted(zone_sk, hourly["pickup_zone_sk"].to_numpy())
    d = (hourly["date_day"] - days[0]).dt.days.to_numpy()
    trips[z, d, hourly["pickup_hour"].to_numpy().astype(int)] = hourly["trips"].to_numpy()
    return History(
        zone_sk=zone_sk,
        zone_name=names["zone_name"].fillna("Unknown").to_numpy(),
        borough=names["borough"].fillna("Unknown").to_numpy(),
        days=days,
        trips=trips,
        holidays=frozenset(pd.Timestamp(h) for h in holidays),
        data_run=data_run,
    )


def load(conn) -> History:
    """Read the published layer with the forecaster role (read-only on analytics)."""

    def frame(sql: str) -> pd.DataFrame:
        with conn.cursor() as cur:
            cur.execute(sql)
            columns = [c.name for c in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=columns)

    calendar = frame(CALENDAR_SQL)
    status = frame(STATUS_SQL)
    return from_frames(
        frame(HOURLY_SQL),
        frame(ZONES_SQL),
        set(calendar.loc[calendar["is_holiday"], "date_day"]),
        str(status["run_id"].iloc[0]) if len(status) else "unknown",
    )
