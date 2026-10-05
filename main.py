"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json.
"""
import json
import os

from coles.products import details, search, specials

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a product id or any coles.com.au product link: price, GTIN, nutrition, ingredients, images
    save("product_329607.json", details("329607"))

    # 48 products per page, with prices and stock at the default store
    save("search_tim_tam.json", search("tim tam"))

    # this week's half-price specials
    save("specials_half_price.json", specials(special_type="halfprice"))
