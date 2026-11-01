"""Shared async HTTP client for ime.co.ir (ASMX web service, grid handlers and news pages).

Every tool goes through `fetch`, which caps concurrency, caches answers briefly and turns HTTP failures
into `ToolError` messages the model can act on.
"""

from __future__ import annotations

import asyncio
import copy
import json as json_lib
import os
import random
import time
from typing import Any

import httpx
from curl_cffi.const import CurlOpt
from httpx_curl_cffi import AsyncCurlTransport
from mcp.server.mcpserver.exceptions import ToolError

SITE = "https://www.ime.co.ir"
ASMX = f"{SITE}/subsystems/ime/services/home/imedata.asmx"
AUCTION = f"{SITE}/subsystems/ime/auction/auction.ashx"
EXPORT = f"{SITE}/subsystems/ime/fiziki/export.ashx"
OPTIONS = f"{SITE}/subsystems/ime/option/optionboarddata.ashx"
FINANCE = f"{SITE}/subsystems/ime/bazaremali/bazaremalidata.ashx"
PREMIUM_TRADES = f"{SITE}/SubSystems/IME/Fiziki/AmarePermium.ashx"
CDC_TRADES = "https://dataapi.ime.co.ir/api/CDC/CDCTrades"  # data API of gold.ime.co.ir (Blazor app)
CDC_CONTRACTS = "https://dataapi.ime.co.ir/api/CDC/CDCContracts"
BOARD = "https://cdn.ime.co.ir/getFinancialMarketData"  # market view board of cdn.ime.co.ir
# the site whose pages call each host (Origin / Referer), checked in Chrome 2026-11-01
ORIGINS = {"dataapi.ime.co.ir": "https://gold.ime.co.ir", "cdn.ime.co.ir": "https://cdn.ime.co.ir"}

HEADERS = {
    # User-Agent, sec-ch-ua and TLS come from the impersonated Chrome profile (see _get_client).
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "priority": "u=1, i",
}

MAX_CONCURRENCY = 3
JITTER = (0.1, 0.4)  # seconds before each uncached call
MAX_RETRIES = 2
MAX_RETRY_WAIT = 10  # cap for Retry-After and backoff, seconds
CACHE_TTL = 120  # seconds
CACHE_MAX = 64
RETRY_DELAY = 0.5  # seconds, doubled per retry
MAX_BODY = 8_000_000  # bytes; larger responses are refused
# jQuery's dataType "text" call (checked in Chrome 2026-10-31).
JQUERY = "text/plain, */*; q=0.01"
AXIOS = "application/json, text/plain, */*"  # cdn.ime.co.ir board (checked in Chrome 2026-11-01)
PAGE_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
    "application/signed-exchange;v=b3;q=0.7"
)
HOSTS = {"www.ime.co.ir", "dataapi.ime.co.ir", "cdn.ime.co.ir"}

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None
_limit: asyncio.Semaphore | None = None
_proxy_index = 0
_retired: set[asyncio.Task] = set()
_cache: dict[tuple, tuple[float, Any]] = {}


class _XhrTransport(AsyncCurlTransport):
    """The Chrome profile sends navigation-only headers; a None value makes curl drop them on XHR calls."""

    def _create_request_params(self, req: httpx.Request) -> dict[str, Any]:
        # The parent drops "accept: */*" as an httpx default; curl would then send Chrome's page Accept instead.
        accept = req.headers.get("accept")
        p = super()._create_request_params(req)
        extra = [(b"cache-control", None)]  # Chrome sends max-age=0 only on a reload
        if req.headers.get("sec-fetch-mode") != "navigate":
            extra += [(b"upgrade-insecure-requests", None), (b"sec-fetch-user", None)]
        p["headers"] = [*p["headers"], *extra, *([(b"accept", b"*/*")] if accept == "*/*" else [])]
        return p


class ApiError(ToolError):
    """A failed upstream call. `status` is the HTTP status, or None for network errors."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport (tests use httpx.MockTransport). Drops the current client."""
    global _transport, _client, _limit, _proxy_index
    _transport, _client, _limit, _proxy_index = transport, None, None, 0
    _cache.clear()


def _proxies() -> list[str]:
    """IME_MCP_PROXY: one proxy URL, or a comma-separated list used one at a time."""
    return [p.strip() for p in os.environ.get("IME_MCP_PROXY", "").split(",") if p.strip()]


def _next_proxy(client: httpx.AsyncClient) -> None:
    """Sticky pool: move to the next proxy after a block or connect error; the next call rebuilds the client.

    Only the client that failed may rotate. The old client is closed late because other requests may still use it.
    """
    global _client, _limit, _proxy_index
    if len(_proxies()) < 2 or client is not _client:
        return
    _client, _limit, _proxy_index = None, None, _proxy_index + 1
    t = asyncio.create_task(_close_later(client))
    _retired.add(t)
    t.add_done_callback(_retired.discard)


async def _close_later(client: httpx.AsyncClient) -> None:
    await asyncio.sleep(30)  # longer than the request timeout
    await client.aclose()


def _get_client() -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
    global _client, _limit
    if _client is None:
        # System proxy settings are ignored; the proxy only comes from IME_MCP_PROXY. curl_cffi
        # presents Chrome's TLS/HTTP2 fingerprint and default headers. The proxy goes to the transport.
        proxies = _proxies()
        _client = httpx.AsyncClient(
            transport=_transport
            or _XhrTransport(
                impersonate="chrome",
                default_headers=True,
                curl_options={
                    CurlOpt.NOPROXY: "*"
                },  # httpx-curl-cffi drops its own NOPROXY unless this dict is non-empty
                proxy=proxies[_proxy_index % len(proxies)] if proxies else None,
                max_connections=2 * MAX_CONCURRENCY,
            ),
            headers=HEADERS,
            timeout=httpx.Timeout(40, connect=8),
            limits=httpx.Limits(max_connections=2 * MAX_CONCURRENCY),
            follow_redirects=False,
            trust_env=False,
        )
        _limit = asyncio.Semaphore(MAX_CONCURRENCY)
    assert _limit is not None
    return _client, _limit


