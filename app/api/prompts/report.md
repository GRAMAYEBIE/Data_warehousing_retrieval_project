
The manager asks for a REPORT or a DASHBOARD, not a single answer. Fill a report request:
- The main fields describe the main chart (same rules as a plan).
- chart_recommendation: line (trend), bar (comparison or breakdown), table, big_number, pie.
- dashboard_title: a short English title, for example "Manhattan weekly demand".
- explanation: one sentence on what the report shows.
- extra_charts: one plan per additional chart the manager asks for (at most 3).

Example: "Create a weekly demand report for Manhattan and add a chart comparing airport
trips this month with last month."
{{"intent":"trend","metrics":["trips"],"grain":"week",
  "filters":[{{"dimension":"pickup_borough","operator":"=","values":["Manhattan"]}}],
  "chart_recommendation":"line","dashboard_title":"Manhattan weekly demand",
  "explanation":"Weekly valid trips picked up in Manhattan, and airport trips this month versus last month.",
  "extra_charts":[{{"intent":"compare","metrics":["airport_trips"],
     "date_range":{{"period":"latest_month"}},"compare_to":"previous_period",
     "filters":[{{"dimension":"pickup_borough","operator":"=","values":["Manhattan"]}}]}}]}}
