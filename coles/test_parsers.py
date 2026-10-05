"""Offline tests: parsers, input resolution, schemas and block classification
against saved coles.com.au payloads (coles/fixtures/, captured 2026-10-05).

    python -m pytest coles/test_parsers.py -q
"""
import json
import os

import pytest

from coles import fetch, parsers, refs, schemas
from schema_fields import load_query

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


# ---- input resolution --------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("8150288", "8150288"),
    ("coles-full-cream-milk-3l-8150288", "8150288"),
    ("https://www.coles.com.au/product/coles-full-cream-milk-3l-8150288", "8150288"),
    ("https://www.coles.com.au/product/coles-rspca-approved-chicken-breast-fillets-large-pack-approx.-1.4kg-2263179?x=1", "2263179"),
    ("www.coles.com.au/product/x-409499", "409499"),
])
def test_resolve_product(value, expected):
    assert refs.resolve_product(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "12", "https://www.woolworths.com.au/product/123456",
                                   "https://www.coles.com.au/browse/dairy-eggs-fridge"])
def test_resolve_product_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_product(value)


@pytest.mark.parametrize("value, expected", [
    ("584", "COL:584"),
    ("0584", "COL:584"),
    ("col:584", "COL:584"),
    ("LQR:6083", "LQR:6083"),
    ("https://www.coles.com.au/find-stores/coles/vic/burwood-east-584", "COL:584"),
    ("https://www.coles.com.au/find-stores/coles-local/nsw/local-pagewood-5751", "COL:5751"),
    ("https://www.coles.com.au/find-stores/liquorland/nsw/liquorland-marrickville-dewall-6083", "LQR:6083"),
])
def test_resolve_branded_store(value, expected):
    assert refs.resolve_branded_store(value) == expected


def test_resolve_store_is_supermarket_only():
    assert refs.resolve_store("COL:0584") == "584"
    for bad in ("LQR:6083", "abc", "XYZ:12", "https://www.coles.com.au/product/x-8150288"):
        with pytest.raises(ValueError):
            refs.resolve_store(bad)


@pytest.mark.parametrize("value, expected", [
    ("1300", "1300"),
    ("dairy-eggs-fridge/milk", "dairy-eggs-fridge/milk"),
    ("/Dairy-Eggs-Fridge/Milk/", "dairy-eggs-fridge/milk"),
    ("https://www.coles.com.au/browse/dairy-eggs-fridge/milk?page=2", "dairy-eggs-fridge/milk"),
    ("https://www.coles.com.au/on-special/pantry", "pantry"),
])
def test_resolve_category(value, expected):
    assert refs.resolve_category(value) == expected


def test_resolve_category_rejects():
    for bad in ("", "a/b/c/d", "https://www.coles.com.au/product/x-8150288"):
        with pytest.raises(ValueError):
            refs.resolve_category(bad)


@pytest.mark.parametrize("value, expected", [
    ("3955134709", "3955134709"),
    ("coles-3955134709", "3955134709"),
    ("https://www.coles.com.au/brands/cadbury-2146288555", "2146288555"),
    ("Cadbury", "Cadbury"),
    ("a2 Milk", "a2 Milk"),
])
def test_resolve_brand(value, expected):
    assert refs.resolve_brand(value) == expected


def test_resolve_location():
    assert refs.resolve_location("-33.8671, 151.2071") == (-33.8671, 151.2071)
    assert refs.resolve_location("  Bondi   NSW ") == "Bondi NSW"
    assert refs.resolve_location("2000") == "2000"
    for bad in ("ab", "-133.0,151.0"):
        with pytest.raises(ValueError):
            refs.resolve_location(bad)


