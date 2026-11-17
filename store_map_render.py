"""Stand-in for the hosted service's store-map renderer. There, a product's
aisle is drawn on the store's floor plan and the image is kept in an image
store; this repo has no image store, so asking for a map image raises
Unavailable and everything else about a product or a store works as usual."""
import contextlib
import threading

from scraper_errors import Unavailable

RENDER_VERSION = 0
DIMS_TTL = 0
SEM = threading.BoundedSemaphore(1)
TEXT_LOCK = threading.Lock()
_NO_STORE = "store-map images need an image store, which this repo does not have"


def shared_get(namespace, key):
    return None


def shared_put(namespace, key, value, ttl):
    return None


def exists_cached(key):
    return False


def mark_exists(key):
    return None


def plan_dims_cached(key):
    return None


def remember_plan_dims(key, w, h):
    return None


def plan_scale(w, h, max_px=None):
    raise Unavailable(_NO_STORE)


def pin_geometry(px, py, w, h, max_px=None):
    raise Unavailable(_NO_STORE)


def render_plan(plan_png, max_px=None):
    raise Unavailable(_NO_STORE)


def render_pin(plan_png, px, py, label=None, color=(224, 26, 34)):
    raise Unavailable(_NO_STORE)


def ensure_uploaded(key, has, render_png, put):
    raise Unavailable(_NO_STORE)


@contextlib.contextmanager
def flight_lock(registry, key):
    yield
