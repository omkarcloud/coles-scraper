"""Coles parsers: raw BFF / GraphQL records -> the public response shapes.

Every function takes whatever the upstream returned (possibly partial or
null) and never raises on a missing field.

Conventions: snake_case, `link` not `url`, booleans as `is_*` / `has_*`,
prices as numbers with a `currency`, null for anything missing, timestamps as
ISO 8601 UTC.

Intentionally dropped upstream fields (and why):
  adId / adSource / adMemoryToken / asmGuestId / searchUid / correlationId
                                   ad + session tracking
  banners, SINGLE_TILE rows        promotional tiles, not catalogue data
  rawPriceNow                      duplicate of pricing.now
  restrictedByOrganisation, pageRestrictions, excludedCatalogGroupView
                                   Coles-for-business account gating
  continuity, collectableCampaign  Flybuys / collectable campaign plumbing
                                   (null for anonymous sessions)
  excludeFromSubstitution, associatedProductId, internalDescription
                                   order-picking internals, empty in practice
  locations[].facing / order / description
                                   planogram sort keys and a sentence that
                                   repeats aisle + a "$STORE" placeholder
  countryOfOrigin.logoRequired / barcodeRequired / descriptionRequired
                                   label-rendering switches
  nutrients[].nutrientDisplayOrder presentation order (the list is kept in
                                   that order)
  nutrition.dailyIntakeDisclaimer  boilerplate
  resultType, alternateResult      internal search-mode flags
  brand.storeFinderId              duplicate key of brand.id
  recipes: stores, sourceData      always empty / null
"""
import html
import math
import re
from datetime import datetime, timezone

from coles import refs

PAGE_SIZE = 48
# The search gateway serves at most 104 pages (4,992 products) of any listing
# whatever its total: page 105 of a 22,000-product listing comes back empty.
MAX_PAGES = 104


# ---- small helpers ---------------------------------------------------------------

def as_dict(value):
    return value if isinstance(value, dict) else {}


def as_list(value):
    return value if isinstance(value, list) else []


def text(value):
    """Trimmed, entity-decoded string; None for empty / non-strings."""
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    value = html.unescape(str(value)).replace("\xa0", " ")
    value = " ".join(value.split())
    return value or None


_BREAKS = re.compile(r"<\s*(br|li|/p|/li|/div|/h\d)\b[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")


def plain(value):
    """HTML fragment -> plain text, one line per <br> / <li> / <p>."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = _TAGS.sub("", _BREAKS.sub("\n", value))
    lines = [" ".join(html.unescape(line).replace("\xa0", " ").split()) for line in value.split("\n")]
    return "\n".join(line for line in lines if line) or None


def number(value):
    """int/float, or None. Whole floats collapse to int (1.0 -> 1)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return int(value) if float(value).is_integer() else value
    try:
        parsed = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def price(value):
    """A positive amount, or None (Coles sends 0 for "no was-price")."""
    value = number(value)
    return value if value else None


def integer(value):
    value = number(value)
    return int(value) if value is not None else None


