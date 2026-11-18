"""Bazar Historias query commands."""

from __future__ import annotations

import itertools
import sys
import threading
import time
import traceback
from contextlib import contextmanager

import click
import requests

from .client import BazarClient
from .output import show


def _set_mode(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if value:
        ctx.find_root().ensure_object(dict)[param.name] = True


def output_options(function):
    for flag, help_text in reversed((
        ("--json", "Show data as JSON."),
        ("--quiet", "Output JSON without progress messages."),
        ("--verbose", "Show tracebacks for errors."),
    )):
        function = click.option(flag, is_flag=True, expose_value=False, callback=_set_mode, help=help_text)(function)
    return function


@contextmanager
def _spinner(enabled: bool):
    stop = threading.Event()
    def animate():
        for frame in itertools.cycle("|/-\\"):
            click.echo(f"\r{frame} Working...", nl=False, err=True)
            if stop.wait(0.1):
                break
    worker = threading.Thread(target=animate, daemon=True) if enabled else None
    if worker:
        worker.start()
    try:
        yield
    finally:
        if worker:
            stop.set()
            worker.join()
            click.echo("\r            \r", nl=False, err=True)


class CommandError(click.ClickException):
    def show(self, file=None):
        click.echo(f"✖ {self.format_message()}", file=file, err=file is None)


OPERATIONS = {
    "login": ("Signing in to Bazar Historias", "Signed in"),
    "status": ("Checking the session", "Session checked"),
    "logout": ("Removing the local session", "Local session removed"),
    "account": ("Fetching account details", "Account details retrieved"),
    "orders": ("Fetching orders", "Orders retrieved"),
    "spend": ("Totaling spend by month", "Spend totaled"),
    "order": ("Fetching order details", "Order details retrieved"),
    "bazarcoins": ("Fetching BazarCoins", "BazarCoins retrieved"),
    "addresses": ("Fetching addresses", "Addresses retrieved"),
    "wishlist": ("Fetching wishlist", "Wishlist retrieved"),
    "search": ("Fetching catalog results", "Catalog results retrieved"),
}


def _call(ctx: click.Context, method: str, *args: object) -> None:
    options = ctx.find_root().obj or {}
    json_mode = bool(options.get("json") or options.get("quiet") or not sys.stdout.isatty())
    log_status = not (options.get("json") or options.get("quiet"))
    action, completed = OPERATIONS[method]
    started = time.monotonic()
    try:
        if log_status:
            click.echo(f"ℹ {action}...", err=True)
        with _spinner(log_status and not json_mode and sys.stderr.isatty() and method != "logout"):
            result = getattr(BazarClient(), method)(*args)
        if log_status:
            count = len(result) if method == "orders" and isinstance(result, list) else None
            if method == "search" and isinstance(result, dict) and isinstance(result.get("products"), list):
                count = len(result["products"])
            detail = f": {count} {'order' if method == 'orders' and count == 1 else 'orders' if method == 'orders' else 'item' if count == 1 else 'items'}" if count is not None else ""
            click.echo(f"✔ {completed}{detail} ({time.monotonic() - started:.1f}s)", err=True)
        show(result, json_mode=json_mode, quiet=bool(options.get("quiet")))
    except Exception as exc:
        if options.get("verbose"):
            traceback.print_exc(file=sys.stderr)
        message = "Unable to reach Bazar Historias. Check your connection and try again." if isinstance(exc, requests.RequestException) else str(exc) or "Command failed. Try again."
        raise CommandError(message) from exc


@click.group()
@output_options
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Query your Bazar Historias account and catalog.

    \b
    Command reference:
      bazar auth login              Sign in
      bazar auth status             Check the session
      bazar auth logout             Remove the local session
      bazar account                 Show account details
      bazar orders                  List and filter orders
      bazar orders show ORDER_ID    Show an order
      bazar spend                   Total spend by purchase month
      bazar bazarcoins              Show balance and activity
      bazar addresses               Show saved addresses
      bazar wishlist                Show the wishlist
      bazar search QUERY            Search English-language titles

    Run 'bazar COMMAND --help' for options and examples. Piped output is JSON.
    """
    ctx.ensure_object(dict)


@cli.group()
@output_options
def auth() -> None:
    """Manage the local session.

    \b
    Examples:
      bazar auth login
      bazar auth status
      bazar auth logout
    """


@auth.command("login")
@output_options
@click.pass_context
def login(ctx: click.Context) -> None:
    """Log in."""
    _call(ctx, "login")


@auth.command("status")
@output_options
@click.pass_context
def status(ctx: click.Context) -> None:
    """Check the session."""
    _call(ctx, "status")


@auth.command("logout")
@output_options
@click.pass_context
def logout(ctx: click.Context) -> None:
    """Remove the local session."""
    _call(ctx, "logout")


@cli.group(invoke_without_command=True)
@click.option("--from", "date_from", type=click.DateTime(formats=["%Y-%m-%d"]), help="Include orders on or after YYYY-MM-DD.")
@click.option("--to", "date_to", type=click.DateTime(formats=["%Y-%m-%d"]), help="Include orders on or before YYYY-MM-DD.")
@click.option("--status", help="Match part of the English order status, ignoring case.")
@click.option("--realized", is_flag=True, help="Exclude cancelled orders.")
@output_options
@click.pass_context
def orders(ctx: click.Context, date_from, date_to, status, realized) -> None:
    """List orders and filter by date or status.

    \b
    Examples:
      bazar orders
      bazar orders --realized
      bazar orders --status completed
      bazar orders --from 2026-01-01 --to 2026-12-31
      bazar orders show 12345
    """
    if realized and status is not None:
        raise click.UsageError("Use --realized or --status, not both.")
    if ctx.invoked_subcommand is None:
        _call(ctx, "orders", date_from.date() if date_from else None, date_to.date() if date_to else None, status, realized)
    elif date_from or date_to or status is not None or realized:
        raise click.UsageError("Order filters apply to the order list, not subcommands.")


@orders.command("show")
@click.argument("order_id")
@output_options
@click.pass_context
def order(ctx: click.Context, order_id: str) -> None:
    """Show order details."""
    _call(ctx, "order", order_id)


@cli.command()
@click.option("--from", "date_from", type=click.DateTime(formats=["%Y-%m-%d"]), help="Include orders on or after YYYY-MM-DD.")
@click.option("--to", "date_to", type=click.DateTime(formats=["%Y-%m-%d"]), help="Include orders on or before YYYY-MM-DD.")
@click.option("--realized", is_flag=True, help="Count only completed purchases (Completed or Paid).")
@output_options
@click.pass_context
def spend(ctx: click.Context, date_from, date_to, realized) -> None:
    """Total spend grouped by YYYY-MM purchase month (excludes cancelled).

    \b
    Examples:
      bazar spend
      bazar spend --realized
      bazar spend --from 2026-01-01 --to 2026-12-31
    """
    _call(ctx, "spend", date_from.date() if date_from else None, date_to.date() if date_to else None, realized)


@cli.command()
@output_options
@click.pass_context
def account(ctx: click.Context) -> None:
    """Show account information."""
    _call(ctx, "account")


@cli.command()
@output_options
@click.pass_context
def bazarcoins(ctx: click.Context) -> None:
    """Show BazarCoins."""
    _call(ctx, "bazarcoins")


@cli.command()
@output_options
@click.pass_context
def addresses(ctx: click.Context) -> None:
    """Show addresses."""
    _call(ctx, "addresses")


@cli.command()
@output_options
@click.pass_context
def wishlist(ctx: click.Context) -> None:
    """Show wishlist."""
    _call(ctx, "wishlist")


@cli.command()
@click.argument("query")
@click.option("--availability", type=click.Choice(["all", "stock", "on-request", "preorder", "unavailable"]), default="all", show_default=True, help="Filter by availability.")
@click.option("--page", type=click.IntRange(min=1), help="Show a single page (default page size: 20).")
@click.option("--per-page", type=click.IntRange(1, 50), help="Show a single page with this many items (default page: 1).")
@click.option("--sort", type=click.Choice(["relevance", "newest", "oldest"]), default="relevance", show_default=True, help="Sort by date added to the catalog.")
@click.option("--with-sku", is_flag=True, help="Add each result's SKU by fetching its product page (slower).")
@output_options
@click.pass_context
def search(ctx: click.Context, query: str, availability: str, page: int | None, per_page: int | None, sort: str, with_sku: bool) -> None:
    """Search all English-language titles and editions.

    \b
    Examples:
      bazar search "Absolute Batman"
      bazar search "Batman hardcover" --availability preorder
      bazar search "Batman" --page 2 --per-page 20
      bazar search "Batman" --sort newest --json

    Searches return all pages by default. HC and hardcover searches include
    the site's equivalent term and do not support date sorting.
    """
    _call(ctx, "search", query, availability, page, per_page, sort, with_sku)
