# 🛒 Coles Scraper

Coles Scraper is a **free and open-source** scraper that gets you **unlimited** Coles product, price, specials and store data for free.

## ✨ What Can I Get?

- 🛒 **Search 22,000+ products** — live prices, unit prices, stock & specials at any store
- 🧾 **Full product details** — barcode (GTIN), nutrition panel, ingredients, allergens & images
- 🏷️ **7,000+ specials every week** — half price, multi-buy & online-only deals, by category
- 🏬 **Every Coles store, 880+ of them** — addresses, trading hours, per-store prices & stockists

## 🎥 Example: A Full Coles Product

```json
{
  "id": 329607,
  "name": "Tim Tam Chocolate Biscuits Original",
  "brand": "Arnott's",
  "size": "200g",
  "link": "https://www.coles.com.au/product/arnott-s-tim-tam-chocolate-biscuits-original-200g-329607",
  "gtin": "9310072000282",
  "image": "https://cdn.productimages.coles.com.au/productimages/3/329607.jpg",
  "is_available": true,
  "available_quantity": 519,
  "pricing": {
    "currency": "AUD",
    "price": 6,
    "unit_price": { "amount": 3, "quantity": 100, "unit": "g", "label": "$3.00/ 100g" },
    "is_on_special": false
  },
  "categories": [
    {
      "department": { "id": "8916201", "name": "Chips, Chocolates & Snacks" },
      "category": { "id": "657638318", "name": "Biscuits & Cookies" },
      "subcategory": { "id": "657638597", "name": "Chocolate Biscuits" }
    }
  ],
  "country_of_origin": { "country": "Australia", "statement": "Made in Australia" },
  "ingredients": "Milk Chocolate (38%) [Emulsifiers (Lecithin (Soy), 476), Sugar, Milk Solids, Cocoa Butter, Cocoa Mass, Vegetable Oil, Flavour], Wheat Flour, Sugar, ...",
  "allergens": "Contains Gluten, Wheat\nMay Contain Egg, Peanut, Sesame",
  "nutrition": {
    "serving_size": "100g",
    "servings_per_package": 2,
    "panels": [
      {
        "basis": "per_serving",
        "nutrients": [
          { "name": "Energy (kJ)", "amount": 2190, "unit": "kJ", "daily_intake_percent": 25 },
          { "name": "Protein", "amount": 4.6, "unit": "g", "daily_intake_percent": 9 }
        ]
      }
    ]
  },
  "variations": {
    "total": 4,
    "sizes": [
      { "id": 6634760, "name": "Tim Tam Original Chocolate Biscuit Large Pack", "size": "365g", "pricing": { "price": 6.4, "was_price": 8 } }
    ]
  },
  "store_id": "584",
  "last_updated": "2026-10-05T10:55:28Z"
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Coles Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/coles-scraper
cd coles-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

On an Australian, New Zealand or US home or office connection, that's it — no proxy, no API key. Coles blocks other countries and cloud servers, so anywhere else start it with an Australian residential proxy instead:
```bash
COLES_PROXY=http://user:pass@host:port python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/products/details?product=329607"
```

```json
{
  "id": 329607,
  "name": "Tim Tam Chocolate Biscuits Original",
  "brand": "Arnott's",
  "size": "200g",
  "link": "https://www.coles.com.au/product/arnott-s-tim-tam-chocolate-biscuits-original-200g-329607",
  "gtin": "9310072000282",
  "is_available": true,
  "available_quantity": 519,
  "pricing": {
    "currency": "AUD",
    "price": 6,
    "unit_price": { "amount": 3, "quantity": 100, "unit": "g", "label": "$3.00/ 100g" },
    "is_on_special": false
  },
  "country_of_origin": { "country": "Australia", "statement": "Made in Australia" },
  "allergens": "Contains Gluten, Wheat\nMay Contain Egg, Peanut, Sesame",
  "store_id": "584"
}
```

All 16 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

16 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Product Details | `/products/details` | Everything about one product in a single call |
| Search Products | `/products/search` | 48 products per page with brand, dietary & specials filters |
| Search Suggestions | `/products/suggestions` | Autocomplete terms, ranked the way Coles ranks them |
| Bulk Product Lookup | `/products/bulk` | Prices and stock for 20 products at once |
| Product Alternatives | `/products/alternatives` | Substitutes for a product, with live prices |
| Product Stockists | `/products/stockists` | Every store that ranges a product, by state |
| Specials | `/specials` | Half-price, multi-buy and online-only deals |
| Categories | `/categories` | The full category tree with IDs and product counts |
| Category Products | `/categories/products` | Every product in any category or subcategory |
| Brand Products | `/brands/products` | Every product of one brand |
| Search Stores | `/stores/search` | Nearest stores to a suburb, postcode or coordinates |
| Store Details | `/stores/details` | Address, phone, weekly hours and Click & Collect |
| Location Suggestions | `/locations/suggestions` | Suburb and postcode autocomplete with coordinates |
| Public Holidays | `/public-holidays` | Public holidays for any Australian state |
| Search Recipes | `/recipes/search` | Recipes with ingredients, steps, cost and nutrition |
| Recipe Details | `/recipes/details` | One recipe in full, by ID |

Prices, stock and aisle locations are per store. Every product endpoint takes an optional `store` (a store ID from `/stores/search`, or any coles.com.au store link).

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-coles-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-coles-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-coles-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/products/details",
    params={"product": "329607"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Coles Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Coles%20Scraper%20API.)

[![Ask Us by Email about Coles Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Coles%20Scraper%20API&body=I%20need%20help%20using%20the%20Coles%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**Amazon Scraper**](https://www.omkar.cloud/tools/amazon-scraper) — Amazon products: prices, ratings, reviews & offers
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper) — live product details, SKU variants, stock & shipping
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/coles-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/coles-scraper)
