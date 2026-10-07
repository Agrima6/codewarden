from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from codewarden import __version__
from codewarden.config import Config
from codewarden.github import GitHubClient, GitHubError
from codewarden.llm import LLMError, get_llm
from codewarden.models import ReviewResult, severity_rank
from codewarden.rag import build_retriever
from codewarden.report import render_summary, render_terminal
from codewarden.review import review_diff

TRIGGER_PHRASE = "/codewarden review"


def _git_diff(args: list[str]) -> str:
    proc = subprocess.run(["git", "diff", "--no-color", "-U3", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"git diff failed: {proc.stderr.strip()}")
    return proc.stdout


def _exit_code(result: ReviewResult, cfg: Config) -> int:
    if cfg.fail_on == "none" or not result.findings:
        return 0
    worst = result.worst_severity()
    return 1 if worst and severity_rank(worst) >= severity_rank(cfg.fail_on) else 0


def _apply_overrides(cfg: Config, args) -> Config:
    if getattr(args, "provider", None):
        cfg.provider = args.provider
    if getattr(args, "model", None):
        cfg.model = args.model
    if getattr(args, "no_rag", False):
        cfg.rag.enabled = False
    cfg.validate()
    return cfg


def cmd_review(args) -> int:
    cfg = _apply_overrides(Config.load(args.config), args)
    if args.diff_file:
        diff = sys.stdin.read() if args.diff_file == "-" else Path(args.diff_file).read_text()
    elif args.staged:
        diff = _git_diff(["--cached"])
    else:
        diff = _git_diff([f"{args.base}...{args.head}"])
    if not diff.strip():
        print("No changes to review.")
        return 0
    try:
        llm = get_llm(cfg)
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    retriever = build_retriever(args.repo_root, cfg.rag)
    result = review_diff(diff, cfg, llm, retriever)
    if args.format == "json":
        print(json.dumps([f.__dict__ | {"fingerprint": f.fingerprint} for f in result.findings], indent=2))
    elif args.format == "markdown":
        print(render_summary(result))
    else:
        print(render_terminal(result))
    return _exit_code(result, cfg)


def cmd_action(args) -> int:
    cfg = _apply_overrides(Config.load(args.config), args)
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not event_path:
        print("error: run `codewarden action` inside GitHub Actions (GITHUB_EVENT_PATH missing)", file=sys.stderr)
        return 2
    event = json.loads(Path(event_path).read_text())

    if event_name in ("pull_request", "pull_request_target"):
        number = event["pull_request"]["number"]
        from_fork = event["pull_request"]["head"]["repo"] and event["pull_request"]["head"]["repo"]["full_name"] != repo
    elif event_name == "issue_comment":
        if not event.get("issue", {}).get("pull_request") or TRIGGER_PHRASE not in event["comment"]["body"]:
            print("Comment is not a CodeWarden trigger; nothing to do.")
            return 0
        number, from_fork = event["issue"]["number"], False
    else:
        print(f"Unsupported event {event_name!r}; use pull_request or issue_comment.")
        return 0

    try:
        llm = get_llm(cfg)
    except LLMError as exc:
        if from_fork:
            print(f"::warning::Skipping review of fork PR (secrets unavailable): {exc}")
            return 0
        print(f"::error::{exc}")
        return 2

    try:
        gh = GitHubClient(os.environ.get("GITHUB_TOKEN", ""), repo)
        pr = gh.get_pr(number)
        if pr["draft"] and event_name != "issue_comment":
            print("Draft PR; skipping.")
            return 0
        diff = gh.get_diff(number)
        seen = gh.existing_fingerprints(number)
        retriever = build_retriever(os.environ.get("GITHUB_WORKSPACE", "."), cfg.rag)
        result = review_diff(diff, cfg, llm, retriever, pr["title"], pr["body"], seen)
        print(render_terminal(result))
        if result.findings:
            posted, moved = gh.post_review(number, pr["head_sha"], render_summary(result), result.findings)
            print(f"Posted {posted} inline comment(s); {moved} could not be anchored.")
        else:
            print("No new findings; nothing posted.")
    except GitHubError as exc:
        print(f"::error::{exc}")
        return 2
    return _exit_code(result, cfg)


def cmd_search(args) -> int:
    cfg = _apply_overrides(Config.load(args.config), args)
    cfg.rag.enabled = True
    retriever = build_retriever(args.repo_root, cfg.rag)
    if retriever is None:
        print("No indexable files found.")
        return 1
    print(f"Indexed {len(retriever.chunks)} chunks.")
    for c in retriever.search(args.query, k=args.k):
        print(f"\n--- {c.path}:{c.start}-{c.end}")
        print("\n".join(c.text.splitlines()[:8]))
    return 0


def cmd_eval(args) -> int:
    from codewarden.evaluate import run_eval, summarize
    cfg = _apply_overrides(Config.load(args.config), args)
    cfg.min_confidence = args.min_confidence
    try:
        llm = get_llm(cfg)
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    scores = run_eval(Path(args.cases), cfg, llm)
    print(f"{'case':28} {'expected':>8} {'found':>6} {'hit':>4} {'cat ok':>6}")
    for s in scores:
        print(f"{s.name:28} {s.expected:>8} {s.findings:>6} {s.true_positive_findings:>4} {s.categories_ok:>6}")
    t = summarize(scores)
    p = "n/a" if t["precision"] is None else f"{t['precision']:.0%}"
    r = "n/a" if t["recall"] is None else f"{t['recall']:.0%}"
    print(f"\nprovider={cfg.provider} model={cfg.resolved_model() or '-'}  precision={p}  recall={r}  "
          f"false_positives={t['false_positives']}")
    return 0


def _find_dir(rel: str) -> Path | None:
    for base in (Path.cwd(), Path(__file__).resolve().parents[2]):
        if (base / rel).is_dir():
            return base / rel
    return None


def _serve(args, *, repo_root: Path, db: Path, seed: bool) -> int:
    try:
        import uvicorn
        from codewarden.server import create_app
    except ImportError:
        print("error: the dashboard needs: pip install 'codewarden[web]'", file=sys.stderr)
        return 2
    from codewarden.services import Engine
    from codewarden.store import Store

    token = os.environ.get("CODEWARDEN_DASHBOARD_TOKEN") or None
    if args.host not in ("127.0.0.1", "localhost", "::1") and not token:
        print("error: refusing to listen on a non-local address without CODEWARDEN_DASHBOARD_TOKEN set", file=sys.stderr)
        return 2
    engine = Engine(Store(db), repo_root, args.config, _find_dir(args.eval_dir), _find_dir(args.demo_dir),
                    repos_dir=db.parent / "repos")
    if seed:
        import threading

        def _seed():
            print("Preparing sample reviews...", flush=True)
            try:
                for w in engine.seed_demo().get("warnings", []):
                    print(f"  note: {w}", flush=True)
                print("Sample reviews ready.", flush=True)
            except Exception as exc:  # keep the server up even if seeding fails
                print(f"  seeding failed: {exc}", flush=True)
        threading.Thread(target=_seed, daemon=True).start()
    url = f"http://{args.host}:{args.port}"
    print(f"CodeWarden dashboard: {url}   (repo: {engine.repo_root}, db: {db})")
    if args.open:
        import threading
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(engine, token), host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_serve(args) -> int:
    return _serve(args, repo_root=Path(args.repo_root), db=Path(args.db), seed=False)


def cmd_demo(args) -> int:
    shop = _find_dir("demo/shop")
    if shop is None or _find_dir(args.demo_dir) is None:
        print("error: run this from the codewarden repository (demo/ folder not found)", file=sys.stderr)
        return 2
    db = Path(args.db)
    db.unlink(missing_ok=True)
    demo_cfg = _find_dir("demo")
    if not args.config and demo_cfg and (demo_cfg / "codewarden.yml").exists():
        args.config = str(demo_cfg / "codewarden.yml")
    return _serve(args, repo_root=shop, db=db, seed=True)


def cmd_ask(args) -> int:
    from codewarden.qa import answer_question
    cfg = _apply_overrides(Config.load(args.config), args)
    cfg.rag.enabled = True
    retriever = build_retriever(args.repo_root, cfg.rag)
    if retriever is None:
        print("No indexable files found.")
        return 1
    try:
        llm = get_llm(cfg)
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    res = answer_question(args.question, retriever, llm, k=args.k)
    print(res["answer"] or f"error: {res['error']}")
    print("\nSources:")
    for s in res["sources"]:
        print(f"  {s['path']}:{s['start']}-{s['end']}")
    return 0


def cmd_testgen(args) -> int:
    from codewarden.testgen import generate_tests
    cfg = _apply_overrides(Config.load(args.config), args)
    try:
        llm = get_llm(cfg)
        out = generate_tests(Path(args.diff_file).read_text(), args.file, llm)
    except (LLMError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(out["code"] or out["note"])
    return 0


def cmd_experiment(args) -> int:
    from codewarden.experiment import ExperimentError, build_systems, run_experiment
    cfg = Config.load(args.config)
    eval_dir = _find_dir(args.eval_dir)
    if eval_dir is None:
        print("error: eval/ folder not found; run from the repository root", file=sys.stderr)
        return 2
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    systems = build_systems(providers, {"ollama": args.ollama_model} if args.ollama_model else {})

    def progress(done, total, label):
        print(f"[{done}/{total}] {label}", flush=True)

    try:
        res = run_experiment(systems=systems, repeats=args.repeats, eval_dir=eval_dir, base_cfg=cfg, progress=progress)
    except ExperimentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"\n{'system':34} {'suite':8} {'P':>6} {'R':>6} {'F1':>6} {'FP':>4} {'FN':>4} {'latency':>9}")
    for key, m in res["metrics"].items():
        sid, suite = key.split("|")
        label = next(s["label"] for s in res["systems"] if s["id"] == sid)
        f = lambda v: "n/a" if v is None else f"{v:.2f}"
        print(f"{label[:34]:34} {suite:8} {f(m['precision']):>6} {f(m['recall']):>6} {f(m['f1']):>6} "
              f"{m['false_positives']:>4} {m['false_negatives']:>4} {m['avg_latency_ms']:>7}ms")
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=2))
        print(f"\nFull results written to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="codewarden", description="AI-powered pull request review assistant")
    p.add_argument("--version", action="version", version=f"codewarden {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, rag=True):
        sp.add_argument("--config", help="path to .codewarden.yml")
        sp.add_argument("--provider", choices=["gemini", "ollama", "rules"])
        sp.add_argument("--model")
        if rag:
            sp.add_argument("--no-rag", action="store_true", help="review the diff without repository context")

    r = sub.add_parser("review", help="review a local diff")
    common(r)
    src = r.add_mutually_exclusive_group()
    src.add_argument("--diff-file", help="unified diff file, or - for stdin")
    src.add_argument("--staged", action="store_true", help="review staged changes")
    r.add_argument("--base", default="origin/main")
    r.add_argument("--head", default="HEAD")
    r.add_argument("--repo-root", default=".")
    r.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    r.set_defaults(fn=cmd_review)

    a = sub.add_parser("action", help="review the current PR inside GitHub Actions and post comments")
    common(a)
    a.set_defaults(fn=cmd_action)

    s = sub.add_parser("search", help="query the repository index (debug the RAG layer)")
    common(s, rag=False)
    s.add_argument("query")
    s.add_argument("-k", type=int, default=4)
    s.add_argument("--repo-root", default=".")
    s.set_defaults(fn=cmd_search)

    def web_opts(sp):
        sp.add_argument("--host", default="127.0.0.1")
        sp.add_argument("--port", type=int, default=8765)
        sp.add_argument("--config")
        sp.add_argument("--eval-dir", default="eval/cases")
        sp.add_argument("--demo-dir", default="demo/prs")
        sp.add_argument("--no-open", dest="open", action="store_false", help="do not open a browser tab")

    sv = sub.add_parser("serve", help="start the web dashboard")
    web_opts(sv)
    sv.add_argument("--repo-root", default=".", help="repository indexed for RAG context and code Q&A")
    sv.add_argument("--db", default=".codewarden/dashboard.db")
    sv.set_defaults(fn=cmd_serve)

    dm = sub.add_parser("demo", help="start the dashboard pre-loaded with demo pull requests (no API key needed)")
    web_opts(dm)
    dm.add_argument("--db", default=".codewarden/demo.db")
    dm.set_defaults(fn=cmd_demo)

    q = sub.add_parser("ask", help="ask a question about the repository (RAG Q&A)")
    common(q, rag=False)
    q.add_argument("question")
    q.add_argument("-k", type=int, default=5)
    q.add_argument("--repo-root", default=".")
    q.set_defaults(fn=cmd_ask)

    t = sub.add_parser("testgen", help="generate unit tests for a file in a diff")
    common(t, rag=False)
    t.add_argument("--diff-file", required=True)
    t.add_argument("--file", required=True, help="path of the file inside the diff")
    t.set_defaults(fn=cmd_testgen)

    x = sub.add_parser("experiment", help="baseline vs LLM vs LLM+RAG on labelled datasets (reproducible)")
    x.add_argument("--providers", default="rules", help="comma list of rules,gemini,ollama")
    x.add_argument("--repeats", type=int, default=1)
    x.add_argument("--ollama-model", default="")
    x.add_argument("--eval-dir", default="eval/cases")
    x.add_argument("--config")
    x.add_argument("--out", help="write the full JSON results here")
    x.set_defaults(fn=cmd_experiment)

    e = sub.add_parser("eval", help="score the reviewer on seeded-bug cases")
    common(e, rag=False)
    e.add_argument("--cases", default="eval/cases")
    e.add_argument("--min-confidence", type=float, default=0.5)
    e.set_defaults(fn=cmd_eval)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
