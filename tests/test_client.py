import pytest
from datetime import date
from bs4 import BeautifulSoup

from bazar.client import BazarClient, table_rows


def test_table_rows_handles_headers_and_empty_table():
    html = "<table><thead><tr><th>Order</th><th>Total</th></tr></thead><tbody><tr><td>42</td><td>S/ 10</td></tr></tbody></table>"
    assert table_rows(BeautifulSoup(html, "html.parser").table) == [{"Order": "42", "Total": "S/ 10"}]
    assert table_rows(None) == []


def test_order_rejects_invalid_identifier():
    with pytest.raises(ValueError):
        BazarClient().order("../orders")


def test_expired_session_is_not_treated_as_empty(monkeypatch):
    client = BazarClient()
    monkeypatch.setattr(client, "_get", lambda *args, **kwargs: BeautifulSoup('<form class="woocommerce-form-login"></form>', "html.parser"))
    with pytest.raises(RuntimeError, match="Session is not active"):
        client.orders()


def test_cyclic_pagination_is_rejected(monkeypatch):
    client = BazarClient()
    page = BeautifulSoup('<table class="woocommerce-orders-table"></table><a class="woocommerce-button--next" href="/my-account-2/orders/">Next</a>', "html.parser")
    monkeypatch.setattr(client, "_page", lambda path: page)
    with pytest.raises(RuntimeError, match="cycle"):
        client.orders()


def test_order_filters_use_iso_dates_and_status_across_pages(monkeypatch):
    client = BazarClient()
    def page(rows, next_page=""):
        body = "".join(
            f'<tr><th>{number}</th><td class="woocommerce-orders-table__cell-order-date"><time datetime="{day}T10:00:00-05:00">{day}</time></td><td class="woocommerce-orders-table__cell-order-status">{status}</td></tr>'
            for number, day, status in rows
        )
        return BeautifulSoup(f'<table class="woocommerce-orders-table"><thead><tr><th>Order</th><th>Date</th><th>Status</th></tr></thead><tbody>{body}</tbody></table>{next_page}', "html.parser")

    pages = {
        "orders/": page([("1", "2026-01-01", "En proceso"), ("2", "2026-01-02", "Completado")], '<a class="woocommerce-button--next" href="/my-account-2/orders/page/2/">Next</a>'),
        "https://bazarhistorias.pe/my-account-2/orders/page/2/": page([("3", "2026-01-03", "EN PROCESO"), ("4", "2026-01-04", "En proceso")]),
    }
    monkeypatch.setattr(client, "_page", pages.__getitem__)
    assert [row["Order"] for row in client.orders(date(2026, 1, 1), date(2026, 1, 3), "proceso")] == ["1", "3"]
    assert len(client.orders()) == 4
    with pytest.raises(ValueError, match="Start date"):
        client.orders(date(2026, 2, 1), date(2026, 1, 1))


def test_order_filter_rejects_missing_date(monkeypatch):
    client = BazarClient()
    page = BeautifulSoup('<table class="woocommerce-orders-table"><tbody><tr><td>Order</td></tr></tbody></table>', "html.parser")
    monkeypatch.setattr(client, "_page", lambda path: page)
    with pytest.raises(RuntimeError, match="missing or invalid date"):
        client.orders(date_from=date(2026, 1, 1))


def test_order_status_uses_current_status_not_tracking_history(monkeypatch):
    client = BazarClient()
    page = BeautifulSoup('''<table class="woocommerce-orders-table"><thead><tr><th>Pedido</th><th>Estado</th></tr></thead>
        <tbody><tr><th>#123</th><td class="woocommerce-orders-table__cell-order-status">
        <span class="bh-order-tracking__table-fallback">Solicitado parcial</span>
        <section><h3 class="bh-order-tracking__status">Solicitado parcial</h3><p>Completado Enviado</p>
        <div class="bh-order-tracking__step" aria-current="step"><span class="bh-order-tracking__label">Pagado</span></div></section>
        </td></tr></tbody></table>''', "html.parser")
    monkeypatch.setattr(client, "_page", lambda path: page)
    assert client.orders()[0]["Estado"] == "Solicitado parcial"
    assert client.orders()[0]["Seguimiento"] == "Pagado"
    assert len(client.orders(status="solicitado")) == 1
    assert len(client.orders(status="PARTIALLY REQUESTED")) == 1
    assert client.orders(status="completado") == []
    assert client.orders(status="completed") == []


def test_cancelled_order_without_current_tracking_is_unknown(monkeypatch):
    client = BazarClient()
    page = BeautifulSoup('''<table class="woocommerce-orders-table"><thead><tr><th>Pedido</th><th>Estado</th></tr></thead>
        <tbody><tr><th>#123</th><td class="woocommerce-orders-table__cell-order-status">
        <span class="bh-order-tracking__table-fallback">Cancelado</span>
        <div class="bh-order-tracking__step"><span class="bh-order-tracking__label">Pagado</span></div>
        </td></tr></tbody></table>''', "html.parser")
    monkeypatch.setattr(client, "_page", lambda path: page)
    assert client.orders()[0]["Seguimiento"] is None
    assert len(client.orders(status="cancelled")) == 1
    assert len(client.orders(status="canceled")) == 1


