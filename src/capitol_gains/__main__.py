"""Command line for ingestion, scoring, the sample league, and a static server."""

from __future__ import annotations

import argparse
import os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from capitol_gains.config import ROOT, load_settings
from capitol_gains.db import connect


def _load_env_file() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def main(argv: list[str] | None = None) -> None:
    _load_env_file()
    parser = argparse.ArgumentParser(prog="capitol-gains")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sample", help="Write the fictional sample league into the site data folder")
    sub.add_parser("ingest", help="Fetch what today's Alpha Vantage budget allows")
    sub.add_parser("compute", help="Score the SQLite cache and write JSON")
    sub.add_parser("run", help="Ingest, then compute")
    serve = sub.add_parser("serve", help="Serve the built static site")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--site", default="")

    args = parser.parse_args(argv)
    settings = load_settings()

    if args.command == "sample":
        from capitol_gains.sample_league import summarize, write_sample

        league = write_sample(settings.site_data)
        print(summarize(league))
        print(f"wrote {settings.site_data}")
        return

    if args.command == "serve":
        site = Path(args.site) if args.site else ROOT / "web" / "dist"
        if not (site / "index.html").exists():
            raise SystemExit("No built site at web/dist. From web/, run `npm run build`, or `npm run dev` while developing.")
        _serve(site, args.host, args.port)
        return

    conn = connect(settings.db_path)
    try:
        if args.command in {"ingest", "run"}:
            if not settings.api_key:
                raise SystemExit("ALPHAVANTAGE_API_KEY is not set. Copy .env.example to .env or run `python -m capitol_gains sample`.")
            from capitol_gains.av import AlphaVantageClient
            from capitol_gains.ingest import ingest

            client = AlphaVantageClient(settings, conn)
            report = ingest(settings, conn, client)
            print(
                "ingest members={members} prices={prices} metadata={metadata} stopped={stopped}".format(
                    members=len(report["members"]),
                    prices=len(report["prices"]),
                    metadata=report["metadata"],
                    stopped=report["stopped"],
                )
            )
        if args.command in {"compute", "run"}:
            from capitol_gains.ingest import compute_site

            result = compute_site(settings, conn)
            print(f"computed {result['members']} members as of {result['as_of']}")
    finally:
        conn.close()


def _serve(site: Path, host: str, port: int) -> None:
    directory = str(site.resolve())

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"serving {directory} on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
