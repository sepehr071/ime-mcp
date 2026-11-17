<!-- mcp-name: io.github.sepehr071/ime-mcp -->

<div align="center">

# ime-mcp: Iran Mercantile Exchange (بورس کالای ایران) MCP server for AI agents

**ime-mcp is an unofficial, read-only MCP server that gives AI agents the public trade and supply data of the Iran Mercantile Exchange (IME, ime.co.ir).**<br>
Its 14 tools list commodity trades (steel, petrochemicals, cement, oil products, metals, agriculture) with prices and volumes,<br>
upcoming supply offers, daily price series, rankings by producer and broker, market and hall totals, the USD settlement rate,<br>
the options board, gold, silver and other deposit certificates, gold funds and exchange news and weekly reports.<br>
No API key or account is needed. It works in Claude, Cursor, Copilot and any other MCP client.

[![PyPI](https://img.shields.io/pypi/v/ime-mcp?color=2563eb)](https://pypi.org/project/ime-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/ime-mcp)](https://pypi.org/project/ime-mcp/)
[![CI](https://github.com/sepehr071/ime-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sepehr071/ime-mcp/actions/workflows/ci.yml)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-io.github.sepehr071%2Fime--mcp-7c3aed)](https://registry.modelcontextprotocol.io/?q=ime-mcp)
[![License: PolyForm Noncommercial](https://img.shields.io/badge/license-PolyForm%20Noncommercial-c2410c)](https://github.com/sepehr071/ime-mcp/blob/main/LICENSE)

[For AI agents](#for-ai-agents) · [Quick start](#quick-start) · [What it can do](#what-it-can-do) · [Tools](#tools) · [FAQ](#faq) · [فارسی](#فارسی)

</div>

---

## For AI agents

- **What:** unofficial MCP server (model context protocol) for ime.co.ir, the Iranian commodity exchange: physical market trades (industrial and mineral, petrochemical and oil products, cement, subsidiary market, Kish export hall), supply offers (including premium and export), price history, rankings by producer or broker, market totals, USD rate, news, weekly report links, the options board, deposit certificates (gold bar, gold coin, silver...), salaf and commodity funds.
- **Install:** `uvx ime-mcp` or `claude mcp add ime -- uvx ime-mcp`. Transport: stdio. Needs [uv](https://docs.astral.sh/uv/getting-started/installation/) (Python 3.10+).
- **Auth:** none. Optional `IME_MCP_PROXY` (HTTP proxy URL, or a comma-separated list); system proxy settings are ignored.
- **Access:** read-only. It cannot trade or place orders, so no confirmation is needed before calling any tool.
- **Tools:** 14, all prefixed `ime_`. Typical sequences: `ime_categories` -> `ime_price_history` / `ime_trades` / `ime_supply`; `ime_producers` -> `ime_trades`; `ime_options` -> `ime_options(contract=...)`; `ime_certificates` -> `ime_certificates(commodity=...)`.
- **Use when:** the user asks what traded on the exchange, the price of steel, rebar, hot sheet, polymers, bitumen or cement, what will be offered next session, how big trading was, the exchange's USD rate, option contracts, or gold bar, gold coin and silver certificate prices.
- **Do not use when:** the question is about the stock market (TSETMC), or real estate and car trading: those are not covered here.
- **Output:** compact JSON. Dates are Persian (`1405/08/09`); Gregorian input is accepted. Prices are Rial (per kg for goods counted in tonnes: check `unit`); `value_k_rial` is thousand Rial; summary values are million Rial; `value_rial` (options, certificates, funds) is Rial. Text is Persian.
- **Machine-readable:** [`server.json`](https://github.com/sepehr071/ime-mcp/blob/main/server.json) and the
  [iran-mcp catalog](https://github.com/sepehr071/iran-mcp).

## Why

The IME site shows trades and supply only through filter forms and paged tables. "How did the hot sheet price move
this month?" means picking the group, the subgroup and a date range, then reading the table row by row. With
`ime-mcp` an agent does it in one call:

> **You:** How did hot sheet prices move since the start of Aban?
>
> **Agent:** *calls* `ime_price_history(search="ورق گرم", date_from="1405/08/01")`
>
> Kavian hot sheet (KAS-HS00000-00) traded at 1,305,425 Rial/kg on 08/02 (3,740 t), 1,296,722 on 08/03 (1,430 t),
> 1,370,586 on 08/06 (2,310 t) and 1,352,960 on 08/09 (110 t).

<sub>Numbers from a live call on 2026-10-31.</sub>

## What it can do

- **Trades**: every trade of a date range in the physical market, the subsidiary market (بازار فرعی) or the Kish export hall, with the weighted closing price, low and high, supply, demand, volume, value, producer, contract type, delivery and broker; filter by commodity group, producer or text
- **Supply offers** (اطلاعیه عرضه): what is up for sale in coming sessions with volume, base price, delivery place and date, settlement and broker
- **Price history**: daily low, high, volume-weighted average and volume per symbol over up to 45 days
- **Market totals**: value and volume by market and hall for a range, plus the USD settlement rate; day-by-day totals of one market
- **Rankings**: producers, commodities, brokers or halls ordered by traded value with market share
- **Options**: the options board (gold, gold coin, gold funds, saffron futures) with settlement prices and open interest, and the history of one contract
- **Certificates and funds**: gold bar, gold coin, silver, copper and steel deposit certificates, saffron certificates, salaf and gold funds, daily and with a bid/ask board
- **Groups and producers**: the exchange's commodity group tree and producer ids
- **News and reports**: the latest announcements and links to the weekly report PDFs

Example prompts:

- "What were the biggest trades on the exchange today?"
- "How did rebar prices move over the last two weeks?"
- "What is offered on the exchange next week from Mobarakeh Steel?"
- "How much did the physical market trade this week, by hall?"
- <span dir="rtl">قیمت ورق گرم در بورس کالا در یک ماه گذشته چطور تغییر کرده؟</span>
- <span dir="rtl">فردا چه محصولاتی در بورس کالا عرضه می‌شود؟</span>

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). No API key or account.

<details open>
<summary><b>Claude Code</b></summary>

```bash
claude mcp add ime -- uvx ime-mcp
```
</details>

<details>
<summary><b>Claude Desktop</b></summary>

Settings → Developer → Edit Config, then add:

```json
{
  "mcpServers": {
    "ime": { "command": "uvx", "args": ["ime-mcp"] }
  }
}
```
</details>

<details>
<summary><b>Cursor, VS Code, Codex CLI, Gemini CLI, Windsurf</b></summary>

Use the same command (`uvx ime-mcp`) in your client's MCP settings, for example `codex mcp add ime -- uvx ime-mcp`
or the Claude Desktop block above in `~/.cursor/mcp.json`.
</details>

<details>
<summary><b>Anything else</b></summary>

It is a standard stdio MCP server: run `uvx ime-mcp`, or `pip install ime-mcp` and run `ime-mcp`.
</details>

## Tools

Group ids come from `ime_categories`, producer ids from `ime_producers`. Dates are `1405/08/09` or `2026-10-31`; the
default is today (Tehran time). Ranges are limited to 45 days.

| Tool | What it does |
|---|---|
| `ime_categories` | List the exchange's commodity groups: main groups, then groups, then subgroups, with their ids |
| `ime_producers` | Find producers and suppliers listed on the exchange by name, to get the producer id for the trade and supply tools |
| `ime_trades` | List commodity trades (price, volume, supply, demand, buyer broker) for a date range, with totals |
| `ime_supply` | List supply offers (اطلاعیه عرضه): what is up for sale on which session, volume and base price (physical, premium or export) |
| `ime_price_history` | Daily price series (low, high, volume-weighted average, volume) per symbol over a date range |
| `ime_market_summary` | Exchange-wide trade value and volume for a date range: by market, by physical-market hall, plus the USD rate |
| `ime_daily_totals` | Day-by-day trade value and volume of one market over a date range (the site's market chart) |
| `ime_news` | Latest news and notices from the exchange's news archive: title, lead, date and link |
| `ime_trade_stats` | Rank producers, commodities, brokers or halls by traded value over a date range, with each one's market share |
| `ime_weekly_reports` | List the exchange's weekly market reports (گزارش هفتگی), newest first, with the PDF link of each |
| `ime_options` | Options on gold, gold coin, gold funds and saffron futures (اختیار معامله): one day's board or one contract's history |
| `ime_securities` | Daily trades of the exchange's financial-market symbols: salaf, commodity deposit certificates and commodity funds |
| `ime_certificates` | Continuous commodity deposit certificates (گواهی سپرده پیوسته): gold bar, gold coin, silver, copper, steel and more |
| `ime_board` | Market-view board (cdn.ime.co.ir) with the best bid and ask for funds, certificates and salaf |

All 14 tools are annotated `readOnlyHint: true`.

## How it works

```text
  AI agent  (Claude, Cursor, Copilot, ...)
      │
      │  MCP over stdio
      ▼
  ime-mcp  (runs on your machine)
      │
      │  HTTPS
      └──────▶  www.ime.co.ir   imedata.asmx, auction.ashx, export.ashx, news archive
```

`ime-mcp` runs locally and calls the same public endpoints the ime.co.ir pages use, with no hosted server in between
and no API key. Requests go out through a Chrome-impersonating client. It makes at most 3 requests at a time with a
little jitter, keeps answers for 2 minutes, retries a failed request up to twice, and only talks to www.ime.co.ir, dataapi.ime.co.ir (gold and other deposit certificates) and cdn.ime.co.ir (bid/ask board).

## Good to know

- **Iranian network.** ime.co.ir answers from Iran. From a Turkish exit it timed out in testing; use a direct Iranian line or set `IME_MCP_PROXY` to a proxy that can reach it.
- **The site mixes up the physical and subsidiary lists.** Its trade-list service keeps the first answer per date range and then ignores the market flag. The server asks for a fresh (padded) date range and checks the halls, retrying up to 6 times, so a slow answer is normal.
- **Units.** Prices are Rial per kg for goods listed in tonnes. `value_k_rial` is price x volume in thousand Rial; market summaries are million Rial; options, securities, certificates and boards give `value_rial` in Rial.
- **Trading days.** Saturday to Wednesday and some Thursdays; other days return nothing.
- **Not covered:** real estate, car trading and the stock sub-sites are separate ime.co.ir sub-sites. Statistical report archives (market-reports.html) need a form post and are not read; weekly report PDFs are linked, not parsed. The subsidiary market list has no price or value, only base price, supply, demand and volume.
- **Persian data.** Names, halls, contracts and news come back in Persian.

## FAQ

<details>
<summary><b>Is there an official IME API?</b></summary>

IME publishes data through its website only. `ime-mcp` is a separate, unofficial MCP server that calls the public
endpoints behind the website's tables and charts and returns compact JSON.
</details>

<details>
<summary><b>Does it need an API key or account?</b></summary>

No. Install with `uvx ime-mcp` and it works from an Iranian network.
</details>

<details>
<summary><b>Can it show live prices?</b></summary>

It shows trades published on the site, including the current session as the site lists them. It is not a tick feed.
</details>

<details>
<summary><b>Can it place orders?</b></summary>

No. It only reads public data.
</details>

<details>
<summary><b>How do I debug what the agent sees?</b></summary>

```bash
npx @modelcontextprotocol/inspector uvx ime-mcp
```
</details>

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `IME_MCP_PROXY` | unset | Optional HTTP proxy URL for the ime.co.ir requests; system proxy settings are ignored. A comma-separated list is used one at a time: the next proxy takes over when one is blocked or cannot connect |

<a id="فارسی"></a>

## فارسی: سرور MCP بورس کالای ایران

<div dir="rtl">

**سرور ime-mcp** یک سرور MCP غیررسمی و فقط‌خواندنی برای [بورس کالای ایران](https://www.ime.co.ir) است. با آن دستیار هوش مصنوعی شما همان داده‌های عمومی سایت را می‌بیند: معاملات، قیمت‌ها، عرضه‌های پیش‌رو و آمار بازار.

**چه کارهایی می‌کند**

- **معاملات** بازار فیزیکی، بازار فرعی و تالار صادراتی کیش برای هر بازهٔ تاریخی، با قیمت پایانی (میانگین موزون)، کمترین و بیشترین قیمت، عرضه، تقاضا، حجم، ارزش، تولیدکننده و کارگزار.
- **اطلاعیهٔ عرضه** جلسه‌های پیش‌رو با حجم و قیمت پایه.
- **سابقهٔ قیمت** هر نماد به‌صورت روزانه تا ۴۵ روز.
- **آمار بازار** بر اساس بازار و تالار، و نرخ دلار تسویهٔ بورس.
- **اخبار** و گزارش‌های هفتگی بورس کالا.

**نکته‌ها:** فقط‌خواندنی است و سفارشی ثبت نمی‌کند؛ کلید API نمی‌خواهد؛ سایت بورس کالا فقط از شبکهٔ ایران پاسخ می‌دهد؛ معاملات سکه و گواهی طلا در زیرسایت دیگری هستند و پوشش داده نمی‌شوند.

**نصب** (اول [uv](https://docs.astral.sh/uv/getting-started/installation/) را نصب کنید). در Claude Code:

</div>

```bash
claude mcp add ime -- uvx ime-mcp
```

<div dir="rtl">

**نمونه پرسش‌ها**

- «قیمت ورق گرم در بورس کالا در یک ماه گذشته چطور تغییر کرده؟»
- «فردا چه محصولاتی در بورس کالا عرضه می‌شود؟»
- «بزرگ‌ترین معاملات امروز بورس کالا کدام‌اند؟»

</div>

## Development

```bash
git clone https://github.com/sepehr071/ime-mcp && cd ime-mcp
uv sync
uv run ruff check . && uv run ruff format --check .
uv run python -m pytest -q          # offline unit tests on recorded IME answers
uv run python -m pytest -m live -q  # calls the real ime.co.ir (needs an Iranian line)
uv build
```

The physical-market tools live in `src/ime_mcp/ime.py`, the derivatives and securities tools in `src/ime_mcp/securities.py`; each is a typed async function with a docstring that tells the agent when to
use it. Issues and PRs are welcome.

Releases: bump the version in `pyproject.toml` and `server.json`, then push a `v*` tag. GitHub Actions publishes to PyPI.

## Related servers

- [iran-mcp](https://github.com/sepehr071/iran-mcp): catalog of all Iranian-service MCP servers
- [mcpfarsi.ir](https://mcpfarsi.ir/): Persian marketplace of MCP servers for Iranian services

## Disclaimer

Unofficial and not affiliated with or endorsed by the Iran Mercantile Exchange. It is read-only and uses the public
endpoints of the ime.co.ir website, which can change without notice. Not investment advice; check prices on the
exchange before acting on them.

## Author

Built and maintained by **Sepehr Radmard** (سپهر رادمرد). Connect on [LinkedIn](https://www.linkedin.com/in/sepehr-radmard) or follow [@sepehr071 on GitHub](https://github.com/sepehr071) for more MCP servers for Iranian websites, all listed in [iran-mcp](https://github.com/sepehr071/iran-mcp). If this saves you time, a star on the repo helps other people find it.

## مجوز استفاده (License)

<a href="https://www.linkedin.com/in/sepehr-radmard"><img src="https://raw.githubusercontent.com/sepehr071/iran-mcp/main/assets/license-banner.png" alt="استفادهٔ شخصی و غیرتجاری رایگان است؛ برای استفادهٔ تجاری با سپهر رادمرد تماس بگیرید. Free for personal and non-commercial use; commercial use needs a license." width="100%"></a>

**استفادهٔ شخصی و غیرتجاری رایگان است.** استفاده در شرکت، محصول پولی یا پروژهٔ مشتری به مجوز تجاری نیاز دارد؛ از راه [لینکدین](https://www.linkedin.com/in/sepehr-radmard) یا [گیت&zwnj;هاب](https://github.com/sepehr071) با سپهر رادمرد تماس بگیرید. متن کامل: [PolyForm Noncommercial 1.0.0](https://github.com/sepehr071/ime-mcp/blob/main/LICENSE). نسخه&zwnj;های پیش از 0.2.1 با مجوز MIT منتشر شده&zwnj;اند و همان مجوز را دارند.

Free for personal and non-commercial use under the [PolyForm Noncommercial License 1.0.0](https://github.com/sepehr071/ime-mcp/blob/main/LICENSE). Using it in a company, a paid product or a client project needs a commercial license: contact Sepehr Radmard on [LinkedIn](https://www.linkedin.com/in/sepehr-radmard) or [GitHub](https://github.com/sepehr071). Versions before 0.2.1 were released under MIT and stay under it.
