"""CPS command-line entrypoints."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cps", description="Cloud Provider Management Service")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the CPS HTTP API")
    serve.add_argument("--host", default="0.0.0.0", help="Bind host")
    serve.add_argument("--port", type=int, default=8000, help="Bind port")
    serve.add_argument(
        "--internal",
        action="store_true",
        help="Run the private credential resolver listener",
    )

    worker = subparsers.add_parser("worker", help="Run the CPS background worker")
    worker.add_argument(
        "--once",
        action="store_true",
        help="Connect once to RabbitMQ and exit (smoke mode)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    from cps.runtime import configure_event_loop_policy

    configure_event_loop_policy()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "serve":
        import uvicorn

        app_factory = "cps.main:create_internal_app" if args.internal else "cps.main:create_app"
        uvicorn.run(app_factory, factory=True, host=args.host, port=args.port)
        return

    if args.command == "worker":
        from cps.config import get_settings
        from cps.messaging.lifecycle import WorkerLifecycle
        from cps.messaging.runtime import run_worker
        from cps.observability.logging import configure_logging

        settings = get_settings()
        configure_logging(level=settings.log_level, service_name=settings.service_name)
        lifecycle = WorkerLifecycle()
        asyncio.run(
            run_worker(
                settings=settings,
                lifecycle=lifecycle,
                once=args.once,
                publish_outbox=True,
            )
        )
        if args.once:
            print("cps worker initialized", flush=True)
        return

    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    main(sys.argv[1:])
