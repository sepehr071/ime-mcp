import pytest

pytestmark = [pytest.mark.live, pytest.mark.anyio]

# A past range with trading days; trades are not republished or changed after the session.
FROM, TO = "1405/07/20", "1405/07/22"


async def test_live_categories(client):
    main = (await client.call_tool("ime_categories", {})).structured_content
    assert len(main["groups"]) >= 5
    sub = (await client.call_tool("ime_categories", {"main_cat": 1, "cat": 1})).structured_content
    assert any(g["name"] == "ورق گرم" for g in sub["groups"])


async def test_live_producers(client):
    r = (await client.call_tool("ime_producers", {"query": "مبارکه"})).structured_content
    assert r["found"] >= 1


async def test_live_trades_physical_has_no_subsidiary_hall(client):
    r = (await client.call_tool("ime_trades", {"date_from": FROM, "date_to": TO, "limit": 100})).structured_content
    assert r["count"] > 50 and r["total_value_k_rial"] > 0
    assert all("فرعی" not in t["hall"] for t in r["trades"])


async def test_live_trades_subsidiary_and_export(client):
    sub = (
        await client.call_tool(
            "ime_trades", {"date_from": "1405/06/20", "date_to": "1405/06/22", "market": "subsidiary"}
        )
    ).structured_content
    assert sub["count"] > 0 and all("فرعی" in t["hall"] for t in sub["trades"])
    exp = (
        await client.call_tool("ime_trades", {"date_from": "1405/07/20", "date_to": "1405/08/05", "market": "export"})
    ).structured_content
    assert exp["count"] > 100


async def test_live_supply(client):
    r = (
        await client.call_tool("ime_supply", {"date_from": "1405/08/09", "date_to": "1405/08/16", "limit": 5})
    ).structured_content
    assert r["total"] > 0 and len(r["offers"]) == 5 and r["offers"][0]["commodity"]


async def test_live_price_history(client):
    r = (
        await client.call_tool(
            "ime_price_history", {"search": "ورق گرم", "date_from": "1405/08/01", "date_to": "1405/08/09"}
        )
    ).structured_content
    assert r["series"] and r["series"][0]["days"]


async def test_live_market_summary_and_totals(client):
    s = (
        await client.call_tool("ime_market_summary", {"date_from": "1405/08/05", "date_to": "1405/08/09"})
    ).structured_content
    assert s["markets"] and s["physical_halls"] and s["usd_rate"]
    d = (
        await client.call_tool("ime_daily_totals", {"date_from": "1405/08/01", "date_to": "1405/08/09"})
    ).structured_content
    assert len(d["days"]) >= 4


async def test_live_news(client):
    r = (await client.call_tool("ime_news", {"limit": 3})).structured_content
    assert r["count"] >= 1 and r["news"][0]["title"]


async def test_live_trade_stats_and_premium_and_supply_markets(client):
    s = (
        await client.call_tool(
            "ime_trade_stats", {"group_by": "producer", "date_from": "1405/08/05", "date_to": "1405/08/09"}
        )
    ).structured_content
    assert s["groups"] and s["total_value_k_rial"] > 0
    p = (
        await client.call_tool("ime_trades", {"market": "premium", "date_from": "1404/05/20", "date_to": "1404/05/30"})
    ).structured_content
    assert p["count"] >= 1
    e = (
        await client.call_tool(
            "ime_supply", {"market": "export", "date_from": "1405/08/09", "date_to": "1405/08/09", "limit": 3}
        )
    ).structured_content
    assert e["total"] > 0 and e["offers"][0]["commodity"]


async def test_live_subsidiary_single_day_is_not_the_physical_list(client):
    r = (
        await client.call_tool(
            "ime_trades", {"market": "subsidiary", "date_from": "1405/08/05", "date_to": "1405/08/05", "limit": 100}
        )
    ).structured_content
    assert r["count"] > 0 and all("فرعی" in t["hall"] for t in r["trades"])


async def test_live_weekly_reports(client):
    r = (await client.call_tool("ime_weekly_reports", {"limit": 3})).structured_content
    assert r["found"] > 100 and r["reports"][0]["url"].endswith(".pdf")


async def test_live_options(client):
    r = (await client.call_tool("ime_options", {"limit": 3})).structured_content
    assert r["contracts"] and r["contracts"][0]["type"] in ("call", "put")
    h = (await client.call_tool("ime_options", {"contract": r["contracts"][0]["contract"]})).structured_content
    assert h["days"]


async def test_live_securities_and_board(client):
    s = (
        await client.call_tool("ime_securities", {"kind": "fund", "date_from": "1405/08/05", "date_to": "1405/08/09"})
    ).structured_content
    assert s["rows_found"] > 10 and s["total_value_rial"] > 0
    b = (await client.call_tool("ime_board", {"kind": "fund", "limit": 3})).structured_content
    assert b["found"] > 10 and b["symbols"][0]["last"]


async def test_live_certificates(client):
    allc = (await client.call_tool("ime_certificates", {})).structured_content
    assert {"GoldBar", "GoldCoin"} <= {c["code"] for c in allc["certificates"]}
    coin = (
        await client.call_tool(
            "ime_certificates", {"commodity": "GoldCoin", "date_from": "1405/08/05", "date_to": "1405/08/09"}
        )
    ).structured_content
    assert coin["days"] and coin["days"][0]["volume"] > 0