def test_links():
    assert refs.product_link(8150288, "Coles", "Full Cream Milk", "3L") == \
        "https://www.coles.com.au/product/coles-full-cream-milk-3l-8150288"
    assert refs.product_link(None) is None
    assert refs.image_link("/8/8150288.jpg") == "https://cdn.productimages.coles.com.au/productimages/8/8150288.jpg"
    assert refs.store_link("COL", "VIC", "Coles Burwood East", "584") == \
        "https://www.coles.com.au/find-stores/coles/vic/burwood-east-584"
    assert refs.store_link("LQR", "NSW", "Liquorland Marrickville Dewall", "6083") == \
        "https://www.coles.com.au/find-stores/liquorland/nsw/liquorland-marrickville-dewall-6083"


# ---- helpers -------------------------------------------------------------------------

def test_value_helpers():
    assert parsers.number("12.00") == 12 and parsers.number("1.5") == 1.5 and parsers.number("x") is None
    assert parsers.number(True) is None and parsers.price(0) is None and parsers.price(4.95) == 4.95
    assert parsers.text("  Store at 5&deg;C \n") == "Store at 5°C" and parsers.text("") is None
    assert parsers.iso_utc("2026-10-05T20:47:24.561+11:00") == "2026-10-05T09:47:24Z"
    assert parsers.iso_utc("2026-10-05T09:53:01Z") == "2026-10-05T09:53:01Z" and parsers.iso_utc("nope") is None
    assert parsers.plain("A<br /><br />B <li>C</li><br>") == "A\nB\nC"
    assert parsers.pagination(2, 297) == {"page": 2, "items_per_page": 48, "total_pages": 7, "total_count": 297}
    assert parsers.pagination(1, 22723, max_pages=parsers.MAX_PAGES)["total_pages"] == 104


def test_pricing():
    assert parsers.pricing(None) is None and parsers.pricing({}) is None
    plain = parsers.pricing({"now": 4.95, "was": 0, "comparable": "$1.65/ 1L", "onlineSpecial": False,
                             "unit": {"ofMeasureQuantity": 1, "ofMeasureUnits": "l", "price": 1.65}})
    assert plain["price"] == 4.95 and plain["was_price"] is None and plain["is_on_special"] is False
    assert plain["currency"] == "AUD"
    assert plain["unit_price"] == {"amount": 1.65, "quantity": 1, "unit": "l", "label": "$1.65/ 1L",
                                   "is_weighted": False}
    half = parsers.pricing({"now": 2.02, "was": 4.05, "saveAmount": 2.03, "savePercent": 50,
                            "priceDescription": "1/2 Price", "promotionType": "SPECIAL",
                            "specialType": "PERCENT_OFF"})
    assert half["is_on_special"] and half["save_percent"] == 50 and half["special_type"] == "percent_off"
    derived = parsers.pricing({"now": 3, "was": 4})
    assert derived["save_amount"] == 1 and derived["save_percent"] == 25
    assert parsers.pricing({"now": 6.4, "was": 8, "savePercent": 0})["save_percent"] == 20
    assert parsers.product_information([{"title": "Allergen", "description": "Contains Gluten<br/>May Contain Egg"}]) == {
        "allergen": "Contains Gluten\nMay Contain Egg"}


def test_nutrient():
    assert parsers.nutrient({"nutrient": "Energy (kJ)", "value": "646 kJ", "dailyIntakeInfo": "(7% DI)"}) == {
        "name": "Energy (kJ)", "amount": 646, "unit": "kJ", "is_less_than": False,
        "daily_intake_percent": 7, "text": "646 kJ"}
    less = parsers.nutrient({"nutrient": "Sodium", "value": "<5 mg", "dailyIntakeInfo": None})
    assert less["amount"] == 5 and less["is_less_than"] and less["daily_intake_percent"] is None
    odd = parsers.nutrient({"nutrient": "Fibre", "value": "trace"})
    assert odd["amount"] is None and odd["text"] == "trace"
    assert parsers.nutrient(None)["name"] is None


# ---- listings ------------------------------------------------------------------------

