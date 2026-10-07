"""Explicit local launch modes. Importing the package never starts a provider."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from .config import default_data_dir, load_bindings
from .models import HomeError


def create_app(data_dir: Path, config: Path | None, demo: bool, port: int):
    from .council import Council
    from .residents import demo_registry, native_registry
    from .server import HomeServer
    from .store import Store

    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if demo:
        bindings, seeds = demo_registry()
    else:
        if config is None:
            raise ValueError("Choose a demo or an explicit native provider configuration")
        bindings, seeds = native_registry(load_bindings(config))
    store = Store(data_dir / "home.sqlite")
    try:
        if not store.list_rooms_page()["rooms"]:
            store.create_room()
        council = Council(store, bindings=bindings, seeds=seeds)
        try:
            server = HomeServer(port, store, council, fixture=demo)
        except BaseException:
            council.close()
            raise
    except BaseException:
        store.close()
        raise
    return server, council, store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open your local shared AI home")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo", action="store_true", help="explicit offline fixture demonstration")
    mode.add_argument("--config", type=Path, help="local native resident TOML bindings")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--open", action="store_true", help="open the private launch in your browser")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("Port must be between 0 and 65535")
    try:
        server, council, store = create_app(args.data_dir, args.config, args.demo, args.port)
    except (HomeError, ValueError, OSError) as error:
        print(f"Home could not start: {error}", file=sys.stderr)
        return 2
    origin = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"KiFoundry Home is running at {origin}", flush=True)
    print("Fixture demo: simulated replies" if args.demo else "Native providers: actual usage applies", flush=True)
    if args.open:
        if not webbrowser.open(server.launch_url):
            print("Browser did not open. Private local launch URL:", server.launch_url, flush=True)
    else:
        print("Private local launch URL:", server.launch_url, flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        council.close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
