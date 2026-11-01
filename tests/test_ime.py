import json

import httpx
import pytest
from conftest import FIXTURES, fixture, page

from ime_mcp import ime

pytestmark = pytest.mark.anyio

ASMX = "/subsystems/ime/services/home/imedata.asmx/"
TOOLS = {
    "ime_categories",
    "ime_producers",
    "ime_trades",
    "ime_supply",
    "ime_price_history",
    "ime_market_summary",
    "ime_daily_totals",
    "ime_news",
    "ime_trade_stats",
    "ime_weekly_reports",
    "ime_options",
    "ime_securities",
    "ime_certificates",
    "ime_board",
}


def body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def test_gregorian_to_jalali_and_date_parsing():
    assert ime.g2j(2026, 10, 31) == (1405, 8, 9)
    assert ime.g2j(2025, 3, 21) == (1404, 1, 1)
    assert ime.j2g(1405, 8, 9) == (2026, 10, 31) and ime.j2g(1404, 1, 1) == (2025, 3, 21)
    assert ime.jdate("2026-10-31") == "1405/08/09"
    assert ime.jdate("۱۴۰۵/۸/۹") == "1405/08/09"
    with pytest.raises(ime.ApiError):
        ime.jdate("yesterday")
    with pytest.raises(ime.ApiError):
        ime._check_len("1405/01/01", "1405/08/09")


async def test_all_tools_are_read_only_and_described(client):
    tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True, t.name
        assert t.title and t.description.splitlines()[0].endswith("."), t.name
        assert "title" not in str(t.input_schema.get("properties", {}).values()), t.name


async def test_categories_levels(client, api):
    api[ASMX + "GetMainGroups"] = fixture("main_groups.json")
    api[ASMX + "GetSubCatGroups"] = fixture("sub_groups.json")
    main = (await client.call_tool("ime_categories", {})).structured_content
    assert main["level"] == "main" and {"id": 1, "name": "صنعتی"} in main["groups"]
    sub = (await client.call_tool("ime_categories", {"main_cat": 1, "cat": 1})).structured_content
    assert sub["level"] == "subgroup" and any(g["name"] == "ورق گرم" for g in sub["groups"])
    assert body(api.calls[-1]) == {"Language": 8, "MainCat": 1, "Cat": 1}
    assert api.calls[-1].method == "POST" and api.calls[-1].headers["x-requested-with"] == "XMLHttpRequest"


async def test_producers_filter_by_name(client, api):
    api[ASMX + "GetProducers"] = fixture("producers.json")
    r = (await client.call_tool("ime_producers", {"query": "مبارکه"})).structured_content
    assert r["found"] >= 1 and all("مبارکه" in p["name"] for p in r["producers"])


async def test_trades_sorted_with_totals(client, api):
    api[ASMX + "GetAmareMoamelatList"] = fixture("trades_physical.json")
    r = (
        await client.call_tool("ime_trades", {"date_from": "2026-10-28", "date_to": "1405/08/09", "limit": 3})
    ).structured_content
    assert (r["from"], r["to"], r["market"]) == ("1405/08/06", "1405/08/09", "physical")
    rows = json.loads(fixture("trades_physical.json")["d"])
    assert r["count"] == len(rows) and len(r["trades"]) == 3
    values = [t["value_k_rial"] for t in r["trades"]]
    assert values == sorted(values, reverse=True)
    assert r["total_value_k_rial"] == round(sum(x["TotalPrice"] for x in rows))
    t = r["trades"][0]
    assert t["commodity"] and t["symbol"] and t["unit"] and t["low"] <= t["price"] <= t["high"]
    sent = body(api.calls[0])
    assert sent["fari"] is False and sent["GregorianFromDate"] == "1405/08/06" and sent["MainCat"] == 0


async def test_trades_search_filters_rows(client, api):
    api[ASMX + "GetAmareMoamelatList"] = fixture("trades_physical.json")
    r = (await client.call_tool("ime_trades", {"search": "zzzz-none"})).structured_content
    assert r["count"] == 0 and r["trades"] == []


