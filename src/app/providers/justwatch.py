"""Watch providers with direct links from JustWatch.

JustWatch has no public API, this uses the GraphQL API of its website. It can
change without notice, so it is disabled by default and every failure is
handled by falling back to the TMDB watch providers without links.

TMDB gets its watch providers from JustWatch but updates them later, so when
JustWatch has the media its offers replace the TMDB providers.
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
          presentationType
          standardWebURL
          retailPrice(language: $language)
          package {
            packageId
            clearName
            icon(profile: S100, format: PNG)
          }
        }
      }
    }
  }
}
"""

packages_query = """
query GetPackages($country: Country!, $platform: Platform!) {
  packages(country: $country, platform: $platform, includeAddons: true) {
    packageId
    clearName
    icon(profile: S100, format: PNG)
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
# JustWatch presentation types of the streaming video qualities
QUALITIES = {"SD": "SD", "HD": "HD", "_4K": "4K"}
QUALITY_ORDER = ["SD", "HD", "4K"]
# Physical media sold by stores like Amazon DVD / Blu-ray, not streaming
PHYSICAL_PRESENTATION_TYPES = {"DVD", "BLURAY", "_4K_BLURAY"}
images_url = "https://images.justwatch.com"


def is_enabled():
    """Return whether JustWatch links are enabled."""
    return settings.JUSTWATCH_ENABLED


def get_offers(media_type, tmdb_id, title, region):
    """Return the JustWatch offers of a movie or tv show, keyed by provider ID.

    Each provider has its `link` and the `buy_price` and `rent_price` if any.
    Returns an empty dict when no JustWatch title matches the TMDB ID.
    """
    cache_key = f"{PROVIDER}_{media_type}_{tmdb_id}_{region}_v3"
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


def get_packages(region):
    """Return every JustWatch provider (package) of a region, keyed by provider ID.

    JustWatch package IDs are the TMDB provider IDs. Each provider has its
    `provider_name` and `image`.
    """
    cache_key = f"{PROVIDER}_packages_{region}"
    data = cache.get(cache_key)

    if data is None:
        response = services.api_request(
            PROVIDER,
            "POST",
            base_url,
            headers=headers,
            params={
                "query": packages_query,
                "variables": {"country": region, "platform": "WEB"},
            },
        )
        packages = (response.get("data") or {}).get("packages") or []
        data = {
            package["packageId"]: {
                "provider_name": package.get("clearName"),
                "image": f"{images_url}{package['icon']}"
                if package.get("icon")
                else None,
            }
            for package in packages
            if package.get("packageId") is not None and package.get("clearName")
        }
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
    """Return the providers of the JustWatch offers, keyed by provider ID.

    Each provider has its name, icon, `link`, whether it is `no_charge` and/or
    `paid`, and its rent and buy `prices` by video quality (SD, HD, 4K).
    """
    providers = {}
    for offer in offers or []:
        package = offer.get("package") or {}
        package_id = package.get("packageId")
        monetization_type = offer.get("monetizationType")
        if (
            package_id is None
            or not offer.get("standardWebURL")
            or offer.get("presentationType") in PHYSICAL_PRESENTATION_TYPES
            or monetization_type not in NO_CHARGE_TYPES | PAID_TYPES
        ):
            continue

        entry = providers.setdefault(
            package_id,
            {
                "provider_name": package.get("clearName"),
                "image": f"{images_url}{package['icon']}"
                if package.get("icon")
                else None,
                "link": None,
                "no_charge": False,
                "paid": False,
                "prices": {"rent": {}, "buy": {}},
            },
        )
        # Prefer the no charge link when a provider has several offers
        if monetization_type in NO_CHARGE_TYPES:
            entry["no_charge"] = True
            entry["link"] = offer["standardWebURL"]
            continue

        entry["paid"] = True
        entry["link"] = entry["link"] or offer["standardWebURL"]
        if offer.get("retailPrice"):
            quality = QUALITIES.get(offer.get("presentationType"), "SD")
            prices = entry["prices"][monetization_type.lower()]
            prices[quality] = lowest_price(prices.get(quality), offer["retailPrice"])
    return providers


def pick_price(prices, quality):
    """Return the price and its quality for the preferred quality.

    "lowest" picks the lowest price of any quality. Otherwise the preferred
    quality is used, falling back to the closest lower one, then to the
    lowest higher one. Returns (None, None) when there is no price.
    """
    if not prices:
        return None, None

    if quality not in QUALITY_ORDER:
        lowest = None
        for price_quality, price in prices.items():
            if lowest_price(lowest, price) == price:
                lowest, lowest_quality = price, price_quality
        return lowest, lowest_quality

    index = QUALITY_ORDER.index(quality)
    for candidate in [
        *reversed(QUALITY_ORDER[: index + 1]),
        *QUALITY_ORDER[index + 1 :],
    ]:
        if candidate in prices:
            return prices[candidate], candidate
    return None, None


def lowest_price(current, new):
    """Return the lowest of two formatted prices, keeping the current if unsure."""
    if current is None:
        return new
    try:
        return min(current, new, key=parse_price)
    except ValueError:
        return current


def parse_price(price):
    """Return the numeric value of a formatted price like "$3.99" or "3,99 €"."""
    digits = "".join(char for char in price if char.isdigit() or char in ".,")
    return float(digits.replace(",", "."))


def apply_offers(
    no_charge,
    paid,
    media_type,
    tmdb_id,
    title,
    region,
    *,
    quality="lowest",
):
    """Return the no charge and paid providers updated with JustWatch.

    When JustWatch has the media, its offers replace the TMDB providers, keeping
    the TMDB logo and order of the providers TMDB also lists. Otherwise, or
    when JustWatch is disabled or fails, the TMDB providers are returned as is.
    Rent and buy prices are shown for the given video quality.
    """
    if not is_enabled() or not title or not region:
        return no_charge, paid

    # JustWatch is unofficial, keep the TMDB providers if it fails
    try:
        offers = get_offers(media_type, tmdb_id, title, region)
    except Exception:
        logger.exception("Failed to fetch JustWatch providers for %s", tmdb_id)
        return no_charge, paid

    if not offers:
        return no_charge, paid

    tmdb_providers = {
        provider.get("provider_id"): provider for provider in [*no_charge, *paid]
    }
    return (
        build_providers(offers, tmdb_providers, "no_charge", quality),
        build_providers(offers, tmdb_providers, "paid", quality),
    )


def build_providers(offers, tmdb_providers, group, quality):
    """Build the providers of a group from the JustWatch offers."""
    providers = []
    for order, (provider_id, offer) in enumerate(offers.items()):
        if not offer[group]:
            continue
        tmdb_provider = tmdb_providers.get(provider_id, {})
        priority = tmdb_provider.get("display_priority")
        providers.append(
            {
                "provider_id": provider_id,
                "provider_name": tmdb_provider.get("provider_name")
                or offer["provider_name"],
                "image": tmdb_provider.get("image") or offer["image"],
                # TMDB providers keep their order, the others follow
                "display_priority": priority if priority is not None else 1000 + order,
                "link": offer["link"],
                **price_fields(offer["prices"], quality, paid=group == "paid"),
            },
        )
    return sorted(providers, key=lambda e: e["display_priority"])


def price_fields(prices, quality, *, paid):
    """Return the rent and buy price fields of a provider for the quality."""
    if not paid:
        return {
            "rent_price": None,
            "rent_quality": None,
            "buy_price": None,
            "buy_quality": None,
            "prices": None,
        }
    rent_price, rent_quality = pick_price(prices["rent"], quality)
    buy_price, buy_quality = pick_price(prices["buy"], quality)
    return {
        "rent_price": rent_price,
        "rent_quality": rent_quality,
        "buy_price": buy_price,
        "buy_quality": buy_quality,
        "prices": prices,
    }
