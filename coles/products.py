"""/coles/products/*, /coles/specials, /coles/categories/products and
/coles/brands/products.

Every listing is the storefront's one search gateway (/api/bff/products/search,
48 products a page, `start` = zero-based page index) asked four ways:

    keyword     searchTerm
    category    categoryId + categoryLevel + categoryName   (all three required)
    specials    filters=[{"name": "Special", "values": [...]}] alone
    brand       filters=[{"name": "Brand", "values": [<brand id>]}] alone

Filters (`Special`, `Brand`, `Dietary`, `Allergen`) combine with any of the
four. Brand / dietary / allergen values are numeric facet ids upstream; the
API also accepts their display names and maps them through the facet list of
the unfiltered result set (one extra upstream call, only when a name is used).

Prices, stock and aisle locations are per store (`store`, default
config.COLES_DEFAULT_STORE_ID).
"""
import json

import config
from coles import categories as tree
from coles import fetch, parsers, refs

_PUBLIC_SORT = {token: name for name, token in refs.SORTS.items()}
MAX_BULK = 20


# ---- listing core --------------------------------------------------------------------

def _filters_param(groups):
    """{"Special": ["halfprice"], "Brand": [...]} -> the gateway's JSON list."""
    active = [{"name": name, "values": values} for name, values in groups.items() if values]
    return json.dumps(active) if active else None


def _run(base, store, page, sort_token, groups):
    params = {"storeId": store, "start": page - 1, "excludeAds": "true", **base}
    if sort_token:
        params["sortBy"] = sort_token
    filters = _filters_param(groups)
    if filters:
        params["filters"] = filters
    return fetch.bff("/products/search", params)


def _name_key(name):
    """Comparison key for facet names: case, punctuation and spacing are
    ignored (Coles lists "Arnotts" for Arnott's, "a2 Milk" for A2 Milk)."""
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _resolve_names(kind, values, available):
    """Map facet display names to ids against `available` ([{id, name}])."""
    by_name = {_name_key(f["name"]): f["id"] for f in available}
    by_id = {f["id"] for f in available}
    out = []
    for value in values:
        if value in by_id or value.isdigit():
            out.append(value)
            continue
        facet_id = by_name.get(_name_key(value))
        if facet_id is None:
            shown = ", ".join(f["name"] for f in available[:25] if f["name"]) or "none"
            raise ValueError(f"Unknown {kind} '{value}' for these results. Available: {shown}.")
        out.append(facet_id)
    return out


def _listing(base, context, page, sort_by, default_sort, special_type, brands, dietary, allergens, store,
             fixed_groups=None):
    """Run one listing page and shape it. `context` is the dict of identity
    fields put first in the response (query / category / brand)."""
    store = store or config.COLES_DEFAULT_STORE_ID
    sort_token = sort_by or refs.SORTS[default_sort]
    groups = dict(fixed_groups or {})
    named = {"Brand": ("brand", brands), "Dietary": ("dietary value", dietary), "Allergen": ("allergen", allergens)}
    needs_lookup = any(values and any(not v.isdigit() for v in values) for _, values in named.values())
    available = None
    if needs_lookup:
        # The facet list of the same listing without the name filters.
        lookup_groups = dict(fixed_groups or {})
        if not base and not lookup_groups and special_type:
            # The gateway rejects a call with neither a term, a category nor a filter.
            lookup_groups["Special"] = [special_type]
        available = parsers.facets(_run(base, store, 1, None, lookup_groups).get("filters"))
    for group, (kind, values) in named.items():
        if not values:
            continue
        if available is not None and any(not v.isdigit() for v in values):
            key = {"Brand": "brands", "Dietary": "dietary", "Allergen": "allergens"}[group]
            values = _resolve_names(kind, values, available[key])
        groups[group] = list(groups.get(group, [])) + [v for v in values if v not in groups.get(group, [])]
    if special_type:
        groups["Special"] = [special_type]
    raw = _run(base, store, page, sort_token, groups)
    result = parsers.listing(raw, page, store)
    if page > 1 and not result["products"]:
        raise ValueError(f"page {page} is past the last page.")
    return {**context, "sort_by": _PUBLIC_SORT.get(sort_token), **result}


# ---- listings -------------------------------------------------------------------------

def search(query, page=1, sort_by=None, special_type=None, brands=None, dietary=None, allergens=None,
           store=None):
    """Keyword search of the catalogue."""
    return _listing({"searchTerm": query}, {"query": query}, page, sort_by, "relevance",
                    special_type, brands, dietary, allergens, store)


def _category_base(node):
    return {"categoryId": node["id"], "categoryLevel": node["level"],
            "categoryName": node["upstream_name"]}


def category_products(category, page=1, sort_by=None, special_type=None, brands=None, dietary=None,
                      allergens=None, store=None):
    """Products of one category (any level of the tree)."""
    node = tree.find(category)
    return _listing(_category_base(node), {"category": tree.summary(node)}, page, sort_by, "best_seller",
                    special_type, brands, dietary, allergens, store)


def specials(special_type=None, category=None, page=1, sort_by=None, brands=None, dietary=None,
             allergens=None, store=None):
    """Products on special, optionally inside one category."""
    special_type = special_type or refs.SPECIAL_TYPES["all"]
    base, context = {}, {"category": None}
    if category:
        node = tree.find(category)
        base, context = _category_base(node), {"category": tree.summary(node)}
    public_type = next((name for name, token in refs.SPECIAL_TYPES.items() if token == special_type), None)
    return _listing(base, {"special_type": public_type, **context}, page, sort_by, "recommended",
                    special_type, brands, dietary, allergens, store)


