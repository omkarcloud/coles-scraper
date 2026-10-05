"""/coles/recipes/* — Coles' recipe search (GraphQL `searchRecipes` /
`searchRecipesByIds`): ingredients with quantities, method steps, timings,
basket cost and nutrition.
"""
from coles import fetch, parsers


def search(query, page=1, page_size=20, max_cooking_minutes=None):
    variables = {"searchTerm": query, "page": page, "pageSize": page_size}
    if max_cooking_minutes:
        variables["maxCookingTime"] = max_cooking_minutes
    data = parsers.as_dict(fetch.gql("SearchRecipes", variables).get("searchRecipes"))
    recipes = [parsers.recipe(row) for row in parsers.as_list(data.get("results"))]
    if page > 1 and not recipes:
        raise ValueError(f"page {page} is past the last page.")
    return {
        "query": query,
        "recipes": recipes,
        "pagination": parsers.pagination(page, data.get("noOfResults"), page_size),
    }


def details(recipe_id):
    data = parsers.as_dict(fetch.gql("SearchRecipesByIds", {"recipeIds": [recipe_id], "page": 1, "pageSize": 1})
                           .get("searchRecipesByIds"))
    rows = parsers.as_list(data.get("results"))
    if not rows:
        raise fetch.ColesNotFound(f"No Coles recipe with id {recipe_id}.")
    return parsers.recipe(rows[0])