def iso_utc(value):
    """2026-10-05T20:47:24.561+11:00 -> 2026-10-05T09:47:24Z."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def snake(label):
    return re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")


def pagination(page, total_count, per_page=PAGE_SIZE, max_pages=None):
    """The block route_glue.paginate lifts into the gateway's flat fields.
    `max_pages` caps total_pages at what the upstream will actually serve."""
    total_count = integer(total_count) or 0
    total_pages = (total_count + per_page - 1) // per_page
    return {
        "page": page,
        "items_per_page": per_page,
        "total_pages": min(total_pages, max_pages) if max_pages else total_pages,
        "total_count": total_count,
    }


# ---- pricing -----------------------------------------------------------------------

def unit_price(raw_unit, comparable=None):
    """{price, ofMeasureQuantity, ofMeasureUnits} -> price per measure."""
    unit = as_dict(raw_unit)
    amount = price(unit.get("price"))
    if amount is None and not comparable:
        return None
    measure = text(unit.get("ofMeasureUnits"))
    return {
        "amount": amount,
        "quantity": number(unit.get("ofMeasureQuantity")),
        "unit": measure.lower() if measure else None,
        "label": text(comparable),
        "is_weighted": bool(unit.get("isWeighted")),
    }


def multi_buy(raw):
    """"Pick any 2 for $6": minQuantity 2, reward 3.0 (price each)."""
    promo = as_dict(raw)
    if not promo:
        return None
    quantity = integer(promo.get("minQuantity"))
    each = price(promo.get("reward"))
    return {
        "id": text(promo.get("id")),
        "type": text(promo.get("type")),
        "min_quantity": quantity,
        "price_each": each,
        "total_price": round(each * quantity, 2) if each and quantity else None,
        "unit_price_label": text(promo.get("unitPriceDisplay")),
    }


def pricing(raw):
    """Coles `pricing` -> prices in AUD. None when the product has no price
    at the store (out of range / unavailable)."""
    p = as_dict(raw)
    now = price(p.get("now"))
    if now is None and not p:
        return None
    was = price(p.get("was"))
    save_amount = price(p.get("saveAmount"))
    if save_amount is None and was and now and was > now:
        save_amount = round(was - now, 2)
    save_percent = number(p.get("savePercent")) or None      # Coles sends 0 on some marked-down rows
    if save_percent is None and was and now and was > now:
        save_percent = round((was - now) / was * 100)
    promotion = text(p.get("promotionType"))
    return {
        "currency": refs.CURRENCY,
        "price": now,
        "was_price": was,
        "save_amount": save_amount,
        "save_percent": save_percent,
        "unit_price": unit_price(p.get("unit"), p.get("comparable")),
        "is_on_special": bool(promotion or was),
        "is_online_only_special": bool(p.get("onlineSpecial")),
        "promotion_type": promotion.lower() if promotion else None,
        "special_type": (text(p.get("specialType")) or "").lower() or None,
        "price_description": text(p.get("priceDescription")),
        "offer_description": text(p.get("offerDescription")),
        "multi_buy": multi_buy(p.get("multiBuyPromotion")),
    }


# ---- product building blocks ---------------------------------------------------------

def online_categories(raw):
    """onlineHeirs -> browse path. Coles' keys are shifted one level: its
    `subCategory` is the top-level department, `category` the middle level
    and `aisle` the leaf."""
    out = []
    for heir in as_list(raw):
        heir = as_dict(heir)
        levels = [("department", "subCategory", "subCategoryId"),
                  ("category", "category", "categoryId"),
                  ("subcategory", "aisle", "aisleId")]
        entry = {}
        for key, name_key, id_key in levels:
            name = text(heir.get(name_key))
            entry[key] = {"id": text(heir.get(id_key)), "name": name} if name or heir.get(id_key) else None
        if any(entry.values()):
            out.append(entry)
    return out


def merchandise_category(raw):
    """merchandiseHeir -> Coles' internal merchandising hierarchy."""
    heir = as_dict(raw)
    if not heir:
        return None
    return {
        "profit_centre": text(heir.get("tradeProfitCentre")),
        "group": text(heir.get("categoryGroup")),
        "category": text(heir.get("category")),
        "subcategory": text(heir.get("subCategory")),
        "class": text(heir.get("className")),
    }


def aisle_locations(raw):
    """In-store shelf positions at the requested store. Rows without an
    aisle only carry Coles' "ask a team member" placeholder and are dropped."""
    out = []
    for loc in as_list(raw):
        loc = as_dict(loc)
        aisle = text(loc.get("aisle"))
        if not aisle:
            continue
        out.append({
            "aisle": aisle,
            "aisle_side": text(loc.get("aisleSide")),
            "shelf": text(loc.get("shelf")),
        })
    return out


def purchase_limits(raw):
    r = as_dict(raw)
    if not r:
        return None
    return {
        "retail_limit": integer(r.get("retailLimit")),
        "promotional_limit": integer(r.get("promotionalLimit")),
        "is_liquor_age_restricted": bool(r.get("liquorAgeRestrictionFlag")),
        "is_tobacco_age_restricted": bool(r.get("tobaccoAgeRestrictionFlag")),
        "delivery_restrictions": [t for t in (text(d) for d in as_list(r.get("delivery"))) if t],
    }


def primary_image(product):
    uris = as_list(as_dict(product).get("imageUris"))
    first = as_dict(uris[0]) if uris else {}
    return refs.image_link(first.get("uri"))


