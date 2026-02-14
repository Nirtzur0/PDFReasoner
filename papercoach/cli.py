from __future__ import annotations

import argparse
from pathlib import Path

from papercoach.config import RunConfig, ServiceConfig
from papercoach.pipeline import analyze, annotate, render


def _common_run_args(parser: argparse.ArgumentParser, include_output: bool = True) -> None:
    parser.add_argument("input_pdf", type=Path)
    if include_output:
        parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--level", choices=["light", "medium", "heavy"], default="medium")
    parser.add_argument("--margin-width", type=float, default=180)
    parser.add_argument("--max-notes-per-page", type=int, default=8)
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--mindmap-position", choices=["cover", "appendix"], default="appendix")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="papercoach")
    sub = parser.add_subparsers(dest="command", required=True)

    annotate_cmd = sub.add_parser("annotate")
    _common_run_args(annotate_cmd, include_output=True)

    plan_cmd = sub.add_parser("plan")
    _common_run_args(plan_cmd, include_output=False)
    plan_cmd.add_argument("--out", type=Path, required=False)

    render_cmd = sub.add_parser("render")
    render_cmd.add_argument("input_pdf", type=Path)
    render_cmd.add_argument("plan_json", type=Path)
    render_cmd.add_argument("--out", type=Path, required=True)
    render_cmd.add_argument("--workdir", type=Path, required=True)
    render_cmd.add_argument("--margin-width", type=float, default=180)
    render_cmd.add_argument("--max-notes-per-page", type=int, default=8)
    render_cmd.add_argument("--mindmap-position", choices=["cover", "appendix"], default="appendix")

    return parser


def _run_config_from_args(args: argparse.Namespace) -> RunConfig:
    out = args.out if getattr(args, "out", None) else args.workdir / "enhanced.pdf"
    return RunConfig(
        input_pdf=args.input_pdf,
        out_pdf=out,
        workdir=args.workdir,
        level=getattr(args, "level", "medium"),
        margin_width=getattr(args, "margin_width", 180),
        max_notes_per_page=getattr(args, "max_notes_per_page", 8),
        no_web=getattr(args, "no_web", False),
        mindmap_position=getattr(args, "mindmap_position", "appendix"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    services = ServiceConfig()
    if args.command == "annotate":
        run = _run_config_from_args(args)
        annotate(run, services)
        return 0

    if args.command == "plan":
        run = _run_config_from_args(args)
        plan = analyze(run, services)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        return 0

    if args.command == "render":
        run = RunConfig(
            input_pdf=args.input_pdf,
            out_pdf=args.out,
            workdir=args.workdir,
            margin_width=args.margin_width,
            max_notes_per_page=args.max_notes_per_page,
            mindmap_position=args.mindmap_position,
        )
        render(run, plan_path=args.plan_json)
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
