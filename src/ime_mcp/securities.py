"""Derivative and securities boards: options, deposit certificates (gold, silver, ...), salaf, commodity funds."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field

from .http import BOARD, CDC_CONTRACTS, CDC_TRADES, FINANCE, OPTIONS, ApiError, fetch
from .ime import TEHRAN, Date, _check_len, _shift, _span, g2j, j2g
from .registry import tool

MAX_OPTION_DAYS = 10  # about 270 option contracts per trading day
SEARCH = Annotated[str | None, Field(description="Symbol, code or name contains this text.", max_length=80)]


def _latest(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """The rows of the newest day in `rows` (Persian dates compare as text)."""
    top = max((r[key] for r in rows), default=None)
    return [r for r in rows if r[key] == top]


def _hit(text: str | None, search: str | None) -> bool:
    return not (search and (s := search.strip().lower())) or s in (text or "").lower()


def _pct(now: float | None, before: float | None) -> float | None:
    return round(100 * (now - before) / before, 2) if now is not None and before else None


def _iso(persian: str) -> str:
    return "{}-{:02d}-{:02d}".format(*j2g(*map(int, persian.split("/"))))


async def _option_rows(f: str, t: str, contract_id: int) -> list[dict[str, Any]]:
    q = {"f": f, "t": t, "c": contract_id, "ot": 0, "lang": 8, "order": "asc", "offset": 0, "limit": 0}
    return (await fetch(OPTIONS, params=q, page="/optionboard.html"))["rows"]


def _option(r: dict[str, Any]) -> dict[str, Any]:
    desc = r.get("ContractDescription") or ""
    kind = re.search(r"اختیار معامله (خرید|فروش) (.*?) سررسید", desc)
    strike = re.search(r"قیمت اعمال ([\d,،]+)", desc)
    return {
        "date": r.get("DT"),
        "contract": r.get("ContractCode"),
        "type": {"خرید": "call", "فروش": "put"}.get(kind.group(1)) if kind else None,
        "underlying": kind.group(2) if kind else None,
        "strike": int(re.sub(r"\D", "", strike.group(1))) if strike else None,
        "expiry": r.get("DeliveryDate"),
        "first": r.get("FirstPrice"),
        "high": r.get("MaxPrice"),
        "low": r.get("MinPrice"),
        "last": r.get("LastPrice"),
        "settlement": r.get("TodaySettlementPrice"),
        "settlement_change_pct": r.get("SettlementPricePercent"),
        "volume": r.get("TradesVolume"),
        "value_rial": r.get("TradesValue"),
        "open_interest": r.get("OpenInterest"),
        "open_interest_change": r.get("ChangeOpenInterest"),
        "buyers": r.get("C_Buy"),
        "sellers": r.get("C_Sell"),
    }


@tool("Options board")
async def ime_options(
    date_from: Date = None,
    date_to: Date = None,
    option_type: Annotated[Literal["call", "put", "all"], Field(description="call (خرید), put (فروش) or all.")] = "all",
    search: Annotated[
        str | None,
        Field(
            description="Code or description contains this text, e.g. GCES or صندوق طلا.",
            max_length=80,
        ),
    ] = None,
    contract: Annotated[
        str | None,
        Field(
            description="One contract code: returns its day-by-day history.",
            max_length=24,
        ),
    ] = None,
    traded_only: Annotated[bool, Field(description="Only contracts that traded (volume above 0).")] = True,
    sort: Annotated[
        Literal["volume", "value", "open_interest", "settlement_change"],
        Field(description="Largest first (settlement_change by size of move)."),
    ] = "volume",
    limit: Annotated[int, Field(description="Max contracts or days to return (1-100).", ge=1, le=100)] = 30,
) -> dict[str, Any]:
    """Options on gold, gold coin, gold funds and saffron futures (اختیار معامله): one day's board or one contract's history.

    No dates: latest trading day. With dates (at most 10 days): every day in the range. `contract` (a code from
    the list): that contract's days, up to 45. Prices and strike are Rial. Daily market totals: ime_daily_totals(market="options").
    """
    f, t = _span(date_from, date_to, 7)
    if contract:
        code = contract.strip().lower()
        _check_len(f, t)
        found, day = [], t
        for _ in range(5):  # every active contract is listed each trading day, even without trades
            found = [r for r in await _option_rows(day, day, 0) if (r.get("ContractCode") or "").lower() == code]
            if found:
                break
            day = _shift(day, -1)
        if not found:
            raise ApiError(f"Contract {contract!r} not found in the 5 days up to {t}. Check the code with ime_options.")
        rows = await _option_rows(f, t, found[0]["ContractID"])
        days = sorted((_option(r) for r in rows), key=lambda x: x["date"], reverse=True)
        return {"from": f, "to": t, "contract": found[0]["ContractCode"], "days": days[:limit]}
    if date_from or date_to:
        _check_len(f, t, MAX_OPTION_DAYS)
    rows = await _option_rows(f, t, -1)
    if not (date_from or date_to):
        rows = _latest(rows, "DT")
    out = [_option(r) for r in rows if _hit(f"{r.get('ContractCode')} {r.get('ContractDescription')}", search)]
    if option_type != "all":
        out = [x for x in out if x["type"] == option_type]
    if traded_only:
        out = [x for x in out if x["volume"]]
    key = {"volume": "volume", "value": "value_rial", "open_interest": "open_interest"}.get(sort)
    out.sort(key=(lambda x: x[key] or 0) if key else (lambda x: abs(x["settlement_change_pct"] or 0)), reverse=True)
    return {
        "from": f,
        "to": t,
        "date": out[0]["date"] if out and not (date_from or date_to) else None,
        "contracts_found": len(out),
        "total_volume": sum(x["volume"] or 0 for x in out),
        "total_value_rial": round(sum(x["value_rial"] or 0 for x in out)),
        "contracts": out[:limit],
    }


@tool("Commodity securities trades")
async def ime_securities(
    kind: Annotated[
        Literal["all", "salaf", "certificate", "fund"],
        Field(description="salaf (سلف), certificate (saffron etc.), fund (commodity ETFs, mostly gold) or all."),
    ] = "all",
    date_from: Date = None,
    date_to: Date = None,
    search: SEARCH = None,
    sort: Annotated[
        Literal["value", "volume", "change", "date"],
        Field(description="value/volume largest first, change biggest move first, date newest first."),
    ] = "value",
    limit: Annotated[int, Field(description="Max rows to return (1-100).", ge=1, le=100)] = 30,
) -> dict[str, Any]:
    """Daily trades of the exchange's financial-market symbols: salaf, commodity deposit certificates and commodity funds.

    No dates: latest trading day; with dates every day in the range (at most 45). Prices are Rial per unit, value
    in Rial. Gold bar / gold coin / silver certificates: ime_certificates; live bid and ask: ime_board.
    """
    f, t = _span(date_from, date_to, 7)
    _check_len(f, t)
    q = {"f": f, "t": t, "c": "ALL", "ot": "ALL", "lang": 8, "order": "asc", "offset": 0, "limit": 0}
    rows = (await fetch(FINANCE, params=q, page="/standard-transactions.html"))["rows"]
    if not (date_from or date_to):
        rows = _latest(rows, "DT")
    prefix = {"salaf": "IRBK", "certificate": "IRK", "fund": "IRTK"}  # ISIN prefixes, checked against the site's lists
    out = []
    for r in rows:
        if kind != "all" and not r["Namad"].startswith(prefix[kind]):
            continue
        if not _hit(f"{r['LVal18AFC']} {r['Namad']} {r['NamadDescription']}", search):
            continue
        out.append(
            {
                "date": r["DT"],
                "symbol": r["LVal18AFC"],
                "isin": r["Namad"],
                "name": r["NamadDescription"],
                "close": r["PClosing"],
                "last": r["PDrCotVal"],
                "previous_close": r["PriceYesterday"],
                "change_pct": _pct(r["PClosing"], r["PriceYesterday"]),
                "trades": r["ZTotTran"],
                "volume": r["QTotTran5J"],
                "value_rial": r["QTotCap"],
                "low": r["PriceMin"],
                "high": r["PriceMax"],
            }
        )
    key = {"value": "value_rial", "volume": "volume", "date": "date"}.get(sort)
    out.sort(key=(lambda x: x[key] or 0) if key else (lambda x: abs(x["change_pct"] or 0)), reverse=True)
    return {
        "from": f,
        "to": t,
        "kind": kind,
        "rows_found": len(out),
        "total_value_rial": round(sum(x["value_rial"] or 0 for x in out)),
        "rows": out[:limit],
    }


def _day(x: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": x["PersianDate"],
        "first": x["FirstPrice"],
        "high": x["MaxPrice"],
        "low": x["MinPrice"],
        "last": x["LastPrice"],
        "settlement": x["TodaySettlementPrice"],
        "settlement_change_pct": x["SettlementPricePercent"],
        "volume": x["TradesVolume"],
        "value_rial": x["TradesValue"],
        "open_interest": x["OpenInterest"],
        "open_interest_change": x["ChangeOpenInterest"],
        "customers": x["ActiveCustomers"],
    }


@tool("Gold and other deposit certificates")
async def ime_certificates(
    commodity: Annotated[
        str | None,
        Field(
            description="Certificate id, code or name part: GoldBar, GoldCoin, SilverBar, SteelRebar... or طلا, سکه. Empty = all.",
            max_length=40,
        ),
    ] = None,
    date_from: Date = None,
    date_to: Date = None,
) -> dict[str, Any]:
    """Continuous commodity deposit certificates (گواهی سپرده پیوسته): gold bar, gold coin, silver, copper, steel and more.

    No `commodity`: every certificate with its latest day. With `commodity`: its day-by-day history (default last
    30 days, at most 90). Prices are Rial per certificate unit (about one gram for gold bar, one coin for GoldCoin).
    Fund and saffron symbols: ime_securities.
    """
    contracts = await fetch(CDC_CONTRACTS)
    pick = None
    if commodity and (c := commodity.strip().lower()):
        pick = next(
            (x for x in contracts if c == str(x["ID"]) or c == x["Code"].lower()),
            next((x for x in contracts if c in x["Code"].lower() or c in x["Description"].lower()), None),
        )
        if not pick:
            raise ApiError("Unknown certificate. Known: " + ", ".join(f"{x['Code']} ({x['ID']})" for x in contracts))
    f, t = _span(date_from, date_to, 30 if pick else 7)
    _check_len(f, t, 90)
    rows: list[dict[str, Any]] = []
    for page in range(1, 6):
        body = {
            "fromDate": _iso(f),
            "toDate": _iso(t),
            "pageNumber": page,
            "pageSize": 100,
            "customFilter": str(pick["ID"]) if pick else "",
            "sortOrder": "desc",
        }
        r = await fetch(CDC_TRADES, body=body)
        rows += r["Data"]
        if not r.get("HasNextPage"):
            break
    if pick:
        days = sorted(rows, key=lambda x: x["PersianDate"], reverse=True)
        return {
            "from": f,
            "to": t,
            "certificate": pick["Code"],
            "name": pick["Description"],
            "days": [_day(x) for x in days],
        }
    names = {x["ID"]: x for x in contracts}
    best: dict[int, dict[str, Any]] = {}
    for x in rows:
        if x["CommodityID"] not in best or x["PersianDate"] > best[x["CommodityID"]]["PersianDate"]:
            best[x["CommodityID"]] = x
    return {
        "from": f,
        "to": t,
        "certificates": [
            {
                "id": i,
                "code": names.get(i, {}).get("Code"),
                "name": names.get(i, {}).get("Description"),
                **_day(x),
            }
            for i, x in best.items()
        ],
    }


@tool("Live board of funds, certificates and salaf")
async def ime_board(
    kind: Annotated[
        Literal["fund", "certificate", "salaf"],
        Field(description="fund (mostly gold), certificate (saffron etc.) or salaf."),
    ] = "fund",
    search: SEARCH = None,
    sort: Annotated[
        Literal["value", "volume", "change"],
        Field(description="value/volume largest first, change biggest move first."),
    ] = "value",
    limit: Annotated[int, Field(description="Max symbols to return (1-60).", ge=1, le=60)] = 20,
) -> dict[str, Any]:
    """Market-view board (cdn.ime.co.ir) with the best bid and ask: use it to see where a fund or certificate trades now.

    Live during the session; after the close the last session (see `time`, `date`). Value in Rial. Daily history:
    ime_securities.
    """
    param = {"fund": "sandoq", "certificate": "gavahi", "salaf": "salaf"}[kind]
    rows = await fetch(BOARD, params={"param": param})
    out = []
    for r in rows:
        if not _hit(f"{r.get('Symbol')} {r.get('Code')} {r.get('Name')} {r.get('EnName')}", search):
            continue
        ms = re.search(r"\d+", r.get("ModifyDate") or "")
        d = datetime.fromtimestamp(int(ms.group()) / 1000, TEHRAN) if ms else None
        out.append(
            {
                "symbol": r["Symbol"],
                "isin": r["Code"],
                "name": r["Name"],
                "date": "{}/{:02d}/{:02d}".format(*g2j(d.year, d.month, d.day)) if d else None,
                "time": r.get("Time"),
                "last": r["LastPrice"],
                "close": r["FinalPrice"],
                "previous_close": r["YesterdayPrice"],
                "change_pct": _pct(r["LastPrice"], r["YesterdayPrice"]),
                "low": r["MinPrice"],
                "high": r["MaxPrice"],
                "volume": r["Volume"],
                "value_rial": round(r["Value"] * 1000),  # the board reports thousand Rial
                "trades": r["Quantity"],
                "bid": r["DemandPrice1"],
                "bid_volume": r["DemandVolume1"],
                "ask": r["OfferPrice1"],
                "ask_volume": r["OfferVolume1"],
            }
        )
    key = {"value": "value_rial", "volume": "volume"}.get(sort)
    out.sort(key=(lambda x: x[key] or 0) if key else (lambda x: abs(x["change_pct"] or 0)), reverse=True)
    return {"kind": kind, "found": len(out), "symbols": out[:limit]}
