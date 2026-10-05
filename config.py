"""Configuration for the Coles Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT          port the API listens on (default 8000)
    COLES_PROXY   proxy URL for every request, e.g. http://user:pass@host:port
                  (default: none — direct). Coles sits behind Imperva, which
                  decides by where the request comes from: an Australian,
                  New Zealand or US home / office connection gets data straight
                  away with no proxy at all. From anywhere else (or from a
                  cloud server) set this to an Australian residential proxy.
                  A sticky session works best — the scraper keeps one
                  connection per worker and opens a fresh one on any block.
    COLES_STORE   default store for prices and stock when a request passes no
                  `store` (default 584 — Coles Burwood East, VIC)

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

COLES_PROXY = os.environ.get("COLES_PROXY") or None

# Prices, stock and aisle locations are per store.
COLES_DEFAULT_STORE_ID = os.environ.get("COLES_STORE") or "584"

# The public key coles.com.au ships in every page (BFF_API_SUBSCRIPTION_KEY in
# its __NEXT_DATA__). If Coles rotates it, the scraper re-reads it from the
# home page by itself.
COLES_SUBSCRIPTION_KEY = "eae83861d1cd4de6bb9cd8a2cd6f041e"

COLES_MAX_ATTEMPTS = MAX_RETRIES   # attempts per request, each on a fresh connection after a block
COLES_REQUESTS_PER_EXIT = 300      # requests per connection before a fresh one
COLES_BULK_WORKERS = 4             # parallel upstream calls inside one request

# The hosted version can fall back to a real browser when every attempt is
# challenged; this kit ships without one, so the fallback stays off.
COLES_BROWSER_FALLBACK = False
COLES_CLEARANCE_TTL = 15 * 60


def coles_proxy():
    """Proxy for every request (None = direct)."""
    return os.environ.get("COLES_PROXY") or None
