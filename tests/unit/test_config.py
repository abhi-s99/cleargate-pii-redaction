"""Policy loading, validation and hashing (TRD section 11, FR-17, TR-GT-05)."""

from __future__ import annotations

import copy
import random
from pathlib import Path
from typing import Any

import pytest
import yaml
from cryptography.fernet import Fernet
from hypothesis import given
from hypothesis import strategies as st
from pydantic import SecretStr

from cleargate.core.config import (
    DEFAULT_POLICY_PATH,
    check_gate_key,
    check_vault_key,
    load_policy,
    load_settings,
    parse_policy,
    policy_hash,
)
from cleargate.core.errors import ConfigError, ErrorCode
from cleargate.core.models import EntityType


def raw_default() -> dict[str, Any]:
    data = yaml.safe_load(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def reorder(obj: Any, rng: random.Random) -> Any:
    """Shuffle mapping key order at every level; keep list order (it is semantic)."""
    if isinstance(obj, dict):
        items = list(obj.items())
        rng.shuffle(items)
        return {k: reorder(v, rng) for k, v in items}
    if isinstance(obj, list):
        return [reorder(v, rng) for v in obj]
    return obj


def test_default_policy_loads() -> None:
    policy = load_policy()
    assert policy.policy_name == "cadence-default"
    assert EntityType.PHOTO in policy.entities.enabled
    assert policy.ocr.dpi == 300
    assert policy.ocr.unreadable_policy == "mask_and_review"
    assert policy.llm.enabled is False
    assert "Torii" in policy.allowlist.products


def test_policy_hash_is_sha256_hex_and_deterministic() -> None:
    h1, h2 = policy_hash(load_policy()), policy_hash(load_policy())
    assert h1 == h2
    assert len(h1) == 64
    int(h1, 16)


def test_policy_hash_stable_across_key_reordering_in_yaml(tmp_path: Path) -> None:
    baseline = policy_hash(load_policy())
    for seed in range(5):
        shuffled = reorder(raw_default(), random.Random(seed))
        path = tmp_path / f"p{seed}.yaml"
        # sort_keys=False keeps the shuffled order in the file itself
        path.write_text(yaml.safe_dump(shuffled, sort_keys=False), encoding="utf-8")
        assert list(yaml.safe_load(path.read_text())) == list(shuffled)
        assert policy_hash(load_policy(path)) == baseline


@given(st.randoms(use_true_random=False))
def test_property_hash_independent_of_mapping_order(rng: random.Random) -> None:
    assert policy_hash(parse_policy(reorder(raw_default(), rng))) == policy_hash(load_policy())


def test_policy_hash_changes_when_a_value_changes() -> None:
    data = raw_default()
    changed = copy.deepcopy(data)
    changed["detection"]["review_threshold"] = 0.41
    assert policy_hash(parse_policy(changed)) != policy_hash(parse_policy(data))


def test_policy_hash_counts_defaults_explicitly() -> None:
    # Omitting a key that equals its default must give the same policy and hash.
    data = raw_default()
    trimmed = copy.deepcopy(data)
    del trimmed["retention"]
    assert policy_hash(parse_policy(trimmed)) == policy_hash(parse_policy(data))


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (lambda d: d.update(unknown_section={}), "unknown_section"),
        (lambda d: d["entities"]["enabled"].append("FAVOURITE_COLOUR"), "entities.enabled.14"),
        (lambda d: d["entities"]["employee_id_patterns"].append("EMP-(\\d"), "entities"),
        (lambda d: d["detection"].update(review_threshold=1.5), "detection.review_threshold"),
        (lambda d: d["ocr"].update(unreadable_policy="ignore"), "ocr.unreadable_policy"),
        (lambda d: d["redaction"].update(token_style="faker"), "redaction.token_style"),
        (lambda d: d["llm"].update(enabled=True), "llm"),
        (lambda d: d["llm"].update(enabled=True, provider="x", endpoint="y"), "llm"),
    ],
)
def test_invalid_policies_are_rejected(mutate: Any, field: str) -> None:
    data = raw_default()
    mutate(data)
    with pytest.raises(ConfigError) as exc_info:
        parse_policy(data)
    assert exc_info.value.code is ErrorCode.CONFIG_INVALID
    assert exc_info.value.details["field"] == field


def test_llm_enabled_with_full_approval_is_accepted() -> None:
    data = raw_default()
    data["llm"] = {"enabled": True, "provider": "p", "endpoint": "e", "approved_by": "dpo"}
    assert parse_policy(data).llm.enabled is True


def test_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    text = DEFAULT_POLICY_PATH.read_text(encoding="utf-8") + "\nllm:\n  enabled: false\n"
    path = tmp_path / "dup.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info:
        load_policy(path)
    assert exc_info.value.details["field"] == "duplicate_key:llm"


def test_missing_policy_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_policy(tmp_path / "nope.yaml")
    assert exc_info.value.code is ErrorCode.CONFIG_NOT_FOUND


def test_malformed_yaml(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("entities: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info:
        load_policy(path)
    assert exc_info.value.details["field"] == "yaml_syntax"


def test_settings_from_env_hide_secrets(tmp_path: Path) -> None:
    key = Fernet.generate_key().decode()
    settings = load_settings(
        {
            "CLEARGATE_DATA_DIR": str(tmp_path),
            "CLEARGATE_VAULT_KEY": key,
            "CLEARGATE_GATE_KEY": "g" * 40,
            "CLEARGATE_TESSERACT_CMD": "/opt/tess",
        }
    )
    assert settings.data_dir == tmp_path
    assert settings.tesseract_cmd == "/opt/tess"
    assert key not in repr(settings)
    assert key not in settings.model_dump_json()
    check_vault_key(settings.vault_key)
    check_gate_key(settings.gate_key)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (None, ErrorCode.KEY_MISSING),
        (SecretStr("not-base64!!"), ErrorCode.KEY_INVALID),
        (SecretStr("c2hvcnQ="), ErrorCode.KEY_INVALID),
    ],
)
def test_vault_key_validation(value: SecretStr | None, code: ErrorCode) -> None:
    with pytest.raises(ConfigError) as exc_info:
        check_vault_key(value)
    assert exc_info.value.code is code


@pytest.mark.parametrize(
    ("value", "code"),
    [(None, ErrorCode.KEY_MISSING), (SecretStr("short"), ErrorCode.KEY_INVALID)],
)
def test_gate_key_validation(value: SecretStr | None, code: ErrorCode) -> None:
    with pytest.raises(ConfigError) as exc_info:
        check_gate_key(value)
    assert exc_info.value.code is code