async def test_subsidiary_retries_until_the_answer_fits_the_market(client, api):
    """The site often answers with the other market's trades; the tool asks again."""
    wrong, right = fixture("trades_physical.json"), fixture("trades_subsidiary.json")
    answers = iter([wrong, wrong, right])
    api[ASMX + "GetAmareMoamelatList"] = lambda request: httpx.Response(200, json=next(answers))
    day = {"date_from": "1405/08/09", "date_to": "1405/08/09"}
    r = (await client.call_tool("ime_trades", {"market": "subsidiary", **day})).structured_content
    assert len(api.calls) == 3 and r["count"] == len(json.loads(right["d"]))
    assert all("فرعی" in t["hall"] for t in r["trades"]) and body(api.calls[0])["fari"] is True
    # each retry asks a fresh date range: the site caches the first answer per range and then ignores the flag
    assert [body(c)["GregorianToDate"] for c in api.calls] == ["1405/08/20", "1405/08/21", "1405/08/22"]
    assert body(api.calls[0])["GregorianFromDate"] == "1405/08/09"


async def test_physical_gives_up_with_only_physical_rows(client, api):
    """If the site keeps answering with the subsidiary set, the physical answer is empty rather than wrong."""
    api[ASMX + "GetAmareMoamelatList"] = fixture("trades_subsidiary.json")
    r = (await client.call_tool("ime_trades", {})).structured_content
    assert r["count"] == 0 and len(api.calls) == 6


async def test_export_trades_use_the_grid_handler(client, api):
    api["/subsystems/ime/fiziki/export.ashx"] = fixture("export.json")
    r = (await client.call_tool("ime_trades", {"market": "export", "date_from": "1405/08/01"})).structured_content
    assert r["count"] == 4 and r["trades"][0]["hall"]
    q = api.calls[0].url.params
    assert api.calls[0].method == "GET" and q["f"] == "1405/08/01" and q["lang"] == "8"


async def test_supply_pages_server_side(client, api):
    api["/subsystems/ime/auction/auction.ashx"] = fixture("supply.json")
    r = (await client.call_tool("ime_supply", {"limit": 3, "offset": 6, "search": "میلگرد"})).structured_content
    assert r["total"] == 410 and r["offset"] == 6 and len(r["offers"]) == 3
    o = r["offers"][0]
    assert o["commodity"] and o["symbol"] and o["volume"] and o["base_price"] and len(o.get("notes", "")) <= 200
    q = api.calls[0].url.params
    assert (q["limit"], q["offset"], q["search"], q["fr"]) == ("3", "6", "میلگرد", "false")


async def test_price_history_groups_by_symbol_and_day(client, api):
    api[ASMX + "GetAmareMoamelatList"] = fixture("trades_physical.json")
    r = (await client.call_tool("ime_price_history", {"sub_cat": 9, "date_from": "1405/08/06"})).structured_content
    assert r["series"] and r["symbols_found"] >= 1
    s = r["series"][0]
    assert s["symbol"] and s["unit"]
    for d in s["days"]:
        assert d["low"] <= d["avg"] <= d["high"] and d["volume"] > 0
    assert [d["date"] for d in s["days"]] == sorted(d["date"] for d in s["days"])


async def test_market_summary_combines_grids_and_rate(client, api):
    api[ASMX + "GetHomeNamaWithDateGrid"] = fixture("grid_markets.json")
    api[ASMX + "GetHomeFizikiWithDateGrid"] = fixture("grid_halls.json")
    api[ASMX + "GetHomeSaderatiGridWithDate"] = fixture("grid_export.json")
    api[ASMX + "GetHomeExchangeRateData"] = fixture("rate.json")
    r = (
        await client.call_tool("ime_market_summary", {"date_from": "1405/08/05", "date_to": "1405/08/09"})
    ).structured_content
    assert r["markets"][0]["value_m_rial"] == 597400734 and r["markets"][0]["volume"] == 742089
    assert {h["hall"] for h in r["physical_halls"]} >= {"صنعتی"} and r["export_halls"]
    assert r["usd_rate"] and r["usd_rate"][0]["rial"] > 100000


async def test_daily_totals_convert_chart_units(client, api):
    api[ASMX + "GetHomeNamaChartData"] = fixture("chart.json")
    r = (
        await client.call_tool("ime_daily_totals", {"market": "options", "date_from": "1405/08/02"})
    ).structured_content
    first = json.loads(fixture("chart.json")["d"])[0]
    assert r["days"][0] == {
        "date": first["TradeDate"],
        "value_m_rial": round(first["TradeValue"] / 1_000_000),  # the options chart is in Rial
        "volume": round(first["TradeVolume"]),
    }
    assert body(api.calls[0])["MarketId"] == 3


async def test_news_parsed_from_archive_page(client, api):
    page = (FIXTURES / "news.html").read_text(encoding="utf-8")
    api["/newsarchive.html"] = lambda request: httpx.Response(200, text=page)
    r = (await client.call_tool("ime_news", {"limit": 10})).structured_content
    assert (
        r["count"] == 4 and r["news"][0]["lead"] and r["news"][0]["url"].startswith("https://www.ime.co.ir/ShowContent")
    )
    assert all(n["title"] and n["date"] and n["summary"] for n in r["news"])
    assert any("lead" not in n for n in r["news"])  # items without a lead line exist


