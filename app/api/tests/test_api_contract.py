"""The OpenAPI contract the web interface's types are generated from."""

from assistant.main import app


def response_ref(spec: dict, path: str, method: str, code: str = "200") -> str:
    content = spec["paths"][path][method]["responses"][code]["content"]["application/json"]
    return content["schema"].get("$ref", "")


def test_every_endpoint_of_the_interface_has_a_typed_response():
    spec = app.openapi()
    expected = {
        ("/health", "get"): "Health",
        ("/catalog", "get"): "CatalogView",
        ("/sessions", "post"): "SessionCreated",
        ("/sessions/{session_id}/ask", "post"): "Answer",
        ("/sessions/{session_id}/reset", "post"): "SessionReset",
        ("/sessions/{session_id}", "get"): "SessionState",
        ("/reports", "post"): "ReportView",
        ("/reports/{report_id}/confirm", "post"): "ReportView",
    }
    for (path, method), model in expected.items():
        assert response_ref(spec, path, method).endswith(f"/{model}"), (path, method)
    assert response_ref(spec, "/reports", "post", "422").endswith("/Rejection")


def test_the_answer_contract_carries_provenance_and_observability_fields():
    answer = app.openapi()["components"]["schemas"]["Answer"]["properties"]
    for field in ("provenance", "active_filters", "reasons", "trace_id", "step_ms", "llm_usage"):
        assert field in answer


def test_the_streaming_endpoint_is_documented_as_ndjson():
    spec = app.openapi()["paths"]["/sessions/{session_id}/ask/stream"]["post"]
    assert "application/x-ndjson" in spec["responses"]["200"]["content"]
