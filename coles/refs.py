"""Coles references: resolvers for the ONE-param-per-input convention (a bare
id OR a coles.com.au link), link builders and the public -> upstream value
maps used by the schemas.

Resolvers raise ValueError with a user-facing message (schema_fields.RefField
turns it into a 400).
"""
import re
from urllib.parse import unquote, urlparse

SITE = "https://www.coles.com.au"
IMAGE_HOST = "https://cdn.productimages.coles.com.au/productimages"
# Pack-shot galleries on product pages are served by the legacy shop host.
GALLERY_HOST = "https://shop.coles.com.au"
CURRENCY = "AUD"

# public sort value -> BFF sortBy (the storefront's own dropdown plus the two
# brand orders the gateway also accepts).
SORTS = {
    "relevance": "relevance",
    "best_seller": "salesDescending",
    "recommended": "recommendedDescending",
    "price_low_to_high": "priceAscending",
    "price_high_to_low": "priceDescending",
    "unit_price_low_to_high": "unitPriceAscending",
    "brand_a_to_z": "brandAscending",
    "brand_z_to_a": "brandDescending",
}

# public special type -> `Special` facet value.
SPECIAL_TYPES = {
    "all": "all",
    "half_price": "halfprice",
    "multi_buy": "multibuy",
    "online_only": "onlineonly",
}

# public store brand -> Coles Group brand code (GraphQL BrandId).
STORE_BRANDS = {
    "coles": ["COL"],
    "liquorland": ["LQR"],
    "first_choice": ["FCL"],
    "vintage_cellars": ["VIN"],
    "all": ["COL", "LQR", "FCL", "VIN"],
}
BRAND_CODES = {"COL", "LQR", "FCL", "VIN"}
# find-stores/<slug>/... -> brand code
STORE_LINK_BRANDS = {
    "coles": "COL", "coles-local": "COL", "coles-central": "COL", "coles-express": "COL",
    "liquorland": "LQR", "first-choice-liquor-market": "FCL", "first-choice": "FCL",
    "vintage-cellars": "VIN",
}
BRAND_LINK_SLUGS = {"COL": "coles", "LQR": "liquorland", "FCL": "first-choice-liquor-market",
                    "VIN": "vintage-cellars"}

STATES = ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA")

_PRODUCT_ID = re.compile(r"\d{4,7}")
_TRAILING_ID = re.compile(r"(?:^|-)(\d{3,10})$")


def _coles_path(value):
    """Path of a coles.com.au link (None when `value` is not a link). Raises
    ValueError for another site's link."""
    if not re.match(r"^(https?:)?//|^www\.|^coles\.com\.au", value, re.I):
        return None
    url = value if "//" in value else "https://" + value
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not (host == "coles.com.au" or host.endswith(".coles.com.au")):
        raise ValueError("Must be a coles.com.au link.")
    return unquote(parsed.path).strip("/")


def slugify(text):
    return re.sub(r"[^a-z0-9.]+", "-", (text or "").lower()).strip("-.")


# ---- products ------------------------------------------------------------------

def resolve_product(value):
    """8150288 | coles-full-cream-milk-3l-8150288 |
    https://www.coles.com.au/product/coles-full-cream-milk-3l-8150288 -> "8150288"."""
    value = (value or "").strip()
    path = _coles_path(value)
    if path is not None:
        if not path.startswith("product/"):
            raise ValueError("Must be a Coles product link (coles.com.au/product/...) or a product id.")
        value = path.split("/", 1)[1].split("/")[0]
    if _PRODUCT_ID.fullmatch(value):
        return value
    found = _TRAILING_ID.search(value)
    if found and _PRODUCT_ID.fullmatch(found.group(1)):
        return found.group(1)
    raise ValueError("Must be a Coles product id (e.g. 8150288) or a coles.com.au/product/... link.")


def product_link(product_id, brand=None, name=None, size=None):
    if not product_id:
        return None
    slug = slugify(" ".join(part for part in (brand, name, size) if part))
    return f"{SITE}/product/{slug + '-' if slug else ''}{product_id}"


def image_link(uri):
    """/8/8150288.jpg -> CDN link; absolute links pass through."""
    if not uri or not isinstance(uri, str):
        return None
    if uri.startswith("http"):
        return uri
    return IMAGE_HOST + ("" if uri.startswith("/") else "/") + uri


def gallery_link(path):
    """/wcsstore/Coles-CAS/images/8/1/5/8150288-zm.jpg -> shop.coles.com.au link."""
    if not path or not isinstance(path, str):
        return None
    if path.startswith("http"):
        return path
    return GALLERY_HOST + ("" if path.startswith("/") else "/") + path


# ---- stores ----------------------------------------------------------------------

