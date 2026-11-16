"""Render command results for terminals and machine consumers."""

import json
import re
import shutil
import unicodedata
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit

import click

from .status import ORDER_STATUSES

HEADERS = {
    "pedido": "Order", "fecha": "Date", "estado": "Status", "total": "Total",
    "acciones": "Actions", "detalle": "Details", "coins": "Coins",
    "producto": "Product", "productos": "Products", "cantidad": "Quantity",
    "availability label": "Availability", "seguimiento": "Tracking",
}

AVAILABILITY = {
    "a pedido · importado de usa": "On request · imported from USA",
    "agotado": "Out of stock",
    "consultar disponibilidad": "Check availability",
    "reposición del editor": "Publisher restock",
    "physical_stock": "In stock",
    "on_request": "On request",
    "on_request_confirm": "Check availability",
    "preorder": "Preorder",
    "unavailable": "Out of stock",
    "backorder": "Publisher restock",
}
MONTHS = dict(zip(
    ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"),
    ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
))
def _order_row(row):
    result = dict(row)
    result.pop("Acciones", None)
    tracking = result.pop("Seguimiento", None)
    status = result.get("Estado")
    if isinstance(status, str):
        result["Estado"] = ORDER_STATUSES.get(status.casefold(), status)
    if "Seguimiento" in row:
        fields = list(result.items())
        position = next((i + 1 for i, (key, _) in enumerate(fields) if key == "Estado"), len(fields))
        fields.insert(position, ("Seguimiento", ORDER_STATUSES.get(tracking.casefold(), tracking) if tracking else "N/A"))
        result = dict(fields)
    total = result.get("Total")
    if isinstance(total, str):
        match = re.fullmatch(r"(.*?)\s+para\s+(\d+)\s+elementos?", total, re.IGNORECASE)
        if match:
            result["Total"] = match.group(1)
            result["Items"] = match.group(2)
    return result


def _availability(label, mode=None):
    text = str(label or mode or "")
    translated = AVAILABILITY.get(text.casefold())
    if translated:
        return translated
    match = re.fullmatch(r"Preventa\s*·\s*sale el\s+(\d{1,2})\s+de\s+(\w+)(?:\s+de\s+(\d{4}))?", text, re.IGNORECASE)
    if match and match.group(2).casefold() in MONTHS:
        day, month, year = match.groups()
        return f"Preorder · releases {MONTHS[month.casefold()]} {day}" + (f", {year}" if year else "")
    match = re.fullmatch(r"Llega entre el\s+(\d{1,2})\s+de\s+(\w+)(?:\s+de\s+(\d{4}))?\s+y\s+el\s+(\d{1,2})\s+de\s+(\w+)(?:\s+de\s+(\d{4}))?", text, re.IGNORECASE)
    if match:
        first_day, first_month, first_year, last_day, last_month, last_year = match.groups()
        if first_month.casefold() in MONTHS and last_month.casefold() in MONTHS:
            first = f"{MONTHS[first_month.casefold()][:3]} {first_day}" + (f", {first_year}" if first_year else "")
            last = f"{MONTHS[last_month.casefold()][:3]} {last_day}" + (f", {last_year}" if last_year else "")
            return f"Arrives {first} - {last}"
    return text


def _order_product(item):
    text = item.get("Product", item.get("Producto", ""))
    extra = {key: value for key, value in item.items() if key not in ("Product", "Producto", "Total")}
    match = re.fullmatch(r"(.*?)\s*×\s*(\d+)(?:\s+Entrega final estimada:\s*(.*))?", text, re.IGNORECASE)
    if not match:
        return {"Product": text, "Qty": "", "Delivery": "", "Total": item.get("Total", ""), **extra}
    title, quantity, delivery = match.groups()
    delivery = _availability(delivery) if delivery else ""
    return {"Product": title, "Qty": quantity, "Delivery": delivery, "Total": item.get("Total", ""), **extra}


def _order_totals(totals):
    labels = {"subtotal": "Subtotal", "descuento": "Discount", "envío": "Shipping",
              "medio de pago": "Payment method", "total": "Total"}
    values = {"débito y crédito": "Debit and credit card", "envío domicilio": "Home delivery"}
    rows = []
    for line in totals:
        label, separator, value = line.partition(":")
        if not separator:
            rows.append({"Field": line, "Value": ""})
            continue
        if label.strip().casefold() == "acciones":
            continue
        value = value.strip()
        for original, translated in values.items():
            value = re.sub(re.escape(original), lambda _: translated, value, flags=re.IGNORECASE)
        value = re.sub(r"\bvía\b", "via", value, flags=re.IGNORECASE)
        rows.append({"Field": labels.get(label.strip().casefold(), label.strip()), "Value": value})
    return rows


def _product_url(item):
    url = item.get("url", "")
    product_id = item.get("id")
    if not isinstance(url, str) or not isinstance(product_id, (str, int)) or isinstance(product_id, bool):
        return url
    try:
        parsed = urlsplit(url)
        if (parsed.scheme == "https" and parsed.netloc == "bazarhistorias.pe" and not parsed.query
                and not parsed.fragment and parsed.path not in ("", "/") and str(product_id).isascii()
                and str(product_id).isdigit() and int(product_id) > 0):
            return f"https://bazarhistorias.pe/?p={product_id}"
    except ValueError:
        pass
    return url


