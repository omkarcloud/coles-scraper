"""Offline tests: Coles store-map pin transform.

Ground truth captured 2026-11-10 (live inStoreMap params + aisle API at stores 584 and 616,
19 products each). The first version mapped rotation 90 as (v, u) -- an axis SWAP (reflection):
the aisle was right but the position along the aisle was mirrored, putting shelved products
inside the checkout area / outside the walls. A true 90-degree rotation is (W - v, u).

    python -m pytest coles/test_store_map.py -q
"""
import pytest

import store_map_render as render
from coles import store_map as co
from scraper_utils.testing import hosted_only

# Every test here draws or measures with the hosted store-map renderer, which a repo does not have.
pytestmark = hosted_only

W, H = 2000, 3450   # the DAM plan renditions at 584 / 616
META_584 = {"mapLocation": "/content/dam/coles/stores/instore-maps/584.png", "mx": 0.343308963,
            "my": -0.336096494, "bx": 536.0963225, "by": 1798.60136, "rotation": 90}
META_616 = {"mapLocation": "/content/dam/coles/stores/instore-maps/616.png", "mx": 0.45412929786275724,
            "my": -0.445406463043597, "bx": 117.73115908173259, "by": 1750.968536838307, "rotation": 90}


def test_rot90_is_a_rotation_not_an_axis_swap():
    x, y = 5459.3586, 2213.8807                       # colgate, Aisle 9 @584
    u = META_584["mx"] * x + META_584["bx"]
    v = META_584["my"] * y + META_584["by"]
    assert co._pixel(META_584, x, y, W, H) == pytest.approx((W - v, u))


def test_584_back_of_store_items_are_at_the_back():
    """Entry + checkout are on the LEFT of the 584 plan (x < ~420 px), so 'Back of Store'
    products must land on the right half -- the old mirror put them inside the checkout."""
    for x, y in [(2465.0779, 4305.4328),   # rice, Aisle 1 Back of Store
                 (2465.0779, 3298.9328),   # pasta, Aisle 1 Back of Store
                 (2856.7347, 4146.909)]:   # tomatoes, Aisle 2 Back of Store
        px, _ = co._pixel(META_584, x, y, W, H)
        assert px > W / 2


def test_616_shelved_items_stay_out_of_the_checkout_and_inside_the_walls():
    """At 616 the checkout block spans x < ~520 px and the aisles start at x ~ 640 px."""
    for x, y in [(3556.2745, 2978.0369),   # Aisle 5 Left
                 (3912.3945, 2691.7669),   # Aisle 6 Left
                 (4229.2845, 2871.4469),   # Aisle 7 Left
                 (5163.5345, 2419.9569),   # Aisle 10 Left
                 (6424.3445, 2691.3569)]:  # Aisle 14 Left
        px, py = co._pixel(META_616, x, y, W, H)
        assert 640 <= px <= W and 0 <= py <= H


def test_aisle_order_runs_down_the_plan():
    ys = [co._pixel(META_584, x, 3000, W, H)[1] for x in (3218.1579, 3865.6904, 5106.3886, 6742.5279)]  # A3, A4, A8, A12
    assert ys == sorted(ys)


@pytest.mark.parametrize("rot,expect", [(0, lambda u, v: (u, v)), (180, lambda u, v: (W - u, H - v)),
                                        (270, lambda u, v: (v, H - u))])
def test_other_rotations_are_proper_rotations(rot, expect):
    meta = dict(META_584, rotation=rot)
    x, y = 4000.0, 2500.0
    u, v = meta["mx"] * x + meta["bx"], meta["my"] * y + meta["by"]
    assert co._pixel(meta, x, y, W, H) == pytest.approx(expect(u, v))


