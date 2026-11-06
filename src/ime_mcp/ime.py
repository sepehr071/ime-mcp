"""Iran Mercantile Exchange tools: physical market trades, supply offers, prices, market totals, news."""

from __future__ import annotations

import asyncio
import html
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from pydantic import Field

from .http import ASMX, AUCTION, EXPORT, PREMIUM_TRADES, SITE, ApiError, fetch
from .registry import tool

TEHRAN = timezone(timedelta(hours=3, minutes=30))
MARKETS = {"physical": 1, "options": 3, "financial": 4}  # MarketId values the site's chart dialogs accept
MAX_DAYS = 45  # trade lists are ~50 rows per trading day; keep one answer bounded
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

Date = Annotated[
    str | None,
    Field(description="Persian 1405/08/09 or Gregorian 2026-10-31.", max_length=12),
]
CatId = Annotated[int, Field(description="Category id from ime_categories (0 = all).", ge=0)]


def g2j(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Gregorian date to Persian (Jalali) date."""
    gdm = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + gdm[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        return jy, 1 + days // 31, 1 + days % 31
    return jy, 7 + (days - 186) // 30, 1 + (days - 186) % 30


def j2g(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """Persian (Jalali) date to Gregorian."""
    jy += 1595
    days = -355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4 + jd
    days += (jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    months = (
        0,
        31,
        29 if (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0 else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    )
    gm = 0
    while gm < 13 and gd > months[gm]:
        gd -= months[gm]
        gm += 1
    return gy, gm, gd


def jdate(value: str | None, offset_days: int = 0) -> str:
    """Normalize a user date to the Persian `yyyy/mm/dd` the site wants; None = today (Tehran) plus offset."""
    if not value:
        d = datetime.now(TEHRAN) + timedelta(days=offset_days)
        y, mo, dd = g2j(d.year, d.month, d.day)
        return f"{y}/{mo:02d}/{dd:02d}"
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", value.translate(DIGITS).strip())
    if not m:
        raise ApiError(f"Bad date {value!r}: use 1405/08/09 (Persian) or 2026-10-31 (Gregorian).")
    y, mo, d = map(int, m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        raise ApiError(f"Bad date {value!r}: month 1-12, day 1-31.")
    if y > 1700:
        y, mo, d = g2j(y, mo, d)
    return f"{y}/{mo:02d}/{d:02d}"


def _span(date_from: str | None, date_to: str | None, default_days: int, forward: bool = False) -> tuple[str, str]:
    """Normalized (from, to). Defaults: the last `default_days` days up to today, or today forward when `forward`."""
    if forward:
        f, t = jdate(date_from), jdate(date_to, default_days)
    else:
        f, t = jdate(date_from, -default_days), jdate(date_to)
    if f > t:
        raise ApiError(f"date_from {f} is after date_to {t}.")
    return f, t


def _check_len(f: str, t: str, limit: int = MAX_DAYS) -> None:
    (fy, fm, fd), (ty, tm, td) = (map(int, x.split("/")) for x in (f, t))
    if (ty - fy) * 372 + (tm - fm) * 31 + (td - fd) > limit:
        raise ApiError(f"Range {f} to {t} is longer than {limit} days; ask for a shorter one.")


async def _asmx(method: str, cache: bool = True, **body: Any) -> Any:
    """Call an ASMX method; its answer is {"d": "<json string>"}."""
    r = await fetch(f"{ASMX}/{method}", body={"Language": 8, **body}, cache=cache)
    try:
        return json.loads(r["d"])
    except (KeyError, TypeError, ValueError) as e:
        raise ApiError(f"Unexpected answer from ime.co.ir {method}.") from e


def _rm(v: Any) -> Any:
    """Round to a whole number when a float is integral-looking."""
    return round(v) if isinstance(v, float) else v


def _trade(r: dict[str, Any]) -> dict[str, Any]:
    """One trade row, trimmed. `value_k_rial` is the site's TotalPrice (thousand Rial for kg-priced goods)."""
    return {
        "date": r.get("date"),
        "commodity": r.get("GoodsName"),
        "symbol": r.get("Symbol"),
        "producer": r.get("ProducerName"),
        "contract": r.get("ContractType"),
        "hall": r.get("Talar") or r.get("xRingName"),
        "low": r.get("MinPrice"),
        "price": r.get("Price"),
        "high": r.get("MaxPrice"),
        "base_price": r.get("ArzeBasePrice"),
        "supply": r.get("arze"),
        "demand": r.get("taghaza"),
        "volume": r.get("Quantity"),
        "value_k_rial": _rm(r.get("TotalPrice")),
        "unit": r.get("Unit"),
        "currency": r.get("Currency"),
        "delivery_date": r.get("DeliveryDate"),
        "delivery_place": r.get("Warehouse"),
        "broker": r.get("cBrokerSpcName"),
    }


def _shift(persian: str, days: int) -> str:
    """Persian `yyyy/mm/dd` moved by `days`."""
    d = date(*j2g(*map(int, persian.split("/")))) + timedelta(days=days)
    return "{}/{:02d}/{:02d}".format(*g2j(d.year, d.month, d.day))


async def _list(
    fari: bool, f: str, t: str, main_cat: int, cat: int, sub_cat: int, producer: int
) -> list[dict[str, Any]]:
    """GetAmareMoamelatList. The service caches the first answer per date range and then ignores `fari` (the other
    market's trades come back for a range somebody asked with the other flag; shown in Chrome, curl and Python
    2026-11-01). So the range is padded with days after `t` (physical 1+, subsidiary 11+: different keys for the two
    markets, a fresh key each retry) and the rows are cut back to f..t. A subsidiary trade is one in a hall named
    فرعی; if the answer does not fit the market, ask again with a new pad, up to 6 times."""
    rows: list[dict[str, Any]] = []
    for i in range(6):
        rows = await _asmx(
            "GetAmareMoamelatList",
            cache=False,
            fari=fari,
            GregorianFromDate=f,
            GregorianToDate=_shift(t, i + (11 if fari else 1)),
            MainCat=main_cat,
            Cat=cat,
            SubCat=sub_cat,
            Producer=producer,
        )
        sub = [r for r in rows if "فرعی" in (r.get("Talar") or "")]
        if not rows or (len(sub) == len(rows) if fari else not sub):
            return [r for r in rows if f <= (r.get("date") or "") <= t]
    # no clean answer: keep only the rows of the asked market (may be partial; the other market's rows are dropped)
    return [r for r in rows if ("فرعی" in (r.get("Talar") or "")) == fari and f <= (r.get("date") or "") <= t]


async def _trades(
    market: str, f: str, t: str, main_cat: int, cat: int, sub_cat: int, producer: int, search: str | None
) -> list[dict[str, Any]]:
    if market == "export":
        q = {"f": f, "t": t, "m": main_cat, "c": cat, "s": sub_cat, "p": producer, "lang": 8}
        rows = (await fetch(EXPORT, params=q, page="/export-stat.html"))["rows"]
    elif market == "premium":
        # the handler takes only the dates (POST, no filters); Category is "main-cat-sub", so filter on that
        rows = await fetch(PREMIUM_TRADES, params={"f": f, "t": t}, body={}, page="/premiumTrades.html")
        want = [str(x) for x in (main_cat, cat, sub_cat)]
        rows = [
            r
            for r in rows
            if all(w == "0" or w == c for w, c in zip(want, str(r.get("Category")).split("-"), strict=False))
        ]
    else:
        rows = await _list(market == "subsidiary", f, t, main_cat, cat, sub_cat, producer)
    out = [_trade(r) for r in rows]
    if search and (s := search.strip().lower()):
        out = [x for x in out if s in " ".join(str(x[k]) for k in ("commodity", "symbol", "producer")).lower()]
    return out


Market = Annotated[
    Literal["physical", "subsidiary", "export", "premium"],
    Field(description="physical, subsidiary (بازار فرعی), export (Kish hall) or premium (no producer filter)."),
]


@tool("Commodity groups")
async def ime_categories(
    main_cat: Annotated[
        int, Field(description="Main group id to list its groups (0 = list the main groups).", ge=0)
    ] = 0,
    cat: Annotated[int, Field(description="Group id (with main_cat) to list its subgroups.", ge=0)] = 0,
) -> dict[str, Any]:
    """List the exchange's commodity groups: main groups, then groups, then subgroups, with their ids.

    No arguments: main groups. main_cat: its groups. main_cat plus cat: subgroups. Use the ids as
    main_cat/cat/sub_cat in ime_trades, ime_supply and ime_price_history.
    """
    if not main_cat:
        rows = [{"id": r["code"], "name": r["Name"]} for r in await _asmx("GetMainGroups")]
        return {"level": "main", "groups": rows}
    if not cat:
        rows = [{"id": r["code"], "name": r["name"]} for r in await _asmx("GetCatGroups", MainCat=main_cat)]
        return {"level": "group", "main_cat": main_cat, "groups": rows}
    rows = [{"id": r["code"], "name": r["name"]} for r in await _asmx("GetSubCatGroups", MainCat=main_cat, Cat=cat)]
    return {"level": "subgroup", "main_cat": main_cat, "cat": cat, "groups": rows}


@tool("Find producers")
async def ime_producers(
    query: Annotated[
        str,
        Field(
            description="Part of a producer name, Persian or English, e.g. فولاد مبارکه.", min_length=1, max_length=80
        ),
    ],
    limit: Annotated[int, Field(description="Max producers (1-50).", ge=1, le=50)] = 20,
) -> dict[str, Any]:
    """Find producers and suppliers listed on the exchange by name, to get the producer id for the trade and supply tools.

    Use the returned id as producer in ime_trades, ime_supply or ime_price_history.
    """
    q = re.sub(r"\s+", " ", query).strip().lower()
    rows = [{"id": r["code"], "name": r["name"].strip()} for r in await _asmx("GetProducers")]
    hits = [r for r in rows if q in re.sub(r"\s+", " ", r["name"]).lower()]
    return {"found": len(hits), "producers": hits[:limit]}


@tool("Trades on the exchange")
async def ime_trades(
    date_from: Date = None,
    date_to: Date = None,
    market: Market = "physical",
    main_cat: CatId = 0,
    cat: CatId = 0,
    sub_cat: CatId = 0,
    producer: CatId = 0,
    search: Annotated[
        str | None,
        Field(description="Commodity, symbol or producer contains this text.", max_length=80),
    ] = None,
    sort: Annotated[
        Literal["value", "volume", "date"],
        Field(description="value (largest first), volume (largest first) or date (newest first)."),
    ] = "value",
    limit: Annotated[int, Field(description="Max trades to return (1-100).", ge=1, le=100)] = 30,
) -> dict[str, Any]:
    """List commodity trades (price, volume, supply, demand, buyer broker) for a date range, with totals.

    Dates default to today (Tehran); at most 45 days. Filter with main_cat/cat/sub_cat (ime_categories), producer
    (ime_producers) or search. `price` is the volume-weighted closing price; Rial per kg for tonne goods; `volume` in
    `unit`; `value_k_rial` in thousand Rial. Subsidiary rows have only base_price, supply, demand, volume. For one
    product's series use ime_price_history; for market totals ime_market_summary.
    """
    f, t = _span(date_from, date_to, 0)
    _check_len(f, t)
    rows = await _trades(market, f, t, main_cat, cat, sub_cat, producer, search)
    key = {"value": "value_k_rial", "volume": "volume", "date": "date"}[sort]
    rows.sort(key=lambda x: x[key] or 0, reverse=True)
    return {
        "from": f,
        "to": t,
        "market": market,
        "count": len(rows),
        "total_value_k_rial": round(sum(x["value_k_rial"] or 0 for x in rows)),
        "trades": rows[:limit],
    }


def _offer(x: dict[str, Any]) -> dict[str, Any]:
    """One supply offer, trimmed (physical, premium and export lists share these field names)."""
    return {
        "id": x.get("bArzehRadifPK"),
        "date": x.get("bArzehTarArzeh"),
        "commodity": x.get("bArzehRadifNamadKala"),
        "symbol": x.get("xKalaNamadKala"),
        "hall": x.get("Talar"),
        "producer": x.get("xTolidKonandehSharh"),
        "supplier": x.get("ArzehKonandeh"),
        "volume": x.get("bArzehRadifArzeh"),
        "unit": x.get("Unit"),
        "base_price": x.get("bArzehRadifMab"),
        "premium_price": x.get("PremiumPrice"),
        "currency": x.get("Currency"),
        "min_lot": x.get("bArzehRadifMinArzeh"),
        "contract": x.get("xContractKindSharh"),
        "settlement": x.get("bArzehRadifTasviehTypeSharh"),
        "delivery_date": x.get("bArzehRadifTarTahvil"),
        "delivery_place": x.get("xMahalTahvilSharh"),
        "packaging": x.get("bArzehRadifShekl"),
        "method": x.get("MethodDescription"),
        "broker": x.get("cBrokerSpcName"),
        "notes": (x.get("bArzehRadifArzehSharh") or "")[:200] or None,
    }


@tool("Supply offers")
async def ime_supply(
    date_from: Date = None,
    date_to: Date = None,
    main_cat: CatId = 0,
    cat: CatId = 0,
    sub_cat: CatId = 0,
    producer: CatId = 0,
    search: Annotated[
        str | None,
        Field(description="Commodity, symbol, producer or supplier contains this text.", max_length=80),
    ] = None,
    limit: Annotated[int, Field(description="Max offers to return (1-50).", ge=1, le=50)] = 20,
    offset: Annotated[int, Field(description="Skip this many offers (paging).", ge=0)] = 0,
    market: Annotated[
        Literal["physical", "premium", "export"],
        Field(description="physical, premium or export (Kish hall, priced in $)."),
    ] = "physical",
) -> dict[str, Any]:
    """List supply offers (اطلاعیه عرضه): what is up for sale on which session, volume and base price.

    Dates are offer dates; default today to 7 days ahead; at most 45 days. Filters as in ime_trades; page with
    offset. market=premium adds `premium_price`. After the session ime_trades shows what sold.
    """
    f, t = _span(date_from, date_to, 7, forward=True)
    _check_len(f, t)
    if market == "physical":
        q = {"fr": "false", "f": f, "t": t, "m": main_cat, "c": cat, "s": sub_cat, "p": producer, "lang": 8}
        q |= {"limit": limit, "offset": offset, **({"search": search.strip()} if search and search.strip() else {})}
        r = await fetch(AUCTION, params=q, page="/arze.html")
        return {"from": f, "to": t, "total": r["total"], "offset": offset, "offers": [_offer(x) for x in r["rows"]]}
    method = "GetPremiumArzeList" if market == "premium" else "GetArzeSaderatiList"
    rows = await _asmx(
        method,
        fari=False,
        GregorianFromDate=f,
        GregorianToDate=t,
        MainCat=main_cat,
        Cat=cat,
        SubCat=sub_cat,
        Producer=producer,
    )
    offers = [_offer(x) for x in rows]
    if search and (needle := search.strip().lower()):
        offers = [
            o
            for o in offers
            if needle in " ".join(str(o[k]) for k in ("commodity", "symbol", "producer", "supplier")).lower()
        ]
    return {
        "from": f,
        "to": t,
        "market": market,
        "total": len(offers),
        "offset": offset,
        "offers": offers[offset : offset + limit],
    }


@tool("Price history of a commodity")
async def ime_price_history(
    date_from: Date = None,
    date_to: Date = None,
    search: Annotated[
        str | None, Field(description="Commodity, symbol or producer text, e.g. ورق گرم.", max_length=80)
    ] = None,
    main_cat: CatId = 0,
    cat: CatId = 0,
    sub_cat: CatId = 0,
    producer: CatId = 0,
    market: Market = "physical",
) -> dict[str, Any]:
    """Daily price series (low, high, volume-weighted average, volume) per symbol over a date range.

    Dates default to the last 14 days; at most 45 days. Narrow with sub_cat or search (a wide filter returns only
    the 8 biggest symbols). Only days with trades appear. Prices as in ime_trades.
    """
    f, t = _span(date_from, date_to, 14)
    _check_len(f, t)
    rows = await _trades(market, f, t, main_cat, cat, sub_cat, producer, search)
    by: dict[str, dict[str, dict[str, Any]]] = {}
    for x in rows:
        if not x["volume"] or x["price"] is None:
            continue
        d = by.setdefault(x["symbol"], {}).setdefault(
            x["date"], {"date": x["date"], "low": x["low"], "high": x["high"], "volume": 0.0, "pv": 0.0, "trades": 0}
        )
        d["low"], d["high"] = min(d["low"], x["low"]), max(d["high"], x["high"])
        d["volume"] += x["volume"]
        d["pv"] += x["volume"] * x["price"]
        d["trades"] += 1
    names = {x["symbol"]: (x["commodity"], x["unit"], x["currency"]) for x in rows}
    ranked = sorted(by, key=lambda s: sum(d["volume"] for d in by[s].values()), reverse=True)
    series = []
    for s in ranked[:8]:
        days = [
            {
                "date": d["date"],
                "low": d["low"],
                "high": d["high"],
                "avg": round(d["pv"] / d["volume"]),
                "volume": round(d["volume"], 3),
                "trades": d["trades"],
            }
            for d in sorted(by[s].values(), key=lambda d: d["date"])
        ]
        series.append(
            {"symbol": s, "commodity": names[s][0], "unit": names[s][1], "currency": names[s][2], "days": days}
        )
    return {"from": f, "to": t, "symbols_found": len(by), "series": series}


@tool("Market totals")
async def ime_market_summary(date_from: Date = None, date_to: Date = None) -> dict[str, Any]:
    """Exchange-wide trade value and volume for a date range: by market, by physical-market hall, plus the USD rate.

    Dates default to today (Tehran). Values are million Rial; volumes are tonnes for physical. `offer_volume` is
    what was offered. The USD rate is the exchange's settlement rate. For a day-by-day series use ime_daily_totals.
    """
    f, t = _span(date_from, date_to, 0)
    kw = {"GregorianFromDate": f, "GregorianToDate": t}
    markets, halls, export, rate = await asyncio.gather(
        _asmx("GetHomeNamaWithDateGrid", **kw),
        _asmx("GetHomeFizikiWithDateGrid", **kw),
        _asmx("GetHomeSaderatiGridWithDate", **kw),
        _asmx("GetHomeExchangeRateData"),
    )
    return {
        "from": f,
        "to": t,
        "markets": [
            {"market": m["name"], "value_m_rial": _rm(m["TradeValue"]), "volume": _rm(m["TradeVolume"])}
            for m in markets
            if m.get("TradeValue") is not None
        ],
        "physical_halls": [
            {
                "hall": h["xRingName"],
                "value_m_rial": _rm(h["Value"]),
                "volume": _rm(h["Volume"]),
                "offer_volume": _rm(h.get("OfferVolume")),
            }
            for h in halls
        ],
        "export_halls": [
            {"hall": h["xRingName"], "value_m_rial": _rm(h["Value"]), "volume": _rm(h["Volume"])} for h in export
        ],
        "usd_rate": [{"date": x["Tarikh"], "rial": _rm(x["Nerkh"])} for x in rate if x.get("Sharh") == "دلار"],
    }


@tool("Daily trade totals")
async def ime_daily_totals(
    date_from: Date = None,
    date_to: Date = None,
    market: Annotated[
        Literal["physical", "options", "financial"],
        Field(description="physical, options or financial."),
    ] = "physical",
) -> dict[str, Any]:
    """Day-by-day trade value and volume of one market over a date range (the site's market chart).

    Dates default to the last 14 days; at most 45 days. Value is million Rial. Volume is tonnes (physical),
    contracts (options) or units (financial).
    """
    f, t = _span(date_from, date_to, 14)
    _check_len(f, t)
    rows = await _asmx("GetHomeNamaChartData", GregorianFromDate=f, GregorianToDate=t, MarketId=MARKETS[market])
    unit = 1_000_000 if market == "options" else 1000
    return {
        "from": f,
        "to": t,
        "market": market,
        "days": [
            # the chart reports thousand Rial (options: Rial, checked against the home grid 2026-11-01); this tool uses million
            {"date": r["TradeDate"], "value_m_rial": round(r["TradeValue"] / unit), "volume": _rm(r["TradeVolume"])}
            for r in rows
        ],
    }


@tool("Exchange news")
async def ime_news(
    limit: Annotated[int, Field(description="Max news items (1-30).", ge=1, le=30)] = 10,
) -> dict[str, Any]:
    """Latest news and notices from the exchange's news archive: title, lead, date and link.

    Text is Persian.
    """
    page = await fetch(f"{SITE}/newsarchive.html", page="/", text=True)
    items = []
    for row in page.split("<div class='NewsLayout12Row'")[1:]:
        m = re.search(
            r"RowContents'>(?:<h3>(.*?)</h3>)?<a href='([^']+)'.*?<h2>(.*?)</h2></a><p>(.*?)</p>.*?>زمان انتشار: (.*?)</div>",
            row,
            re.S,
        )
        if m:
            lead, url, title, summary, date = (
                html.unescape(re.sub(r"<[^>]+>", "", x or "")).strip() for x in m.groups()
            )
            items.append(
                {"title": title, "lead": lead or None, "date": date, "summary": summary[:300], "url": SITE + url}
            )
    return {"count": len(items), "news": items[:limit]}


@tool("Trade statistics by group")
async def ime_trade_stats(
    group_by: Annotated[
        Literal["producer", "commodity", "broker", "hall", "contract"],
        Field(description="Grouping key (broker = buyer broker)."),
    ],
    date_from: Date = None,
    date_to: Date = None,
    market: Market = "physical",
    main_cat: CatId = 0,
    cat: CatId = 0,
    sub_cat: CatId = 0,
    producer: CatId = 0,
    search: Annotated[
        str | None,
        Field(description="Commodity, symbol or producer contains this text.", max_length=80),
    ] = None,
    limit: Annotated[int, Field(description="Max groups to return (1-50).", ge=1, le=50)] = 15,
) -> dict[str, Any]:
    """Rank producers, commodities, brokers or halls by traded value over a date range, with each one's market share.

    Dates default to today (Tehran); at most 45 days; filters as in ime_trades. Value is thousand Rial. `volume`
    only when all trades of the group share one unit. For single trades use ime_trades.
    """
    f, t = _span(date_from, date_to, 0)
    _check_len(f, t)
    rows = await _trades(market, f, t, main_cat, cat, sub_cat, producer, search)
    key = {"producer": "producer", "commodity": "commodity", "broker": "broker", "hall": "hall", "contract": "contract"}
    groups: dict[str, dict[str, Any]] = {}
    for x in rows:
        g = groups.setdefault(
            str(x[key[group_by]] or "?").strip(), {"value": 0.0, "volume": 0.0, "trades": 0, "units": set()}
        )
        g["value"] += x["value_k_rial"] or 0
        g["volume"] += x["volume"] or 0
        g["trades"] += 1
        g["units"].add(x["unit"])
    total = sum(g["value"] for g in groups.values())
    ranked = sorted(groups.items(), key=lambda kv: kv[1]["value"], reverse=True)[:limit]
    return {
        "from": f,
        "to": t,
        "market": market,
        "group_by": group_by,
        "groups_found": len(groups),
        "total_value_k_rial": round(total),
        "groups": [
            {
                "name": n,
                "value_k_rial": round(g["value"]),
                "share_pct": round(100 * g["value"] / total, 1) if total else None,
                "trades": g["trades"],
                **({"volume": round(g["volume"], 3), "unit": next(iter(g["units"]))} if len(g["units"]) == 1 else {}),
            }
            for n, g in ranked
        ],
    }


@tool("Weekly reports")
async def ime_weekly_reports(
    year: Annotated[int | None, Field(description="Persian year, e.g. 1405 (default all).", ge=1380, le=1500)] = None,
    limit: Annotated[int, Field(description="Max reports (1-60).", ge=1, le=60)] = 10,
) -> dict[str, Any]:
    """List the exchange's weekly market reports (گزارش هفتگی), newest first, with the PDF link of each.

    Only lists links to the Persian PDFs, does not read them. For a week's numbers use ime_market_summary.
    """
    page = await fetch(f"{SITE}/weeklyReports.html", page="/", text=True)
    reports = []
    for block in page.split("<table")[1:]:
        month = re.search(r"<th[^>]*>(.*?)</th>", block, re.S)
        for url, label in re.findall(r'<a[^>]*href="(/files/[^"]+?\.pdf)"[^>]*>(.*?)</a>', block, re.S):
            y = re.search(r"/WeeklyReports/(\d{4})/", url)
            reports.append(
                {
                    "month": html.unescape(re.sub(r"<[^>]+>", "", month.group(1))).strip() if month else None,
                    "week": html.unescape(re.sub(r"<[^>]+>", "", label)).strip(),
                    "year": int(y.group(1)) if y else None,
                    "url": SITE + url,
                }
            )
    if year:
        reports = [r for r in reports if r["year"] == year]
    return {"found": len(reports), "reports": reports[:limit]}
