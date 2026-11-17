"""Coles in-store MAP image: the store floor plan with a product pinned at its aisle.

Coles' store map is FIRST-PARTY (not Oriient). Two sources, both reachable with the
tooling the Coles aisle scraper already runs:

  * metadata -- `fetch.app_instore_map(store)` -> the app GraphQL `inStoreMap` query
    (appsgql, X-D-Token-gated like the aisle data): {mapLocation, mx, my, bx, by, rotation}.
  * the floor-plan PNG -- a public AEM asset at
    `https://www.coles.com.au/content/dam/coles/stores/instore-maps/{store}.png`
    (= `mapLocation`), fetched through the existing AU website session (`fetch.store_map_image`).

Pin transform. Model: u = mx*productX + bx, v = my*productY + by, then a true rotation of
(u, v) onto the W x H plan: rot 0 -> (u, v), rot 90 -> (W - v, u), rot 180 -> (W - u, H - v),
rot 270 -> (v, H - u). Most Coles stores are rotation 90:
`image_x = W - (by + my*productY)`, `image_y = bx + mx*productX`.
Verified 2026-11-10 against 19 products x 2 stores (584, 616): every pin lands on its labelled
aisle, and "Back of Store" items sit at the back (away from Entry/Checkout). The first version
used (v, u) for rot 90 -- an axis swap (a reflection, not a rotation): the aisle was right but
the position ALONG the aisle was mirrored (pins inside the checkout / outside the walls).
Stress test 2026-11-11 (2632 products x 14 stores; 22 of 118 sampled stores have a map, with
rotations 0 / 90 / 270): rot 0 (602, 7781, 501), rot 90 (10 stores) and rot 270 (583) all put
every aisle in printed order (|rho| = 1.0), 0 pins off the plan, Front/Back-of-Store items at the
right ends. Rotation 180 has not been seen; it is the consistent proper rotation, best-effort.

The rendered pin is cached (render once) in the shared PRIVATE S3 bucket
(config.STORE_MAP_S3_BUCKET) under prefix "coles/", served to shoppers via CloudFront.
Best-effort throughout: any failure returns None so the aisle response still returns.
"""
import hashlib
import logging
import threading
import time
from io import BytesIO

import config
import store_map_render as render
from coles import fetch

_log = logging.getLogger(__name__)
COLES_RED = (224, 26, 34)

_lock = threading.Lock()
_meta_cache = {}   # store -> (inStoreMap meta or None, expires)
_plan_cache = {}   # mapLocation path -> (PNG bytes, expires)
_meta_flight = {}  # store -> Lock (single-flight the metadata fetch across a cold bulk)
_plan_flight = {}  # path -> Lock (single-flight the plan download across a cold bulk)
_dims_cache = {}   # mapLocation path -> ((W, H) of the native plan, expires): the pin geometry needs it
_s3_local = threading.local()        # boto3 client per thread (a shared client's pool crashes under concurrency)
_s3_create_lock = threading.Lock()   # botocore client creation is not concurrency-safe; serialize it


# ---- sources (cached) ----------------------------------------------------------------

_META_NS = "coles.instore_map"


# A value read FROM the shared cache is held in-process only this long: its row may be about to
# expire there, and holding it for a full TTL of its own doubled the lifetime (a "no map" answer
# lived up to 2 days, not the 1 day COLES_INSTORE_NOMAP_TTL promises). The shared row's expiry decides.
_SHARED_HIT_TTL = 3600


def _meta_ttl(meta):
    return config.COLES_INSTORE_MAP_TTL if meta else config.COLES_INSTORE_NOMAP_TTL


def _instore_map(store):
    """The store's inStoreMap metadata (or None when the store has no map). Cached in-process
    AND in the shared Postgres cache (COLES_INSTORE_MAP_TTL, 7 days; "no map" for
    COLES_INSTORE_NOMAP_TTL, 1 day), so a new pod or a restart does not re-ask the token-gated
    GraphQL for every store; single-flighted per store so a cold bulk makes ONE call, not one per
    product. A transient error is never cached (the next request retries)."""
    from datetime import timedelta
    store = str(store)
    with _lock:
        hit = _meta_cache.get(store)
        if hit and time.time() < hit[1]:
            return hit[0]
    with render.flight_lock(_meta_flight, store):
        with _lock:
            hit = _meta_cache.get(store)
            if hit and time.time() < hit[1]:
                return hit[0]
        found, meta = render.shared_get(_META_NS, store)
        hold = min(_SHARED_HIT_TTL, _meta_ttl(meta))
        if not found:
            meta = fetch.app_instore_map(store)
            hold = _meta_ttl(meta)
            render.shared_put(_META_NS, store, meta, timedelta(seconds=hold))
        with _lock:
            _meta_cache[store] = (meta, time.time() + hold)
        return meta