async def test_http_error_is_readable(client, api):
    api[ASMX + "GetMainGroups"] = lambda request: httpx.Response(500, text="The page cannot be displayed")
    r = await client.call_tool("ime_categories", {})
    assert r.is_error and "server error" in r.content[0].text


async def test_premium_trades_post_and_filter_by_category(client, api):
    api["/SubSystems/IME/Fiziki/AmarePermium.ashx"] = fixture("premium_trades.json")
    r = (
        await client.call_tool("ime_trades", {"market": "premium", "date_from": "1404/05/20", "date_to": "1404/05/30"})
    ).structured_content
    assert r["count"] == 2 and r["trades"][0]["contract"] == "پریمیوم"
    assert api.calls[0].method == "POST" and api.calls[0].url.params["f"] == "1404/05/20"
    none = (await client.call_tool("ime_trades", {"market": "premium", "main_cat": 99})).structured_content
    assert none["count"] == 0


async def test_supply_premium_and_export_lists(client, api):
    api[ASMX + "GetPremiumArzeList"] = fixture("premium_supply.json")
    api[ASMX + "GetArzeSaderatiList"] = fixture("export_supply.json")
    p = (await client.call_tool("ime_supply", {"market": "premium", "limit": 1})).structured_content
    assert p["total"] == 2 and len(p["offers"]) == 1 and p["offers"][0]["premium_price"]
    e = (await client.call_tool("ime_supply", {"market": "export", "offset": 1})).structured_content
    assert e["total"] == 3 and len(e["offers"]) == 2 and e["offers"][0]["currency"]
    none = (await client.call_tool("ime_supply", {"market": "export", "search": "zzzz-none"})).structured_content
    assert none["total"] == 0


async def test_trade_stats_ranks_groups(client, api):
    api[ASMX + "GetAmareMoamelatList"] = fixture("trades_physical.json")
    day = {"date_from": "1405/08/06", "date_to": "1405/08/06"}
    r = (await client.call_tool("ime_trade_stats", {"group_by": "producer", "limit": 3, **day})).structured_content
    rows = json.loads(fixture("trades_physical.json")["d"])
    assert r["total_value_k_rial"] == round(sum(x["TotalPrice"] for x in rows))
    values = [g["value_k_rial"] for g in r["groups"]]
    assert len(values) == 3 and values == sorted(values, reverse=True)
    assert all(g["name"] and g["trades"] for g in r["groups"])
    assert sum(g["share_pct"] for g in r["groups"]) <= 100.3


async def test_weekly_reports_list_pdfs_by_year(client, api):
    api["/weeklyReports.html"] = page("weekly.html")
    r = (await client.call_tool("ime_weekly_reports", {})).structured_content
    assert r["found"] == 3 and r["reports"][0]["url"].endswith("1405/weekly08aban05.pdf")
    assert r["reports"][1]["week"] == "منتهی به 1 آبان"  # link wrapped in <p><span>
    only = (await client.call_tool("ime_weekly_reports", {"year": 1404})).structured_content
    assert [x["month"] for x in only["reports"]] == ["اسفند ماه 1404"]


async def test_options_latest_day_and_history(client, api):
    api["/subsystems/ime/option/optionboarddata.ashx"] = fixture("options.json")
    r = (await client.call_tool("ime_options", {})).structured_content
    assert r["date"] == "1405/08/09" and r["contracts_found"] == 4  # the 2 untraded rows are dropped
    vols = [c["volume"] for c in r["contracts"]]
    assert vols == sorted(vols, reverse=True)
    c = r["contracts"][0]
    assert c["type"] in ("call", "put") and c["strike"] and c["underlying"] and c["expiry"]
    q = api.calls[0].url.params
    assert (q["c"], q["ot"], q["limit"]) == ("-1", "0", "0")
    puts = (await client.call_tool("ime_options", {"option_type": "put", "traded_only": False})).structured_content
    assert puts["contracts_found"] >= 1 and all(x["type"] == "put" for x in puts["contracts"])
    code = r["contracts"][0]["contract"]
    h = (await client.call_tool("ime_options", {"contract": code})).structured_content
    assert h["contract"] == code and h["days"]
    assert api.calls[-1].url.params["c"] == str(
        json.loads((FIXTURES / "options.json").read_text("utf-8"))["rows"][0]["ContractID"]
    )
    bad = await client.call_tool("ime_options", {"contract": "NOPE"})
    assert bad.is_error and "not found" in bad.content[0].text
    long = await client.call_tool("ime_options", {"date_from": "1405/07/01", "date_to": "1405/08/09"})
    assert long.is_error and "longer than 10" in long.content[0].text