def test_listing():
    result = parsers.listing(fixture("search_milk.json"), 1, "584")
    products = result["products"]
    assert len(products) == 4                      # tiles + PRODUCT_ASSOCIATION rows dropped
    first = products[0]
    assert first["id"] == 8150288 and first["name"] == "Full Cream Milk" and first["brand"] == "Coles"
    assert first["link"] == "https://www.coles.com.au/product/coles-full-cream-milk-3l-8150288"
    assert first["image"].endswith("/8/8150288.jpg") and first["store_id"] == "584"
    assert first["pricing"]["price"] > 0 and first["pricing"]["currency"] == "AUD"
    assert first["categories"][0]["department"] == {"id": "1300", "name": "Dairy, Eggs & Fridge"}
    assert first["categories"][0]["subcategory"]["name"] == "Full Cream Milk"
    assert first["purchase_limits"]["retail_limit"] == 20
    assert any(p["is_sponsored"] for p in products) and not first["is_sponsored"]
    assert result["pagination"]["total_count"] > 100 and result["pagination"]["items_per_page"] == 48
    assert {"id", "name", "product_count"} == set(result["filters"]["brands"][0])
    assert result["filters"]["special_types"][0]["id"] == "all"
    assert result["categories"][0]["slug"] and result["did_you_mean"] == []
    assert all(key in first for key in ("aisle_locations", "merchandise_category", "variation_count"))


def test_listing_multi_buy():
    result = parsers.listing(fixture("specials_multibuy.json"), 1, "584")
    promo = result["products"][0]["pricing"]
    assert promo["is_on_special"] and promo["special_type"] in ("multi_save", "mix_save")
    assert promo["multi_buy"]["min_quantity"] >= 2 and promo["multi_buy"]["price_each"] > 0
    assert promo["multi_buy"]["total_price"] == round(
        promo["multi_buy"]["price_each"] * promo["multi_buy"]["min_quantity"], 2)
    assert promo["offer_description"]


def test_listing_survives_junk():
    for junk in (None, {}, [], {"results": [None, 3, {"_type": "PRODUCT"}], "filters": "x", "noOfResults": "7"}):
        result = parsers.listing(junk, 1, "584")
        assert result["pagination"]["page"] == 1 and isinstance(result["products"], list)
    assert parsers.product_card(None)["id"] is None


# ---- product details -------------------------------------------------------------------

def test_product_details():
    product = parsers.product_details(fixture("product_gql.json")["product"], "584", fixture("product_bff.json"))
    assert product["id"] == 1018067 and product["brand"] == "Dare" and product["gtin"] == "9310232962085"
    assert product["unspsc_code"]                               # BFF-only field merged in
    assert product["available_quantity"] is not None and product["store_id"] == "584"
    assert "<" not in product["long_description"]
    assert product["images"][0]["link"].startswith("https://shop.coles.com.au/wcsstore/")
    assert product["brand_details"]["link"].startswith("https://www.coles.com.au/brands/dare-")
    assert product["ingredients"] and not product["ingredients"].startswith("INGREDIENTS")
    panels = product["nutrition"]["panels"]
    assert [p["basis"] for p in panels] == ["per_serving", "per_100g_ml"]
    assert panels[0]["nutrients"][0]["amount"] is not None and panels[0]["nutrients"][0]["unit"]
    assert product["country_of_origin"]["country"]
    assert isinstance(product["nutritional_claims"], list)
    assert product["variations"]["total"] >= len(product["variations"]["sizes"])
    assert product["last_updated"].endswith("Z")
    assert list(product)[:5] == ["id", "name", "brand", "size", "description"]


def test_product_details_from_either_source():
    only_bff = parsers.product_details(None, "584", fixture("product_bff.json"))
    assert only_bff["id"] == 1018067 and only_bff["gtin"] is None and only_bff["pricing"]["price"]
    only_gql = parsers.product_details(fixture("product_gql.json")["product"], "584", None)
    assert only_gql["gtin"] and only_gql["unspsc_code"] is None
    empty = parsers.product_details(None, "584", None)
    assert empty["id"] is None and empty["variations"] == {"total": 0, "varieties": [], "sizes": []}


