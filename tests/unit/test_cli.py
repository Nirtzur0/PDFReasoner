from __future__ import annotations

from papercoach.cli import build_parser


def test_serve_command_defaults_to_port_8080() -> None:
    args = build_parser().parse_args(["serve"])

    assert args.host == "127.0.0.1"
    assert args.port == 8080
