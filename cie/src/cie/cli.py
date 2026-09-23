"""Command line: migrate, bootstrap, ingest, worker, serve, ask, demo, bench."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import uuid
from pathlib import Path

from cie.core.logging import configure_logging
from cie.core.settings import get_settings


def alembic_dir() -> Path:
    """The directory holding alembic.ini and the migrations: $CIE_ALEMBIC_DIR, the working directory, or the source
    checkout this module was loaded from (a regular, non-editable install puts the module in site-packages)."""
    import os

    candidates = [Path(os.environ["CIE_ALEMBIC_DIR"])] if os.environ.get("CIE_ALEMBIC_DIR") else []
    candidates += [Path.cwd(), Path(__file__).resolve().parents[2]]
    for c in candidates:
        if (c / "alembic.ini").exists() and (c / "alembic").is_dir():
            return c
    raise SystemExit("alembic.ini not found: run from the cie checkout or set CIE_ALEMBIC_DIR to it")


def cmd_migrate(args) -> None:
    from alembic.config import Config

    from alembic import command

    base = alembic_dir()
    cfg = Config(str(base / "alembic.ini"))
    cfg.set_main_option("script_location", str(base / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")
    print("migrated to head")


def cmd_bootstrap(args) -> None:
    """Create a tenant, company scope, admin role and admin principal. Prints the API key."""
    from sqlalchemy import select

    from cie.api.deps import hash_key
    from cie.core.db import session_scope
    from cie.core.models import Permission, Principal, PrincipalKind, ScopeKind, Tenant
    from cie.governance.permissions import ensure_role, grant_role
    from cie.memory.scopes import create_scope

    with session_scope() as s:
        tenant = s.scalar(select(Tenant).where(Tenant.name == args.tenant))
        if tenant is None:
            tenant = Tenant(name=args.tenant)
            s.add(tenant)
            s.flush()
        company = create_scope(s, tenant.id, ScopeKind.company, args.company)
        admin_role = ensure_role(s, tenant.id, "admin", Permission.admin, 4)
        ensure_role(s, tenant.id, "editor", Permission.write, 3)
        ensure_role(s, tenant.id, "reader", Permission.read, 2)
        ensure_role(s, tenant.id, "restricted_reader", Permission.read, 1)
        key = secrets.token_urlsafe(32)
        p = s.scalar(select(Principal).where(Principal.tenant_id == tenant.id, Principal.name == args.admin))
        if p is None:
            p = Principal(tenant_id=tenant.id, kind=PrincipalKind.user, name=args.admin, api_key_hash=hash_key(key))
            s.add(p)
            s.flush()
        else:
            p.api_key_hash = hash_key(key)
        grant_role(s, tenant_id=tenant.id, principal=p, role=admin_role, scope=company)
        print(json.dumps({"tenant_id": str(tenant.id), "company_scope_id": str(company.id), "principal_id": str(p.id),
                          "api_key": key}, indent=2))


def cmd_worker(args) -> None:
    from cie.workers.worker import main_loop

    main_loop(poll_seconds=args.poll)


def cmd_serve(args) -> None:
    import uvicorn

    uvicorn.run("cie.api.app:app", host=args.host, port=args.port, reload=args.reload)


def cmd_demo(args) -> None:
    from cie.eval.demo import run_demo

    run_demo(out_dir=Path(args.out))


def cmd_bench(args) -> None:
    from cie.eval import bench_glyph, bench_graph, bench_retrieval

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.which in ("glyph", "all"):
        bench_glyph.main(out)
    if args.which in ("graph", "all"):
        bench_graph.main(out)
    if args.which in ("retrieval", "all"):
        bench_retrieval.main(out, scale=args.scale)


def cmd_simulate(args) -> None:
    from cie.eval.simulation import run_simulation

    run_simulation(out_dir=Path(args.out))


def main(argv: list[str] | None = None) -> int:
    configure_logging(get_settings().log_level)
    ap = argparse.ArgumentParser(prog="cie")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    b = sub.add_parser("bootstrap")
    b.add_argument("--tenant", default="default")
    b.add_argument("--company", default="Company")
    b.add_argument("--admin", default="admin")
    b.set_defaults(fn=cmd_bootstrap)
    w = sub.add_parser("worker")
    w.add_argument("--poll", type=float, default=2.0)
    w.set_defaults(fn=cmd_worker)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    sv.set_defaults(fn=cmd_serve)
    d = sub.add_parser("demo", help="end-to-end vertical slice on a synthetic corpus")
    d.add_argument("--out", default="eval_out/demo")
    d.set_defaults(fn=cmd_demo)
    bn = sub.add_parser("bench")
    bn.add_argument("which", choices=["glyph", "graph", "retrieval", "all"])
    bn.add_argument("--out", default="eval_out/bench")
    bn.add_argument("--scale", type=int, default=1)
    bn.set_defaults(fn=cmd_bench)
    sm = sub.add_parser("simulate", help="multi-agent simulation")
    sm.add_argument("--out", default="eval_out/simulation")
    sm.set_defaults(fn=cmd_simulate)
    args = ap.parse_args(argv)
    args.fn(args)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

_ = uuid