def test_search_filters_english_without_restricting_type_and_applies_options(monkeypatch):
    client = BazarClient()
    sent = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"hits": [], "estimatedTotalHits": 0}

    def post(url, *, json, timeout):
        sent.update(json)
        return Response()

    monkeypatch.setattr(client.session, "post", post)
    result = client.search("absolute batman", "on-request", 2, 12, "newest")
    assert '(language = "Inglés")' in sent["filter"]
    assert 'type =' not in sent["filter"]
    assert all(value in sent["filter"] for value in ("on_request", "preorder", "on_request_confirm"))
    assert sent["offset"] == 12 and sent["limit"] == 12
    assert sent["sort"] == ["date_created:desc"]
    assert result["products"] == []


def test_search_rejects_invalid_options_without_request(monkeypatch):
    client = BazarClient()
    monkeypatch.setattr(client.session, "post", lambda *args, **kwargs: pytest.fail("Should not call the site"))
    with pytest.raises(ValueError):
        client.search("Batman", "other")
    with pytest.raises(ValueError):
        client.search("Batman", page=0)


def test_hc_search_combines_variants_deduplicates_and_paginates(monkeypatch):
    client = BazarClient()
    queries = []
    results = {
        "Batman HC": [{"id": 1}, {"id": 2}],
        "Batman Tapa Dura": [{"id": 1}, {"id": 3}],
    }

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            items = results[self.payload["q"]]
            start = self.payload["offset"]
            return {"hits": items[start:start + self.payload["limit"]], "estimatedTotalHits": len(items)}

    def post(url, *, json, timeout):
        queries.append(json["q"])
        return Response(json)

    monkeypatch.setattr(client.session, "post", post)
    first = client.search("Batman HC", per_page=2)
    second = client.search("Batman HC", page=2, per_page=2)
    assert [item["id"] for item in first["products"]] == [1, 2]
    assert [item["id"] for item in second["products"]] == [3]
    assert first["total"] is None
    assert set(queries) == set(results)
    all_results = client.search("Batman HC")
    assert [item["id"] for item in all_results["products"]] == [1, 2, 3]
    assert all_results["total"] == 3 and all_results["page"] is None
    with pytest.raises(ValueError, match="Date sorting"):
        client.search("Batman HC", order="newest")


def test_hardcover_search_includes_hc_and_translated_variant(monkeypatch):
    client = BazarClient()
    queries = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            items = [{"id": 1}] if self.payload["q"] != "Batman hardcover" else []
            return {"hits": items[self.payload["offset"]:], "estimatedTotalHits": len(items)}

    def post(url, *, json, timeout):
        queries.append(json["q"])
        return Response(json)

    monkeypatch.setattr(client.session, "post", post)
    assert len(client.search("Batman hardcover")["products"]) == 1
    assert set(queries) == {"Batman hardcover", "Batman HC", "Batman Tapa Dura"}


def test_search_fetches_all_pages_even_when_total_is_underestimated(monkeypatch):
    client = BazarClient()
    offsets = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            offset = self.payload["offset"]
            return {"hits": [{"id": i} for i in range(offset, min(offset + 200, 250))], "estimatedTotalHits": 200}

    def post(url, *, json, timeout):
        offsets.append(json["offset"])
        return Response(json)

    monkeypatch.setattr(client.session, "post", post)
    result = client.search("Batman")
    assert offsets == [0, 200, 250]
    assert len(result["products"]) == result["total"] == 250
    assert result["page"] is None


def test_product_sku_reads_span_and_skips_off_domain(monkeypatch):
    client = BazarClient()
    pages = {
        "https://bazarhistorias.pe/product/a/": '<span class="sku">76194138584602241</span>',
        "https://bazarhistorias.pe/product/b/": "<div>no code here</div>",
    }
    monkeypatch.setattr(client, "_get", lambda url: BeautifulSoup(pages[url], "html.parser"))
    assert client.product_sku("https://bazarhistorias.pe/product/a/") == "76194138584602241"
    assert client.product_sku("https://bazarhistorias.pe/product/b/") is None
    # off-domain and empty urls must not trigger a fetch (pages lookup would KeyError)
    assert client.product_sku("https://evil.example/product/a/") is None
    assert client.product_sku(None) is None


def test_search_with_sku_from_thumbnail_and_falls_back_to_page(monkeypatch):
    client = BazarClient()
    hits = [
        # the barcode is embedded in the thumbnail URL → no product page request
        {"id": 1, "title": "A", "url": "https://bazarhistorias.pe/product/a/",
         "thumbnail": "https://cdn.bazarhistorias.cl/cover/76194138584602241_w400"},
        # no barcode in the thumbnail → falls back to the product page's span.sku
        {"id": 2, "title": "B", "url": "https://bazarhistorias.pe/product/b/"},
    ]

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            offset = self.payload["offset"]
            return {"hits": hits[offset:], "estimatedTotalHits": len(hits)}

    monkeypatch.setattr(client.session, "post", lambda url, *, json, timeout: Response(json))
    fetched = []

    def fake_product_sku(url):
        fetched.append(url)
        return {"https://bazarhistorias.pe/product/b/": "75960621451800131"}.get(url)

    monkeypatch.setattr(client, "product_sku", fake_product_sku)
    enriched = client.search("Batman", with_sku=True)["products"]
    assert [product["sku"] for product in enriched] == ["76194138584602241", "75960621451800131"]
    assert fetched == ["https://bazarhistorias.pe/product/b/"]  # only B hit the page; A came from its thumbnail
    assert all("sku" not in product for product in client.search("Batman")["products"])


def test_search_fails_when_site_repeats_page(monkeypatch):
    client = BazarClient()

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"hits": [{"id": 1}], "estimatedTotalHits": 2}

    monkeypatch.setattr(client.session, "post", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="repeated a page"):
        client.search("Batman")