@hosted_only
def test_plan_does_not_cache_a_body_that_is_not_an_image(monkeypatch):
    """A 200 that is not an image (an unrecognised challenge page) used to be cached as the
    plan for 6 h, failing every render of that store; now it raises and the next call refetches."""
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (20, 30), (255, 255, 255)).save(buf, format="PNG")
    bodies = [b"<html>challenge</html>", buf.getvalue()]
    monkeypatch.setattr(co, "_plan_cache", {})
    monkeypatch.setattr(co.fetch, "store_map_image", lambda path: bodies.pop(0))
    with pytest.raises(co.fetch.ColesUpstreamError):
        co._plan("/content/dam/coles/stores/instore-maps/584.png")
    assert co._plan_cache == {}
    assert co._plan("/content/dam/coles/stores/instore-maps/584.png") == buf.getvalue()
    assert co._plan("/content/dam/coles/stores/instore-maps/584.png") == buf.getvalue()   # cached
    assert bodies == []


def test_sig_depends_on_render_version(monkeypatch):
    base = co._sig(META_584, 5459.3586, 2213.8807, "Aisle 9")
    assert base == co._sig(META_584, 5459.3586, 2213.8807, "Aisle 9")
    monkeypatch.setattr(render, "RENDER_VERSION", "v-test")
    assert co._sig(META_584, 5459.3586, 2213.8807, "Aisle 9") != base


# ---- unpin_images: the bare plan + client-side pin geometry (2026-11-13) ----------------

def _png(size, rgba=(255, 255, 255, 255)):
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGBA", size, rgba).save(buf, format="PNG")
    return buf.getvalue()


@hosted_only
def test_pin_geometry_agrees_with_render_pin(monkeypatch):
    """The pixel we tell the client to draw at is where render_pin draws (one plan_scale)."""
    from io import BytesIO
    from PIL import Image
    monkeypatch.setattr(render.config, "STORE_MAP_MAX_PX", 200)
    geo = render.pin_geometry(200, 150, 400, 300, 200)
    assert geo == {"map_image_width": 200, "map_image_height": 150,
                   "map_pin_pixel": {"x": 100, "y": 75}, "map_pin_ratio": {"x": 0.5, "y": 0.5}}
    out = Image.open(BytesIO(render.render_pin(_png((400, 300)), 200, 150, color=(16, 122, 70))))
    assert out.size == (geo["map_image_width"], geo["map_image_height"])
    x, y = geo["map_pin_pixel"]["x"], geo["map_pin_pixel"]["y"]
    assert out.getpixel((x, y - 8)) == (16, 122, 70)        # the pin's tail, just above its point


@pytest.mark.parametrize("pt", [(-1, 10), (10, -1), (401, 10), (10, 301)])
def test_pin_geometry_refuses_a_pin_off_the_plan(pt):
    with pytest.raises(ValueError):
        render.pin_geometry(*pt, 400, 300, 200)


def test_render_plan_is_the_bare_downscaled_plan_on_white():
    from io import BytesIO
    from PIL import Image
    out = Image.open(BytesIO(render.render_plan(_png((400, 300), (0, 0, 0, 0)), 200)))
    assert out.size == (200, 150) and out.mode == "RGB"
    assert out.getpixel((100, 75)) == (255, 255, 255)        # no pin; transparency flattened to white


@pytest.fixture
def map_env(monkeypatch):
    keys = []
    monkeypatch.setattr(co.config, "STORE_MAP_S3_BUCKET", "bucket")
    monkeypatch.setattr(co.config, "STORE_MAP_CDN_BASE", "https://cdn")
    monkeypatch.setattr(co, "_instore_map", lambda store: META_584)
    monkeypatch.setattr(co, "_plan_dims", lambda path: (W, H))
    monkeypatch.setattr(co, "_s3", lambda: pytest.fail("no S3 in an offline test"))
    monkeypatch.setattr(render, "ensure_uploaded", lambda key, has, render_png, put: keys.append(key))
    return keys


