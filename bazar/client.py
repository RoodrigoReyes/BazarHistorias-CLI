"""Read account information from Bazar Historias."""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from itertools import zip_longest
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import credentials
from .status import ORDER_STATUSES

BASE = "https://bazarhistorias.pe/"
ACCOUNT = urljoin(BASE, "my-account-2/")


def clean(node):
    return node.get_text(" ", strip=True) if node else ""


def order_date_of(element):
    time = element.select_one(".woocommerce-orders-table__cell-order-date time[datetime]")
    try:
        return date.fromisoformat(time["datetime"][:10])
    except (TypeError, ValueError, KeyError):
        raise RuntimeError("An order has a missing or invalid date; cannot filter orders.") from None


def order_total(text):
    # Site totals are European (e.g. "S/ 173,89 para 5 elementos"); match output.format_money.
    match = re.search(r"S/\s*((?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{2})?)", text)
    return Decimal(match.group(1).replace(".", "").replace(",", ".")) if match else None


def order_status(cell):
    if cell is None:
        return ""
    current = cell.select_one(".bh-order-tracking__table-fallback, h3.bh-order-tracking__status")
    return clean(current or cell)


def table_rows(table):
    if not table:
        return []
    headers = [clean(cell) for cell in table.select("thead th")]
    result = []
    for row in table.select("tbody tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        result.append({(headers[i] if i < len(headers) and headers[i] else str(i + 1)): clean(cell)
                       for i, cell in enumerate(cells)})
    return result


class BazarClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        for cookie in credentials.load_cookies():
            if isinstance(cookie, dict) and cookie.get("domain", "").lstrip(".") == "bazarhistorias.pe":
                self.session.cookies.set(cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie.get("path", "/"))

    def _get(self, url, **kwargs):
        response = self.session.get(url, timeout=30, **kwargs)
        response.raise_for_status()
        if urlparse(response.url).hostname != "bazarhistorias.pe":
            raise RuntimeError("The site redirected to an unexpected domain.")
        return BeautifulSoup(response.text, "html.parser")

    def _page(self, path=""):
        soup = self._get(urljoin(ACCOUNT, path))
        if soup.select_one("form.woocommerce-form-login") or not soup.select_one(".woocommerce-MyAccount-navigation"):
            raise RuntimeError("Session is not active. Run bazar auth login.")
        content = soup.select_one(".woocommerce-MyAccount-content")
        if not content:
            raise RuntimeError("Account content not found. The site may have changed.")
        return content

    def login(self):
        email, password = credentials.read_credentials()
        self.session.cookies.clear()
        page = self._get(ACCOUNT)
        form = page.select_one("form.woocommerce-form-login")
        nonce = form.select_one('[name="woocommerce-login-nonce"]') if form else None
        if not nonce or not nonce.get("value"):
            raise RuntimeError("Login form not found.")
        response = self.session.post(ACCOUNT, data={"username": email, "password": password,
            "woocommerce-login-nonce": nonce["value"], "_wp_http_referer": "/my-account-2/", "login": "Acceder"}, timeout=30, allow_redirects=False)
        response.raise_for_status()
        if response.is_redirect:
            target = urljoin(ACCOUNT, response.headers["Location"])
            parsed = urlparse(target)
            if response.status_code not in (301, 302, 303) or parsed.scheme != "https" or parsed.hostname != "bazarhistorias.pe":
                raise RuntimeError("The site redirected to an unexpected destination.")
            soup = self._get(target)
        else:
            soup = BeautifulSoup(response.text, "html.parser")
        if soup.select_one("form.woocommerce-form-login") or not soup.select_one(".woocommerce-MyAccount-navigation"):
            raise RuntimeError("Login failed. Check your credentials and site access.")
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path} for c in self.session.cookies
                   if c.domain.lstrip(".") == "bazarhistorias.pe"]
        credentials.save_cookies(cookies)
        return {"session": "active"}

    def status(self):
        self._page()
        return {"session": "active"}

    def logout(self):
        credentials.SESSION_FILE.unlink(missing_ok=True)
        self.session.cookies.clear()
        return {"session": "removed locally"}

    def account(self):
        return {"account": clean(self._page())}

    def _order_pages(self):
        path = "orders/"
        visited = set()
        while path:
            url = urljoin(ACCOUNT, path)
            if url in visited:
                raise RuntimeError("Order pagination contains a cycle.")
            visited.add(url)
            page = self._page(path)
            table = page.select_one(".woocommerce-orders-table")
            if table:
                parsed = table_rows(table)
                elements = [row for row in table.select("tbody tr") if row.find_all(["td", "th"], recursive=False)]
                yield from zip(elements, parsed)
            elif not page.select_one(".woocommerce-info"):
                raise RuntimeError("Order table not found. The site may have changed.")
            next_link = page.select_one("a.woocommerce-button--next[href]")
            if next_link:
                next_url = urljoin(url, next_link["href"])
                if urlparse(next_url).scheme != "https" or urlparse(next_url).hostname != "bazarhistorias.pe" or not urlparse(next_url).path.startswith("/my-account-2/orders/"):
                    raise RuntimeError("The orders page contains an unexpected link.")
                path = next_url
            else:
                path = None

    def orders(self, date_from=None, date_to=None, status=None, realized=False):
        if date_from and date_to and date_from > date_to:
            raise ValueError("Start date must not be after end date.")
        if status is not None and not status.strip():
            raise ValueError("Status must not be empty.")
        rows = []
        for element, order in self._order_pages():
            status_cell = element.select_one(".woocommerce-orders-table__cell-order-status")
            current_status = order_status(status_cell)
            if status_cell and "Estado" in order:
                order["Estado"] = current_status
                tracking = status_cell.select_one('.bh-order-tracking__step[aria-current="step"] .bh-order-tracking__label, .bh-order-tracking__step--current .bh-order-tracking__label')
                order["Seguimiento"] = clean(tracking) or None
            if (date_from or date_to):
                order_date = order_date_of(element)
                if (date_from and order_date < date_from) or (date_to and order_date > date_to):
                    continue
            if status or realized:
                if not current_status:
                    raise RuntimeError("An order has no status; cannot filter orders.")
                english = ORDER_STATUSES.get(current_status.casefold(), current_status).casefold()
            if realized and english == "cancelled":
                continue
            if status:
                query = status.strip().casefold()
                if query == "canceled":
                    query = "cancelled"
                if query not in english and query not in current_status.casefold():
                    continue
            rows.append(order)
        return rows

    def spend(self, date_from=None, date_to=None, realized=False):
        """Total spent per YYYY-MM purchase month; excludes cancelled orders."""
        if date_from and date_to and date_from > date_to:
            raise ValueError("Start date must not be after end date.")
        months = {}
        for element, order in self._order_pages():
            current_status = order_status(element.select_one(".woocommerce-orders-table__cell-order-status"))
            english = ORDER_STATUSES.get(current_status.casefold(), current_status).casefold()
            if english == "cancelled":
                continue
            if realized and english not in ("completed", "paid"):
                continue
            order_date = order_date_of(element)
            if (date_from and order_date < date_from) or (date_to and order_date > date_to):
                continue
            amount = order_total(order.get("Total", ""))
            if amount is None:
                continue
            count, total = months.get(order_date.strftime("%Y-%m"), (0, Decimal("0")))
            months[order_date.strftime("%Y-%m")] = (count + 1, total + amount)
        rows = [{"Month": key, "Orders": c, "Total": f"S/ {t:,.2f}"} for key, (c, t) in sorted(months.items())]
        if rows:
            grand = sum((t for _, t in months.values()), Decimal("0"))
            rows.append({"Month": "Total", "Orders": sum(c for c, _ in months.values()), "Total": f"S/ {grand:,.2f}"})
        return rows

    def order(self, order_id):
        if not str(order_id).isdigit():
            raise ValueError("Order number must contain only digits.")
        page = self._page(f"view-order/{order_id}/")
        table = page.select_one(".woocommerce-order-details table.order_details")
        if not table:
            raise RuntimeError("Order details not found.")
        return {"order": clean(page.select_one(".order-number")), "date": clean(page.select_one(".order-date")),
                "status": clean(page.select_one(".order-status")), "products": table_rows(table),
                "totals": [clean(row) for row in table.select("tfoot tr")]}

    def bazarcoins(self):
        page = self._page("bazarcoins/")
        balance = page.select_one(".bzc-wallet-card__value")
        if not balance:
            raise RuntimeError("BazarCoins balance not found. The site may have changed.")
        return {"balance": clean(balance), "transactions": table_rows(page.select_one(".bzc-movements-table"))}

    def addresses(self):
        standard = self._page("edit-address/")
        additional = self._page("mis-direcciones/")
        return {"primary": [clean(node) for node in standard.select(".woocommerce-Address")],
                "additional": [clean(node) for node in additional.select(".bh-pe-myaddr-card")]}

    def wishlist(self):
        page = self._page("wishlist/")
        items = page.select_one(".woosw-list")
        if not items:
            raise RuntimeError("Wishlist not found. The site may have changed.")
        return {"list": clean(items)}

    def product_sku(self, url):
        if not url or urlparse(url).scheme != "https" or urlparse(url).hostname != "bazarhistorias.pe":
            return None
        return clean(self._get(url).select_one("span.sku")) or None

    def search(self, query, availability="all", page=None, per_page=None, order="relevance", with_sku=False):
        if not query.strip() or len(query) > 200:
            raise ValueError("Search must contain 1 to 200 characters.")
        filters = {
            "all": None,
            "stock": '(fulfillment_mode = "physical_stock")',
            "on-request": '(fulfillment_mode = "on_request" OR fulfillment_mode = "preorder" OR fulfillment_mode = "on_request_confirm")',
            "preorder": '(fulfillment_mode = "preorder")',
            "unavailable": '(fulfillment_mode = "unavailable")',
        }
        sorts = {"relevance": None, "newest": "date_created:desc", "oldest": "date_created:asc"}
        if availability not in filters or order not in sorts or (page is not None and page < 1) or (per_page is not None and not 1 <= per_page <= 50):
            raise ValueError("Invalid filter or pagination.")
        paged = page is not None or per_page is not None
        if paged:
            page, per_page = page or 1, per_page or 20
        conditions = ['(language = "Inglés")']
        if filters[availability]:
            conditions.append(filters[availability])
        payload = {"q": query, "limit": per_page if paged else 200, "offset": (page - 1) * per_page if paged else 0,
                   "facets": [], "filter": " AND ".join(conditions)}
        if sorts[order]:
            payload["sort"] = [sorts[order]]
        def fetch(request):
            response = self.session.post(urljoin(BASE, "ms.php"), json=request, timeout=30)
            response.raise_for_status()
            try:
                data = response.json()
                if not isinstance(data["hits"], list) or not isinstance(data.get("estimatedTotalHits", data.get("totalHits")), (int, float)):
                    raise ValueError
            except (ValueError, KeyError, TypeError) as exc:
                raise RuntimeError("The site returned an unexpected search response.") from exc
            return data

        def collect(text, target=None):
            items, signatures = [], set()
            while target is None or len(items) < target:
                request = {**payload, "q": text, "offset": len(items), "limit": min(200, target - len(items)) if target is not None else 200}
                batch = fetch(request)["hits"]
                if not batch:
                    break
                signature = tuple((item.get("id"), item.get("url")) for item in batch)
                if all(identity == (None, None) for identity in signature):
                    raise RuntimeError("Search results lack product identifiers; cannot paginate safely.")
                if signature in signatures:
                    raise RuntimeError("The search site repeated a page; results may be incomplete.")
                signatures.add(signature)
                items.extend(batch)
            return items

        format_pattern = r'(?i)\b(?:hc|hardcover)\b'
        queries = list(dict.fromkeys((query, re.sub(format_pattern, 'HC', query), re.sub(format_pattern, 'Tapa Dura', query))))
        if len(queries) > 1:
            if any(len(text) > 200 for text in queries):
                raise ValueError("Search is too long after expanding HC.")
            if order != "relevance":
                raise ValueError("Date sorting is unavailable for combined HC searches.")
            lists = [collect(text, page * per_page if paged else None) for text in queries]
            hits, seen = [], set()
            for pair in zip_longest(*lists):
                for item in pair:
                    if item is not None:
                        key = item.get("id") or item.get("url")
                        if key is None or key not in seen:
                            hits.append(item)
                            if key is not None:
                                seen.add(key)
            if paged:
                hits = hits[(page - 1) * per_page:page * per_page]
            # shortcut: a single page cannot reveal the deduplicated total; fetch all pages for a total.
            total = None if paged else len(hits)
        else:
            if paged:
                data = fetch(payload)
                hits = data["hits"]
                total = data.get("estimatedTotalHits", data.get("totalHits"))
            else:
                hits = collect(query)
                total = len(hits)
        products = [{k: hit.get(k) for k in ("id", "title", "price", "fulfillment_mode", "availability_label", "url", "thumbnail")} for hit in hits]
        if with_sku:
            def sku_for(product):  # the barcode is embedded in the thumbnail URL (/cover/<barcode>_...); hit the product page only when it isn't there
                match = re.search(r"/cover/(\d+)", product.get("thumbnail") or "")
                if match:
                    return match.group(1)
                try:
                    return self.product_sku(product["url"])
                except Exception:  # one failed page yields a null sku, never aborts the search
                    return None
            with ThreadPoolExecutor(max_workers=8) as pool:
                skus = list(pool.map(sku_for, products))
            products = [{**product, "sku": sku} for product, sku in zip(products, skus)]
        return {"total": total, "page": page, "products": products}
