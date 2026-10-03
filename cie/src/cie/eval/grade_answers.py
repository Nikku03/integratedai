"""Grade answers with EnterpriseRAG-Bench's own judge, and summarise them.

The benchmark's judge (``src.scripts.answer_evaluation.metrics_based_eval`` in its checkout) asks an LLM two things
about every answer:
- **correct**: does the answer agree with the gold answer as a whole?
- **completeness**: what share of the gold answer's facts does it state?

It runs with ``--no-correction``: answers are scored against the benchmark's original gold answers and documents, and
the gold set is never rewritten. The judge lives in its own virtual environment (its requirements are not this
package's), reads its key from ``LLM_API_KEY`` and its model from ``LLM_MODEL_NAME``.

The judge model decides the provider: ``gpt-*`` and ``o*`` models run on the OpenAI API (key from ``OPENAI_API_KEY``),
``claude-*`` models on the Anthropic API (key from ``ANTHROPIC_API_KEY``). The default, ``gpt-5.4``, is the benchmark's
own default judge. Its OpenAI requests ask for reasoning summaries, which an OpenAI organisation must be verified to
receive; the judge here drops that request (the summaries are only printed, never scored).

**A failed judge call is scored as a wrong answer by the benchmark's code**, with no error. So the judge is checked
with one call before grading, and every summary counts the answers whose correctness call returned nothing
(``judge_failed``). A run with more than 5% of them is reported as unusable rather than as a low score.

With the evidence audit's rows (``cie.eval.evidence_audit``, same memory bank and retrieval settings), correctness is
also split by where the answer facts were lost. Correctness among "everything reached the model" questions is the
model's share of the wrong answers.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

JUDGE_MODULE = "src.scripts.answer_evaluation.metrics_based_eval"
DEFAULT_MODEL = "gpt-5.4"  # the benchmark's own default judge (its default provider is OpenAI)
MAX_FAILED_SHARE = 0.05
STAGES = ["search_missed_document", "right_document_wrong_part", "cut_before_model", "everything_reached_model"]


# The benchmark's requirements pin no versions. Its judge was written for the 0.x Anthropic SDK: the 1.x SDK rejects
# the arguments it sends with extended thinking (``temperature`` in ``messages.stream``).
JUDGE_PINS = ["anthropic>=0.80,<1"]
_RECIPE = "requirements + " + " ".join(JUDGE_PINS) + " + runner 1"
# Runs a module (or -c code) of the benchmark's checkout with one change: the OpenAI judge's requests ask for no
# reasoning summary. Everything else is the benchmark's own code.
_RUNNER = """import os, runpy, sys
sys.path.insert(0, os.getcwd())
try:
    from openai.resources.responses import Responses
    _create = Responses.create
    def create(self, *a, **kw):
        r = kw.get("reasoning")
        if isinstance(r, dict) and "summary" in r:
            kw["reasoning"] = {k: v for k, v in r.items() if k != "summary"}
        return _create(self, *a, **kw)
    Responses.create = create
except Exception:
    pass
if sys.argv[1] == "-c":
    exec(compile(sys.argv[2], "<judge>", "exec"), {"__name__": "__main__"})
else:
    mod = sys.argv[1]
    sys.argv = [mod] + sys.argv[2:]
    runpy.run_module(mod, run_name="__main__", alter_sys=True)
"""


def provider_of(model: str) -> str:
    return "anthropic" if model.startswith("claude") else "openai"


def _clean_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """The judge sees none of this package's import path."""
    env = dict(base if base is not None else os.environ)
    env.pop("PYTHONPATH", None)
    return env


def _has_pip(py: Path, env: dict[str, str]) -> bool:
    return py.exists() and subprocess.run([str(py), "-m", "pip", "--version"], env=env, capture_output=True).returncode == 0


