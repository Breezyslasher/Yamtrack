"""Direct watch links from JustWatch.

JustWatch has no public API, this uses the GraphQL API of its website. It can
change without notice, so it is disabled by default and every failure is
handled by falling back to the TMDB watch providers without links.
"""

import logging

from django.conf import settings
from django.core.cache import cache

from app.models import MediaTypes
from app.providers import services

logger = logging.getLogger(__name__)
PROVIDER = "justwatch"
base_url = "https://apis.justwatch.com/graphql"

# JustWatch rejects requests with the default python-requests user agent (403),
# so identify like its own website does
headers = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
    ),
    "Origin": "https://www.justwatch.com",
    "Referer": "https://www.justwatch.com/",
}

# Offers are cached for a shorter time as prices and catalogs change often
CACHE_TIMEOUT = 60 * 60 * 6

search_query = """
query GetSearchTitles(
  $searchTitlesFilter: TitleFilter!,
  $country: Country!,
  $language: Language!,
  $first: Int!,
  $filter: OfferFilter!
) {
  popularTitles(
    country: $country
    filter: $searchTitlesFilter
    first: $first
    sortBy: POPULAR
    sortRandomSeed: 0
  ) {
    edges {
      node {
        objectType
        content(country: $country, language: $language) {
          title
          originalReleaseYear
          externalIds {
            tmdbId
          }
        }
        offers(country: $country, platform: WEB, filter: $filter) {
          monetizationType
          standardWebURL
          retailPrice(language: $language)
          package {
            packageId
          }
        }
      }
    }
  }
}
"""

OBJECT_TYPES = {
    MediaTypes.MOVIE.value: "MOVIE",
    MediaTypes.TV.value: "SHOW",
}
# FAST is free ad supported streaming, like the TMDB "ads" type
NO_CHARGE_TYPES = {"FLATRATE", "FREE", "ADS", "FAST"}
PAID_TYPES = {"BUY", "RENT"}


def is_enabled():
    """Return whether JustWatch links are enabled."""
    return settings.JUSTWATCH_ENABLED


def get_offers(media_type, tmdb_id, title, region):
    """Return the JustWatch offers of a movie or tv show, keyed by provider ID.

    Each provider has its `link` and the `buy_price` and `rent_price` if any.
    Returns an empty dict when no JustWatch title matches the TMDB ID.
    """
    cache_key = f"{PROVIDER}_{media_type}_{tmdb_id}_{region}"
    data = cache.get(cache_key)

    if data is None:
        language = settings.TMDB_LANG.split("-")[0]
        response = services.api_request(
            PROVIDER,
            "POST",
            base_url,
            headers=headers,
            params={
                "query": search_query,
                "variables": {
                    "searchTitlesFilter": {
                        "searchQuery": title,
                        "objectTypes": [OBJECT_TYPES[media_type]],
                    },
                    "country": region,
                    "language": language,
                    "first": 10,
                    "filter": {"bestOnly": True},
                },
            },
        )
        node = find_title(response, tmdb_id)
        data = process_offers(node["offers"]) if node else {}
        cache.set(cache_key, data, CACHE_TIMEOUT)

    return data


def find_title(response, tmdb_id):
    """Return the search result matching the TMDB ID, None if there is none."""
    edges = ((response.get("data") or {}).get("popularTitles") or {}).get("edges") or []
    for edge in edges:
        node = edge.get("node") or {}
        external_ids = (node.get("content") or {}).get("externalIds") or {}
        if str(external_ids.get("tmdbId")) == str(tmdb_id):
            return node
    return None


def process_offers(offers):
    """Return the link and prices of each provider from the JustWatch offers."""
    providers = {}
    for offer in offers or []:
        package_id = (offer.get("package") or {}).get("packageId")
        monetization_type = offer.get("monetizationType")
        if package_id is None or not offer.get("standardWebURL"):
            continue

        entry = providers.setdefault(
            package_id,
            {"link": None, "buy_price": None, "rent_price": None},
        )
        # Prefer the no charge link when a provider has several offers
        if monetization_type in NO_CHARGE_TYPES or entry["link"] is None:
            entry["link"] = offer["standardWebURL"]
        if monetization_type == "BUY":
            entry["buy_price"] = offer.get("retailPrice")
        elif monetization_type == "RENT":
            entry["rent_price"] = offer.get("retailPrice")
    return providers


def add_links(providers, media_type, tmdb_id, title, region):
    """Add the JustWatch link and prices to TMDB watch providers, in place.

    Providers without a JustWatch offer, or all of them when JustWatch is
    disabled or fails, are left without link.
    """
    if not is_enabled() or not providers or not title or not region:
        return

    # JustWatch is unofficial, keep the TMDB providers if it fails
    try:
        offers = get_offers(media_type, tmdb_id, title, region)
    except Exception:
        logger.exception("Failed to fetch JustWatch links for %s", tmdb_id)
        return

    for provider in providers:
        provider.update(offers.get(provider.get("provider_id"), {}))
