"""Watch providers with direct links from JustWatch.

JustWatch has no public API, this uses the GraphQL API of its website. It can
change without notice, so it is disabled by default and every failure is
handled by falling back to the TMDB watch providers without links.

TMDB gets its watch providers from JustWatch but updates them later, so when
JustWatch has the media its offers replace the TMDB providers.
"""

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
        id
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
        atv: offers(country: $country, platform: ANDROID_TV, filter: $filter) {
          monetizationType
          presentationType
          deeplinkURL(platform: ANDROID_TV)
          package {
            packageId
          }
        }
      }
    }
  }
}
"""

seasons_query = """
query GetShowSeasons($id: ID!, $country: Country!, $language: Language!) {
  node(id: $id) {
    ... on Show {
      seasons(sortDirection: ASC) {
        id
        content(country: $country, language: $language) {
          seasonNumber
        }
      }
    }
  }
}
"""

season_episodes_query = """
query GetSeasonEpisodes(
  $id: ID!,
  $country: Country!,
  $language: Language!,
  $filter: OfferFilter!
) {
  node(id: $id) {
    ... on Season {
      episodes(sortDirection: ASC) {
        id
        content(country: $country, language: $language) {
          episodeNumber
        }
        offers(country: $country, platform: WEB, filter: $filter) {
          monetizationType
          presentationType
          standardWebURL
          deeplinkURL(platform: WEB)
          retailPrice(language: $language)
          package {
            packageId
            clearName
            icon(profile: S100, format: PNG)
          }
        }
        atv: offers(country: $country, platform: ANDROID_TV, filter: $filter) {
          monetizationType
          presentationType
          deeplinkURL(platform: ANDROID_TV)
          package {
            packageId
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
# Schemes of the Android TV deep links that any client can open as a URL
TV_LINK_SCHEMES = {"https", "http"}


def is_enabled():
    """Return whether JustWatch links are enabled."""
    return settings.JUSTWATCH_ENABLED


def get_offers(media_type, tmdb_id, title, region):
    """Return the JustWatch offers of a movie or tv show, keyed by provider ID.

    Each provider has its `link`, `tv_link` and the `buy_price` and
    `rent_price` if any.
    Returns an empty dict when no JustWatch title matches the TMDB ID.
    """
    cache_key = f"{PROVIDER}_{media_type}_{tmdb_id}_{region}_v4"
    data = cache.get(cache_key)

    if data is None:
        node = search_title(media_type, tmdb_id, title, region)
        data = process_offers(node["offers"], node.get("atv")) if node else {}
        cache.set(cache_key, data, CACHE_TIMEOUT)

    return data


def get_episode_offers(tmdb_id, title, season_number, episode_number, region):
    """Return the JustWatch offers of a tv show episode, keyed by provider ID.

    The providers are like the ones of `get_offers`, with the episode's own
    `link` and `tv_link`. Returns an empty dict when JustWatch doesn't have the
    show, season or episode.
    """
    season_id = get_show_seasons(tmdb_id, title, region).get(int(season_number))
    if season_id is None:
        return {}

    episodes = get_season_episodes(tmdb_id, season_number, season_id, region)
    return episodes.get(int(episode_number), {})


def get_show_seasons(tmdb_id, title, region):
    """Return the JustWatch season IDs of a tv show, keyed by season number."""
    cache_key = f"{PROVIDER}_seasons_{tmdb_id}_{region}_v1"
    data = cache.get(cache_key)

    if data is None:
        data = {}
        node = search_title(MediaTypes.TV.value, tmdb_id, title, region)
        if node and node.get("id"):
            response = graphql_request(
                seasons_query,
                {"id": node["id"], "country": region, "language": get_language()},
            )
            show = (response.get("data") or {}).get("node") or {}
            for season in show.get("seasons") or []:
                number = (season.get("content") or {}).get("seasonNumber")
                if number is not None and season.get("id"):
                    data[number] = season["id"]
        cache.set(cache_key, data, CACHE_TIMEOUT)

    return data


def get_season_episodes(tmdb_id, season_number, season_id, region):
    """Return the offers of a JustWatch season's episodes, keyed by episode number.

    The whole season is cached, so the other episodes need no request.
    """
    cache_key = f"{PROVIDER}_episodes_{tmdb_id}_{season_number}_{region}_v1"
    data = cache.get(cache_key)

    if data is None:
        response = graphql_request(
            season_episodes_query,
            {
                "id": season_id,
                "country": region,
                "language": get_language(),
                "filter": {"bestOnly": True},
            },
        )
        season = (response.get("data") or {}).get("node") or {}
        data = {}
        for episode in season.get("episodes") or []:
            number = (episode.get("content") or {}).get("episodeNumber")
            if number is not None:
                data[number] = process_offers(
                    episode.get("offers"),
                    episode.get("atv"),
                    episode=True,
                )
        cache.set(cache_key, data, CACHE_TIMEOUT)

    return data


def search_title(media_type, tmdb_id, title, region):
    """Return the JustWatch title of the search matching the TMDB ID, if any."""
    response = graphql_request(
        search_query,
        {
            "searchTitlesFilter": {
                "searchQuery": title,
                "objectTypes": [OBJECT_TYPES[media_type]],
            },
            "country": region,
            "language": get_language(),
            "first": 10,
            "filter": {"bestOnly": True},
        },
    )
    return find_title(response, tmdb_id)


def graphql_request(query, variables):
    """Send a query to the JustWatch GraphQL API."""
    return services.api_request(
        PROVIDER,
        "POST",
        base_url,
        headers=headers,
        params={"query": query, "variables": variables},
    )


def get_language():
    """Return the language of the JustWatch texts, from the TMDB language."""
    return settings.TMDB_LANG.split("-")[0]


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


def process_offers(offers, tv_offers=None, *, episode=False):
    """Return the providers of the JustWatch offers, keyed by provider ID.

    Each provider has its name, icon, `link`, `tv_link` (from the Android TV
    offers), whether it is `no_charge` and/or `paid`, and its rent and buy
    `prices` by video quality (SD, HD, 4K). With `episode`, the links are the
    ones of an episode, see `offer_link` and `add_episode_tv_links`.
    """
    providers = {}
    for offer in offers or []:
        package = offer.get("package") or {}
        package_id = package.get("packageId")
        monetization_type = offer.get("monetizationType")
        link = offer_link(offer, episode=episode)
        if (
            package_id is None
            or not link
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
                "tv_link": None,
                "no_charge": False,
                "paid": False,
                "prices": {"rent": {}, "buy": {}},
            },
        )
        # Prefer the no charge link when a provider has several offers
        if monetization_type in NO_CHARGE_TYPES:
            entry["no_charge"] = True
            entry["link"] = link
            continue

        entry["paid"] = True
        entry["link"] = entry["link"] or link
        if offer.get("retailPrice"):
            quality = QUALITIES.get(offer.get("presentationType"), "SD")
            prices = entry["prices"][monetization_type.lower()]
            prices[quality] = lowest_price(prices.get(quality), offer["retailPrice"])

    add_tv_links(providers, tv_offers)
    if episode:
        add_episode_tv_links(providers)
    return providers


def offer_link(offer, *, episode=False):
    """Return the web link of an offer.

    The standard web URL of an episode is often the show's page, while its web
    deep link plays the episode, so episodes use the deep link when it is a URL.
    """
    if episode:
        deeplink = offer.get("deeplinkURL")
        if deeplink and urlsplit(deeplink).scheme in TV_LINK_SCHEMES:
            return deeplink
    return offer.get("standardWebURL")


def add_episode_tv_links(providers):
    """Use the episode's web link as the Android TV link of Netflix.

    The Netflix Android TV deep link of an episode is the show's, while its web
    deep link is the episode's `/watch/<id>`, which the Android TV app also
    opens. Netflix is matched by its link, so every Netflix plan is covered.
    """
    for entry in providers.values():
        parts = urlsplit(entry["link"] or "")
        if parts.netloc == "www.netflix.com" and parts.path.startswith("/watch/"):
            entry["tv_link"] = tv_link(entry["link"])


def add_tv_links(providers, tv_offers):
    """Set the Android TV link of the providers from their Android TV offers."""
    no_charge_links = set()
    for offer in tv_offers or []:
        package_id = (offer.get("package") or {}).get("packageId")
        entry = providers.get(package_id)
        link = tv_link(offer.get("deeplinkURL"))
        if (
            entry is None
            or link is None
            or offer.get("presentationType") in PHYSICAL_PRESENTATION_TYPES
            or package_id in no_charge_links
        ):
            continue

        # Prefer the no charge link when a provider has several offers, like `link`
        if offer.get("monetizationType") in NO_CHARGE_TYPES:
            entry["tv_link"] = link
            no_charge_links.add(package_id)
        elif offer.get("monetizationType") in PAID_TYPES:
            entry["tv_link"] = entry["tv_link"] or link


def tv_link(deeplink):
    """Return the web URL of an Android TV deep link, None if it has none.

    Android TV deep links are intent URIs like
    `intent://www.disneyplus.com/play/<id>#Intent;launchFlags=0x00800000;scheme=https;end`.
    Only http(s) links are returned, as apps' own schemes can't be opened as a
    URL, without the `utm_*` tracking parameters.
    """
    if not deeplink:
        return None

    if deeplink.startswith("intent://"):
        target, _, intent = deeplink.removeprefix("intent://").partition("#Intent;")
        extras = dict(part.split("=", 1) for part in intent.split(";") if "=" in part)
        scheme = extras.get("scheme", "").lower()
        if scheme not in TV_LINK_SCHEMES or not target:
            return None
        deeplink = f"{scheme}://{target}"

    parts = urlsplit(deeplink)
    if parts.scheme not in TV_LINK_SCHEMES or not parts.netloc:
        return None
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.startswith("utm_")
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


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
    if not title or not region:
        return no_charge, paid

    return replace_providers(
        no_charge,
        paid,
        lambda: get_offers(media_type, tmdb_id, title, region),
        tmdb_id,
        quality,
    )


def apply_episode_offers(no_charge, paid, tmdb_id, title, region, *, episode, quality):
    """Return the providers of a tv show episode updated with JustWatch.

    Like `apply_offers`, with the offers of the `(season_number, episode_number)`
    episode, whose links start it.
    """
    if not title or not region:
        return no_charge, paid

    season_number, episode_number = episode
    return replace_providers(
        no_charge,
        paid,
        lambda: get_episode_offers(
            tmdb_id,
            title,
            season_number,
            episode_number,
            region,
        ),
        tmdb_id,
        quality,
    )


def replace_providers(no_charge, paid, fetch_offers, tmdb_id, quality):
    """Replace the TMDB providers by the JustWatch offers that `fetch_offers` gets."""
    if not is_enabled():
        return no_charge, paid

    # JustWatch is unofficial, keep the TMDB providers if it fails
    try:
        offers = fetch_offers()
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
                "tv_link": offer["tv_link"],
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