def test_bulk_and_alternatives_cards():
    rows = fixture("products_info.json")["productsInfo"]["results"]
    cards = [parsers.product_card(row, "584") for row in rows]
    assert [c["id"] for c in cards] == [8150288, 409499] and all(c["pricing"]["price"] for c in cards)
    alternatives = fixture("alternatives.json")["results"][0]["alternatives"]
    assert parsers.product_card(alternatives[0], "584")["link"].startswith("https://www.coles.com.au/product/")


# ---- categories / stores / recipes -----------------------------------------------------

def test_category_tree():
    nodes = fixture("categories.json")["productCategories"]["catalogGroupView"]
    tree = [parsers.category_node(node) for node in nodes]
    dairy = next(n for n in tree if n["slug"] == "dairy-eggs-fridge")
    assert dairy["id"] == "1300" and dairy["level"] == 1 and dairy["has_subcategories"]
    child = dairy["subcategories"][0]
    assert child["path"].startswith("dairy-eggs-fridge/") and child["link"].endswith(child["path"])
    assert child["subcategories"][0]["level"] == 3
    shallow = parsers.category_node(nodes[0], depth=1)
    assert shallow["subcategories"] == [] and shallow["has_subcategories"]


def test_stores():
    rows = fixture("stores_find.json")["stores"]["results"]
    stores = [parsers.store(row["store"], row["distance"]) for row in rows]
    first = stores[0]
    assert first["id"].isdigit() and first["brand"]["code"] in ("COL", "LQR")
    assert first["distance_km"] is not None and first["address"]["state"] == "NSW"
    assert first["coordinates"]["latitude"] < 0 and "schedule" not in first["hours"]
    assert "next_door_stores" in first and "collection_points" not in first
    detail = parsers.store(fixture("store_details.json")["store"])
    assert detail["id"] == "584" and detail["link"].endswith("/find-stores/coles/vic/burwood-east-584")
    assert detail["hours"]["schedule"][0] == {"days": "Mon-Sun", "hours": "12am - 12am"}
    assert detail["collection_points"][0]["type"] == "concierge" and detail["distance_km"] is None
    assert parsers.store(None)["id"] is None


def test_stockists():
    raw = fixture("store_range.json")["storeRange"]
    product, states = parsers.stockists(raw, "8150288")
    assert product["id"] == 8150288 and product["name"] == "Full Cream Milk"
    assert {s["state"] for s in states} >= {"NSW", "VIC"} and states[0]["stores"][0]["id"]
    _, only = parsers.stockists(raw, "8150288", "TAS")
    assert [s["state"] for s in only] == ["TAS"]
    assert parsers.stockists(raw, "1") == (None, [])


def test_recipe():
    row = fixture("recipes.json")["searchRecipes"]["results"][0]
    recipe = parsers.recipe(row)
    assert recipe["id"] and recipe["title"] == recipe["title"].strip()
    assert recipe["link"].startswith("https://www.coles.com.au/recipes-inspiration/")
    assert recipe["ingredients"][0]["name"] and isinstance(recipe["ingredients"][0]["amount"], (int, float))
    assert [s["position"] for s in recipe["steps"]] == list(range(1, len(recipe["steps"]) + 1))
    assert recipe["cost"]["currency"] == "AUD" and recipe["servings"]
    assert parsers.recipe(None)["id"] is None and parsers.recipe({})["cost"] is None


# ---- schemas -------------------------------------------------------------------------

def test_search_schema():
    data, error = load_query(schemas.ProductSearchSchema, {
        "query": " milk ", "page": "2", "sort_by": "Price_Low_To_High", "special_type": "half_price",
        "brands": "Pauls, a2 Milk", "store": "COL:0584"})
    assert error is None
    assert data == {"query": "milk", "page": 2, "sort_by": "priceAscending", "special_type": "halfprice",
                    "brands": ["Pauls", "a2 Milk"], "dietary": None, "allergens": None, "store": "584"}
    defaults, _ = load_query(schemas.ProductSearchSchema, {"query": "milk"})
    assert defaults["page"] == 1 and defaults["sort_by"] is None and defaults["store"]