def _plan(path):
    """The floor-plan PNG bytes for a mapLocation path, cached and single-flighted per
    path so a cold bulk downloads the plan ONCE, not once per product; expired purged on miss."""
    with _lock:
        hit = _plan_cache.get(path)
        if hit and time.time() < hit[1]:
            return hit[0]
    with render.flight_lock(_plan_flight, path):
        now = time.time()
        with _lock:
            hit = _plan_cache.get(path)
            if hit and now < hit[1]:
                return hit[0]
            for k in [k for k, v in _plan_cache.items() if v[1] <= now]:
                del _plan_cache[k]
        data = fetch.store_map_image(path)
        try:   # header read only: a 200 that is not an image (an unrecognised challenge / error
            from PIL import Image   # page) must not be cached as the plan -- it would fail every
            Image.open(BytesIO(data)).size   # render of this store for COLES_MAP_PLAN_TTL (6 h)
        except Exception:
            raise fetch.ColesUpstreamError("store map image {}: the body is not an image".format(path))
        with _lock:
            _plan_cache[path] = (data, time.time() + config.COLES_MAP_PLAN_TTL)
        return data


def _plan_dims(path):
    """(W, H) of the native plan PNG -- needed for every pin geometry, even when the image is
    already in S3. A plan's size only changes if Coles republishes it (which also changes nothing
    in our keys), so it is held in-process for render.DIMS_TTL and in the shared Postgres cache
    (config.STORE_MAP_DIMS_TTL_DAYS): the ~85 KB plan is downloaded once per plan fleet-wide,
    not once per pod per day."""
    now = time.time()
    with _lock:
        hit = _dims_cache.get(path)
        if hit and now < hit[1]:
            return hit[0]
    size = render.plan_dims_cached(path)
    if size is None:
        from PIL import Image
        size = Image.open(BytesIO(_plan(path))).size
        render.remember_plan_dims(path, *size)
    with _lock:
        _dims_cache[path] = (size, now + render.DIMS_TTL)
    return size


# ---- transform -----------------------------------------------------------------------

def _pixel(meta, product_x, product_y, w, h):
    mx, my, bx, by = meta.get("mx"), meta.get("my"), meta.get("bx"), meta.get("by")
    rot = int(round(meta.get("rotation") or 0)) % 360
    u = mx * float(product_x) + bx
    v = my * float(product_y) + by
    if rot == 90:    # verified (584 + 616)
        return w - v, u
    if rot == 0:
        return u, v
    if rot == 180:
        return w - u, h - v
    if rot == 270:
        return v, h - u
    return w - v, u  # default to the verified 90 mapping


# ---- rendering (shared pattern with woolworths/store_map.py) --------------------------

def _draw_pin(plan_png, px, py, label=None, color=COLES_RED):
    """The floor plan with a Coles-red pin at native-plan pixel (px, py), as PNG bytes
    (white background, downscaled, relative pin size -- see store_map_render.render_pin)."""
    return render.render_pin(plan_png, px, py, label=label, color=color)


# ---- S3-cached pinned image (what the product lookup returns) -------------------------

def _s3():
    c = getattr(_s3_local, "client", None)
    if c is not None:
        return c
    with _s3_create_lock:  # lazy + serialized: botocore client creation is not concurrency-safe
        import boto3
        c = boto3.client("s3", region_name=config.STORE_MAP_S3_REGION)
    _s3_local.client = c   # thread-local: concurrent use of one shared client crashes its urllib3 pool
    return c


