from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from typing import Any, Callable, Sequence, TextIO

from . import storage
from .runner import CheckRunner


EXIT_OK = 0
EXIT_RUN_FAILED = 1
EXIT_NO_MATCH = 2
EXIT_USAGE = 3
EXIT_INTERNAL_ERROR = 4
TERMINAL_OK_STATUSES = {"ok"}


class CliUsageError(ValueError):
    pass


class CliArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(message)


@dataclass(frozen=True)
class CliFilters:
    ids: tuple[int, ...]
    check_type: str | None
    tag: str
    enabled_only: bool


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是正整数") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = CliArgumentParser(
        prog="pulseguard-cli",
        description="Run configured PulseGuard checks for CLI or CI.",
    )
    parser.add_argument("--id", dest="ids", action="append", type=positive_int, default=[], help="任务 ID，可重复传入")
    parser.add_argument("--type", choices=["api", "ui"], default=None, help="任务类型")
    parser.add_argument("--tag", default="", help="标签 token")
    parser.add_argument("--include-disabled", action="store_true", help="包含已禁用任务")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    return parser


def parse_filters(argv: Sequence[str] | None = None) -> tuple[CliFilters, bool]:
    args = build_parser().parse_args(argv)
    tag = str(args.tag or "").strip()
    if any(char.isspace() or char == "," for char in tag):
        raise CliUsageError("标签必须是单个 token，不能包含空白或逗号")
    filters = CliFilters(
        ids=tuple(dict.fromkeys(int(item) for item in args.ids)),
        check_type=args.type,
        tag=tag.lower(),
        enabled_only=not bool(args.include_disabled),
    )
    return filters, bool(args.pretty)


def select_checks(filters: CliFilters) -> list[dict[str, Any]]:
    if not filters.ids:
        return storage.select_checks_for_batch(filters.check_type, filters.tag, enabled_only=filters.enabled_only)

    selected: list[dict[str, Any]] = []
    for check_id in filters.ids:
        check = storage.get_check(check_id)
        if not check:
            continue
        if filters.check_type and check.get("type") != filters.check_type:
            continue
        if filters.enabled_only and not bool(check.get("enabled")):
            continue
        if filters.tag and filters.tag not in storage.check_tag_set(check.get("tags")):
            continue
        selected.append(check)
    return selected


async def run_checks(checks: list[dict[str, Any]], runner_factory: Callable[[], CheckRunner] = CheckRunner) -> list[dict[str, Any]]:
    runner = runner_factory()
    await runner.start()
    try:
        return await asyncio.gather(
            *[runner.run_check(int(check["id"]), trigger="cli") for check in checks]
        )
    finally:
        await runner.shutdown()


def result_payload(filters: CliFilters, checks: list[dict[str, Any]], runs: list[dict[str, Any]]) -> dict[str, Any]:
    ok = bool(runs) and all(str(run.get("status") or "") in TERMINAL_OK_STATUSES for run in runs)
    return {
        "ok": ok,
        "matched": len(checks),
        "filters": {
            "ids": list(filters.ids),
            "type": filters.check_type,
            "tag": filters.tag,
            "enabled_only": filters.enabled_only,
        },
        "runs": [run_summary(run) for run in runs],
    }


def no_match_payload(filters: CliFilters) -> dict[str, Any]:
    return {
        "ok": False,
        "matched": 0,
        "message": "没有匹配任务",
        "filters": {
            "ids": list(filters.ids),
            "type": filters.check_type,
            "tag": filters.tag,
            "enabled_only": filters.enabled_only,
        },
        "runs": [],
    }


def error_payload(message: str) -> dict[str, Any]:
    return {"ok": False, "message": message, "runs": []}


def run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": run.get("id"),
        "check_id": run.get("check_id"),
        "check_name": run.get("check_name"),
        "check_type": run.get("check_type"),
        "status": run.get("status"),
        "duration_ms": run.get("duration_ms"),
        "error_message": run.get("error_message"),
    }


def write_json(payload: dict[str, Any], stream: TextIO, pretty: bool = False) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None))
    stream.write("\n")


async def async_main(
    argv: Sequence[str] | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    runner_factory: Callable[[], CheckRunner] = CheckRunner,
) -> int:
    try:
        filters, pretty = parse_filters(argv)
        storage.init_db()
        checks = select_checks(filters)
        if not checks:
            write_json(no_match_payload(filters), stdout, pretty=pretty)
            return EXIT_NO_MATCH
        runs = await run_checks(checks, runner_factory=runner_factory)
        write_json(result_payload(filters, checks, runs), stdout, pretty=pretty)
        return EXIT_OK if all(str(run.get("status") or "") in TERMINAL_OK_STATUSES for run in runs) else EXIT_RUN_FAILED
    except CliUsageError as exc:
        write_json(error_payload(str(exc)), stderr)
        return EXIT_USAGE
    except Exception as exc:
        write_json(error_payload(str(exc) or exc.__class__.__name__), stderr)
        return EXIT_INTERNAL_ERROR


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    return asyncio.run(async_main(argv))


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