async def test_securities_kinds_and_change(client, api):
    api["/subsystems/ime/bazaremali/bazaremalidata.ashx"] = fixture("finance.json")
    latest = (await client.call_tool("ime_securities", {})).structured_content
    assert {x["date"] for x in latest["rows"]} == {"1405/08/09"}  # no dates: only the newest day
    allr = (await client.call_tool("ime_securities", {"date_from": "1405/08/03", "limit": 100})).structured_content
    assert allr["rows_found"] == 9
    funds = (
        await client.call_tool("ime_securities", {"kind": "fund", "sort": "change", "date_from": "1405/08/03"})
    ).structured_content
    assert funds["rows_found"] == 3 and all(x["isin"].startswith("IRTK") for x in funds["rows"])
    moves = [abs(x["change_pct"] or 0) for x in funds["rows"]]
    assert moves == sorted(moves, reverse=True)
    x = allr["rows"][0]
    assert x["symbol"] and x["value_rial"] and x["low"] <= x["high"]
    q = api.calls[0].url.params
    assert (q["c"], q["ot"], q["limit"]) == ("ALL", "ALL", "0")


async def test_certificates_board_and_history(client, api):
    api["/api/CDC/CDCContracts"] = fixture("cdc_contracts.json")
    api["/api/CDC/CDCTrades"] = fixture("cdc_trades.json")
    allc = (
        await client.call_tool("ime_certificates", {"date_from": "2026-10-25", "date_to": "2026-11-01"})
    ).structured_content
    assert {c["code"] for c in allc["certificates"]} == {"GoldBar", "GoldCoin"}
    sent = body(api.calls[1])
    assert sent["fromDate"] == "2026-10-25" and sent["toDate"] == "2026-11-01" and sent["customFilter"] == ""
    assert api.calls[1].headers["origin"] == "https://gold.ime.co.ir"
    coin = (
        await client.call_tool("ime_certificates", {"commodity": "gold coin" if False else "GoldCoin"})
    ).structured_content
    assert coin["certificate"] == "GoldCoin" and body(api.calls[-1])["customFilter"] == "4"
    dates = [d["date"] for d in coin["days"]]
    assert dates == sorted(dates, reverse=True) and coin["days"][0]["last"]
    unknown = await client.call_tool("ime_certificates", {"commodity": "uranium"})
    assert unknown.is_error and "GoldBar" in unknown.content[0].text


async def test_board_values_in_rial(client, api):
    api["/getFinancialMarketData"] = fixture("board_sandoq.json")
    r = (await client.call_tool("ime_board", {"kind": "fund", "sort": "volume"})).structured_content
    raw = fixture("board_sandoq.json")
    assert r["found"] == 3 and api.calls[0].url.params["param"] == "sandoq"
    top = max(raw, key=lambda x: x["Volume"])
    assert r["symbols"][0]["isin"] == top["Code"] and r["symbols"][0]["value_rial"] == round(top["Value"] * 1000)
    assert r["symbols"][0]["date"].startswith("14") and r["symbols"][0]["bid"] is not None


async def test_requests_look_like_each_hosts_own_frontend(api):
    from ime_mcp import http

    api[ASMX + "GetX"] = {}
    api["/api/CDC/CDCContracts"] = {}
    api["/getFinancialMarketData"] = []
    api["/newsarchive.html"] = lambda r: httpx.Response(200, text="<html></html>")
    await http.fetch(http.ASMX + "/GetX", body={})
    await http.fetch(http.CDC_CONTRACTS)
    await http.fetch(http.BOARD)
    await http.fetch(http.SITE + "/newsarchive.html", text=True)
    asmx, cdc, board, nav = (c.headers for c in api.calls)
    assert asmx["x-requested-with"] == "XMLHttpRequest" and asmx["origin"] == "https://www.ime.co.ir"
    assert cdc["accept"] == "*/*" and cdc["origin"] == "https://gold.ime.co.ir" and cdc["sec-fetch-site"] == "same-site"
    assert board["accept"] == "application/json, text/plain, */*" and board["x-security-request"] == "required"
    assert "x-requested-with" not in board and "origin" not in board
    assert nav["sec-fetch-mode"] == "navigate" and nav["priority"] == "u=0, i" and "origin" not in nav