def _format_value(value, key=""):
    if key.casefold() == "url":
        return value
    if key.casefold() == "price" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{Decimal(str(value)):,.2f}"
    if not isinstance(value, str) or value.startswith(("https://", "http://")):
        return value
    if key.casefold() in ("product", "producto", "title"):
        value = re.sub(r"\|\s*Inglés\s*\(USA\)", "| English (USA)", value, flags=re.IGNORECASE)

    def format_date(match):
        try:
            return datetime.strptime(match.group(), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            return match.group()

    def format_money(match):
        amount = Decimal(match.group(1).replace(".", "").replace(",", "."))
        return f"S/ {amount:,.2f}"

    value = re.sub(r"(?<![\d/])\d{1,2}/\d{1,2}/\d{4}(?![\d/])", format_date, value)
    return re.sub(r"S/\s*((?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{2})?)(?![\d.,])", format_money, value)


def _width(text):
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def _fit(value, width):
    text = " ".join(str(value if value is not None else "").split())
    if _width(text) <= width:
        return text + " " * (width - _width(text))
    result = ""
    for char in text:
        if _width(result + char) > width - 1:
            break
        result += char
    return result + "…" + " " * max(0, width - _width(result) - 1)


def _header(key):
    value = str(key).replace("_", " ")
    return HEADERS.get(value.casefold(), value.title())


def _table(headers, rows, width):
    columns = len(headers)
    available = width - 3 * (columns - 1)
    url_column = next((i for i, header in enumerate(headers) if str(header).casefold() == "url"), None)
    if url_column is not None:
        url_width = max(_width(str(row[url_column] or "")) for row in rows)
        other_width = sum(max(_width(str(header)), *(_width(str(row[i] or "")) for row in rows))
                          if str(header).casefold() == "availability" else _width(str(header))
                          for i, header in enumerate(headers) if i != url_column)
        if url_width + other_width > available:
            other_headers = [header for i, header in enumerate(headers) if i != url_column]
            for index, row in enumerate(rows):
                if index:
                    click.echo()
                _table(other_headers, [[cell for i, cell in enumerate(row) if i != url_column]], width)
                if row[url_column]:
                    click.echo(f"URL: {row[url_column]}")
            return
    if available < columns * 5 and columns > 2:
        for index, row in enumerate(rows):
            if index:
                click.echo()
            _table(["Field", "Value"], list(zip(headers, row)), width)
        return
    widths = [max(_width(str(header)), *(_width(str(row[i] if row[i] is not None else "")) for row in rows)) for i, header in enumerate(headers)]
    while sum(widths) > available:
        candidates = [i for i in range(columns) if str(headers[i]).casefold() not in ("availability", "url") and widths[i] > _width(str(headers[i]))]
        fallback = [i for i in range(columns) if i != url_column] or list(range(columns))
        largest = max(candidates or fallback, key=lambda i: (widths[i] - _width(str(headers[i])), widths[i]))
        if widths[largest] <= 1:
            break
        widths[largest] -= 1
    click.echo("   ".join(_fit(h, widths[i]) for i, h in enumerate(headers)).rstrip())
    click.echo("   ".join("─" * w for w in widths).rstrip())
    for row in rows:
        click.echo("   ".join(_fit(cell, widths[i]) for i, cell in enumerate(row)).rstrip())


def _render(value, width):
    if isinstance(value, dict):
        if not value:
            click.echo("{}")
            return
        if ({"order", "status", "products", "totals"}.issubset(value)
                and isinstance(value["products"], list) and isinstance(value["totals"], list)
                and all(isinstance(item, str) for item in value["totals"])):
            status = value.get("status") or ""
            status = ORDER_STATUSES.get(status.casefold(), status) if isinstance(status, str) else status
            summary = [f"Order {value['order']}", _format_value(value.get("date", "")), status]
            click.echo(" · ".join(str(part) for part in summary if part))
            click.echo()
            products = [_order_product(item) if isinstance(item, dict) and ("Product" in item or "Producto" in item) else item for item in value["products"]]
            _render(products, width)
            totals = _order_totals(value["totals"])
            if totals:
                click.echo()
                label_width = max(_width(row["Field"]) for row in totals)
                for row in totals:
                    label = _fit(row["Field"], label_width)
                    text = _format_value(row["Value"])
                    click.echo(f"{label}  {_fit(text, max(1, width - label_width - 2)).rstrip()}")
            extra = {key: item for key, item in value.items() if key not in ("order", "date", "status", "products", "totals")}
            if extra:
                click.echo()
                _render(extra, width)
            return
        fields = [(key, item) for key, item in value.items() if not isinstance(item, (dict, list))]
        if fields:
            _table(["Field", "Value"], [(_header(key), _format_value(item, key)) for key, item in fields], width)
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                if fields:
                    click.echo()
                click.echo(_header(key))
                _render(item, width)
                fields = [True]
    elif isinstance(value, list):
        if not value:
            click.echo("[]")
        elif all(isinstance(item, dict) for item in value):
            if all("Pedido" in item and "Estado" in item for item in value):
                value = [_order_row(item) for item in value]
            elif all("id" in item and "url" in item and "title" in item for item in value):
                value = [{**item, "url": _product_url(item)} for item in value]
            keys = list(dict.fromkeys(key for item in value for key in item))
            if "availability_label" in keys and "fulfillment_mode" in keys:
                keys.remove("fulfillment_mode")
            if not keys:
                click.echo("{}")
            else:
                _table([_header(key) for key in keys], [[_format_value(_availability(item.get(key), item.get("fulfillment_mode")) if key == "availability_label" else item.get(key, ""), key) for key in keys] for item in value], width)
        else:
            _table(["Value"], [[_format_value(item)] for item in value], width)
    else:
        click.echo(str(_format_value(value)) if value is not None else "null")


def show(value, json_mode=False, quiet=False):
    """Write result data to stdout in JSON or terminal form."""
    if json_mode or quiet:
        click.echo(json.dumps(value, ensure_ascii=False))
    else:
        _render(value, max(10, shutil.get_terminal_size((80, 24)).columns))