def _brand_id(brand, store):
    """A brand id as-is; a brand NAME through the brand facet of a search
    for that name (exact, case-insensitive match)."""
    if brand.isdigit():
        return brand, None
    raw = _run({"searchTerm": brand}, store, 1, None, {})
    for facet in parsers.facets(raw.get("filters"))["brands"]:
        if _name_key(facet["name"]) == _name_key(brand):
            return facet["id"], facet["name"]
    raise fetch.ColesNotFound(f"No Coles brand named '{brand}'. Pass the brand id or a coles.com.au/brands/... link.")


def brand_products(brand, page=1, sort_by=None, special_type=None, dietary=None, allergens=None, store=None):
    """Every product of one brand."""
    store = store or config.COLES_DEFAULT_STORE_ID
    brand_id, name = _brand_id(brand, store)
    result = _listing({}, {"brand": {"id": brand_id, "name": name, "link": None}}, page, sort_by, "best_seller",
                      special_type, None, dietary, allergens, store, fixed_groups={"Brand": [brand_id]})
    if not result["pagination"]["total_count"]:
        raise fetch.ColesNotFound(f"No products for brand '{brand}'.")
    first = result["products"][0] if result["products"] else {}
    result["brand"]["name"] = name or first.get("brand")
    result["brand"]["link"] = refs.brand_link(refs.slugify(result["brand"]["name"]), brand_id)
    return result


# ---- single products ------------------------------------------------------------------

def details(product, store=None):
    """Full product record: GraphQL `product` (GTIN, nutrition, variations)
    plus the BFF record (UNSPSC code, live stock), fetched in parallel. The
    BFF half is best-effort."""
    store = store or config.COLES_DEFAULT_STORE_ID
    main, extra = fetch.run_parallel([
        lambda: fetch.gql("GetProductDetails", {"storeId": f"COL:{store}", "productId": product,
                                                "useV2NipAndAllergens": True}),
        lambda: fetch.bff(f"/products/{product}", {"storeId": store}, allow_empty=True),
    ], workers=2)
    extra_record = extra[1] if extra[0] == "ok" else None
    record = (main[1] or {}).get("product") if main[0] == "ok" else None
    if not record and not extra_record:
        # Unknown id: GraphQL says "Product <id> not found", the BFF answers
        # an empty 200. Anything else is a real upstream failure.
        failure = main[1] if main[0] == "error" else None
        if failure is None or isinstance(failure, (fetch.ColesNotFound, fetch.ColesBadRequest)):
            raise fetch.ColesNotFound(f"Coles product {product} does not exist.")
        raise failure
    return parsers.product_details(record, store, extra_record)


def bulk(products, store=None):
    """Up to MAX_BULK products in one upstream call (price, stock, category
    for a basket or a watch list)."""
    store = store or config.COLES_DEFAULT_STORE_ID
    data = fetch.gql("GetProductsInfo", {"productIds": products, "brandedStoreId": f"COL:{store}"})
    info = data.get("productsInfo") or {}
    cards = {card["id"]: card for card in (parsers.product_card(row, store) for row in parsers.as_list(info.get("results")))}
    ordered = [cards[int(pid)] for pid in products if int(pid) in cards]
    missing = [int(pid) for pid in products if int(pid) not in cards]
    return {
        "store_id": str(store),
        "count": len(ordered),
        "not_found_ids": missing,
        "products": ordered,
    }


def alternatives(product, store=None):
    """Coles' substitutes for a product (what it offers when the product is
    out of stock)."""
    store = store or config.COLES_DEFAULT_STORE_ID
    data = fetch.bff("/products/recommendations/alternatives", method="POST",
                     body={"storeId": store, "productIds": [product]})
    rows = []
    for entry in parsers.as_list(parsers.as_dict(data).get("results")):
        if str(parsers.as_dict(entry).get("id")) == str(product):
            rows = parsers.as_list(entry.get("alternatives"))
    return {
        "product_id": int(product),
        "store_id": str(store),
        "count": len(rows),
        "products": [parsers.product_card(row, store) for row in rows],
    }


def stockists(product, state=None):
    """The Coles stores that range a product, grouped by state."""
    data = fetch.gql("StoreRange", {"productIds": [product]})
    summary, states = parsers.stockists(data.get("storeRange"), product, state)
    if summary is None:
        raise fetch.ColesNotFound(f"Coles product {product} is not ranged in any store"
                                  + (f" in {state}." if state else "."))
    return {
        "product": summary,
        "store_count": sum(s["store_count"] for s in states),
        "states": states,
    }


def suggestions(query, store=None):
    """Search autocomplete."""
    store = store or config.COLES_DEFAULT_STORE_ID
    data = fetch.bff("/products/search/suggestions", {"searchTerm": query, "storeId": store})
    rows = sorted(parsers.as_list(parsers.as_dict(data).get("results")),
                  key=lambda r: parsers.number(parsers.as_dict(r).get("ranking")) or 0)
    found = [t for t in (parsers.text(parsers.as_dict(r).get("text")) for r in rows) if t]
    return {"query": query, "count": len(found), "suggestions": found}
