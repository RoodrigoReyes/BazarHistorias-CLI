<p align="center">
  <img src="public/bazar-historias-logo.png" alt="Bazar Historias CLI logo" width="200">
</p>

<h1 align="center">Bazar Historias CLI</h1>

<p align="center">Search the Bazar Historias catalog and view your account from the terminal.</p>

Search the [Bazar Historias](https://bazarhistorias.pe/) catalog and view your account from the terminal. Searches are limited to English-language titles, including individual issues and collected editions such as TPBs, hardcovers, and deluxe editions.

The CLI reads account information; it does not place orders or modify your wishlist, addresses, or account.

## Requirements

- Python 3.10 or later
- Internet access
- A Bazar Historias account for account commands; catalog searches do not require login

## Installation

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run `bazar --help` to see all commands. Activate the virtual environment again whenever you open a new terminal.

## Set up your account

Copy `.env.example` to `.env` in the project root and fill in your Bazar Historias credentials:

```dotenv
BAZAR_EMAIL=your_email
BAZAR_PASSWORD=your_password
```

Alternatively, set `BAZAR_EMAIL` and `BAZAR_PASSWORD` as environment variables. Environment variables take precedence over `.env` values.

```bash
bazar auth login
bazar auth status
```

> [!IMPORTANT]
> Keep `.env` private and do not commit it. The saved session at `~/.config/bazar-historias/cookies.json` grants access to your account; protect it as you would a password.

## Search the catalog

```bash
bazar search "Absolute Batman"
bazar search "Absolute Batman Vol. 1 HC"
bazar search "Absolute Batman" --availability preorder
bazar search "Absolute Batman" --availability on-request --sort newest
bazar search "Absolute Batman" --availability unavailable --page 2 --per-page 12
```

Searches filter by English language, not country or product type. Adding `USA` is optional. Results can include individual issues, collected editions, and other matching English-language products. By default, the CLI retrieves every available results page. Set `--page` or `--per-page` to request a single page instead.

| Option | Values | Description |
| --- | --- | --- |
| `--availability` | `all`, `stock`, `on-request`, `preorder`, `unavailable` | Filter by the site's availability category. Default: `all`. |
| `--page` | Integer from 1 | Select a single results page; uses 20 items per page unless `--per-page` is set. |
| `--per-page` | Integer from 1 to 50 | Set the size of a single page; defaults to page 1 unless `--page` is set. |
| `--sort` | `relevance`, `newest`, `oldest` | Sort by relevance or by date added to the catalog. Default: `relevance`. |
| `--json` | Flag | Return JSON output. |
| `--quiet` | Flag | Return JSON without progress messages. |
| `--verbose` | Flag | Include tracebacks when a command fails. |

`on-request` includes items available by request, preorders, and requests subject to confirmation. `unavailable` means the site reports the item as unavailable for purchase, typically out of stock.

> [!NOTE]
> `newest` and `oldest` use the date an item was added to the catalog, not its publication date. Filtering by a date range is not supported.

When a search contains `HC` or `hardcover`, the CLI also searches for the equivalent terms, including `Tapa Dura`, combines the result lists, and removes duplicates. The combined total is unknown (`null` in JSON) when a single page is requested; a full search reports the number of unique results. Date sorting is unavailable for these searches. The site's relevance matching can still return unrelated items. In JSON, `page` is `null` when all pages are retrieved.

In the terminal, product links use Bazar Historias' own short format, `https://bazarhistorias.pe/?p=PRODUCT_ID`. The site redirects these links to the full product page. No external shortening service is used. JSON retains the original product URLs.

## Account commands

```bash
bazar account             # Account overview
bazar orders              # List orders
bazar orders --from 2026-01-01 --to 2026-12-31  # Filter by date
bazar orders --status completed                 # Filter by status
bazar orders show 12345   # Show one order
bazar bazarcoins          # Balance and movements
bazar addresses           # Saved addresses
bazar wishlist            # Wishlist
bazar auth logout         # Remove the local session
```

Replace `12345` with an actual order number. `bazar auth logout` deletes the local session file; it does not close other sessions on the website. If the session expires, run `bazar auth login` again.

Order date filters are inclusive and can be combined with `--status`. Match English status names such as `completed`, `cancelled`, `requested`, `partially requested`, or `processing`; matching is case-insensitive and accepts partial text. Filters apply after the CLI retrieves all order pages.

The order table shows the order status and the site's current tracking step separately, along with the amount and item count. `N/A` means the site provides no current tracking step; it does not imply a payment or delivery state. Known statuses and tracking steps are translated in the terminal; JSON keeps the original Spanish values and uses `null` when tracking is unavailable. Use `bazar orders show NUMBER` to view order details.

Use `--json` before or after a command, for example:

```bash
bazar orders --json
bazar --json search "Batman" --per-page 5
```

Interactive terminals display aligned tables. Dates displayed as `DD/MM/YYYY` by the site use `YYYY-MM-DD` in the terminal. Sol amounts use a comma for thousands and a decimal point, while retaining the `S/` currency symbol. Product availability labels are translated to English when recognized; unknown labels are shown as supplied by the site. The table combines fulfillment mode and availability into one column. When stdout is redirected or piped, the CLI automatically outputs JSON, preserving both original fields and values. Status messages, progress indicators, and errors go to stderr. `--json` and `--quiet` suppress informational messages; errors still appear. Use `--verbose` for an error traceback. Other values and JSON fields supplied by Bazar Historias retain their original language.

## Development

```bash
pip install -e '.[test]'
pytest
```

The CLI depends on Bazar Historias pages and search responses. Changes to the site or access restrictions can affect commands.
