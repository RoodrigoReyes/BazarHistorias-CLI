import json
import os

from click.testing import CliRunner
import click

from bazar.output import _availability, show


def run_show(value, **kwargs):
    @click.command()
    def command():
        show(value, **kwargs)
    return CliRunner().invoke(command)


def test_json_preserves_spanish_data_and_keys():
    value = [{"Pedido": "#1", "Estado": "En proceso"}]
    result = run_show(value, json_mode=True)
    assert result.exit_code == 0
    assert json.loads(result.stdout) == value
    assert result.stderr == ""


def test_terminal_translates_headers_and_truncates(monkeypatch):
    monkeypatch.setattr("bazar.output.shutil.get_terminal_size", lambda *args: os.terminal_size((35, 24)))
    result = run_show([{"Pedido": "#1", "Estado": "En proceso", "Detalle": "Description that is much too long"}])
    assert "Order" in result.output and "Status" in result.output and "Details" in result.output
    assert "Processing" in result.output
    assert "…" in result.output
    assert all(len(line) <= 35 for line in result.output.splitlines())


def test_nested_results_and_empty_state():
    result = run_show({"total": 0, "products": []})
    assert "Total" in result.output and "Products" in result.output
    assert "[]" in result.output


def test_availability_translations_keep_dates_and_unknown_text():
    assert _availability("A pedido · importado de USA") == "On request · imported from USA"
    assert _availability("Preventa · sale el 2 de diciembre") == "Preorder · releases December 2"
    assert _availability("Preventa · sale el 6 de enero de 2027") == "Preorder · releases January 6, 2027"
    assert _availability("Agotado") == "Out of stock"
    assert _availability("Reposición del editor") == "Publisher restock"
    assert _availability("Consultar disponibilidad") == "Check availability"
    assert _availability("Llega entre el 28 de noviembre y el 5 de diciembre") == "Arrives Nov 28 - Dec 5"
    assert _availability("Llega entre el 28 de diciembre de 2026 y el 5 de enero de 2027") == "Arrives Dec 28, 2026 - Jan 5, 2027"
    assert _availability("Etiqueta desconocida") == "Etiqueta desconocida"


def test_availability_table_combines_columns_but_json_stays_unchanged(monkeypatch):
    monkeypatch.setattr("bazar.output.shutil.get_terminal_size", lambda *args: os.terminal_size((120, 24)))
    data = [{"title": "Batman", "fulfillment_mode": "preorder", "availability_label": "Preventa · sale el 6 de enero de 2027"},
            {"title": "Superman", "fulfillment_mode": "unavailable", "availability_label": None}]
    terminal = run_show(data).stdout
    assert "Availability" in terminal and "Fulfillment" not in terminal
    assert "Preorder · releases January 6, 2027" in terminal
    assert "Out of stock" in terminal
    assert json.loads(run_show(data, json_mode=True).stdout) == data


def test_availability_date_fits_in_standard_terminal(monkeypatch):
    monkeypatch.setattr("bazar.output.shutil.get_terminal_size", lambda *args: os.terminal_size((80, 24)))
    data = [{"id": 123, "title": "A very long comic title and edition", "price": 25,
             "fulfillment_mode": "preorder", "availability_label": "Preventa · sale el 6 de enero de 2027",
             "url": "https://example.com/a-long-product-url"}]
    assert "Preorder · releases January 6, 2027" in run_show(data).stdout
    assert data[0]["url"] in run_show(data).stdout


def test_product_short_link_uses_id_without_changing_json(monkeypatch):
    monkeypatch.setattr("bazar.output.shutil.get_terminal_size", lambda *args: os.terminal_size((100, 24)))
    data = [{"id": 252241, "title": "Absolute Batman", "url": "https://bazarhistorias.pe/a-long-product-name/"}]
    assert "https://bazarhistorias.pe/?p=252241" in run_show(data).stdout
    assert json.loads(run_show(data, json_mode=True).stdout) == data


def test_product_short_link_preserves_untrusted_url():
    data = [{"id": "123", "title": "Example", "url": "https://example.com/item"}]
    assert data[0]["url"] in run_show(data).stdout