def product_card(raw, store_id=None):
    """One product row of a listing (search / browse / specials / brand /
    alternatives / bulk / variations)."""
    p = as_dict(raw)
    product_id = integer(p.get("id"))
    name, brand, size = text(p.get("name")), text(p.get("brand")), text(p.get("size"))
    card = {
        "id": product_id,
        "name": name,
        "brand": brand,
        "size": size,
        "description": text(p.get("description")),
        "link": refs.product_link(product_id, brand, name, size),
        "image": primary_image(p),
        "is_available": bool(p.get("availability")),
        "availability_type": text(p.get("availabilityType")),
        "available_quantity": number(p.get("availableQuantity")),
        # Sponsored placements are injected on top of page 1 (most of them
        # reappear in their organic position on a later page).
        "is_sponsored": bool(p.get("featured") or p.get("adId")),
        "pricing": pricing(p.get("pricing")),
        "categories": online_categories(p.get("onlineHeirs")),
        "merchandise_category": merchandise_category(p.get("merchandiseHeir")),
        "aisle_locations": aisle_locations(p.get("locations")),
        "purchase_limits": purchase_limits(p.get("restrictions")),
        "minimum_shelf_life": text(p.get("minGuarantee")),
        "variation_count": integer(as_dict(p.get("variations")).get("total")),
    }
    if store_id is not None:
        card["store_id"] = str(store_id)
    return card


# ---- listings ------------------------------------------------------------------------

_FACET_KEYS = {"Brand": "brands", "Dietary": "dietary", "Allergen": "allergens", "Special": "special_types"}
_SPECIAL_IDS = {"allspecials": "all", "halfprice": "half_price", "multibuy": "multi_buy",
                "onlineonly": "online_only"}


def facets(raw_filters):
    """The filter values available for this result set, with product counts.
    `id` (or `name`) is what the matching request param accepts."""
    out = {key: [] for key in _FACET_KEYS.values()}
    for group in as_list(raw_filters):
        group = as_dict(group)
        key = _FACET_KEYS.get(group.get("name"))
        if not key:
            continue
        for value in as_list(group.get("values")):
            value = as_dict(value)
            facet_id = text(value.get("id"))
            if facet_id is None:
                continue
            if key == "special_types":
                facet_id = _SPECIAL_IDS.get(facet_id, facet_id)
            out[key].append({"id": facet_id, "name": text(value.get("displayText")),
                             "product_count": integer(value.get("count"))})
    return out


def result_categories(raw):
    """catalogGroupView of a listing: where the matches sit in the tree."""
    out = []
    for node in as_list(raw):
        node = as_dict(node)
        out.append({
            "id": text(node.get("id")),
            "name": text(node.get("name")),
            "slug": text(node.get("seoToken")),
            "level": integer(node.get("level")),
            "product_count": integer(node.get("productCount")),
            "subcategories": result_categories(node.get("catalogGroupView")),
        })
    return out


def listing(raw, page, store_id):
    """A /products/search payload -> {products, filters, categories,
    pagination}. Only PRODUCT rows are kept: SINGLE_TILE rows are promo tiles
    and PRODUCT_ASSOCIATION rows are sponsored cross-sell injected on top of
    the organic results (they are not counted in noOfResults)."""
    data = as_dict(raw)
    products = [product_card(row, store_id) for row in as_list(data.get("results"))
                if as_dict(row).get("_type") == "PRODUCT"]
    suggestions = [t for t in (text(s) for s in as_list(data.get("didYouMean"))) if t]
    return {
        "store_id": str(store_id),
        "did_you_mean": suggestions,
        "products": products,
        "filters": facets(data.get("filters")),
        "categories": result_categories(data.get("catalogGroupView")),
        "pagination": pagination(page, data.get("noOfResults"), max_pages=MAX_PAGES),
    }


# ---- product details -------------------------------------------------------------------

_NUTRIENT_VALUE = re.compile(r"^\s*(<|less than)?\s*(-?\d+(?:[.,]\d+)?)\s*([a-zA-Zµ%]*)\s*$", re.I)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def nutrient(raw):
    n = as_dict(raw)
    value = text(n.get("value"))
    amount = unit = None
    is_less_than = False
    found = _NUTRIENT_VALUE.match(value or "")
    if found:
        is_less_than = bool(found.group(1))
        amount = number(found.group(2).replace(",", "."))
        unit = found.group(3) or None
    daily = _PERCENT.search(text(n.get("dailyIntakeInfo")) or "")
    return {
        "name": text(n.get("nutrient")),
        "amount": amount,
        "unit": unit,
        "is_less_than": is_less_than,
        "daily_intake_percent": number(daily.group(1)) if daily else None,
        "text": value,
    }


