"""Cache TTL per /coles/* endpoint (cache.py, keyed on the validated params —
marshmallow fills the defaults, so `?page=1` and no `page` share a row).

Coles reprices weekly (specials run Wednesday to Tuesday) but stock moves all
day, so anything carrying price + stock stays short; the tree, stores and
recipes barely move.
"""
from datetime import timedelta

# --- products ------------------------------------------------------------------
LISTING_CACHE = timedelta(minutes=30)       # search / category / specials / brand pages
PRODUCT_CACHE = timedelta(minutes=30)       # details, bulk, alternatives (price + stock)
STOCKISTS_CACHE = timedelta(hours=12)       # which stores range a product
SUGGESTIONS_CACHE = timedelta(days=1)

# --- categories ----------------------------------------------------------------
CATEGORIES_CACHE = timedelta(hours=12)

# --- stores --------------------------------------------------------------------
STORE_SEARCH_CACHE = timedelta(hours=1)     # carries "open now"
STORE_DETAILS_CACHE = timedelta(hours=1)
LOCATIONS_CACHE = timedelta(days=7)
HOLIDAYS_CACHE = timedelta(days=1)

# --- recipes -------------------------------------------------------------------
RECIPES_CACHE = timedelta(hours=12)
