"""Unit tests: dashboard specs are consistent before anything is sent to Superset."""

import dashboards as d


def test_every_insight_uses_only_numbers_it_computes():
    for spec in d.DASHBOARDS:
        values = d.readable({key: "1.0" for key in spec.insight_sql} | {"stamp": "stamp"})
        spec.insight_template.format(**values)  # KeyError when a placeholder has no query


def test_changes_read_as_plain_english():
    assert d.change_text("2.64") == "rose by 2.6 %"
    assert d.change_text("-1.3") == "fell by 1.3 %"
    assert d.change_text("0.01") == "stayed flat"
    assert d.money_text("1591753.75") == "added **$1.6M**"
    assert d.money_text("-25000") == "removed **$25k**"
    values = d.readable({"volume_effect": "1591753.75", "price_effect": "-1288691.83"})
    assert values["volume_effect_text"] == "**More trips** added **$1.6M**"
    assert values["price_effect_text"] == "**lower revenue per trip** removed **$1.3M**"


def test_waterfall_steps_are_read_in_order():
    chart = next(
        c
        for spec in d.DASHBOARDS
        for row in spec.rows
        if isinstance(row, list)
        for c in row
        if c.kind == "waterfall"
    )
    context = d.query_context(chart, 1)
    assert context["queries"][0]["orderby"] == [["step", True]]
    assert context["form_data"]["viz_type"] == "waterfall"


def test_chart_titles_are_unique():
    titles = [
        c.title for spec in d.DASHBOARDS for row in spec.rows if isinstance(row, list) for c in row
    ]
    shared = {d.DATA_QUALITY.title, d.LAST_REFRESH.title}
    others = [t for t in titles if t not in shared]
    assert len(others) == len(set(others))