def nutrition(raw):
    n = as_dict(raw)
    if not n:
        return None
    panels = []
    for panel in as_list(n.get("breakdown")):
        panel = as_dict(panel)
        title = text(panel.get("title"))
        panels.append({
            "basis": snake(title) or None,          # per_serving | per_100g_ml
            "title": title,
            "description": text(panel.get("subtitle")),
            "nutrients": [nutrient(row) for row in as_list(panel.get("nutrients"))],
        })
    return {
        "serving_size": text(n.get("servingSize")),
        "servings_per_package": number(n.get("servingsPerPackage")),
        "panels": panels,
    }


def product_information(raw):
    """additionalInfo [{title, description}] -> {ingredients, allergen,
    dietary, dimensions, storage_instructions, …} keyed by the snake_cased
    title, so sections Coles adds later come through on their own."""
    out = {}
    for row in as_list(raw):
        row = as_dict(row)
        key = snake(row.get("title"))
        value = plain(row.get("description"))       # "Contains Gluten<br/>May Contain Egg"
        if not key or not value:
            continue
        if key == "ingredients":
            value = re.sub(r"^INGREDIENTS\s*:?\s*", "", value)
        out[key] = value
    return out


def gallery(raw):
    out = []
    for image in as_list(raw):
        image = as_dict(image)
        full, zoom, thumb = as_dict(image.get("full")), as_dict(image.get("zoom")), as_dict(image.get("thumb"))
        link = refs.gallery_link(full.get("path"))
        if not link:
            continue
        out.append({
            "link": link,
            "zoom_link": refs.gallery_link(zoom.get("path")),
            "thumbnail_link": refs.gallery_link(thumb.get("path")),
            "description": text(zoom.get("description") or full.get("description") or thumb.get("description")),
        })
    return out


def country_of_origin(raw):
    c = as_dict(raw)
    if not c:
        return None
    return {
        "country": text(c.get("country")),
        "statement": text(c.get("statement") or c.get("description")),
        "australian_content_percent": number(c.get("barcodePercentage")),
    }


def product_details(raw, store_id, extra=None):
    """GraphQL `product` (GTIN, nutrition, variations) merged with the BFF
    record `extra` (UNSPSC code, live stock at the store) -> full product."""
    p = as_dict(raw)
    extra = as_dict(extra)
    merged = {**extra, **{k: v for k, v in p.items() if v is not None}}
    card = product_card(merged)
    brand = as_dict(merged.get("brandDetails"))
    brand_id = text(brand.get("id"))
    variations = as_dict(merged.get("variations"))
    info = product_information(merged.get("additionalInfo"))
    out = {
        "id": card["id"],
        "name": card["name"],
        "brand": card["brand"],
        "size": card["size"],
        "description": card["description"],
        "long_description": plain(merged.get("longDescription")),
        "link": card["link"],
        "gtin": text(merged.get("gtin")),
        "unspsc_code": text(merged.get("unspscCode")),
        "image": card["image"],
        "images": gallery(merged.get("images")),
        "is_available": card["is_available"],
        "availability_type": card["availability_type"],
        "available_quantity": card["available_quantity"],
        "minimum_shelf_life": card["minimum_shelf_life"],
        "pricing": card["pricing"],
        "brand_details": {
            "id": brand_id,
            "name": text(brand.get("name")),
            "slug": text(brand.get("seoToken")),
            "link": refs.brand_link(text(brand.get("seoToken")), brand_id),
        } if brand else None,
        "categories": card["categories"],
        "merchandise_category": card["merchandise_category"],
        "aisle_locations": card["aisle_locations"],
        "purchase_limits": card["purchase_limits"],
        "country_of_origin": country_of_origin(merged.get("countryOfOrigin")),
        "ingredients": info.pop("ingredients", None),
        "allergens": info.pop("allergen", None),
        "dietary_claims": info.pop("dietary", None),
        "information": info,
        "nutrition": nutrition(merged.get("nutrition")),
        "nutritional_claims": merged.get("nutritionalClaims") if isinstance(merged.get("nutritionalClaims"), (list, dict)) else text(merged.get("nutritionalClaims")),
        "lifestyle": merged.get("lifestyle") if isinstance(merged.get("lifestyle"), (list, dict)) else text(merged.get("lifestyle")),
        "disclaimers": merged.get("disclaimers") if isinstance(merged.get("disclaimers"), list) else text(merged.get("disclaimers")),
        "variations": {
            "total": integer(variations.get("total")) or 0,
            "varieties": [variation(v) for v in as_list(variations.get("byVarieties"))],
            "sizes": [variation(v) for v in as_list(variations.get("bySizes"))],
        },
        "store_id": str(store_id),
        "last_updated": iso_utc(merged.get("lastUpdated")),
    }
    return out


