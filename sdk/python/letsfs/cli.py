"""letsFS command-line interface.

Two implementations are provided:

1. A **rich** ``typer``-based CLI, used when ``typer`` (and ``rich``) are
   installed — install with ``pip install letsfs[cli]``.
2. A **stdlib** ``argparse``-based CLI fallback, used when the optional
   extras are not installed. This keeps the CLI runnable with zero extra
   dependencies (Python ≥ 3.10 only).

Both expose the same three commands:

- ``letsfs search "Bali" --limit 20``                — search hotels
- ``letsfs location "Bali"``                          — resolve a location
- ``letsfs hotel <osm_id> <osm_type>``                — get hotel details
- ``letsfs config``                                   — show resolved config
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from . import __version__
from .client import LetsFS, LetsFSError


# ── Shared command logic ──────────────────────────────────────────────────

def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def _maybe_rich_print(text: str, *, style: Optional[str] = None) -> None:
    """Print with rich styling if rich is available, else plain."""
    try:
        from rich.console import Console
        from rich.text import Text
        console = Console()
        t = Text(text)
        if style:
            t.stylize(style)
        console.print(t)
    except ImportError:
        print(text)


def _cmd_search(args) -> int:
    ls = LetsFS(
        amadeus_key=getattr(args, "amadeus_key", None),
        amadeus_secret=getattr(args, "amadeus_secret", None),
    )
    try:
        res = ls.search(
            location=args.location,
            checkin=args.checkin,
            checkout=args.checkout,
            adults=args.adults,
            rooms=args.rooms,
            limit=args.limit,
            currency=args.currency,
        )
    except LetsFSError as e:
        _maybe_rich_print(f"Error: {e}", style="bold red")
        return 1

    if args.json:
        _print_json(res.to_dict())
        return 0

    # Human-readable summary.
    _maybe_rich_print(
        f"Location: {res.location}", style="bold"
    )
    if res.resolved:
        print(
            f"  Resolved: {res.resolved.display_name} "
            f"({res.resolved.lat}, {res.resolved.lon})"
        )
    print(
        f"  Found {res.total} hotels; showing {res.returned}."
    )
    print(f"  Pricing: {res.pricing_source}")
    print(f"  {res.pricing_note}")
    print()
    if not res.hotels:
        _maybe_rich_print("No named hotels found.", style="yellow")
    for i, h in enumerate(res.hotels, 1):
        print(f"{i:>3}. {h.summary()}")
        extras = []
        if h.phone:
            extras.append(f"☎ {h.phone}")
        if h.website:
            extras.append(f"🌐 {h.website}")
        if h.email:
            extras.append(f"✉ {h.email}")
        if h.city:
            extras.append(f"🏙 {h.city}")
        if extras:
            print(f"     {' | '.join(extras)}")
        print(f"     osm_id={h.osm_id} osm_type={h.osm_type} lat={h.lat} lon={h.lon}")

    if res.amadeus_offers:
        print()
        _maybe_rich_print(
            f"Amadeus live offers ({len(res.amadeus_offers)}):",
            style="bold green",
        )
        for o in res.amadeus_offers:
            price_str = (
                f"{o.currency} {o.price_total:.2f}"
                if o.price_total is not None and o.currency
                else "(no price)"
            )
            print(
                f"  - {o.hotel_name or '(unnamed)'} | {price_str} "
                f"| {o.room_type or '?'} | {o.check_in}→{o.check_out}"
            )
    if res.amadeus_error:
        print()
        _maybe_rich_print(f"Amadeus: {res.amadeus_error}", style="yellow")
    return 0


def _cmd_location(args) -> int:
    ls = LetsFS()
    try:
        loc = ls.resolve_location(args.query)
    except LetsFSError as e:
        _maybe_rich_print(f"Error: {e}", style="bold red")
        return 1
    if args.json:
        _print_json(
            {
                "query": args.query,
                "display_name": loc.display_name,
                "lat": loc.lat,
                "lon": loc.lon,
                "boundingbox": loc.boundingbox,
                "type": loc.type,
                "overpass_bbox": loc.overpass_bbox,
            }
        )
        return 0
    _maybe_rich_print(loc.display_name, style="bold")
    print(f"  lat={loc.lat} lon={loc.lon} type={loc.type or '-'}")
    print(f"  boundingbox (Nominatim: south,north,west,east): {loc.boundingbox}")
    print(f"  overpass_bbox (south,west,north,east): {loc.overpass_bbox}")
    return 0


def _cmd_hotel(args) -> int:
    ls = LetsFS()
    try:
        details = ls.get_hotel_details(args.osm_id, args.osm_type)
    except LetsFSError as e:
        _maybe_rich_print(f"Error: {e}", style="bold red")
        return 1
    if args.json:
        _print_json(details.to_dict())
        return 0
    _maybe_rich_print(details.name or "(unnamed hotel)", style="bold")
    print(f"  osm_id={details.osm_id} osm_type={details.osm_type}")
    print(f"  lat={details.lat} lon={details.lon}")
    if details.stars:
        print(f"  stars: {details.stars}")
    if details.address:
        print(f"  address: {details.address}")
    if details.phone:
        print(f"  phone: {details.phone}")
    if details.website:
        print(f"  website: {details.website}")
    print()
    _maybe_rich_print("Tags:", style="bold")
    for k in sorted(details.tags.keys()):
        print(f"  {k} = {details.tags[k]}")
    return 0


def _cmd_config(args) -> int:
    ls = LetsFS()
    cfg = ls.config
    if args.json:
        _print_json(cfg.to_dict())
        return 0
    _maybe_rich_print("letsFS configuration", style="bold")
    for k, v in cfg.to_dict().items():
        print(f"  {k}: {v}")
    return 0


def _cmd_version(args) -> int:
    print(f"letsfs {__version__}")
    return 0


# ── argparse fallback ─────────────────────────────────────────────────────

def _build_argparse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="letsfs",
        description=(
            "letsFS — Hotel search for AI agents. "
            "Free OSM discovery (Nominatim + Overpass). "
            "Optional Amadeus live pricing."
        ),
    )
    p.add_argument(
        "--version", action="store_true", help="Print version and exit."
    )
    p.add_argument(
        "-V", "--verbose", action="store_true", help="Verbose output."
    )
    sub = p.add_subparsers(dest="command", metavar="<command>")

    # search
    sp = sub.add_parser("search", help="Search hotels in a location.")
    sp.add_argument("location", help="City name or IATA city code (e.g. PAR).")
    sp.add_argument("--checkin", default=None, help="YYYY-MM-DD (Amadeus pricing).")
    sp.add_argument("--checkout", default=None, help="YYYY-MM-DD (Amadeus pricing).")
    sp.add_argument("--adults", type=int, default=1, help="Number of adults (default 1).")
    sp.add_argument("--rooms", type=int, default=1, help="Number of rooms (default 1).")
    sp.add_argument("--limit", type=int, default=20, help="Max hotels (default 20).")
    sp.add_argument("--currency", default="EUR", help="Currency code (default EUR).")
    sp.add_argument(
        "--amadeus-key", dest="amadeus_key", default=None,
        help="Amadeus API key (overrides env/config).",
    )
    sp.add_argument(
        "--amadeus-secret", dest="amadeus_secret", default=None,
        help="Amadeus API secret (overrides env/config).",
    )
    sp.add_argument("--json", action="store_true", help="Emit JSON.")
    sp.set_defaults(func=_cmd_search)

    # location
    sp = sub.add_parser("location", help="Geocode a city/place name (Nominatim).")
    sp.add_argument("query", help="City or place name.")
    sp.add_argument("--json", action="store_true", help="Emit JSON.")
    sp.set_defaults(func=_cmd_location)

    # hotel
    sp = sub.add_parser("hotel", help="Get full OSM tags for a single hotel.")
    sp.add_argument("osm_id", help="Numeric OSM element ID.")
    sp.add_argument("osm_type", help="OSM element type: node, way, or relation.")
    sp.add_argument("--json", action="store_true", help="Emit JSON.")
    sp.set_defaults(func=_cmd_hotel)

    # config
    sp = sub.add_parser("config", help="Show resolved configuration.")
    sp.add_argument("--json", action="store_true", help="Emit JSON.")
    sp.set_defaults(func=_cmd_config)

    return p


def _run_argparse(argv: Optional[list[str]] = None) -> int:
    parser = _build_argparse()
    args = parser.parse_args(argv)
    if args.version:
        return _cmd_version(args)
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


# ── typer entry (preferred when installed) ────────────────────────────────

def _try_typer_main(argv: Optional[list[str]] = None) -> Optional[int]:
    """Run the typer CLI if typer is installed; else return ``None``."""
    try:
        import typer  # type: ignore
    except ImportError:
        return None

    app = typer.Typer(
        name="letsfs",
        add_completion=False,
        no_args_is_help=True,
        help="letsFS — Hotel search for AI agents.",
    )

    @app.command()
    def search(
        location: str = typer.Argument(..., help="City name or IATA city code (e.g. PAR)."),
        checkin: Optional[str] = typer.Option(None, help="YYYY-MM-DD (Amadeus pricing)."),
        checkout: Optional[str] = typer.Option(None, help="YYYY-MM-DD (Amadeus pricing)."),
        adults: int = typer.Option(1, help="Number of adults."),
        rooms: int = typer.Option(1, help="Number of rooms."),
        limit: int = typer.Option(20, help="Max hotels to return."),
        currency: str = typer.Option("EUR", help="Currency code (default EUR)."),
        amadeus_key: Optional[str] = typer.Option(None, help="Amadeus API key (overrides env)."),
        amadeus_secret: Optional[str] = typer.Option(None, help="Amadeus API secret (overrides env)."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        """Search hotels in a location (free OSM discovery; optional Amadeus pricing)."""
        # Reuse the argparse handler via a namespace object.
        ns = argparse.Namespace(
            location=location, checkin=checkin, checkout=checkout,
            adults=adults, rooms=rooms, limit=limit, currency=currency,
            amadeus_key=amadeus_key, amadeus_secret=amadeus_secret,
            json=json_output,
        )
        rc = _cmd_search(ns)
        if rc != 0:
            raise typer.Exit(code=rc)

    @app.command()
    def location(
        query: str = typer.Argument(..., help="City or place name."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        """Geocode a city/place name to lat/lon + bounding box (Nominatim)."""
        ns = argparse.Namespace(query=query, json=json_output)
        rc = _cmd_location(ns)
        if rc != 0:
            raise typer.Exit(code=rc)

    @app.command()
    def hotel(
        osm_id: str = typer.Argument(..., help="Numeric OSM element ID."),
        osm_type: str = typer.Argument(..., help="node, way, or relation."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        """Get the complete OSM tag set for a single hotel."""
        ns = argparse.Namespace(osm_id=osm_id, osm_type=osm_type, json=json_output)
        rc = _cmd_hotel(ns)
        if rc != 0:
            raise typer.Exit(code=rc)

    @app.command()
    def config(
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        """Show resolved configuration (env vars, config file, defaults)."""
        ns = argparse.Namespace(json=json_output)
        rc = _cmd_config(ns)
        if rc != 0:
            raise typer.Exit(code=rc)

    @app.callback(invoke_without_command=True)
    def _root(
        ctx: typer.Context,
        version: bool = typer.Option(False, "--version", help="Print version and exit."),
    ) -> None:
        if version:
            print(f"letsfs {__version__}")
            raise typer.Exit()
        if ctx.invoked_subcommand is None:
            print(ctx.get_help())
            raise typer.Exit()

    try:
        # typer's main() reads sys.argv itself; pass `args` to override.
        app(args=argv, standalone_mode=False)
        return 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
        return code


# ── Public entry point ────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Returns a process exit code.

    Tries typer first (rich UI); falls back to argparse (stdlib) when the
    optional ``cli`` extras are not installed.
    """
    rc = _try_typer_main(argv)
    if rc is not None:
        return rc
    return _run_argparse(argv)


if __name__ == "__main__":
    sys.exit(main())