def _store_from_link(path):
    parts = path.split("/")
    if len(parts) < 2 or parts[0] != "find-stores":
        raise ValueError("Must be a Coles store link (coles.com.au/find-stores/...) or a store id.")
    found = _TRAILING_ID.search(parts[-1])
    if not found:
        raise ValueError("That store link carries no store id.")
    return STORE_LINK_BRANDS.get(parts[1], "COL"), found.group(1)


def resolve_branded_store(value):
    """584 | 0584 | COL:584 | LQR:6083 | a find-stores link -> "COL:584"."""
    value = (value or "").strip()
    path = _coles_path(value)
    if path is not None:
        brand, number = _store_from_link(path)
    else:
        brand, sep, number = value.upper().rpartition(":")
        brand = brand if sep else "COL"
    if brand not in BRAND_CODES or not re.fullmatch(r"\d{1,6}", number or ""):
        raise ValueError("Must be a store id (e.g. 584, COL:584, LQR:6083) or a coles.com.au/find-stores/... link.")
    return f"{brand}:{int(number)}"


def resolve_store(value):
    """A Coles supermarket for prices and stock -> its numeric id ("584").
    Liquorland / First Choice / Vintage Cellars stores carry no grocery range."""
    brand, number = resolve_branded_store(value).split(":")
    if brand != "COL":
        raise ValueError("Prices are per Coles supermarket: pass a Coles store id (e.g. 584), not a liquor store.")
    return number


def store_link(brand_code, state, name, number):
    """Coles' own store page link; the page is keyed on the trailing id."""
    if not number:
        return None
    brand_slug = BRAND_LINK_SLUGS.get(brand_code or "COL", "coles")
    label = re.sub(r"^coles\s+", "", name or "", flags=re.I) if brand_code in (None, "COL") else (name or "")
    slug = slugify(label)
    return f"{SITE}/find-stores/{brand_slug}/{(state or 'au').lower()}/{slug + '-' if slug else ''}{number}"


# ---- categories / brands -----------------------------------------------------------

def resolve_category(value):
    """1300 | dairy-eggs-fridge/milk | a /browse/... or /on-special/... link
    -> "1300" or "dairy-eggs-fridge/milk" (looked up in the category tree by
    coles/categories.py)."""
    value = (value or "").strip()
    path = _coles_path(value)
    if path is not None:
        parts = path.split("/")
        if parts[0] not in ("browse", "on-special") or len(parts) < 2:
            raise ValueError("Must be a Coles category link (coles.com.au/browse/...), a category id or a slug path.")
        value = "/".join(parts[1:])
    if value.isdigit():
        return value
    slugs = [slugify(part) for part in value.strip("/").split("/") if part.strip()]
    if not slugs or any(not s for s in slugs) or len(slugs) > 3:
        raise ValueError("Must be a category id (1300), a slug path (dairy-eggs-fridge/milk) or a coles.com.au/browse/... link.")
    return "/".join(slugs)


def category_link(slug_path):
    return f"{SITE}/browse/{slug_path}" if slug_path else None


def resolve_brand(value):
    """3955134709 | coles-3955134709 | a /brands/coles-3955134709 link -> the
    numeric brand id; any other text is kept as a brand NAME (resolved
    against the brand facets by coles/products.py)."""
    value = (value or "").strip()
    path = _coles_path(value)
    if path is not None:
        parts = path.split("/")
        if parts[0] not in ("brands", "brand") or len(parts) < 2:
            raise ValueError("Must be a Coles brand link (coles.com.au/brands/...), a brand id or a brand name.")
        value = parts[1]
    if value.isdigit():
        return value
    found = re.search(r"-(\d{6,12})$", value)
    if found:
        return found.group(1)
    if not value:
        raise ValueError("Must be a brand name (Cadbury), a brand id or a coles.com.au/brands/... link.")
    return value


def brand_link(slug, brand_id):
    if not brand_id:
        return None
    return f"{SITE}/brands/{(slug or 'brand')}-{brand_id}"


# ---- locations -----------------------------------------------------------------------

_COORDS = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def resolve_location(value):
    """"-33.8671,151.2071" -> (lat, lng); anything else (suburb, postcode,
    "Bondi NSW") is kept as text for the locality lookup."""
    value = " ".join((value or "").split())
    found = _COORDS.match(value)
    if found:
        lat, lng = float(found.group(1)), float(found.group(2))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("Coordinates must be latitude,longitude (e.g. -33.8671,151.2071).")
        return (lat, lng)
    if len(value) < 3:
        raise ValueError("Must be a suburb, a postcode or latitude,longitude (e.g. Bondi, 2000 or -33.8671,151.2071).")
    return value
