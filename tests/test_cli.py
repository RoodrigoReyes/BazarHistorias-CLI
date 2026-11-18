import json

from click.testing import CliRunner
import requests

from bazar import cli


class FakeClient:
    def orders(self, date_from=None, date_to=None, status=None, realized=False):
        return [{"id": "123", "status": "completed"}]

    def spend(self, date_from=None, date_to=None, realized=False):
        return [{"Month": "2026-01", "Orders": 1, "Total": "S/ 54.10"}]

    def order(self, order_id):
        return {"id": order_id}

    def search(self, query, availability, page, per_page, order, with_sku=False):
        return [{"title": query, "filter": availability, "page": page, "limit": per_page, "order": order}]

    def wishlist(self):
        return []

    def account(self):
        raise ValueError("Session expired")


def test_help_maps_commands_and_examples():
    runner = CliRunner()
    root = runner.invoke(cli.cli, ["--help"])
    assert root.exit_code == 0
    for command in ("auth login", "auth status", "auth logout", "orders show", "search QUERY", "bazarcoins", "addresses", "wishlist"):
        assert command in root.stdout
    assert "--status completed" in runner.invoke(cli.cli, ["orders", "--help"]).stdout
    assert "--availability preorder" in runner.invoke(cli.cli, ["search", "--help"]).stdout


def test_orders_json_before_or_after_command(monkeypatch):
    monkeypatch.setattr(cli, "BazarClient", FakeClient)
    runner = CliRunner()
    for args in (["--json", "orders"], ["orders", "--json"]):
        result = runner.invoke(cli.cli, args)
        assert result.exit_code == 0
        assert json.loads(result.output) == [{"id": "123", "status": "completed"}]


def test_order_and_search_forward_arguments(monkeypatch):
    monkeypatch.setattr(cli, "BazarClient", FakeClient)
    runner = CliRunner()
    order = runner.invoke(cli.cli, ["orders", "show", "42", "--json"])
    search = runner.invoke(cli.cli, ["search", "Batman", "--availability", "preorder", "--page", "2", "--per-page", "12", "--sort", "newest", "--json"])
    assert json.loads(order.output) == {"id": "42"}
    assert json.loads(search.output) == [{"title": "Batman", "filter": "preorder", "page": 2, "limit": 12, "order": "newest"}]
    all_results = runner.invoke(cli.cli, ["search", "Batman", "--json"])
    assert json.loads(all_results.stdout)[0]["page"] is None


def test_empty_and_client_error(monkeypatch):
    monkeypatch.setattr(cli, "BazarClient", FakeClient)
    runner = CliRunner()
    assert json.loads(runner.invoke(cli.cli, ["wishlist"]).stdout) == []
    error = runner.invoke(cli.cli, ["account"])
    assert error.exit_code == 1
    assert error.stdout == ""
    assert "Session expired" in error.stderr
    assert "Traceback" not in error.stderr


def test_pipe_quiet_and_verbose(monkeypatch):
    monkeypatch.setattr(cli, "BazarClient", FakeClient)
    runner = CliRunner()
    for args in (["--quiet", "orders"], ["orders", "--quiet"], ["orders", "--json"]):
        result = runner.invoke(cli.cli, args)
        assert result.exit_code == 0
        assert json.loads(result.stdout) == [{"id": "123", "status": "completed"}]
        assert result.stderr == ""
    piped = runner.invoke(cli.cli, ["orders"])
    assert json.loads(piped.stdout) == [{"id": "123", "status": "completed"}]
    assert "ℹ Fetching orders..." in piped.stderr
    assert "✔ Orders retrieved: 1 order" in piped.stderr
    error = runner.invoke(cli.cli, ["account", "--verbose"])
    assert error.exit_code == 1
    assert error.stdout == ""
    assert "Traceback" in error.stderr and "Session expired" in error.stderr


def test_network_errors_are_short_and_on_stderr(monkeypatch):
    class NetworkFailure:
        def orders(self, *args):
            raise requests.ConnectionError("connection details")

    monkeypatch.setattr(cli, "BazarClient", NetworkFailure)
    result = CliRunner().invoke(cli.cli, ["orders", "--json"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Check your connection" in result.stderr
    assert "connection details" not in result.stderr


def test_failure_has_no_success_message(monkeypatch):
    monkeypatch.setattr(cli, "BazarClient", FakeClient)
    result = CliRunner().invoke(cli.cli, ["account"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "ℹ Fetching account details..." in result.stderr
    assert "✖ Session expired" in result.stderr
    assert "✔" not in result.stderr


def test_orders_reject_invalid_filter_arguments(monkeypatch):
    monkeypatch.setattr(cli, "BazarClient", FakeClient)
    runner = CliRunner()
    assert runner.invoke(cli.cli, ["orders", "--from", "invalid"]).exit_code != 0
    assert runner.invoke(cli.cli, ["orders", "--from", "2026-01-01", "show", "42"]).exit_code != 0
