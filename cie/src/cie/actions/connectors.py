"""Where actions are carried out. A connector executes an action (passing its idempotency key, so the other side
carries it out at most once) and confirms it by reading back what the other side holds.

* ``OutboxConnector``: appends the action to a JSON-lines outbox file, once per key, for whatever delivers it; it
  confirms by finding the key with the same payload. It does not deliver anything itself.
* ``WebhookConnector``: POSTs the action to an HTTP endpoint with an ``Idempotency-Key`` header and an HMAC-SHA256
  signature (``X-CIE-Signature``) of the body; the endpoint answers with a receipt ``id``. It confirms with a GET of
  ``{url}/{id}`` whose ``idempotency_key`` must match.

Other systems (ERP, email, payments) are not connected in this build.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any, Protocol


class ActionConnector(Protocol):
    name: str

    def execute(self, action) -> dict[str, Any]: ...

    def confirm(self, action) -> tuple[bool, str]: ...


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class OutboxConnector:
    name = "outbox"

    def __init__(self, path: Path):
        self.path = Path(path)

    def _lines(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]

    def execute(self, action) -> dict[str, Any]:
        for n, row in enumerate(self._lines()):
            if row["key"] == action.idempotency_key:  # already in the outbox: not written twice
                return {"outbox": str(self.path), "line": n, "key": row["key"], "duplicate": True}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"key": action.idempotency_key, "kind": action.kind, "payload": action.payload, "hash": payload_hash(action.payload),
               "action_id": str(action.id)}
        with self.path.open("a") as f:
            f.write(json.dumps(row, default=str) + "\n")
        return {"outbox": str(self.path), "line": len(self._lines()) - 1, "key": action.idempotency_key}

    def confirm(self, action) -> tuple[bool, str]:
        for row in self._lines():
            if row["key"] == action.idempotency_key:
                ok = row["hash"] == payload_hash(action.payload)
                return ok, "in the outbox" if ok else "in the outbox with a different payload"
        return False, "not in the outbox"


class WebhookConnector:
    def __init__(self, name: str, url: str, secret: str, client=None):
        import httpx

        self.name, self.url, self.secret = name, url.rstrip("/"), secret
        self.client = client or httpx.Client(timeout=30)

    def _sign(self, body: bytes) -> str:
        return hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()

    def execute(self, action) -> dict[str, Any]:
        body = json.dumps({"kind": action.kind, "payload": action.payload, "action_id": str(action.id)}, sort_keys=True, default=str).encode()
        r = self.client.post(self.url, content=body, headers={"Content-Type": "application/json", "Idempotency-Key": action.idempotency_key,
                                                               "X-CIE-Signature": self._sign(body)})
        r.raise_for_status()
        data = r.json()
        if not data.get("id"):
            raise RuntimeError("the endpoint returned no receipt id")
        return {"id": str(data["id"]), "status_code": r.status_code}

    def confirm(self, action) -> tuple[bool, str]:
        rid = (action.receipt or {}).get("id")
        if not rid:
            return False, "no receipt"
        r = self.client.get(f"{self.url}/{rid}", headers={"X-CIE-Signature": self._sign(rid.encode())})
        if r.status_code != 200:
            return False, f"read-back answered {r.status_code}"
        ok = r.json().get("idempotency_key") == action.idempotency_key
        return ok, "confirmed by read-back" if ok else "read-back holds a different action"


def connectors_from_settings(settings) -> dict[str, ActionConnector]:
    """The outbox (always), and webhooks named in ``CIE_ACTION_WEBHOOKS``: a JSON object
    ``{"erp": {"url": "https://...", "secret_env": "ERP_WEBHOOK_SECRET"}}``. Secrets are read from the named
    environment variables, never stored."""
    out: dict[str, ActionConnector] = {"outbox": OutboxConnector(Path(settings.actions_outbox or (Path(settings.vault_path) / "actions_outbox.jsonl")))}
    for name, spec in (json.loads(settings.action_webhooks or "{}") or {}).items():
        secret = os.environ.get(spec.get("secret_env", ""), "")
        if spec.get("url") and secret:
            out[name] = WebhookConnector(name, spec["url"], secret)
    return out