def test_map_info_unpinned_returns_the_shared_plan_and_the_pin_geometry(map_env):
    a = co.map_info("584", "4504673", 5459.3586, 2213.8807, label="Aisle 9", pinned=False)
    b = co.map_info("584", "5795130", 7191.1679, 4359.2928, label="Aisle 14", pinned=False)
    assert a["map_image_url"].startswith("https://cdn/coles/plan/584-") and a["map_image_url"] == b["map_image_url"]
    f, wo, ho = render.plan_scale(W, H, co.config.STORE_MAP_PLAN_MAX_PX)
    assert (a["map_image_width"], a["map_image_height"]) == (wo, ho) == (1159, 2000)
    px, py = co._pixel(META_584, 5459.3586, 2213.8807, W, H)
    assert a["map_pin_pixel"] == {"x": round(px * f), "y": round(py * f)}
    assert a["map_pin_ratio"] == {"x": round(px / W, 4), "y": round(py / H, 4)}
    assert all(isinstance(v, int) for v in a["map_pin_pixel"].values())
    assert 0 <= a["map_pin_ratio"]["x"] <= 1 and 0 <= a["map_pin_ratio"]["y"] <= 1
    assert len(set(map_env)) == 1 and map_env[0].startswith("coles/plan/584-")   # one plan object per store


def test_map_info_pinned_keeps_the_per_product_key_and_the_same_geometry(map_env):
    p = co.map_info("584", "4504673", 5459.3586, 2213.8807, label="Aisle 9", pinned=True)
    u = co.map_info("584", "4504673", 5459.3586, 2213.8807, label="Aisle 9", pinned=False)
    assert p["map_image_url"].startswith("https://cdn/coles/584/4504673-")
    assert p["map_pin_pixel"] == u["map_pin_pixel"] and p["map_image_width"] == u["map_image_width"]
    assert co.map_image_url("584", "4504673", 5459.3586, 2213.8807, label="Aisle 9") == p["map_image_url"]


def test_map_info_is_none_when_the_pin_is_off_the_plan(map_env, monkeypatch):
    monkeypatch.setattr(co, "_pixel", lambda *a: (-5.0, 10.0))
    assert co.map_info("584", "x", 1, 2, pinned=False) is None
    assert map_env == []


def test_attach_map_images_merges_the_fields_and_passes_unpin(monkeypatch):
    from coles import products
    seen = []
    monkeypatch.setattr(products.store_map, "map_info",
                        lambda store, product, x, y, label=None, pinned=True:
                        (seen.append((store, product, x, y, label, pinned)) or
                         {"map_image_url": "u", "map_image_width": 1, "map_image_height": 2,
                          "map_pin_pixel": {"x": 3, "y": 4}, "map_pin_ratio": {"x": 0.5, "y": 0.5}}))
    rec = {"aisle_locations": [{"aisle": "Aisle 9", "map_pin": {"x": 1, "y": 2}}, {"aisle": "Aisle 2"}]}
    products._attach_map_images("584", "4504673", rec, unpin=True)
    assert seen == [("584", "4504673", 1, 2, "Aisle 9", False)]
    assert rec["aisle_locations"][0]["map_pin_pixel"] == {"x": 3, "y": 4}
    assert "map_image_url" not in rec["aisle_locations"][1]


def test_plan_dims_uses_the_shared_cache_before_downloading(monkeypatch):
    """A plan's size is needed for every pin geometry even when the image is in S3; it must come
    from the shared cache (one fetch fleet-wide), not an ~85 KB download per pod per day."""
    monkeypatch.setattr(co, "_dims_cache", {})
    monkeypatch.setattr(co, "_plan", lambda path: pytest.fail("must not download the plan"))
    monkeypatch.setattr(render, "plan_dims_cached", lambda key: (2000, 3450))
    assert co._plan_dims("/content/dam/coles/stores/instore-maps/584.png") == (2000, 3450)
    monkeypatch.setattr(render, "plan_dims_cached", lambda key: pytest.fail("in-process cache must serve the repeat"))
    assert co._plan_dims("/content/dam/coles/stores/instore-maps/584.png") == (2000, 3450)


