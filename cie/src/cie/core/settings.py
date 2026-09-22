"""Runtime configuration. Every setting has a local-development default.

Values come from environment variables prefixed ``CIE_`` (or a ``.env`` file).
Provider API keys use their conventional unprefixed names.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CIE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://cie:cie@localhost:5432/cie"
    test_database_url: str = "postgresql+psycopg://cie:cie@localhost:5432/cie_test"

    vault_backend: Literal["local", "s3"] = "local"
    vault_path: Path = Path("./.cie_data/vault")
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "cie-vault"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    encryption_key: str = ""  # base64 32-byte key; empty disables at-rest encryption

    embedding_provider: Literal["fastembed", "hashed", "openai", "sentence_transformers"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    model_cache: Path = Path("./.models")

    llm_provider: Literal["none", "anthropic", "openai", "gemini", "local", "fake"] = "none"
    llm_model: str = "claude-sonnet-5"
    llm_base_url: str = ""  # for local OpenAI-compatible servers
    llm_max_output_tokens: int = 2048

    ocr_backend: Literal["auto", "pymupdf", "tesseract", "unlimited_ocr"] = "auto"
    ocr_dpi: int = 200
    ocr_min_chars_per_page: int = 25  # below this a PDF page is treated as scanned
    unlimited_ocr_url: str = ""
    unlimited_ocr_model: str = "Unlimited-OCR"

    redis_url: str = "redis://localhost:6379/0"

    # Retrieval defaults
    packet_min_records: int = 20
    packet_max_records: int = 100
    packet_token_budget: int = 12000
    graph_budget_coefficient: float = 4.0  # expansion budget = ceil(coef * log2(N))
    section_target_tokens: int = 400
    section_max_tokens: int = 900

    # Governance
    strict_evidence_mode: bool = True
    audit_enabled: bool = True
    log_level: str = "INFO"

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")


@lru_cache
def get_settings() -> Settings:
    return Settings()
