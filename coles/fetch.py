"""Coles transport: plain curl_cffi on the site's own JSON, through sticky
Australian residential exits, with a headed cookie mint on the browser box
as the last resort.

Two upstreams, both on www.coles.com.au and both authenticated by the public
Azure APIM key the site ships in every page (validated 2026-10-05):

  * BFF   GET/POST /api/bff/<path>        REST gateway behind the storefront
      /products/search                    keyword search, category browse,
                                          specials, brand listings (one
                                          endpoint, 48 products a page)
      /products/<id>?storeId=             product record with live stock
      /products/search/suggestions        search autocomplete
      /products/recommendations/alternatives   (POST) substitutes
  * GQL   POST /api/graphql               raw documents (coles/queries.py):
                                          product details (GTIN, nutrition,
                                          variations), bulk product info,
                                          the category tree, store finder,
                                          store details, locality lookup,
                                          stockists, recipes, holidays

Nothing needs a login or a page-derived token. The Next.js data routes
(/_next/data/<buildId>/...) carry the same records but depend on a build id
that changes with every deploy, so they are not used.

Anti-bot: Imperva (Incapsula) challenges by exit geography, not by TLS
fingerprint — Australian, NZ and US residential exits get JSON immediately,
GB / IN exits and datacenter IPs get a 212-byte page that loads
/_Incapsula_Resource. So:

  * every worker thread holds one sticky Australian exit (config.coles_proxy)
    and one curl session on it, rotated after config.COLES_REQUESTS_PER_EXIT
    requests or on any block / transport failure;
  * when config.COLES_MAX_ATTEMPTS exits in a row are challenged, ONE headed
    load of the home page (single-flight) mints the Incapsula cookies on a
    fresh exit. Since 2026-10-22 that load runs on the browser box, never on
    GKE: browser_client.mint("coles", proxy=<fresh sticky AU port>)
    (recipes/coles.py) returns the cookies and the pod replays them over
    curl_cffi on that same port (one proxy port = one IP for the box
    and the pod) — proven on a challenged GB exit: visid_incap_* +
    incap_ses_* + nlbi_* turn the challenge into JSON, reese84 alone does
    not — and every thread shares that clearance for
    config.COLES_CLEARANCE_TTL.

Since 2026-11-11 everything on www.coles.com.au EXCEPT /api/graphql — the
BFF, the home page (key refresh) and the floor-plan PNG — is tried ONCE
through the gateway exit first (config.COLES_GATEWAY_EXIT = "gateway:au", the
Sydney gateway; _gateway_send): 147 of 147 such requests answered there
with the full records, a fresh gateway address per request and no cookies
kept. A gateway failure or challenge falls through to the residential
attempts above, unchanged. /api/graphql stays on the residential exit:
Incapsula answers it 403 ("Request unsuccessful. Incapsula incident ID")
from the gateway, 10 of 10, Sydney and US alike, GET or POST, with or
without cookies (evidence table in config.py's Coles block).

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  ColesUpstreamError  transport failure / 5xx / unexpected body — retryable
  ColesBlocked        Incapsula challenge / 403 / 429            — retryable on a new exit
  ColesBadRequest     upstream rejected the params (bad store id, …)
  ColesNotFound       product / store / recipe does not exist

Smoke test:  python coles/fetch.py [search term]
"""
import json
import os
import re
import sys
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait as wait_futures

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_client
import config
import egress
from browser_client import BoxRefused, BoxUnavailable
from coles.queries import DOCUMENTS
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from scraper_utils import fanout, memo, sessions

SITE = "https://www.coles.com.au"
BFF = SITE + "/api/bff"
GRAPHQL = SITE + "/api/graphql"
IMPERSONATE = "chrome"
TIMEOUT = 40

# The headers the storefront's own fetch layer sends with every API call.
API_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": egress.site_accept_language("coles"),
    "dsch-channel": "coles.online.1site.desktop",
    "x-api-version": "2",
    "origin": SITE,
    "referer": SITE + "/",
}

BLOCK_MARKERS = ("_Incapsula_Resource", "Incapsula incident", "Request unsuccessful",
                 "Pardon Our Interruption")
INCAPSULA_COOKIE_PREFIXES = ("visid_incap", "incap_ses", "nlbi_", "reese84")
BOX_SITE = "coles"               # recipes/coles.py (home page seed, 40 s settle, ttl 900)
KEY_PATTERN = re.compile(r'"BFF_API_SUBSCRIPTION_KEY"\s*:\s*"([0-9a-f]{32})"')


class ColesUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unexpected body."""


class ColesBlocked(ColesUpstreamError, Blocked):
    """Incapsula challenge / 403 / 429."""


class ColesBadRequest(BadRequest):
    """Coles rejected the params."""


class ColesNotFound(NotFound):
    """The product / store / recipe does not exist."""


# ---- subscription key ----------------------------------------------------------

_key = config.COLES_SUBSCRIPTION_KEY
_key_lock = threading.Lock()


def _refresh_key(stale):
    """Re-read the APIM key from the home page after a 401 (single-flight:
    a thread that waited reuses the winner's key). Returns True when the key
    changed."""
    global _key
    with _key_lock:
        if _key != stale:
            return True
        resp = _send("GET", SITE + "/", headers={"accept": "text/html"}, api=False)
        found = KEY_PATTERN.search(resp.text or "")
        if not found or found.group(1) == stale:
            return False
        _key = found.group(1)
        print("coles: subscription key refreshed from the home page")
        return True


# ---- identities ------------------------------------------------------------------
# Thread-local: one sticky exit + curl session per worker (a curl handle must
# not be shared across threads). Process-wide: the browser-minted clearance
# {proxy, cookies, minted_at} that every thread adopts while it is fresh.

_local = threading.local()
_clearance = None
_clearance_lock = threading.Lock()
_mint_lock = threading.Lock()


def _current_clearance():
    with _clearance_lock:
        clearance = _clearance
    if clearance and time.monotonic() - clearance["minted_at"] < config.COLES_CLEARANCE_TTL:
        return clearance
    return None


def _drop_session():
    sess = getattr(_local, "session", None)
    _local.session = None
    _local.clearance = None
    sessions.close_quietly(sess)


def _new_session(proxy, cookies=None):
    from curl_cffi import requests as curl_requests
    sess = curl_requests.Session(impersonate=IMPERSONATE)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    for name, value in (cookies or {}).items():
        sess.cookies.set(name, value, domain=".coles.com.au")
    return sess


def _session():
    """The thread's session: on the shared clearance when one is fresh, else
    on the thread's own sticky exit (rotated every COLES_REQUESTS_PER_EXIT)."""
    clearance = _current_clearance()
    sess = getattr(_local, "session", None)
    if clearance is not None:
        if sess is None or getattr(_local, "clearance", None) is not clearance:
            _drop_session()
            sess = _new_session(clearance["proxy"], clearance["cookies"])
            _local.session, _local.clearance, _local.uses = sess, clearance, 0
        return sess
    if (sess is None or getattr(_local, "clearance", None) is not None
            or getattr(_local, "uses", 0) >= config.COLES_REQUESTS_PER_EXIT):
        _drop_session()
        sess = _new_session(config.coles_proxy())
        _local.session, _local.uses = sess, 0
    return sess


def _mint_clearance():
    """One /mint on the coles browser box through a fresh sticky AU exit
    (recipes/coles.py: a throwaway headed load of the home page; the
    Incapsula challenge clears itself and sets its cookies). Returns
    {"proxy", "cookies", "minted_at"}: the exit every thread rebuilds on and
    the Incapsula cookies to replay there. A box that is down or busy is a
    ColesUpstreamError; a box that could not clear the site on this exit, or
    answered without an incap_ses_* cookie, is a ColesBlocked."""
    proxy = config.coles_proxy()
    print("coles: every curl exit was challenged; minting Incapsula cookies on the browser box...")
    try:
        ident = browser_client.mint(BOX_SITE, proxy=proxy)
    except BoxUnavailable as e:
        raise ColesUpstreamError(f"browser box unavailable for the Incapsula cookie mint: {e}")
    except BoxRefused as e:
        raise ColesBlocked(f"the Incapsula challenge did not clear on the browser box: {e}")
    cookies = {c["name"]: c["value"] for c in ident.get("cookies") or []
               if c["name"].startswith(INCAPSULA_COOKIE_PREFIXES)}
    if not any(name.startswith("incap_ses") for name in cookies):
        raise ColesBlocked("the browser box load set no Incapsula session cookie")
    print(f"coles: clearance minted ({len(cookies)} cookies)")
    return {"proxy": proxy, "cookies": cookies, "minted_at": time.monotonic()}


def _ensure_clearance(failed=None):
    """Mint a clearance unless another thread already did (single-flight).
    `failed` is the clearance the caller was just blocked on, if any."""
    global _clearance
    with _mint_lock:
        current = _current_clearance()
        if current is not None and current is not failed:
            return current
        clearance = _mint_clearance()
        with _clearance_lock:
            _clearance = clearance
        return clearance


# ---- requests ----------------------------------------------------------------------

def _is_block(resp):
    if resp.status_code in (403, 429):
        return True
    if "json" in (resp.headers.get("content-type") or ""):
        return False
    text = (resp.text or "")[:20000]
    return any(marker in text for marker in BLOCK_MARKERS)


def _request_headers(body, headers, api, language=None):
    request_headers = dict(API_HEADERS) if api else {}
    if api:
        request_headers["ocp-apim-subscription-key"] = _key
        if language:
            request_headers["accept-language"] = language
    if body is not None:
        request_headers["content-type"] = "application/json"
    request_headers.update(headers or {})
    return request_headers


def _gateway_session():
    """The thread's session on the gateway exit (config.COLES_GATEWAY_EXIT);
    it announces the gateway country's Accept-Language."""
    sess = getattr(_local, "gateway", None)
    if sess is None:
        sess = _local.gateway = egress.exit_session(config.coles_gateway_exit(), impersonate=IMPERSONATE)
    return sess


def _gateway_send(method, url, params, body, headers, api):
    """ONE try through the gateway exit, in front of the residential
    attempts: the response, or None when the gateway failed or Incapsula
    refused it (the caller then runs the residential attempts exactly as
    before, browser mint included). Stateless: every request leaves from
    another gateway address, so the Incapsula cookies an answer sets are not
    carried to the next one."""
    exit = config.coles_gateway_exit()
    try:
        sess = _gateway_session()
        resp = sess.request(method, url, params=params,
                            data=json.dumps(body) if body is not None else None,
                            headers=_request_headers(body, headers, api, egress.accept_language(exit)),
                            timeout=TIMEOUT)
        sess.cookies.clear()
    except Exception as e:
        sess, _local.gateway = getattr(_local, "gateway", None), None
        sessions.close_quietly(sess)
        print(f"coles: gateway exit ({exit}) failed, residential exit next: {type(e).__name__}: {e}")
        return None
    if _is_block(resp):
        print(f"coles: gateway exit ({exit}) was challenged (HTTP {resp.status_code}), residential exit next")
        return None
    return resp


def _send(method, url, params=None, body=None, headers=None, api=True):
    """One upstream call with exit rotation and the browser fallback.
    Returns the curl response of the first non-blocked attempt; raises
    ColesBlocked / ColesUpstreamError otherwise. Everything but
    /api/graphql (Incapsula refuses it from the gateway) is tried once through the
    gateway exit first when config.COLES_GATEWAY_EXIT names one."""
    if config.coles_gateway_exit() and not url.startswith(GRAPHQL):
        resp = _gateway_send(method, url, params, body, headers, api)
        if resp is not None:
            return resp
    last = None
    attempts = config.COLES_MAX_ATTEMPTS
    minted = False
    attempt = 0
    while attempt < attempts:
        attempt += 1
        request_headers = _request_headers(body, headers, api)
        used = _current_clearance()
        try:
            sess = _session()
            _local.uses = getattr(_local, "uses", 0) + 1
            resp = sess.request(method, url, params=params,
                                data=json.dumps(body) if body is not None else None,
                                headers=request_headers, timeout=TIMEOUT)
        except Exception as e:
            _drop_session()
            last = ColesUpstreamError(f"{type(e).__name__}: {e}")
            continue
        if not _is_block(resp):
            return resp
        _drop_session()
        last = ColesBlocked(f"Incapsula challenge (HTTP {resp.status_code})")
        if attempt == attempts and config.COLES_BROWSER_FALLBACK and not minted:
            # Every exit was challenged: mint cookies once and go again.
            try:
                _ensure_clearance(failed=used)
            except ColesBlocked as e:
                raise ColesBlocked(f"Incapsula challenge and the browser fallback failed: {e}")
            except ColesUpstreamError as e:
                # The box is down or busy: an upstream error, not a block.
                raise ColesUpstreamError(f"Incapsula challenge and the browser box is unavailable: {e}")
            except Exception as e:
                raise ColesBlocked(f"Incapsula challenge and the browser fallback failed: {e}")
            minted = True
            attempts += 2
    raise last


def _json(resp, what):
    try:
        return resp.json()
    except Exception:
        raise ColesUpstreamError(f"{what} returned a non-JSON body (HTTP {resp.status_code})")


def _error_message(payload):
    """The first upstream error message of a BFF error envelope
    ({"errors": [{"errorCode", "message"}]} or {"statusCode", "message"})."""
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            return errors[0].get("message") or errors[0].get("errorCode")
        return payload.get("message")
    return None


def bff(path, params=None, method="GET", body=None, allow_empty=False):
    """Call /api/bff<path>. Returns the parsed JSON (None for an empty 200
    body when allow_empty — how the gateway answers an unknown product id)."""
    url = BFF + path
    used = _key
    resp = _send(method, url, params=params, body=body)
    if resp.status_code == 401 and _refresh_key(used):
        resp = _send(method, url, params=params, body=body)
    if resp.status_code == 200:
        if not (resp.text or "").strip():
            if allow_empty:
                return None
            raise ColesUpstreamError(f"{path} returned an empty body")
        return _json(resp, path)
    message = None
    try:
        message = _error_message(resp.json())
    except Exception:
        pass
    message = message or f"HTTP {resp.status_code}"
    if resp.status_code == 400:
        raise ColesBadRequest(message)
    if resp.status_code == 404:
        raise ColesNotFound(message)
    raise ColesUpstreamError(f"{path}: {message}")


def gql(operation, variables):
    """Run one of coles/queries.py's documents. Returns `data`; when the
    gateway reports errors the first one is mapped to the taxonomy unless
    `data` still carries the requested root (partial success)."""
    payload = {"operationName": operation, "variables": variables, "query": DOCUMENTS[operation]}
    used = _key
    resp = _send("POST", GRAPHQL, body=payload)
    if resp.status_code == 401 and _refresh_key(used):
        resp = _send("POST", GRAPHQL, body=payload)
    if resp.status_code >= 500:
        raise ColesUpstreamError(f"{operation}: HTTP {resp.status_code}")
    result = _json(resp, operation)
    data = result.get("data") if isinstance(result, dict) else None
    errors = result.get("errors") if isinstance(result, dict) else None
    if errors:
        if isinstance(data, dict) and any(v is not None for v in data.values()):
            return data
        first = errors[0] if isinstance(errors[0], dict) else {}
        message = first.get("message") or "GraphQL error"
        extensions = first.get("extensions") or {}
        code = extensions.get("code")
        detail = json.dumps(extensions.get("response") or extensions.get("validationErrors") or "")
        if "not found" in message.lower() or "Invalid StoreId" in detail:
            raise ColesNotFound(message)
        if code in ("BAD_USER_INPUT", "VALIDATION_ERROR", "GRAPHQL_VALIDATION_FAILED"):
            raise ColesBadRequest(extensions.get("description") or message)
        raise ColesUpstreamError(f"{operation}: {message}")
    if not isinstance(data, dict):
        raise ColesUpstreamError(f"{operation} returned no data")
    return data


# ---- app gateway (colesappbff) -------------------------------------------------------
# The Coles *app* API carries the real per-store aisle + map pin that the
# website BFF only returns as a "$STORE" placeholder. It is gated by an
# Imperva/Distil anti-bot token (X-D-Token) minted by a running copy of the
# app (a Hetzner Redroid box) and served over HTTP at config.COLES_TOKEN_URL.
# The token is reusable and NOT bound to IP or device, so these calls run from
# the pod's own IP with no proxy; on a 403 the token is re-minted once.

APP_GATEWAY = "https://apigw.coles.com.au/digital/colesappbff"
APP_TIMEOUT = 30
APP_HEADERS = {
    "Client": "Android 6.90.1",
    "X-App-Version": "Release:6.90.1(20456)",
    "X-Device-Model": "Google sdk_gphone64_arm64",
    "X-Client-OS": "Android:14",
    "dsch-channel": "coles.app.aos",
    "Accept-Language": "en-AU;q=1",
    "User-Agent": "okhttp/5.3.2",
}

_xd = {"value": None, "expires": 0.0}
_xd_lock = threading.Lock()


def _fetch_xd_token():
    """GET the current X-D-Token from the minter box (config.COLES_TOKEN_URL)."""
    if not config.COLES_TOKEN_URL:
        raise ColesUpstreamError("COLES_TOKEN_URL is not configured; in-store aisle is unavailable")
    from curl_cffi import requests as curl_requests
    try:
        resp = curl_requests.get(config.COLES_TOKEN_URL, timeout=15)
    except Exception as e:
        raise ColesUpstreamError(f"X-D-Token fetch failed: {type(e).__name__}: {e}")
    if resp.status_code != 200:
        raise ColesUpstreamError(f"X-D-Token endpoint returned HTTP {resp.status_code}")
    token = (_json(resp, "x-d-token") or {}).get("token")
    if not token:
        raise ColesUpstreamError("X-D-Token endpoint returned no token")
    return token


def xd_token(force=False, replace=None):
    """Process-wide cache of the X-D-Token (reddit.bearer pattern). `replace`
    re-fetches only when `replace` is still current, so many threads rejected
    at once cause a single re-fetch."""
    now = time.time()
    current = _xd["value"]
    if replace is not None and current != replace:
        return xd_token()
    if not force and replace is None and current and _xd["expires"] > now:
        return current
    with _xd_lock:
        current = _xd["value"]
        if replace is not None and current != replace:
            return current
        if not force and replace is None and current and _xd["expires"] > time.time():
            return current
        _xd["value"] = None
        token = _fetch_xd_token()
        _xd["value"] = token
        _xd["expires"] = time.time() + config.COLES_APP_TOKEN_TTL
        return token


def _app_session():
    """One curl session per worker thread for the app gateway. Plain TLS (NO
    browser impersonation) to match the okhttp client the app uses — Imperva
    403s app headers that arrive with a browser JA3 (same as the Shein app
    finding); the gate here is the X-D-Token, not the TLS fingerprint. No proxy
    (the token is not IP-bound)."""
    sess = getattr(_local, "app_session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session()
        _local.app_session = sess
    return sess


def _app_request(method, path, params=None, body=None):
    url = APP_GATEWAY + path
    token = xd_token()
    for attempt in range(2):
        headers = dict(APP_HEADERS)
        headers["Ocp-Apim-Subscription-Key"] = config.COLES_APP_SUBSCRIPTION_KEY
        headers["X-D-Token"] = token
        headers["X-Device-Id"] = str(uuid.uuid4())
        headers["dsch-sessionid"] = str(uuid.uuid4())
        headers["dsch-searchid"] = str(uuid.uuid4())
        headers["dsch-visitorid"] = uuid.uuid4().hex
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        try:
            resp = _app_session().request(
                method, url, params=params,
                data=json.dumps(body) if body is not None else None,
                headers=headers, timeout=APP_TIMEOUT)
        except Exception as e:
            raise ColesUpstreamError(f"app {path}: {type(e).__name__}: {e}")
        if resp.status_code == 403 and attempt == 0:
            token = xd_token(replace=token)
            continue
        if resp.status_code == 404:
            raise ColesNotFound("app product not found")
        if resp.status_code == 200:
            return _json(resp, path)
        raise ColesUpstreamError(f"app {path}: HTTP {resp.status_code}")
    raise ColesBlocked(f"app {path}: token rejected after re-mint")


def app_product(sku, store):
    """One product's in-store record (aisle + map pin + availability) from the
    app gateway, at the given numeric store id. ColesNotFound when the sku is
    not ranged at that store."""
    return _app_request("GET", f"/v3/api/2/products/{sku}",
                        params={"type": "sku", "htmlBody": "true", "storeId": store,
                                "shoppingMethod": "inStore", "includeLiquor": "true"})


# The app's GraphQL gateway (appsgql, NOT colesappbff) carries the in-store MAP: the
# floor-plan asset path + the pin transform. Same X-D-Token gate as the REST app API.
APPSGQL = "https://apigw.coles.com.au/digital/appsgql/v1/graphql"
_INSTORE_MAP_QUERY = ("query InstoreMapQuery($storeId: ID!) { inStoreMap(storeId: $storeId) "
                      "{ __typename ... on InStoreMapData { mapLocation mx my bx by rotation } } }")


def app_instore_map(store):
    """The store's in-store map metadata from the app GraphQL gateway, X-D-Token-gated
    like app_product: {mapLocation, mx, my, bx, by, rotation}, or None when the store has
    no map (InStoreMapDataNotFound). `mapLocation` is a www.coles.com.au AEM path."""
    token = xd_token()
    body = {"operationName": "InstoreMapQuery", "query": _INSTORE_MAP_QUERY, "variables": {"storeId": str(store)}}
    for attempt in range(2):
        headers = dict(APP_HEADERS)
        headers["Ocp-Apim-Subscription-Key"] = config.COLES_APP_SUBSCRIPTION_KEY
        headers["X-D-Token"] = token
        headers["X-Device-Id"] = str(uuid.uuid4())
        headers["Content-Type"] = "application/json; charset=utf-8"
        try:
            resp = _app_session().request("POST", APPSGQL, data=json.dumps(body),
                                          headers=headers, timeout=APP_TIMEOUT)
        except Exception as e:
            raise ColesUpstreamError(f"app inStoreMap: {type(e).__name__}: {e}")
        if resp.status_code == 403:
            if attempt == 0:
                token = xd_token(replace=token)
                continue
            break                                   # refused again on the re-minted token
        if resp.status_code != 200:
            raise ColesUpstreamError(f"app inStoreMap: HTTP {resp.status_code}")
        payload = _json(resp, "inStoreMap")
        node = ((payload.get("data") or {}).get("inStoreMap")) if isinstance(payload, dict) else None
        if not node:
            # a GraphQL-level failure is an upstream error, not "this store has no map"
            # (the caller caches a None answer for a day)
            errors = payload.get("errors") if isinstance(payload, dict) else None
            if errors or node is None:
                first = errors[0] if isinstance(errors, list) and errors else {}
                message = first.get("message") if isinstance(first, dict) else None
                raise ColesUpstreamError(f"app inStoreMap: {message or 'empty GraphQL response'}")
            return None
        return node if node.get("__typename") == "InStoreMapData" else None
    raise ColesBlocked("app inStoreMap: token rejected after re-mint")


def store_map_image(path):
    """The floor-plan PNG bytes for an AEM `mapLocation` path (e.g.
    "/content/dam/coles/stores/instore-maps/584.png"), fetched through the website
    session (AU exit clears the Incapsula geo-gate on the static asset). Raises on block."""
    resp = _send("GET", SITE + path, headers={"accept": "image/png,image/*,*/*"}, api=False)
    if resp.status_code != 200:
        raise ColesUpstreamError(f"store map image {path}: HTTP {resp.status_code}")
    return resp.content


# ---- shared helpers ------------------------------------------------------------------

MEMO_TTL = 6 * 3600
MEMO_MAX = 64
_memo = OrderedDict()
_memo_lock = threading.Lock()


def memoized(key, fn, ttl=MEMO_TTL):
    """Small in-process TTL memo for slow-moving datasets (the category tree)."""
    return memo.memoized(_memo, _memo_lock, MEMO_MAX, key, fn, ttl)


# Long-lived pools (2026-10-23): their threads keep their thread-local curl
# sessions — and the sticky exits behind them — between requests. The
# per-call executor they replace opened fresh sessions/exits for every
# fan-out and threw them away when the call returned. Two levels: a fan-out
# running inside a fan-out goes to the second pool, so it neither waits on
# the workers it occupies (deadlock) nor loses its parallelism; a third
# level runs inline.
_pools = (ThreadPoolExecutor(max_workers=config.COLES_BULK_WORKERS * 4, thread_name_prefix="coles-fanout-0"),
          ThreadPoolExecutor(max_workers=config.COLES_BULK_WORKERS * 4, thread_name_prefix="coles-fanout-1"))


def _windowed(fns, workers):
    """Run `fns` on the pool for this nesting level, at most `workers` at a
    time; results align with `fns`. The first failure (in `fns` order)
    propagates once the callables already started have finished."""
    return fanout.windowed(_pools, "coles-fanout", fns, workers)


def run_parallel(fns, workers=None):
    """Run zero-arg callables in parallel; results align with `fns`.
    Each result is ("ok", value) or ("error", exception)."""
    def guard(fn):
        try:
            return ("ok", fn())
        except Exception as e:
            return ("error", e)
    if not fns:
        return []
    workers = workers or config.COLES_BULK_WORKERS
    return _windowed([lambda fn=fn: guard(fn) for fn in fns], max(1, workers))


if __name__ == "__main__":
    term = sys.argv[1] if len(sys.argv) > 1 else "milk"
    started = time.monotonic()
    found = bff("/products/search", {"storeId": config.COLES_DEFAULT_STORE_ID, "start": 0,
                                     "searchTerm": term, "excludeAds": "true"})
    print(f"search {term!r}: {found.get('noOfResults')} results ({time.monotonic() - started:.1f}s)")
    suburbs = gql("GetStoreLocationSuggestions", {"term": "sydney", "count": 3})
    print("localities:", [r["suburb"] for r in suburbs["localitySearch"]["results"]])