def test_plan_dims_records_a_fresh_measurement_for_the_fleet(monkeypatch):
    monkeypatch.setattr(co, "_dims_cache", {})
    monkeypatch.setattr(co, "_plan", lambda path: _png((20, 30)))
    monkeypatch.setattr(render, "plan_dims_cached", lambda key: None)
    remembered = []
    monkeypatch.setattr(render, "remember_plan_dims", lambda key, w, h: remembered.append((key, w, h)))
    assert co._plan_dims("/p/584.png") == (20, 30)
    assert remembered == [("/p/584.png", 20, 30)]


def test_every_product_route_accepts_every_field_its_schema_declares():
    """ProductSchema is shared by details AND alternatives: adding `unpin_images` to it made
    every /coles/products/alternatives call a TypeError (HTTP 500) until the signature took the
    flag. The route calls impl(**loaded), so each impl must accept all of its schema's fields."""
    import inspect
    from coles import products, schemas
    for impl, schema in [(products.details, schemas.ProductSchema), (products.alternatives, schemas.ProductSchema),
                         (products.bulk, schemas.BulkProductsSchema)]:
        params = inspect.signature(impl).parameters
        missing = [f for f in schema().fields if f not in params
                   and not any(p.kind is p.VAR_KEYWORD for p in params.values())]
        assert not missing, "{} does not accept {}".format(impl.__name__, missing)


# ---- inStoreMap metadata: 7 days, shared across pods (2026-11-13) -------------------------

@pytest.fixture
def meta_env(monkeypatch):
    rows, calls = {}, []
    monkeypatch.setattr(co, "_meta_cache", {})
    monkeypatch.setattr(render, "shared_get", lambda ns, k: ((True, rows[(ns, k)]) if (ns, k) in rows else (False, None)))
    monkeypatch.setattr(render, "shared_put", lambda ns, k, v, ttl: rows.__setitem__((ns, k), v) or calls.append(("put", k, ttl)))
    return rows, calls


def test_instore_map_from_another_pod_skips_the_graphql(meta_env, monkeypatch):
    rows, _ = meta_env
    rows[(co._META_NS, "584")] = META_584
    monkeypatch.setattr(co.fetch, "app_instore_map", lambda store: pytest.fail("must not call the GraphQL"))
    assert co._instore_map("584") == META_584
    assert co._instore_map(584) == META_584                            # in-process now


def test_instore_map_fetch_is_shared_for_7_days_and_no_map_for_1_day(meta_env, monkeypatch):
    rows, calls = meta_env
    answers = {"584": META_584, "728": None}
    monkeypatch.setattr(co.fetch, "app_instore_map", lambda store: answers[store])
    assert co._instore_map("584") == META_584
    assert co._instore_map("728") is None
    ttls = {k: ttl.total_seconds() for _, k, ttl in calls}
    assert ttls == {"584": 7 * 86400, "728": 86400}
    assert rows[(co._META_NS, "728")] is None                           # the negative is shared too


def test_instore_map_error_is_not_cached(meta_env, monkeypatch):
    rows, calls = meta_env
    def boom(store):
        raise co.fetch.ColesUpstreamError("token box down")
    monkeypatch.setattr(co.fetch, "app_instore_map", boom)
    with pytest.raises(co.fetch.ColesUpstreamError):
        co._instore_map("584")
    assert calls == [] and co._meta_cache == {}


def test_instore_map_read_from_the_shared_cache_is_not_held_for_a_second_full_ttl(meta_env, monkeypatch):
    rows, _ = meta_env
    rows[(co._META_NS, "728")] = None                                   # "no map", written by another pod
    rows[(co._META_NS, "584")] = META_584
    monkeypatch.setattr(co.fetch, "app_instore_map", lambda store: pytest.fail("must not call the GraphQL"))
    now = co.time.time()
    assert co._instore_map("728") is None and co._instore_map("584") == META_584
    # the shared row may expire any moment: its own expiry decides, not a fresh TTL started here
    for store in ("728", "584"):
        assert co._meta_cache[store][1] - now <= co._SHARED_HIT_TTL + 5