def variation(raw):
    """A sibling product (other variety / pack size) — the slim card Coles
    shows in the "more sizes" strip."""
    card = product_card(raw)
    return {key: card[key] for key in ("id", "name", "brand", "size", "description", "link", "image",
                                       "is_available", "pricing")}


# ---- categories --------------------------------------------------------------------------

def category_node(raw, parent_path="", depth=3):
    node = as_dict(raw)
    slug = text(node.get("seoToken"))
    path = f"{parent_path}/{slug}".strip("/") if slug else parent_path
    children = as_list(node.get("catalogGroupView"))
    sub_type = text(node.get("subType"))
    return {
        "id": text(node.get("id")),
        "name": text(node.get("name")),
        "slug": slug,
        "path": path or None,
        "link": refs.category_link(path),
        "level": integer(node.get("level")),
        "product_count": integer(node.get("productCount")),
        "is_seasonal": sub_type == "SEASONAL",
        "has_subcategories": bool(children),
        "subcategories": [category_node(child, path, depth - 1) for child in children] if depth > 1 else [],
    }


# ---- stores --------------------------------------------------------------------------------

def _opening(raw):
    row = as_dict(raw)
    return {"days": text(row.get("daysOfWeek")), "hours": text(row.get("time"))}


def store(raw, distance=None):
    """GraphQL Store -> public store. `id` is the numeric store number; with
    brand.code it forms the reference ("COL:584") the store routes accept."""
    s = as_dict(raw)
    brand_code, _, store_number = (text(s.get("id")) or "").rpartition(":")
    brand_code = brand_code or text(as_dict(s.get("brand")).get("id"))
    address = as_dict(s.get("address"))
    position = as_dict(s.get("position"))
    hours = as_dict(s.get("hours"))
    today = as_dict(hours.get("today"))
    name = text(s.get("name"))
    out = {
        "id": store_number or None,
        "name": name,
        "link": refs.store_link(brand_code, text(address.get("state")), name, store_number),
        "phone": text(s.get("phone")),
        "brand": {"code": brand_code or None, "name": text(as_dict(s.get("brand")).get("name"))},
        "distance_km": number(distance),
        "is_trading": bool(s.get("isTrading")),
        "is_open_now": bool(today.get("isOpen")) if today else None,
        "address": {
            "line": text(address.get("addressLine")),
            "suburb": text(address.get("suburb")),
            "state": text(address.get("state")),
            "postcode": text(address.get("postcode")),
            "country_code": "AU",
        },
        "coordinates": {"latitude": number(position.get("latitude")),
                        "longitude": number(position.get("longitude"))},
        "hours": {
            "today": text(today.get("time")),
            "holiday_reason": text(today.get("holidayReason")),
        },
        "services": [{"name": text(as_dict(row).get("name")), "type": text(as_dict(row).get("type"))}
                     for row in as_list(s.get("services"))],
    }
    if "schedule" in hours:     # store details only: the finder list carries today's hours alone
        out["hours"]["schedule"] = [_opening(row) for row in as_list(hours.get("schedule"))]
        out["hours"]["exceptions"] = [{
            "date": text(as_dict(row).get("date")),
            "hours": text(as_dict(row).get("time")),
            "reason": text(as_dict(row).get("reason")),
            "is_open": bool(as_dict(row).get("isOpen")),
        } for row in as_list(hours.get("exceptions"))]
    if "collectionPoints" in s:
        out["collection_points"] = [
            {"id": text(as_dict(row).get("id")), "type": (text(as_dict(row).get("type")) or "").lower() or None}
            for row in as_list(as_dict(s.get("collectionPoints")).get("results"))]
    if "nextDoorStores" in s:
        out["next_door_stores"] = []
        for row in as_list(as_dict(s.get("nextDoorStores")).get("results")):
            neighbour = as_dict(as_dict(row).get("store"))
            code, _, num = (text(neighbour.get("id")) or "").rpartition(":")
            out["next_door_stores"].append({"id": num or None, "name": text(neighbour.get("name")),
                                            "brand_code": code or None})
    return out


