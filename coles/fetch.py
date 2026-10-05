"""Coles transport: plain curl_cffi on the site's own JSON, through sticky
Australian residential exits, with a headful patchright cookie mint as the
last resort.

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
  * when config.COLES_MAX_ATTEMPTS exits in a row are challenged, ONE headful
    patchright load of the home page (single-flight) mints the Incapsula
    cookies on a fresh exit. curl_cffi replays them on that same exit —
    proven on a challenged GB exit: visid_incap_* + incap_ses_* + nlbi_*
    turn the challenge into JSON, reese84 alone does not — and every thread
    shares that clearance for config.COLES_CLEARANCE_TTL.

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
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from coles.queries import DOCUMENTS
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

SITE = "https://www.coles.com.au"
BFF = SITE + "/api/bff"
GRAPHQL = SITE + "/api/graphql"
IMPERSONATE = "chrome"
TIMEOUT = 40

# The headers the storefront's own fetch layer sends with every API call.
API_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-AU,en;q=0.9",
    "dsch-channel": "coles.online.1site.desktop",
    "x-api-version": "2",
    "origin": SITE,
    "referer": SITE + "/",
}

BLOCK_MARKERS = ("_Incapsula_Resource", "Incapsula incident", "Request unsuccessful",
                 "Pardon Our Interruption")
INCAPSULA_COOKIE_PREFIXES = ("visid_incap", "incap_ses", "nlbi_", "reese84")
BROWSER_SETTLE_TIMEOUT = 40      # seconds the mint waits for the home page to render
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
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


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
    """One throwaway headful patchright load of the home page on a fresh
    exit; the Incapsula challenge clears itself and sets its cookies.
    create_scope() keeps a pool janitor in this process from reaping the
    half-launched ad-hoc browser (booking / trustpilot convention)."""
    from chrome_manager import create_scope
    from patchright_driver import PatchrightDriver

    proxy = config.coles_proxy()
    print("coles: every curl exit was challenged; minting Incapsula cookies via patchright...")
    with create_scope():
        driver = PatchrightDriver(proxy_url=proxy, geoip_timezone=True)
    try:
        driver.nav(SITE + "/", referer="https://www.google.com/", mode="blocked",
                   challenge_markers=BLOCK_MARKERS[:1])
        deadline = time.monotonic() + BROWSER_SETTLE_TIMEOUT
        while "__NEXT_DATA__" not in (driver.content() or ""):
            if time.monotonic() >= deadline:
                raise ColesBlocked("the Incapsula challenge did not clear in the browser")
            time.sleep(2)
        cookies = {c["name"]: c["value"] for c in driver.cookies()
                   if "coles.com.au" in (c.get("domain") or "")
                   and c["name"].startswith(INCAPSULA_COOKIE_PREFIXES)}
    finally:
        driver.close()
    if not any(name.startswith("incap_ses") for name in cookies):
        raise ColesBlocked("the browser load set no Incapsula session cookie")
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


def _send(method, url, params=None, body=None, headers=None, api=True):
    """One upstream call with exit rotation and the browser fallback.
    Returns the curl response of the first non-blocked attempt; raises
    ColesBlocked / ColesUpstreamError otherwise."""
    last = None
    attempts = config.COLES_MAX_ATTEMPTS
    minted = False
    attempt = 0
    while attempt < attempts:
        attempt += 1
        request_headers = dict(API_HEADERS) if api else {}
        if api:
            request_headers["ocp-apim-subscription-key"] = _key
        if body is not None:
            request_headers["content-type"] = "application/json"
        request_headers.update(headers or {})
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


# ---- shared helpers ------------------------------------------------------------------

MEMO_TTL = 6 * 3600
MEMO_MAX = 64
_memo = OrderedDict()
_memo_lock = threading.Lock()


def memoized(key, fn, ttl=MEMO_TTL):
    """Small in-process TTL memo for slow-moving datasets (the category tree)."""
    now = time.monotonic()
    with _memo_lock:
        hit = _memo.get(key)
        if hit and now - hit[0] < ttl:
            _memo.move_to_end(key)
            return hit[1]
    value = fn()
    with _memo_lock:
        _memo[key] = (now, value)
        _memo.move_to_end(key)
        while len(_memo) > MEMO_MAX:
            _memo.popitem(last=False)
    return value


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
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(fns)))) as ex:
        return list(ex.map(guard, fns))


if __name__ == "__main__":
    term = sys.argv[1] if len(sys.argv) > 1 else "milk"
    started = time.monotonic()
    found = bff("/products/search", {"storeId": config.COLES_DEFAULT_STORE_ID, "start": 0,
                                     "searchTerm": term, "excludeAds": "true"})
    print(f"search {term!r}: {found.get('noOfResults')} results ({time.monotonic() - started:.1f}s)")
    suburbs = gql("GetStoreLocationSuggestions", {"term": "sydney", "count": 3})
    print("localities:", [r["suburb"] for r in suburbs["localitySearch"]["results"]])
