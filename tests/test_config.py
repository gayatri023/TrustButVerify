import pytest

from tbv.core.config import Settings, config_hash, load_agents, load_gate, load_pricing


def test_shipped_configs_load() -> None:
    assert len(load_agents().agents) >= 2
    assert load_gate().version == 1
    assert load_pricing().pricing


def test_models_are_resolved_at_run_time_not_hardcoded() -> None:
    assert all(a.model.startswith("AUTO:") for a in load_agents().agents)
    assert all(a.is_configured for a in load_agents().agents)


def test_shipped_agents_carry_the_free_tier_limits_read_from_ai_studio() -> None:
    cfgs = {a.name: a for a in load_agents().agents}
    g, f = cfgs["gemma-4-31b"], cfgs["gemini-3-1-flash-lite"]
    assert (g.rpm, g.tpm, g.rpd) == (30, 16000, 14400)
    assert (f.rpm, f.tpm, f.rpd) == (15, 250000, 500)
    assert g.context_keep_last == 6 and f.context_keep_last is None


def test_prices_are_not_invented() -> None:
    assert all(p.input is None and p.output is None for p in load_pricing().pricing.values())


def test_config_hash_is_order_insensitive_and_change_sensitive() -> None:
    assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})
    assert config_hash({"a": 1}) != config_hash({"a": 2})
    assert len(config_hash(load_gate())) == 64


def test_settings_parse_cap_and_hide_secrets() -> None:
    s = Settings.from_env({"SPEND_CAP_USD": "12.5", "GEMINI_API_KEY": "secret-key"})
    assert s.spend_cap_usd == 12.5
    assert "secret-key" not in repr(s)


def test_settings_cap_required_for_model_calls() -> None:
    with pytest.raises(RuntimeError):
        Settings.from_env({}).require_spend_cap()


@pytest.mark.parametrize("bad", ["0", "-3", "abc"])
def test_settings_reject_bad_cap(bad: str) -> None:
    with pytest.raises(ValueError):
        Settings.from_env({"SPEND_CAP_USD": bad})