@pytest.mark.parametrize("schema, query", [
    (schemas.ProductSearchSchema, {}),
    (schemas.ProductSearchSchema, {"query": "milk", "sort_by": "cheapest"}),
    (schemas.ProductSearchSchema, {"query": "milk", "page": "105"}),
    (schemas.ProductSearchSchema, {"query": "milk", "url": "x"}),
    (schemas.ProductSearchSchema, {"query": "milk", "store": "LQR:6083"}),
    (schemas.ProductSchema, {"product": "abc"}),
    (schemas.BulkProductsSchema, {"products": ",".join(str(1000 + i) for i in range(21))}),
    (schemas.CategoryProductsSchema, {}),
    (schemas.StoreSearchSchema, {"location": "x"}),
    (schemas.StoreSearchSchema, {"location": "Bondi", "brand": "aldi"}),
    (schemas.StockistsSchema, {"product": "8150288", "state": "zz"}),
    (schemas.PublicHolidaysSchema, {}),
    (schemas.RecipeSchema, {"recipe_id": "honey-soy"}),
    (schemas.CategoriesSchema, {"depth": "4"}),
])
def test_schemas_reject(schema, query):
    data, error = load_query(schema, query)
    assert data is None and error["error"].startswith("Invalid parameters")


def test_other_schemas():
    bulk, _ = load_query(schemas.BulkProductsSchema, {
        "products": "8150288, https://www.coles.com.au/product/x-409499,8150288"})
    assert bulk["products"] == ["8150288", "409499"]
    stores, _ = load_query(schemas.StoreSearchSchema, {"location": "-33.8671,151.2071", "brand": "ALL"})
    assert stores["location"] == (-33.8671, 151.2071) and stores["brand"] == ["COL", "LQR", "FCL", "VIN"]
    assert stores["radius_km"] == 20 and stores["limit"] == 20
    assert load_query(schemas.StoreSchema, {"store": "lqr:6083"})[0] == {"store": "LQR:6083"}
    assert load_query(schemas.StockistsSchema, {"product": "8150288", "state": "tas"})[0]["state"] == "TAS"
    specials, _ = load_query(schemas.SpecialsSchema, {"category": "https://www.coles.com.au/on-special/pantry"})
    assert specials["category"] == "pantry" and specials["special_type"] is None


# ---- transport classification ----------------------------------------------------------

class _Resp:
    def __init__(self, status_code, text, content_type="text/html"):
        self.status_code, self.text, self.headers = status_code, text, {"content-type": content_type}


def test_block_detection():
    challenge = '<html><head><script src="/_Incapsula_Resource?SWJIYLWA=5074"></script><body></body></html>'
    assert fetch._is_block(_Resp(200, challenge))
    assert fetch._is_block(_Resp(403, "")) and fetch._is_block(_Resp(429, "{}", "application/json"))
    assert fetch._is_block(_Resp(200, "<title>Pardon Our Interruption</title>"))
    assert not fetch._is_block(_Resp(200, '{"noOfResults": 3}', "application/json"))
    assert not fetch._is_block(_Resp(404, '{ "statusCode": 404, "message": "Resource not found" }',
                                     "application/json"))


def test_error_message():
    assert fetch._error_message({"errors": [{"errorCode": "x", "message": "Invalid storeId"}]}) == "Invalid storeId"
    assert fetch._error_message({"statusCode": 404, "message": "Resource not found"}) == "Resource not found"
    assert fetch._error_message("nope") is None


def test_documents_are_self_contained():
    import re
    for name, document in fetch.DOCUMENTS.items():
        spreads = set(re.findall(r"\.\.\.([A-Za-z_]+)", document))
        defined = set(re.findall(r"fragment ([A-Za-z_]+) on", document))
        assert spreads <= defined, f"{name} misses fragments {spreads - defined}"
        assert f"query {name}(" in document
