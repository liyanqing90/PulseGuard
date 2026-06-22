from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Start a PulseGuard child execution node.")
    parser.add_argument("--host", default=os.getenv("PULSEGUARD_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PULSEGUARD_PORT", "8788")))
    parser.add_argument("--name", default=os.getenv("PULSEGUARD_WORKER_NAME", "worker"))
    parser.add_argument("--region", default=os.getenv("PULSEGUARD_WORKER_REGION", "local"))
    parser.add_argument("--address", default=os.getenv("PULSEGUARD_WORKER_ADDRESS", ""))
    parser.add_argument("--token", default=os.getenv("PULSEGUARD_WORKER_TOKEN", ""))
    parser.add_argument("--token-file", default=os.getenv("PULSEGUARD_WORKER_TOKEN_FILE", ""))
    parser.add_argument("--show-token", action="store_true", help="Print the current worker token and exit.")
    parser.add_argument("--rotate-token", action="store_true", help="Generate and store a new worker token, then exit.")
    args = parser.parse_args()

    if args.rotate_token and args.token:
        parser.error("--rotate-token cannot be used when PULSEGUARD_WORKER_TOKEN or --token is set")

    os.environ["PULSEGUARD_NODE_ROLE"] = "worker"
    os.environ["PULSEGUARD_HOST"] = str(args.host)
    os.environ["PULSEGUARD_PORT"] = str(args.port)
    os.environ["PULSEGUARD_WORKER_NAME"] = str(args.name or "worker")
    os.environ["PULSEGUARD_WORKER_REGION"] = str(args.region or "local")
    if args.token:
        os.environ["PULSEGUARD_WORKER_TOKEN"] = str(args.token)
    if args.token_file:
        os.environ["PULSEGUARD_WORKER_TOKEN_FILE"] = str(args.token_file)
    if args.address:
        os.environ["PULSEGUARD_WORKER_ADDRESS"] = str(args.address).rstrip("/")

    from . import config

    if args.rotate_token:
        token = _rotate_token_file(config.WORKER_TOKEN_FILE)
        _print_startup_info(config.WORKER_ADDRESS, config.WORKER_NAME, config.WORKER_REGION, token, str(config.WORKER_TOKEN_FILE))
        return

    if args.show_token:
        _print_startup_info(config.WORKER_ADDRESS, config.WORKER_NAME, config.WORKER_REGION, config.WORKER_TOKEN, config.WORKER_TOKEN_SOURCE)
        return

    _print_startup_info(
        config.WORKER_ADDRESS,
        config.WORKER_NAME,
        config.WORKER_REGION,
        config.WORKER_TOKEN,
        config.WORKER_TOKEN_SOURCE,
        print_token=config.WORKER_PRINT_TOKEN,
    )
    os.environ["PULSEGUARD_WORKER_INFO_PRINTED"] = "1"

    import uvicorn

    uvicorn.run(f"{__package__}.main:app", host=str(args.host), port=int(args.port), log_level="info")


def _rotate_token_file(token_file: Path) -> str:
    token = f"pgrn_{secrets.token_urlsafe(32)}"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token + "\n", encoding="utf-8")
    try:
        token_file.chmod(0o600)
    except OSError:
        pass
    return token


def _print_startup_info(address: str, name: str, region: str, token: str, token_source: str, *, print_token: bool = True) -> None:
    display_address = address or "set this in the main console, for example http://<child-node-ip>:8788"
    print("", flush=True)
    print("PulseGuard worker node is ready.", flush=True)
    print(f"  name: {name}", flush=True)
    print(f"  address: {display_address}", flush=True)
    print(f"  region: {region}", flush=True)
    print(f"  token: {token if print_token else '<hidden>'}", flush=True)
    print(f"  token_source: {token_source}", flush=True)
    if print_token:
        print("Add this child node manually in the main console with the address and token above.", flush=True)
    else:
        print("Worker token is configured; token logging is disabled for this deployment.", flush=True)
    print("", flush=True)


if __name__ == "__main__":
    main()
