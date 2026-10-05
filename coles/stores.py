"""/coles/stores/*, /coles/locations/suggestions and /coles/public-holidays —
the store finder (GraphQL `stores`, `store`, `localitySearch`,
`publicHolidays`). Covers Coles supermarkets and the group's liquor brands
(Liquorland, First Choice Liquor Market, Vintage Cellars).
"""
from coles import fetch, parsers


def _localities(term, count):
    data = fetch.gql("GetStoreLocationSuggestions", {"term": term, "count": count})
    rows = parsers.as_list(parsers.as_dict(data.get("localitySearch")).get("results"))
    return [parsers.locality(row) for row in rows]


def location_suggestions(query, limit=10):
    """Suburb / postcode autocomplete with coordinates."""
    found = _localities(query, limit)
    return {"query": query, "count": len(found), "locations": found}


def search(location, radius_km=20, limit=20, brand=None):
    """Stores nearest to a suburb, postcode or latitude,longitude."""
    brand_codes = brand or ["COL"]
    if isinstance(location, tuple):
        origin = {"suburb": None, "state": None, "postcode": None,
                  "latitude": location[0], "longitude": location[1]}
    else:
        matches = _localities(location, 1)
        if not matches:
            raise fetch.ColesNotFound(f"No Australian suburb or postcode matches '{location}'.")
        origin = matches[0]
    data = fetch.gql("FindStores", {"latitude": origin["latitude"], "longitude": origin["longitude"],
                                    "brandIds": brand_codes, "count": limit, "distance": radius_km})
    rows = parsers.as_list(parsers.as_dict(data.get("stores")).get("results"))
    stores = [parsers.store(parsers.as_dict(row).get("store"), parsers.as_dict(row).get("distance"))
              for row in rows]
    return {"location": origin, "radius_km": radius_km, "count": len(stores), "stores": stores}


def details(store):
    """One store: address, phone, weekly hours, holiday exceptions,
    services and Click & Collect points."""
    try:
        record = fetch.gql("GetStoreDetails", {"id": store}).get("store")
    except fetch.ColesNotFound:      # upstream: "One or more validation errors occurred."
        record = None
    if not record:
        raise fetch.ColesNotFound(f"No Coles store {store}.")
    return parsers.store(record)


def public_holidays(state):
    """The public holidays Coles' trading hours follow in one state (the
    gateway answers an empty list without a state)."""
    data = fetch.gql("PublicHolidays", {"state": state})
    rows = []
    for row in parsers.as_list(data.get("publicHolidays")):
        row = parsers.as_dict(row)
        rows.append({"date": parsers.text(row.get("date")), "name": parsers.text(row.get("name")),
                     "state": (parsers.text(row.get("state")) or "").upper() or None})
    rows.sort(key=lambda r: (r["date"] or "", r["state"] or ""))
    return {"state": state, "count": len(rows), "holidays": rows}