def test_orders_table_uses_concise_english_values_and_preserves_json(monkeypatch):
    monkeypatch.setattr("bazar.output.shutil.get_terminal_size", lambda *args: os.terminal_size((100, 24)))
    data = [{"Pedido": "#123", "Fecha": "13/11/2026", "Estado": "Solicitado parcial", "Seguimiento": "Pagado",
             "Total": "S/ 113,32 para 4 elementos", "Acciones": "Ver Seguimiento"}]
    terminal = run_show(data).stdout
    assert "Partially requested" in terminal
    assert "Tracking" in terminal and "Paid" in terminal
    assert "S/ 113.32" in terminal and "2026-11-13" in terminal and "Items" in terminal and "4" in terminal
    assert "Actions" not in terminal and "Seguimiento" not in terminal and "para 4 elementos" not in terminal
    assert json.loads(run_show(data, json_mode=True).stdout) == data


def test_order_without_tracking_displays_na():
    terminal = run_show([{"Pedido": "#123", "Estado": "Cancelado", "Seguimiento": None}]).stdout
    assert "Cancelled" in terminal and "N/A" in terminal


def test_terminal_formats_dates_and_soles_without_changing_json():
    data = {"date": "01/02/2026", "total": "S/ 1.234,56", "price": 28.5,
            "invalid_date": "31/02/2026", "url": "https://example.com/01/02/2026"}
    terminal = run_show(data).stdout
    assert "2026-02-01" in terminal and "S/ 1,234.56" in terminal and "28.50" in terminal
    assert "31/02/2026" in terminal and "https://example.com/01/02/2026" in terminal
    assert json.loads(run_show(data, json_mode=True).stdout) == data


def test_formatting_applies_to_nested_rows_and_text_lists():
    data = {"transactions": [{"Fecha": "13/11/2026", "Detalle": "Total S/ 3,50"}],
            "totals": ["Shipping S/ 12,00"]}
    terminal = run_show(data).stdout
    assert "2026-11-13" in terminal and "S/ 3.50" in terminal and "S/ 12.00" in terminal


def test_order_detail_separates_products_and_translates_totals_without_changing_json(monkeypatch):
    monkeypatch.setattr("bazar.output.shutil.get_terminal_size", lambda *args: os.terminal_size((120, 24)))
    data = {"order": "123", "date": "13/11/2026", "status": "Completado",
            "products": [{"Producto": "Batman #2 | Inglés (USA) × 2 Entrega final estimada: Preventa · sale el 18 de noviembre", "Total": "S/ 28,70"}],
            "totals": ["Subtotal: S/ 28,70", "Descuento: - S/ 1,00", "Envío: S/ 10,00 vía Envío Domicilio", "Medio de pago: Débito y Crédito", "Total: S/ 37,70", "Acciones: Seguimiento"]}
    terminal = run_show(data).stdout
    assert "Completed" in terminal and "2026-11-13" in terminal
    assert "Qty" in terminal and "Delivery" in terminal and "Preorder · releases November 18" in terminal
    assert "English (USA)" in terminal and "Inglés (USA)" not in terminal
    assert "Discount" in terminal and "Shipping" in terminal and "Home delivery" in terminal
    assert "Payment method" in terminal and "Debit and credit card" in terminal and "S/ 37.70" in terminal
    assert "Entrega final estimada" not in terminal and "Acciones" not in terminal
    assert "Order 123 · 2026-11-13 · Completed" in terminal
    assert "Field" not in terminal and "Value" not in terminal
    assert "\nProducts\n" not in terminal and "\nTotals\n" not in terminal
    assert json.loads(run_show(data, json_mode=True).stdout) == data


def test_order_detail_keeps_unrecognized_product_text():
    data = {"order": "123", "status": "unknown", "products": [{"Product": "Unknown formatting", "Total": "S/ 10,00"}], "totals": []}
    assert "Unknown formatting" in run_show(data).stdout


def test_order_detail_translates_delivery_range_and_preserves_json(monkeypatch):
    monkeypatch.setattr("bazar.output.shutil.get_terminal_size", lambda *args: os.terminal_size((160, 24)))
    data = {"order": "123", "status": "Completado", "products": [{"Producto": "Comic | Inglés (USA) × 1 Entrega final estimada: Llega entre el 28 de noviembre y el 5 de diciembre", "Total": "S/ 10,00"}], "totals": []}
    terminal = run_show(data).stdout
    assert "Arrives Nov 28 - Dec 5" in terminal and "English (USA)" in terminal
    assert json.loads(run_show(data, json_mode=True).stdout) == data