def ensure_venv(path: Path, bench: Path, log=print) -> Path:
    """A virtual environment with the benchmark's requirements and the pins above; returns its python (an absolute
    path: the judge runs from the benchmark's folder)."""
    path = path.resolve()
    py = path / "bin" / "python"
    marker = path / ".cie_judge_ready"
    if not marker.exists() or marker.read_text().strip() != _RECIPE:
        log(f"preparing the judge's environment at {path}")
        env = _clean_env()
        if not _has_pip(py, env):
            shutil.rmtree(path, ignore_errors=True)
            if subprocess.run([sys.executable, "-m", "venv", str(path)], env=env).returncode != 0 or not _has_pip(py, env):
                # some images (Colab's among them) lack ensurepip, so venv leaves no pip behind: virtualenv brings its own
                shutil.rmtree(path, ignore_errors=True)
                subprocess.run([sys.executable, "-m", "pip", "install", "-q", "virtualenv"], check=True, env=env)
                subprocess.run([sys.executable, "-m", "virtualenv", "-q", str(path)], check=True, env=env)
        subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", str(bench / "requirements.txt")], check=True, env=env)
        subprocess.run([str(py), "-m", "pip", "install", "-q", *JUDGE_PINS], check=True, env=env)
        marker.write_text(_RECIPE + "\n")
    (path / "cie_judge_run.py").write_text(_RUNNER)
    return py


def _runner(py: Path) -> str:
    return str(py.parent.parent / "cie_judge_run.py")


def judge_env(model: str, key: str | None = None, base: dict[str, str] | None = None) -> dict[str, str]:
    """The judge's environment: the benchmark's OpenAI or Anthropic client, by the model's name. The key is taken
    from ``OPENAI_API_KEY`` or ``ANTHROPIC_API_KEY`` when not given, and is never printed."""
    env = _clean_env(base)
    provider = provider_of(model)
    var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    key = key or env.get(var)
    if not key:
        raise SystemExit(f"the judge {model} needs {var} (on Colab, a secret named {var})")
    env.update({"LLM_PROVIDER": provider, "LLM_MODEL_NAME": model, "LLM_API_KEY": key, "PYTHONUNBUFFERED": "1"})
    return env


