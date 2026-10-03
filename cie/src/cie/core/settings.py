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
    # a local open model (Ollama, vLLM) has a small context and follows long prompts poorly: give it the best evidence
    # items up to this many characters (about 6k tokens) and let it answer in at most this many tokens
    llm_local_evidence_chars: int = 24000
    llm_local_max_output_tokens: int = 1024

    ocr_backend: Literal["auto", "pymupdf", "tesseract", "unlimited_ocr"] = "auto"
    ocr_dpi: int = 200
    ocr_min_chars_per_page: int = 25  # below this a PDF page is treated as scanned
    unlimited_ocr_url: str = ""  # an OpenAI-compatible server (vLLM or SGLang) serving the model
    unlimited_ocr_model: str = "Unlimited-OCR"
    # with no server, load the model in this process (transformers on a CUDA GPU) when a scanned page needs it. On by
    # default since its pre-registered test (docs/OCR_RESULTS.md); without a GPU, auto uses Tesseract. 6.7 GB of weights,
    # about 34 s per page on an A100: a vLLM or SGLang server (unlimited_ocr_url) is the way to read scans in volume
    unlimited_ocr_local: bool = True
    unlimited_ocr_max_tokens: int = 8192

    redis_url: str = "redis://localhost:6379/0"

    # the action gateway (cie.actions): kinds that always need a person's approval, the outbox file, and webhooks
    actions_always_approve: list[str] = ["payment", "contract_signature", "external_message"]
    actions_outbox: str = ""  # default: <vault_path>/actions_outbox.jsonl
    action_webhooks: str = ""  # JSON {"name": {"url": ..., "secret_env": ...}}

    # Retrieval defaults
    packet_min_records: int = 20
    packet_max_records: int = 100
    packet_token_budget: int = 12000
    # document expansion: for the first N documents of the ranked list, a keyword search inside each document adds its
    # best passages next to it (the right document often comes with the wrong passage). 0 turns it off. 3 x 5 met every
    # pre-registered criterion (docs/EXPANSION_PREREGISTRATION.md, docs/EXPANSION_RESULTS.md)
    packet_expand_documents: int = 3
    # the evidence-only answer (strict mode, no model): "cards" gives the top records' summaries and the start of their
    # text; "quotes" quotes the sentences of the leading items that best match the question (docs/QUOTES_PREREGISTRATION.md)
    extractive_answer: str = "cards"
    packet_expand_sections: int = 5
    # keyword search: a BM25 index per tenant (cie.retrieval.bm25), or PostgreSQL full text (fts). bm25 serves a tenant
    # once its index is built (bootstrap, bulk loads, `cie lexical build`) and falls back to full text otherwise. The
    # default follows the pre-registered test in docs/BM25_RESULTS.md
    lexical_engine: Literal["fts", "bm25"] = "bm25"
    lexical_index_dir: Path = Path("./.cie_data/lexical")
    lexical_tail_max: int = 20000  # above this many rows waiting for the index, a tenant is served by full text
    graph_budget_coefficient: float = 4.0  # expansion budget = ceil(coef * log2(N))
    named_document_max_matches: int = 5  # a capitalised name that matches more files than this is a topic, not a document name
    dynamic_memory: bool = False  # wire records that fire together in answers (cie.topology.dynamic)
    # REM (cie.rem): the conventional typed traversal is the default; the priority policy and routing shortcuts are
    # opt-in until the benchmark in docs/REM.md shows they help without regressions
    rem_policy_enabled: bool = False
    rem_routing_enabled: bool = False
    dynamic_max_fired: int = 6
    dynamic_min_support: float = 0.5
    dynamic_max_degree: int = 12
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
