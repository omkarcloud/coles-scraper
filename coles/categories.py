"""/coles/categories — the browse tree (3 levels, ~1,400 nodes) from the
GraphQL `productCategories` query, and the lookup the listing routes use to
turn a `category` (id, slug path or browse link) into the id + level + name
triple the search gateway requires.

The tree is one 230 KB upstream call: memoized in-process and stored in the
response cache, so listings never pay for it twice.
"""
import config
from cache import cached_call
from coles import cache_config as ttl
from coles import fetch, parsers


def _fetch_tree(store):
    data = fetch.gql("GetProductCategories", {"storeId": f"COL:{store}", "withCampaignLinks": False})
    nodes = parsers.as_list(parsers.as_dict(data.get("productCategories")).get("catalogGroupView"))
    if not nodes:
        raise fetch.ColesUpstreamError("the category tree came back empty")
    return nodes


def raw_tree(store=None):
    """The upstream tree for a store (product counts are per store; ids,
    names and slugs are the same everywhere)."""
    store = store or config.COLES_DEFAULT_STORE_ID
    return fetch.memoized(("categories", store), lambda: cached_call(
        "coles.category_tree", {"store": store}, lambda **_: _fetch_tree(store), ttl.CATEGORIES_CACHE))


def _walk(nodes, ancestors=()):
    for node in nodes:
        node = parsers.as_dict(node)
        yield node, ancestors
        yield from _walk(parsers.as_list(node.get("catalogGroupView")), ancestors + (node,))


def _located(node, ancestors):
    slugs = [parsers.text(n.get("seoToken")) or "" for n in ancestors + (node,)]
    return {
        "id": parsers.text(node.get("id")),
        "name": parsers.text(node.get("name")),
        # The gateway matches on the untouched upstream name.
        "upstream_name": node.get("originalName") or node.get("name"),
        "level": parsers.integer(node.get("level")) or len(slugs),
        "path": "/".join(slugs),
        "raw": node,
    }


def find(ref, store=None):
    """A resolved category ref ("1300" or "dairy-eggs-fridge/milk") -> the
    located node. A one-segment slug may name a node at any level when it is
    unique. Raises ColesNotFound."""
    nodes = raw_tree(store)
    if ref.isdigit():
        for node, ancestors in _walk(nodes):
            if str(node.get("id")) == ref:
                return _located(node, ancestors)
        raise fetch.ColesNotFound(f"No Coles category with id {ref}.")
    slugs = ref.split("/")
    matches = [(node, ancestors) for node, ancestors in _walk(nodes)
               if [n.get("seoToken") for n in ancestors + (node,)] == slugs]
    if not matches and len(slugs) == 1:
        matches = [(node, ancestors) for node, ancestors in _walk(nodes) if node.get("seoToken") == slugs[0]]
        if len(matches) > 1:
            paths = ", ".join(_located(n, a)["path"] for n, a in matches[:8])
            raise ValueError(f"'{ref}' names several categories; pass the full path: {paths}.")
    if not matches:
        raise fetch.ColesNotFound(f"No Coles category '{ref}'. See /coles/categories for the tree.")
    return _located(*matches[0])


def summary(located):
    """The identity block listings put in their response."""
    from coles import refs
    return {"id": located["id"], "name": located["name"], "path": located["path"],
            "link": refs.category_link(located["path"]), "level": located["level"]}


def categories(category=None, depth=3, store=None):
    """The whole tree, or the subtree under `category`, `depth` levels deep."""
    store = store or config.COLES_DEFAULT_STORE_ID
    if category:
        located = find(category, store)
        parent_path = located["path"].rpartition("/")[0]
        root = parsers.category_node(located["raw"], parent_path, depth + 1)
        return {"store_id": str(store), "category": {k: root[k] for k in root if k != "subcategories"},
                "count": len(root["subcategories"]), "categories": root["subcategories"]}
    nodes = [parsers.category_node(node, "", depth) for node in raw_tree(store)]
    return {"store_id": str(store), "category": None, "count": len(nodes), "categories": nodes}
