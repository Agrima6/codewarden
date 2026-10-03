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
