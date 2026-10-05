"""Marshmallow request schemas for every /coles/* route.

Generic fields live in the shared top-level schema_fields.py; this module
adds the Coles resolvers and the per-route schemas. Every schema's load()
output is the kwargs dict its endpoint function takes.

ONE param per input (tripadvisor QueryOrLinkField convention, never a sibling
`url`/`id` pair):

    product    8150288 | coles.com.au/product/coles-full-cream-milk-3l-8150288
    products   up to 20 of the above, comma-separated
    store      584 | COL:584 | coles.com.au/find-stores/coles/vic/burwood-east-584
               (store routes also take liquor stores: LQR:6083)
    category   1300 | dairy-eggs-fridge/milk | coles.com.au/browse/dairy-eggs-fridge/milk
    brand      Cadbury | 3955134709 | coles.com.au/brands/coles-3955134709
    location   Bondi | 2000 | -33.8671,151.2071
"""
from marshmallow import ValidationError, fields, missing, validate

import config
from coles import refs
from coles.parsers import MAX_PAGES
from coles.products import MAX_BULK
from schema_fields import (BaseSchema, ChoiceField, CommaListField, PageField, PageSizeField, PositiveInt,
                           QueryField, RefField, StrippedString)

MAX_PAGE = MAX_PAGES     # 48 products a page; the gateway serves no listing deeper than this


class ProductRefField(RefField):
    """`product`: a product id or product link -> the id."""
    resolver = staticmethod(refs.resolve_product)


class ProductListField(fields.Field):
    """`products`: comma-separated product ids / links -> deduped id list."""

    def __init__(self, max_items=MAX_BULK, **kwargs):
        kwargs.setdefault("required", True)
        super().__init__(**kwargs)
        self.max_items = max_items

    def _deserialize(self, value, attr, data, **kwargs):
        items = []
        for raw in str(value or "").replace("\n", ",").split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                product_id = refs.resolve_product(raw)
            except ValueError as e:
                raise ValidationError(f"'{raw}': {e}")
            if product_id not in items:
                items.append(product_id)
        if not items:
            raise ValidationError("Pass at least one product id (e.g. 8150288,409499).")
        if len(items) > self.max_items:
            raise ValidationError(f"At most {self.max_items} products per request.")
        return items


class StoreRefField(RefField):
    """`store` on product routes: a Coles supermarket -> its numeric id.
    Optional; defaults to config.COLES_DEFAULT_STORE_ID."""
    resolver = staticmethod(refs.resolve_store)

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", config.COLES_DEFAULT_STORE_ID)
        super().__init__(**kwargs)


class BrandedStoreRefField(RefField):
    """`store` on store routes: any Coles Group store -> "COL:584"."""
    resolver = staticmethod(refs.resolve_branded_store)


class CategoryRefField(RefField):
    """`category`: id, slug path or browse link."""
    resolver = staticmethod(refs.resolve_category)


class BrandRefField(RefField):
    """`brand`: brand name, id or brand link."""
    resolver = staticmethod(refs.resolve_brand)


class LocationField(RefField):
    """`location`: suburb / postcode text, or latitude,longitude."""
    resolver = staticmethod(refs.resolve_location)


def _sort_field():
    return ChoiceField(refs.SORTS)


def _special_field():
    return ChoiceField(refs.SPECIAL_TYPES)


def _names_field():
    """Comma list of facet names or ids (case kept: ids are numeric, names
    are matched case-insensitively later)."""
    return CommaListField(upper=False, max_items=10)


class _ListingSchema(BaseSchema):
    page = PageField(max_page=MAX_PAGE)
    sort_by = _sort_field()
    dietary = _names_field()
    allergens = _names_field()
    store = StoreRefField()


# ---- products ---------------------------------------------------------------------

class ProductSearchSchema(_ListingSchema):
    query = QueryField(max_length=120)
    special_type = _special_field()
    brands = _names_field()


class CategoryProductsSchema(_ListingSchema):
    category = CategoryRefField()
    special_type = _special_field()
    brands = _names_field()


class SpecialsSchema(_ListingSchema):
    special_type = _special_field()
    category = CategoryRefField(required=False, load_default=None)
    brands = _names_field()


class BrandProductsSchema(_ListingSchema):
    brand = BrandRefField()
    special_type = _special_field()


class ProductSchema(BaseSchema):
    product = ProductRefField()
    store = StoreRefField()


class BulkProductsSchema(BaseSchema):
    products = ProductListField()
    store = StoreRefField()


class StockistsSchema(BaseSchema):
    product = ProductRefField()
    state = ChoiceField({s.lower(): s for s in refs.STATES})


class SuggestionsSchema(BaseSchema):
    query = QueryField(max_length=120)
    store = StoreRefField()


# ---- categories -------------------------------------------------------------------

class CategoriesSchema(BaseSchema):
    category = CategoryRefField(required=False, load_default=None)
    depth = fields.Integer(load_default=3, strict=False, validate=validate.Range(min=1, max=3))
    store = StoreRefField()


# ---- stores -----------------------------------------------------------------------

class StoreSearchSchema(BaseSchema):
    location = LocationField()
    radius_km = fields.Integer(load_default=20, strict=False, validate=validate.Range(min=1, max=500))
    limit = PageSizeField(default=20, max_size=100)
    brand = ChoiceField(refs.STORE_BRANDS)


class StoreSchema(BaseSchema):
    store = BrandedStoreRefField()


class LocationSuggestionsSchema(BaseSchema):
    query = QueryField(max_length=100, validate=validate.Length(min=2, max=100))
    limit = PageSizeField(default=10, max_size=25)


class PublicHolidaysSchema(BaseSchema):
    state = ChoiceField({s.lower(): s for s in refs.STATES}, required=True, load_default=missing)


# ---- recipes ----------------------------------------------------------------------

class RecipeSearchSchema(BaseSchema):
    query = QueryField(max_length=100)
    page = PageField(max_page=100)
    page_size = PageSizeField(default=20, max_size=50)
    max_cooking_minutes = PositiveInt(max_value=600)


class RecipeSchema(BaseSchema):
    recipe_id = StrippedString(required=True, validate=validate.Regexp(
        r"^\d{1,12}$", error="Must be a numeric recipe id (the `id` of a /coles/recipes/search result)."))
