"""Live endpoint smoke tests: one call per /coles/* route against a running
service, with example values proven to return data (2026-10-05). The
listing tooling reads these calls as each route's working example.

Skipped unless COLES_BASE points at a running service:

    ONLY_SCRAPER=coles python run.py            # or any bottle runner
    COLES_BASE=http://127.0.0.1:6002 python -m pytest coles/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("COLES_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set COLES_BASE to run live endpoint tests")


def get(path, **params):
    from curl_cffi import requests
    return requests.get(BASE + path, params=params, timeout=300)


def call(path, **params):
    resp = get(path, **params)
    assert resp.status_code == 200, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


# ---- products ----------------------------------------------------------------------

def test_product_search():
    body = call("/coles/products/search", query="milk")
    assert body["count"] > 100 and body["total_pages"] > 1 and body["next"]
    first = body["products"][0]
    assert first["id"] and first["name"] and first["pricing"]["price"] and first["link"]
    assert body["filters"]["brands"] and body["categories"]
    cheap = call("/coles/products/search", query="milk", sort_by="price_low_to_high", page=2)
    prices = [p["pricing"]["price"] for p in cheap["products"] if p["pricing"] and not p["is_sponsored"]]
    assert prices == sorted(prices) and cheap["previous"]
    filtered = call("/coles/products/search", query="chocolate", brands="Cadbury", special_type="all")
    assert filtered["products"] and all(p["brand"] == "Cadbury" for p in filtered["products"])
    assert all(p["pricing"]["is_on_special"] for p in filtered["products"])


def test_product_search_store_prices():
    burwood = call("/coles/products/search", query="bananas", store="584")
    marrickville = call("/coles/products/search", query="bananas",
                        store="https://www.coles.com.au/find-stores/coles/nsw/marrickville-4166")
    assert burwood["store_id"] == "584" and marrickville["store_id"] == "4166"
    assert burwood["products"] and marrickville["products"]


def test_product_details():
    product = call("/coles/products/details", product="8150288")
    assert product["gtin"] == "9300601186945" and product["nutrition"]["panels"]
    assert product["ingredients"] and product["images"] and product["country_of_origin"]["country"]
    assert product["variations"]["total"] > 0 and product["pricing"]["price"]
    by_link = call("/coles/products/details",
                   product="https://www.coles.com.au/product/coles-full-cream-milk-3l-8150288", store="4166")
    assert by_link["id"] == 8150288 and by_link["store_id"] == "4166"


def test_product_bulk():
    body = call("/coles/products/bulk", products="8150288,409499,9999999")
    assert body["count"] == 2 and body["not_found_ids"] == [9999999]
    assert [p["id"] for p in body["products"]] == [8150288, 409499]


def test_product_alternatives():
    body = call("/coles/products/alternatives", product="8150288")
    assert body["count"] > 0 and body["products"][0]["pricing"]["price"]


def test_product_stockists():
    body = call("/coles/products/stockists", product="8150288")
    assert body["store_count"] > 500 and len(body["states"]) >= 6
    tas = call("/coles/products/stockists", product="8150288", state="TAS")
    assert [s["state"] for s in tas["states"]] == ["TAS"] and tas["states"][0]["stores"]


def test_product_suggestions():
    assert "chocolate" in call("/coles/products/suggestions", query="choc")["suggestions"]


# ---- specials / categories / brands ---------------------------------------------------

def test_specials():
    body = call("/coles/specials")
    assert body["count"] > 1000 and body["products"] and body["special_type"] == "all"
    half = call("/coles/specials", special_type="half_price", category="pantry")
    assert half["products"] and half["category"]["id"] == "10302"
    assert all(p["pricing"]["save_percent"] for p in half["products"] if not p["is_sponsored"])
    multi = call("/coles/specials", special_type="multi_buy")
    assert any(p["pricing"]["multi_buy"] for p in multi["products"])


def test_categories():
    tree = call("/coles/categories")
    assert tree["count"] >= 15 and tree["categories"][0]["subcategories"][0]["subcategories"]
    sub = call("/coles/categories", category="dairy-eggs-fridge", depth=1)
    assert sub["category"]["id"] == "1300" and sub["categories"] and not sub["categories"][0]["subcategories"]


def test_category_products():
    body = call("/coles/categories/products", category="dairy-eggs-fridge/milk")
    assert body["category"]["id"] == "8881800" and body["count"] > 50 and body["products"]
    by_id = call("/coles/categories/products", category="8881801", sort_by="price_high_to_low")
    assert by_id["category"]["path"] == "dairy-eggs-fridge/milk/full-cream-milk" and by_id["products"]
    by_link = call("/coles/categories/products", category="https://www.coles.com.au/browse/bakery", page=2)
    assert by_link["category"]["level"] == 1 and by_link["current_page"] == 2


def test_brand_products():
    body = call("/coles/brands/products", brand="Cadbury")
    assert body["brand"]["id"] and body["count"] > 50
    assert all(p["brand"] == "Cadbury" for p in body["products"])
    by_link = call("/coles/brands/products", brand="https://www.coles.com.au/brands/coles-3955134709")
    assert by_link["brand"]["name"] == "Coles" and by_link["count"] > 1000


# ---- stores --------------------------------------------------------------------------

def test_stores():
    body = call("/coles/stores/search", location="Bondi")
    assert body["location"]["state"] == "NSW" and body["stores"][0]["address"]["postcode"]
    near = call("/coles/stores/search", location="-33.8671,151.2071", brand="all", radius_km=2, limit=50)
    assert {s["brand"]["code"] for s in near["stores"]} >= {"COL", "LQR"}
    distances = [s["distance_km"] for s in near["stores"]]
    assert distances == sorted(distances) and distances[-1] <= 2
    store = call("/coles/stores/details", store="584")
    assert store["name"] == "Coles Burwood East" and store["hours"]["schedule"] and store["collection_points"]
    liquor = call("/coles/stores/details", store="LQR:6083")
    assert liquor["brand"]["code"] == "LQR"


def test_locations_and_holidays():
    places = call("/coles/locations/suggestions", query="parramatta")["locations"]
    assert places[0]["postcode"] == "2150" and places[0]["latitude"]
    holidays = call("/coles/public-holidays", state="NSW")["holidays"]
    assert holidays and all(h["state"] == "NSW" for h in holidays)


# ---- recipes -------------------------------------------------------------------------

def test_recipes():
    body = call("/coles/recipes/search", query="chicken", page_size=5)
    assert body["count"] > 100 and len(body["recipes"]) == 5
    recipe = call("/coles/recipes/details", recipe_id=body["recipes"][0]["id"])
    assert recipe["ingredients"] and recipe["steps"] and recipe["title"]
    assert call("/coles/recipes/details", recipe_id="463581")["title"] == "Honey Soy Chicken Stir Fry"
    quick = call("/coles/recipes/search", query="pasta", max_cooking_minutes=20)
    assert all((r["cooking_minutes"] or 0) <= 20 for r in quick["recipes"])


# ---- errors --------------------------------------------------------------------------

@pytest.mark.parametrize("path, params, status", [
    ("/coles/products/search", {}, 400),
    ("/coles/products/search", {"query": "milk", "sort_by": "cheapest"}, 400),
    ("/coles/products/search", {"query": "milk", "brands": "NoSuchBrandAtAll"}, 400),
    ("/coles/products/search", {"query": "milk", "page": 60}, 400),
    ("/coles/products/search", {"query": "milk", "store": "999999"}, 400),
    ("/coles/products/details", {"product": "9999999"}, 404),
    ("/coles/products/details", {"product": "not-a-product"}, 400),
    ("/coles/categories/products", {"category": "no-such-category"}, 404),
    ("/coles/brands/products", {"brand": "zzzznobrand"}, 404),
    ("/coles/stores/details", {"store": "99999"}, 404),
    ("/coles/stores/search", {"location": "qqqqzzzz"}, 404),
    ("/coles/recipes/details", {"recipe_id": "1"}, 404),
])
def test_errors(path, params, status):
    resp = get(path, **params)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:200]}"
    assert resp.json()["error"]
