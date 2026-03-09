from __future__ import annotations

import argparse
from pathlib import Path

from papercoach.config import RunConfig, ServiceConfig
from papercoach.pipeline import PaperCoachPipeline, build_default_out_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="papercoach")
    subparsers = parser.add_subparsers(dest="command", required=True)

    highlight = subparsers.add_parser("highlight")
    _add_run_args(highlight, include_output=True)

    highlight_plan = subparsers.add_parser("highlight-plan")
    _add_run_args(highlight_plan, include_output=False)

    render = subparsers.add_parser("render-highlights")
    render.add_argument("input_pdf", type=Path)
    render.add_argument("plan_json", type=Path)
    render.add_argument("--out", type=Path, required=True)
    render.add_argument("--workdir", type=Path, required=True)
    render.add_argument("--style", choices=["minimal"], default="minimal")
    render.add_argument("--margin-width", type=float, default=240.0)
    render.add_argument("--max-notes-per-page", type=int, default=3)
    render.add_argument("--max-equations-per-page", type=int, default=2)

    return parser


def _add_run_args(parser: argparse.ArgumentParser, include_output: bool) -> None:
    parser.add_argument("input_pdf", type=Path)
    if include_output:
        parser.add_argument("--out", type=Path, required=False)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--density", choices=["balanced"], default="balanced")
    parser.add_argument("--style", choices=["minimal"], default="minimal")
    parser.add_argument("--max-highlights-per-page", type=int, default=3)
    parser.add_argument("--margin-width", type=float, default=240.0)
    parser.add_argument("--max-notes-per-page", type=int, default=3)
    parser.add_argument("--max-equations-per-page", type=int, default=2)


def _run_config_from_args(args: argparse.Namespace) -> RunConfig:
    out_pdf = args.out if getattr(args, "out", None) else build_default_out_path(args.input_pdf)
    return RunConfig(
        input_pdf=args.input_pdf,
        out_pdf=out_pdf,
        workdir=args.workdir,
        density=args.density,
        style=args.style,
        max_highlights_per_page=args.max_highlights_per_page,
        margin_width=args.margin_width,
        max_notes_per_page=args.max_notes_per_page,
        max_equations_per_page=args.max_equations_per_page,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pipeline = PaperCoachPipeline(ServiceConfig())

    if args.command == "highlight":
        pipeline.highlight(_run_config_from_args(args))
        return 0

    if args.command == "highlight-plan":
        pipeline.highlight_plan(_run_config_from_args(args))
        return 0

    if args.command == "render-highlights":
        run = RunConfig(
            input_pdf=args.input_pdf,
            out_pdf=args.out,
            workdir=args.workdir,
            style=args.style,
            margin_width=args.margin_width,
            max_notes_per_page=args.max_notes_per_page,
            max_equations_per_page=args.max_equations_per_page,
        )
        pipeline.render_highlights(run, args.plan_json)
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