async def fetch(
    url: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    page: str = "/",
    text: bool = False,
    cache: bool = True,
) -> Any:
    """Call ime.co.ir the way its pages do and return the parsed JSON body (or the text when `text`).

    With `body` it is a POST of that JSON (the ASMX service); otherwise a GET with `params`. `page` is the site
    page the call is made from (Referer). Retried up to MAX_RETRIES times on timeout, network error, 5xx or 429,
    with jittered exponential backoff or after Retry-After when sent. 403 is never retried.
    """
    query = dict(params or {})
    host = httpx.URL(url).host
    if host not in HOSTS:
        raise ApiError(f"Refusing to call unexpected host {host}.")
    key = (url, tuple(sorted(query.items())), json_lib.dumps(body, sort_keys=True), text)
    if cache and (hit := _cache.get(key)) and time.monotonic() - hit[0] < CACHE_TTL:
        return copy.deepcopy(hit[1])
    origin = ORIGINS.get(host, SITE)
    headers = {"Accept": JQUERY, "Referer": origin + page, "X-Requested-With": "XMLHttpRequest"}
    if host == "dataapi.ime.co.ir":  # called by fetch() in gold.ime.co.ir: no XHR header, cross-origin same-site
        headers = {"Accept": "*/*", "Referer": origin + "/", "Origin": origin, "sec-fetch-site": "same-site"}
    elif host == "cdn.ime.co.ir":  # axios call of the market board, with the custom header the page always sends
        headers = {"Accept": AXIOS, "Referer": origin + "/", "X-Security-Request": "required"}
    if body is not None:
        headers["Origin"] = origin
        headers["Content-Type"] = "application/json; charset=utf-8"
    if text:
        headers = {"Referer": origin + page, "sec-fetch-mode": "navigate", "sec-fetch-dest": "document"}
        headers["Accept"] = PAGE_ACCEPT
        headers["priority"] = "u=0, i"
    for attempt in range(MAX_RETRIES + 1):
        last = attempt == MAX_RETRIES
        wait = RETRY_DELAY * 2**attempt * random.uniform(1, 1.5)
        try:
            r, content = await _request(url, query, body, headers, host)
        except ApiError as e:
            if last or e.status is not None:
                raise
            await asyncio.sleep(min(wait, MAX_RETRY_WAIT))
            continue
        if (r.status_code == 429 or r.status_code >= 500) and not last:
            await asyncio.sleep(min(_retry_after(r) or wait, MAX_RETRY_WAIT))
            continue
        break

    if r.status_code >= 400:
        raise ApiError(_status_message(r, host), r.status_code)
    if text:
        result: Any = content.decode("utf-8", "replace")
    else:
        try:
            result = json_lib.loads(content)
        except ValueError as e:
            raise ApiError(f"{host} returned a non-JSON response (HTTP {r.status_code}).", r.status_code) from e
    if cache:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.monotonic(), copy.deepcopy(result))
    return result


async def _send(client, limit, url, query, body, headers, host) -> tuple[httpx.Response, bytes]:
    try:
        async with limit:
            await asyncio.sleep(random.uniform(*JITTER))
            if body is None:
                req = client.stream("GET", url, params=query, headers=headers)
            else:
                req = client.stream("POST", url, params=query, headers=headers, content=json_lib.dumps(body))
            async with req as r:
                return r, await _read_capped(r, host)
    except httpx.TimeoutException as e:
        raise ApiError(f"{host} did not answer in time. Try again in a moment.") from e
    except httpx.RequestError as e:
        if isinstance(e, httpx.ConnectError | httpx.ProxyError):
            _next_proxy(client)
        raise ApiError(
            f"Could not reach {host} ({type(e).__name__}). ime.co.ir answers from Iran; check the internet "
            "connection (or the IME_MCP_PROXY setting if you use one)."
        ) from e


async def _request(url, query, body, headers, host) -> tuple[httpx.Response, bytes]:
    client, limit = _get_client()
    r, content = await _send(client, limit, url, query, body, headers, host)
    if r.status_code in (403, 429):
        _next_proxy(client)  # blocked: try the next proxy on the following call
    return r, content


async def _read_capped(r: httpx.Response, host: str) -> bytes:
    """Read the body, refusing anything over MAX_BODY so one huge answer cannot flood memory or context."""
    buf = bytearray()
    async for chunk in r.aiter_bytes():
        buf += chunk
        if len(buf) > MAX_BODY:
            raise ApiError(f"{host} sent a response over {MAX_BODY // 1_000_000} MB; refused.", r.status_code)
    return bytes(buf)


def _retry_after(r: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After on a 429/503, else None (HTTP-date form is ignored)."""
    v = r.headers.get("retry-after", "")
    return float(v) if r.status_code in (429, 503) and v.replace(".", "", 1).isdigit() else None


def _status_message(r: httpx.Response, host: str) -> str:
    code = r.status_code
    if code == 403:
        return f"{host} blocked the request (HTTP 403). Try another network or set IME_MCP_PROXY."
    if code == 404:
        return f"{host} found nothing at that address (HTTP 404)."
    if code == 429:
        return f"{host} is rate limiting requests (HTTP 429). Wait a minute before retrying."
    if code >= 500:
        return f"{host} had a server error (HTTP {code}). Check the dates (Persian yyyy/mm/dd) and ids, or retry later."
    return f"{host} rejected the request (HTTP {code})."
