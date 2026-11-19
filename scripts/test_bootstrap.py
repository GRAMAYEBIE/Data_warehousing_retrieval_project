"""Unit tests of the bootstrap: month ranges and the generated .env."""

import base64

import bootstrap


def test_month_ranges_cross_the_year():
    assert bootstrap.month_list("2024-11..2025-02") == ["2024-11", "2024-12", "2025-01", "2025-02"]
    assert bootstrap.month_list("2025-01, 2025-03") == ["2025-01", "2025-03"]


def test_env_gets_random_secrets_and_keeps_the_rest(tmp_path, monkeypatch):
    example = tmp_path / ".env.example"
    example.write_text(
        "# comment with change_me\nPOSTGRES_DB=warehouse\nPOSTGRES_PASSWORD=change_me\n"
        "API_TOKEN=change_me\nAIRFLOW_FERNET_KEY=change_me\nOLLAMA_MODEL=qwen2.5:3b\n"
        "PIPELINE_SCHEDULE=0 6 3 * *\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "ENV_EXAMPLE", example)
    monkeypatch.setattr(bootstrap, "ENV", tmp_path / ".env")
    bootstrap.make_env(model="qwen2.5:7b", gpu=True, max_tasks=None)
    values = dict(
        line.split("=", 1)
        for line in (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    )
    assert values["POSTGRES_DB"] == "warehouse"
    assert values["POSTGRES_PASSWORD"] != values["API_TOKEN"]
    assert "change_me" not in values.values()
    assert len(base64.urlsafe_b64decode(values["AIRFLOW_FERNET_KEY"])) == 32  # Fernet format
    assert values["OLLAMA_MODEL"] == "qwen2.5:7b"
    assert values["PIPELINE_SCHEDULE"] == ""  # manual runs while history is loaded
    assert "docker-compose.gpu.yml" in values["COMPOSE_FILE"]


def test_public_env_example_holds_no_real_secret():
    """.env.example is public: every secret must stay the placeholder, so the bootstrap
    replaces it with a random value (an edited value would ship the same password to
    every machine, and a non-Fernet key would stop Airflow)."""
    secret = ("PASSWORD", "SECRET", "_KEY", "TOKEN")
    for line in bootstrap.ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.startswith("#") and any(s in key for s in secret):
            assert value == "change_me", f"{key} must be change_me in .env.example"


def test_existing_env_is_never_overwritten(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("POSTGRES_PASSWORD=mine\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "ENV", env)
    bootstrap.make_env(model=None, gpu=False, max_tasks=None)
    assert env.read_text(encoding="utf-8") == "POSTGRES_PASSWORD=mine\n"
