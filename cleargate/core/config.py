"""Policy and runtime settings (TRD section 11, FR-17).

``load_policy`` validates ``config/policy.default.yaml`` (or another policy file)
into a strict Pydantic model: unknown keys, duplicate YAML keys, unknown entity
types, invalid regexes and out-of-range thresholds are rejected. ``policy_hash``
is the SHA-256 of the canonical JSON of the *validated* policy, so it does not
depend on key order, comments or formatting in the YAML file.

``load_settings`` reads secrets and paths from ``CLEARGATE_*`` environment
variables. Secrets are ``SecretStr`` so they never appear in ``repr`` or logs.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from cleargate.core.errors import ConfigError, ErrorCode
from cleargate.core.models import EntityType

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "policy.default.yaml"
WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EntitiesPolicy(_Strict):
    enabled: list[EntityType]
    employee_id_patterns: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _patterns_compile(self) -> EntitiesPolicy:
        for i, pattern in enumerate(self.employee_id_patterns):
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"employee_id_patterns[{i}] is not a valid regex") from exc
        return self


class KeepPolicy(_Strict):
    organisations: bool = True
    role_titles: bool = True
    corporate_addresses: bool = True
    non_dob_dates: bool = True


class AllowlistPolicy(_Strict):
    organisations: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    auto_learn_orgs: bool = True


class DetectionPolicy(_Strict):
    ner_model: str = "en_core_web_lg"
    review_threshold: float = Field(0.40, ge=0.0, le=1.0)
    surname_only_propagation: bool = True
    fuzzy_ocr_ratio: int = Field(90, ge=50, le=100)


class UnreadableRegion(_Strict):
    min_area_ratio: float = Field(0.02, gt=0.0, le=1.0)
    max_mean_conf: float = Field(70, ge=0, le=100)


class OcrPolicy(_Strict):
    dpi: int = Field(300, ge=72, le=1200)
    min_native_chars: int = Field(25, ge=0)
    word_conf_floor: float = Field(60, ge=0, le=100)
    unreadable_region: UnreadableRegion = Field(default_factory=UnreadableRegion)
    unreadable_policy: Literal["mask_and_review", "mask_only", "block"] = "mask_and_review"
    timeout_s_per_page: int = Field(120, gt=0)


class RedactionPolicy(_Strict):
    token_style: Literal["typed_numbered", "typed", "fixed"] = "typed_numbered"  # noqa: S105
    pdf_padding_px: int = Field(3, ge=0, le=50)


class VerificationPolicy(_Strict):
    srs_min: float = Field(0.80, ge=0.0, le=1.0)
    verify_ocr_dpi: int = Field(300, ge=72, le=1200)


class RetentionPolicy(_Strict):
    job_ttl_hours: int = Field(24, gt=0)


class LlmPolicy(_Strict):
    enabled: bool = False
    provider: str | None = None
    endpoint: str | None = None
    approved_by: str | None = None

    @model_validator(mode="after")
    def _enabled_needs_approval(self) -> LlmPolicy:
        # TR-GT-05: a real LLM client needs provider, endpoint and an explicit approver.
        if self.enabled and not (self.provider and self.endpoint and self.approved_by):
            raise ValueError("llm.enabled=true requires provider, endpoint and approved_by")
        return self


class LimitsPolicy(_Strict):
    max_file_bytes: int = Field(50 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(300, gt=0)
    max_uncompressed_bytes: int = Field(250 * 1024 * 1024, gt=0)
    max_compression_ratio: float = Field(100, gt=1)
    max_files_per_batch: int = Field(20, gt=0)
    max_image_megapixels: float = Field(80, gt=0)


class Policy(_Strict):
    policy_name: str
    entities: EntitiesPolicy
    keep: KeepPolicy = Field(default_factory=KeepPolicy)
    allowlist: AllowlistPolicy = Field(default_factory=AllowlistPolicy)
    detection: DetectionPolicy = Field(default_factory=DetectionPolicy)
    ocr: OcrPolicy = Field(default_factory=OcrPolicy)
    redaction: RedactionPolicy = Field(default_factory=RedactionPolicy)
    verification: VerificationPolicy = Field(default_factory=VerificationPolicy)
    retention: RetentionPolicy = Field(default_factory=RetentionPolicy)
    llm: LlmPolicy = Field(default_factory=LlmPolicy)
    limits: LimitsPolicy = Field(default_factory=LimitsPolicy)


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of silently overriding."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            raise ConfigError(ErrorCode.CONFIG_INVALID, field=f"duplicate_key:{key}")
        seen.add(key)
    return dict(loader.construct_pairs(node))


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def parse_policy(data: Mapping[str, Any]) -> Policy:
    try:
        return Policy.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first.get("loc", ())) or "root"
        raise ConfigError(ErrorCode.CONFIG_INVALID, field=field) from None


def load_policy(path: Path | str | None = None) -> Policy:
    policy_path = Path(path) if path else DEFAULT_POLICY_PATH
    if not policy_path.is_file():
        raise ConfigError(ErrorCode.CONFIG_NOT_FOUND, name=policy_path.name)
    try:
        data = yaml.load(policy_path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)  # noqa: S506
    except yaml.YAMLError:
        raise ConfigError(ErrorCode.CONFIG_INVALID, field="yaml_syntax") from None
    if not isinstance(data, dict):
        raise ConfigError(ErrorCode.CONFIG_INVALID, field="root")
    return parse_policy(data)


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 characters kept."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def policy_hash(policy: Policy) -> str:
    return hashlib.sha256(canonical_json(policy.model_dump(mode="json")).encode()).hexdigest()


# --------------------------------------------------------------------- settings


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    data_dir: Path
    vault_key: SecretStr | None = None
    gate_key: SecretStr | None = None
    submitter_token: SecretStr | None = None
    reviewer_token: SecretStr | None = None
    tesseract_cmd: str | None = None
    policy_path: Path = DEFAULT_POLICY_PATH


def _secret(env: Mapping[str, str], name: str) -> SecretStr | None:
    value = env.get(name, "").strip()
    return SecretStr(value) if value else None


def resolve_tesseract(env: Mapping[str, str]) -> str | None:
    explicit = env.get("CLEARGATE_TESSERACT_CMD", "").strip()
    if explicit:
        return explicit
    found = shutil.which("tesseract")
    if found:
        return found
    if WINDOWS_TESSERACT.is_file():
        return str(WINDOWS_TESSERACT)
    return None


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    policy = env.get("CLEARGATE_POLICY", "").strip()
    return Settings(
        data_dir=Path(env.get("CLEARGATE_DATA_DIR", "").strip() or REPO_ROOT / "data"),
        vault_key=_secret(env, "CLEARGATE_VAULT_KEY"),
        gate_key=_secret(env, "CLEARGATE_GATE_KEY"),
        submitter_token=_secret(env, "CLEARGATE_SUBMITTER_TOKEN"),
        reviewer_token=_secret(env, "CLEARGATE_REVIEWER_TOKEN"),
        tesseract_cmd=resolve_tesseract(env),
        policy_path=Path(policy) if policy else DEFAULT_POLICY_PATH,
    )


def check_vault_key(key: SecretStr | None) -> None:
    """TR-RD-02: a Fernet key, i.e. 32 bytes in urlsafe base64."""
    if key is None:
        raise ConfigError(ErrorCode.KEY_MISSING, name="CLEARGATE_VAULT_KEY")
    try:
        raw = base64.urlsafe_b64decode(key.get_secret_value().encode())
    except (binascii.Error, ValueError):
        raise ConfigError(ErrorCode.KEY_INVALID, name="CLEARGATE_VAULT_KEY") from None
    if len(raw) != 32:
        raise ConfigError(ErrorCode.KEY_INVALID, name="CLEARGATE_VAULT_KEY")


def check_gate_key(key: SecretStr | None) -> None:
    """TR-GT-03: HMAC key for SafeHandles, at least 32 bytes of material."""
    if key is None:
        raise ConfigError(ErrorCode.KEY_MISSING, name="CLEARGATE_GATE_KEY")
    if len(key.get_secret_value().encode()) < 32:
        raise ConfigError(ErrorCode.KEY_INVALID, name="CLEARGATE_GATE_KEY")