def locality(raw):
    row = as_dict(raw)
    return {
        "suburb": text(row.get("suburb")),
        "state": text(row.get("state")),
        "postcode": text(row.get("postcode")),
        "latitude": number(row.get("latitude")),
        "longitude": number(row.get("longitude")),
    }


def stockists(raw_states, product_id, state=None):
    """StoreRange -> the stores that range one product, grouped by state."""
    product = None
    states = []
    for group in as_list(raw_states):
        group = as_dict(group)
        code = text(group.get("stateCode"))
        if state and code != state:
            continue
        for row in as_list(group.get("products")):
            row = as_dict(row)
            if str(row.get("productId")) != str(product_id):
                continue
            if product is None:
                name, brand, size = text(row.get("name")), text(row.get("brand")), text(row.get("size"))
                product = {"id": integer(product_id), "name": name, "brand": brand, "size": size,
                           "link": refs.product_link(product_id, brand, name, size)}
            stores = [{"id": text(as_dict(s).get("storeId")), "name": text(as_dict(s).get("storeName"))}
                      for s in as_list(row.get("stores"))]
            if stores:
                states.append({"state": code, "store_count": len(stores), "stores": stores})
    return product, states


# ---- recipes ---------------------------------------------------------------------------------

def recipe(raw):
    r = as_dict(raw)
    cost = as_dict(r.get("price"))
    facts = as_dict(r.get("nutrition"))
    steps = sorted((as_dict(s) for s in as_list(r.get("steps"))),
                   key=lambda s: number(s.get("sortOrder")) or 0)
    return {
        "id": text(r.get("id")),
        "title": text(r.get("title")),
        "slug": text(r.get("slug")),
        "link": text(r.get("sourceUrl")),
        "description": text(r.get("description")),
        "servings": integer(r.get("portions")),
        "preparation_minutes": integer(r.get("preparationTime")),
        "cooking_minutes": integer(r.get("cookingTime")),
        "total_minutes": integer(r.get("totalTime")),
        "images": [link for link in (text(as_dict(i).get("url")) for i in as_list(r.get("images"))) if link],
        # total / per_serving: price of the packs to buy; used_*: price of
        # the quantity the recipe actually consumes.
        "cost": {
            "currency": refs.CURRENCY,
            "total": price(cost.get("total")),
            "per_serving": price(cost.get("portion")),
            "used_total": price(cost.get("consumptionTotal")),
            "used_per_serving": price(cost.get("consumptionPortion")),
        } if cost else None,
        "nutrition": {
            "calories": number(facts.get("calories")),
            "carbohydrates_g": number(facts.get("carbohydrates")),
            "fat_g": number(facts.get("fat")),
            "protein_g": number(facts.get("protein")),
            "sugar_g": number(facts.get("sugar")),
            "fiber_g": number(facts.get("fiber")),
            "updated_at": iso_utc(facts.get("updatedAt")),
        } if facts else None,
        "ingredients": [{
            "name": text(as_dict(i).get("name")),
            "amount": number(as_dict(i).get("amount")),
            "unit": text(as_dict(i).get("unit")),
            "note": text(as_dict(i).get("subTitle")),
            "image": text(as_dict(i).get("imageUrl")),
        } for i in as_list(r.get("ingredients"))],
        "steps": [{"position": index, "title": text(s.get("title")), "text": text(s.get("text"))}
                  for index, s in enumerate(steps, start=1)],
        "tags": [{"id": text(as_dict(t).get("id")), "name": text(as_dict(t).get("name")),
                  "slug": text(as_dict(t).get("alias"))} for t in as_list(r.get("tags"))],
    }