def _s3_has(bucket, key):
    try:
        _s3().head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _public_url(bucket, key):
    base = config.STORE_MAP_CDN_BASE
    if base:
        return "{}/{}".format(base.rstrip("/"), key)
    return "https://{}.s3.{}.amazonaws.com/{}".format(bucket, config.STORE_MAP_S3_REGION, key)


def _sig(meta, product_x, product_y, label=None):
    # content-addressed: the label is drawn into the image, so it is part of the key too;
    # RENDER_VERSION changes the key whenever the transform/drawing changes (S3 objects are immutable)
    raw = "{}|{}|{}|{}|{}|{}|{}|{}|{}|{}".format(
        render.RENDER_VERSION, product_x, product_y, meta.get("mapLocation"), meta.get("mx"),
        meta.get("my"), meta.get("bx"), meta.get("by"), meta.get("rotation"), label or "")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _put(bucket, key):
    return lambda png: _s3().put_object(Bucket=bucket, Key=key, Body=png, ContentType="image/png",
                                        CacheControl="public, max-age=31536000, immutable")


def _plan_sig(meta):
    # one object per store: no product / label in the key; RENDER_VERSION + the served size are in it
    raw = "{}|{}|{}".format(render.RENDER_VERSION, meta.get("mapLocation"), config.STORE_MAP_PLAN_MAX_PX)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def plan_image_url(store, meta):
    """CDN URL of the store's UNPINNED floor plan (white-flattened, downscaled to
    config.STORE_MAP_PLAN_MAX_PX), uploaded once per store and shared by all its products --
    what `unpin_images=true` returns; the client draws the pin at map_pin_pixel."""
    bucket = config.STORE_MAP_S3_BUCKET
    key = "coles/plan/{}-{}.png".format(store, _plan_sig(meta))
    render.ensure_uploaded(key, lambda k: _s3_has(bucket, k),
                           lambda: render.render_plan(_plan(meta["mapLocation"])), _put(bucket, key))
    return _public_url(bucket, key)


def map_info(store, product, product_x, product_y, label=None, pinned=True):
    """The map fields for one aisle location, or None:
      map_image_url      the floor plan with `product` pinned at (product_x, product_y) -- the
                         indoorCoordinates from the aisle lookup -- or, with pinned=False (the
                         `unpin_images` flag), the bare plan for the client to pin itself;
      map_image_width/height, map_pin_pixel {x,y} (pixels of that image), map_pin_ratio {x,y} (0..1).
    Rendered once and cached in the shared private S3 bucket behind CloudFront (content-addressed
    keys: an unchanged position reuses the object). Best-effort: None on any failure (no map for the
    store, pin off the plan, bucket unset, S3/render error) so the aisle response still returns."""
    bucket = config.STORE_MAP_S3_BUCKET
    if not bucket or product_x is None or product_y is None:
        return None
    try:
        meta = _instore_map(store)
        if not meta or not meta.get("mapLocation"):
            return None
        w, h = _plan_dims(meta["mapLocation"])
        px, py = _pixel(meta, product_x, product_y, w, h)
        if pinned:
            geo = render.pin_geometry(px, py, w, h, config.STORE_MAP_MAX_PX)
            key = "coles/{}/{}-{}.png".format(store, product, _sig(meta, product_x, product_y, label))
            render.ensure_uploaded(key, lambda k: _s3_has(bucket, k),
                                   lambda: _draw_pin(_plan(meta["mapLocation"]), px, py, label=label),
                                   _put(bucket, key))
            url = _public_url(bucket, key)
        else:
            geo = render.pin_geometry(px, py, w, h, config.STORE_MAP_PLAN_MAX_PX)
            url = plan_image_url(store, meta)
        return dict(map_image_url=url, **geo)
    except Exception:
        _log.warning("coles map_info failed (store=%s product=%s pinned=%s)", store, product, pinned, exc_info=True)
        return None


def map_image_url(store, product, product_x, product_y, label=None):
    """The pinned image's CloudFront URL alone (see map_info), or None."""
    info = map_info(store, product, product_x, product_y, label=label, pinned=True)
    return info["map_image_url"] if info else None


if __name__ == "__main__":  # smoke test: python -m coles.store_map 584 4504673 5459.36 2213.88 "Aisle 9"
    import sys
    print(map_image_url(sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]),
                        label=(sys.argv[5] if len(sys.argv) > 5 else None)))