def preflight(py: Path, bench: Path, env: dict[str, str]) -> str:
    """One call through the judge's own client: a wrong model name or key fails here, not as 500 'wrong' answers."""
    code = ("from src.llm import get_llm, Message\n"
            "out = ''.join(c for c in get_llm(quiet=True).generate([Message(role='user', content='Reply with the single word: ready')])"
            " if isinstance(c, str))\nprint(out.strip()[:200])")
    r = subprocess.run([str(py), _runner(py), "-c", code], cwd=bench, env=env, capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not r.stdout.strip():
        tail = (r.stderr or r.stdout).strip().splitlines()[-5:]
        raise SystemExit("the judge's test call failed:\n  " + "\n  ".join(tail))
    return r.stdout.strip()


def run_judge(py: Path, bench: Path, answers: Path, results: Path, env: dict[str, str], parallelism: int = 8,
              limit: int | None = None, log=print) -> None:
    """The benchmark's judge on one answers file. ``--resume`` lets an interrupted run continue where it stopped."""
    args = [str(py), _runner(py), JUDGE_MODULE, "--answers-file", str(answers.resolve()), "--questions-file", str(bench / "questions.jsonl"),
            "--results-file", str(results.resolve()), "--no-correction", "--parallelism", str(parallelism), "--resume"]
    if limit:
        args += ["--limit", str(limit)]
    if results.exists() and results.stat().st_mtime < answers.stat().st_mtime:
        results.unlink()  # judgements of an earlier set of answers: never resumed into this one
    results.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(args, cwd=bench, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    tail: list[str] = []
    for line in proc.stdout:  # type: ignore[union-attr]
        tail = (tail + [line.rstrip()])[-20:]
        if line.startswith(("  Questions scored", "  Avg ", "  Combined")) or "[FAIL]" in line:
            log(line.rstrip())
    if proc.wait() != 0:
        raise SystemExit("the judge failed:\n" + "\n".join(tail))


def _rows(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _group(rows: list[dict]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0}
    return {"n": n, "correct_pct": round(100 * sum(1 for r in rows if r.get("answer_correct")) / n, 1),
            "completeness_pct": round(sum(r.get("completeness_pct") or 0.0 for r in rows) / n, 1)}


def summarise(results: dict, answers: list[dict], audit_rows: list[dict] | None = None) -> dict[str, Any]:
    """Correctness and completeness overall, by question type, for answered and declined questions, and (with the
    evidence audit's rows) by where the answer facts were lost."""
    qs = results.get("questions") or []
    by_ans = {a["question_id"]: a for a in answers}
    answered = [r for r in qs if (by_ans.get(r["question_id"]) or {}).get("answer")]
    failed = [r for r in answered if not r.get("answer_correct") and not (r.get("correctness_reasoning") or "").strip()]
    declined = [r for r in qs if (by_ans.get(r["question_id"]) or {}).get("status") == "insufficient_evidence"]
    out: dict[str, Any] = {"overall": _group(qs), "judge_failed": len(failed),
                           "usable": len(failed) <= MAX_FAILED_SHARE * max(len(answered), 1),
                           "declined": {**_group(declined), "note": "answers that said the evidence was insufficient"},
                           "not_declined": _group([r for r in qs if r not in declined])}
    cats: dict[str, list[dict]] = defaultdict(list)
    for r in qs:
        cats[r.get("question_type") or "?"].append(r)
    out["by_question_type"] = {c: _group(v) for c, v in sorted(cats.items())}
    if audit_rows:
        stage = {a["question_id"]: a.get("stage") for a in audit_rows}
        by_stage: dict[str, list[dict]] = defaultdict(list)
        for r in qs:
            by_stage[stage.get(r["question_id"]) or "not judged by the audit"].append(r)
        out["by_audit_stage"] = {s: _group(by_stage[s]) for s in [*STAGES, "not judged by the audit"] if by_stage.get(s)}
    return out


def detail_file(answers: Path) -> Path:
    """The ``_detail`` file ``bench_enterprise`` writes beside each answers file (status and category per answer)."""
    return answers.with_name(answers.stem + "_detail.jsonl")


def grade(bench: Path, answer_files: list[Path], out: Path, venv: Path, model: str = DEFAULT_MODEL, parallelism: int = 8,
          limit: int | None = None, audit_rows: Path | None = None, log=print) -> dict[str, Any]:
    py = ensure_venv(venv, bench, log=log)
    env = judge_env(model)
    log(f"judge {model}: test call answered {preflight(py, bench, env)!r}")
    audit = _rows(audit_rows)
    report: dict[str, Any] = {"judge": model, "mode": "--no-correction (original gold answers and documents)", "files": {}}
    for f in answer_files:
        results = out / f"judge_{f.stem}.json"
        log(f"grading {f.name} -> {results.name}")
        run_judge(py, bench, f, results, env, parallelism, limit, log=log)
        answers = _rows(detail_file(f)) or _rows(f)
        report["files"][f.name] = summarise(json.loads(results.read_text()), answers, audit)
    out.mkdir(parents=True, exist_ok=True)
    (out / "grading.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bench", required=True, help="the EnterpriseRAG-Bench checkout (its src/ and questions.jsonl)")
    ap.add_argument("--answers", required=True, nargs="+", help="answers files written by cie.eval.bench_enterprise")
    ap.add_argument("--out", default="eval_out/grading")
    ap.add_argument("--venv", default=None, help="the judge's virtual environment (default: <out>/judge-venv)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"the judge model (default: {DEFAULT_MODEL}, the benchmark's own)")
    ap.add_argument("--parallelism", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None, help="only the first N answers (a smoke test)")
    ap.add_argument("--audit-rows", default=None, help="evidence_audit_rows.jsonl for the same memory bank and retrieval settings")
    a = ap.parse_args(argv)
    out = Path(a.out)
    rep = grade(Path(a.bench), [Path(x) for x in a.answers], out, Path(a.venv) if a.venv else out / "judge-venv", a.model,
                a.parallelism, a.limit, Path(a.audit_rows) if a.audit_rows else None)
    print(json.dumps({k: {"overall": v["overall"], "judge_failed": v["judge_failed"], "usable": v["usable"]}
                      for k, v in rep["files"].items()}, indent=2))
    return rep


if __name__ == "__main__":  # pragma: no cover
    main()
