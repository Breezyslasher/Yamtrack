from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from app.providers import justwatch

DISNEY_INTENT = (
    "intent://www.disneyplus.com/play/f51dce23-7d8f-490a-9f0c-be1b5432c2a9"
    "#Intent;launchFlags=0x00800000;scheme=https;end"
)
DISNEY_TV_LINK = "https://www.disneyplus.com/play/f51dce23-7d8f-490a-9f0c-be1b5432c2a9"


def web_offer(package_id, link, monetization_type="FLATRATE"):
    """Build a JustWatch web offer."""
    return {
        "monetizationType": monetization_type,
        "presentationType": "HD",
        "standardWebURL": link,
        "retailPrice": None,
        "package": {"packageId": package_id, "clearName": "Name", "icon": None},
    }


def tv_offer(package_id, deeplink, monetization_type="FLATRATE"):
    """Build a JustWatch Android TV offer."""
    return {
        "monetizationType": monetization_type,
        "presentationType": "HD",
        "deeplinkURL": deeplink,
        "package": {"packageId": package_id},
    }


class TVLinkTests(SimpleTestCase):
    """Test the conversion of the Android TV deep links."""

    def test_https_intent_returns_https_url(self):
        """An https intent URI should give the https URL it opens."""
        self.assertEqual(justwatch.tv_link(DISNEY_INTENT), DISNEY_TV_LINK)

    def test_query_is_kept_without_utm_parameters(self):
        """The query should be kept, without the utm tracking parameters."""
        self.assertEqual(
            justwatch.tv_link(
                "intent://play.hbomax.com/video/watch/07323549?utm_source=universal"
                "_search&utm_medium=tv#Intent;launchFlags=0x00800000;scheme=https;end",
            ),
            "https://play.hbomax.com/video/watch/07323549",
        )
        self.assertEqual(
            justwatch.tv_link(
                "intent://watch.amazon.com/watch?asin=B0BZ3DN1TW&time=0&territory=US"
                "#Intent;package=com.amazon.amazonvideo.livingroom;scheme=https;end",
            ),
            "https://watch.amazon.com/watch?asin=B0BZ3DN1TW&time=0&territory=US",
        )

    def test_custom_scheme_returns_none(self):
        """Intents of an app's own scheme can't be opened as a URL."""
        self.assertIsNone(
            justwatch.tv_link(
                "intent://play?type=movies/action=play/searchKeys=10429467"
                "#Intent;launchFlags=0x00800000;scheme=Movies by fawesome;end",
            ),
        )

    def test_missing_deeplink_returns_none(self):
        """Offers without a deep link have no Android TV link."""
        self.assertIsNone(justwatch.tv_link(None))
        self.assertIsNone(justwatch.tv_link(""))


class ProcessOffersTVLinkTests(SimpleTestCase):
    """Test the Android TV links of the processed JustWatch offers."""

    def test_provider_without_android_tv_offer(self):
        """Providers without an Android TV offer keep their link and no tv_link."""
        web_link = "https://www.disneyplus.com/browse/entity-f51dce23"
        providers = justwatch.process_offers(
            [web_offer(337, web_link), web_offer(8, "https://www.netflix.com/title/1")],
            [tv_offer(337, DISNEY_INTENT)],
        )

        self.assertEqual(providers[337]["link"], web_link)
        self.assertEqual(providers[337]["tv_link"], DISNEY_TV_LINK)
        self.assertEqual(providers[8]["link"], "https://www.netflix.com/title/1")
        self.assertIsNone(providers[8]["tv_link"])

    def test_no_charge_android_tv_link_is_preferred(self):
        """The no charge offer's link is used when a provider has several."""
        providers = justwatch.process_offers(
            [
                web_offer(10, "https://watch.amazon.com/detail?gti=1", "RENT"),
                web_offer(10, "https://watch.amazon.com/detail?gti=1"),
            ],
            [
                tv_offer(
                    10, "intent://watch.amazon.com/rent#Intent;scheme=https;end", "RENT"
                ),
                tv_offer(10, "intent://watch.amazon.com/free#Intent;scheme=https;end"),
                tv_offer(
                    10, "intent://watch.amazon.com/buy#Intent;scheme=https;end", "BUY"
                ),
            ],
        )

        self.assertEqual(providers[10]["tv_link"], "https://watch.amazon.com/free")

    def test_android_tv_offer_of_unknown_provider_is_ignored(self):
        """Android TV offers only add links to the providers of the web offers."""
        providers = justwatch.process_offers(
            [web_offer(8, "https://www.netflix.com/title/1")],
            [tv_offer(337, DISNEY_INTENT)],
        )

        self.assertEqual(list(providers), [8])

    def test_without_android_tv_offers(self):
        """Offers cached or fetched without Android TV offers have no tv_link."""
        providers = justwatch.process_offers(
            [web_offer(8, "https://www.netflix.com/title/1")],
        )

        self.assertIsNone(providers[8]["tv_link"])


ANDOR_E1_WEB = "https://www.disneyplus.com/play/91310366-d44b-44a4-bdc4-71f999472826"
ANDOR_SHOW_PAGE = "https://www.disneyplus.com/browse/entity-faba988a-3d6c-4a19-a7d5"
LAST_OF_US_E1_WEB = (
    "https://play.hbomax.com/video/watch/dae9e532-3714-4f2e-b758-fb9a13def902"
)
SEVERANCE_E1_WEB = "https://tv.apple.com/us/episode/good-news-about-hell/umc.cmc.s80mx1ic96pu6ewupz8pfasf"
NETFLIX_SHOW_ID = "82939566"


def episode_web_offer(package_id, deeplink, standard_url, name="Name"):
    """Build a JustWatch web offer of an episode."""
    return {
        "monetizationType": "FLATRATE",
        "presentationType": "HD",
        "standardWebURL": standard_url,
        "deeplinkURL": deeplink,
        "retailPrice": None,
        "package": {"packageId": package_id, "clearName": name, "icon": None},
    }


def intent(target, extras="launchFlags=0x00800000;scheme=https"):
    """Build an Android TV intent deep link."""
    return f"intent://{target}#Intent;{extras};end"


def search_response(tmdb_id, show_id="ts38796"):
    """Build a JustWatch search response with a show."""
    return {
        "data": {
            "popularTitles": {
                "edges": [
                    {
                        "node": {
                            "id": show_id,
                            "objectType": "SHOW",
                            "content": {"externalIds": {"tmdbId": tmdb_id}},
                            "offers": [],
                            "atv": [],
                        },
                    },
                ],
            },
        },
    }


def seasons_response(season_ids):
    """Build a JustWatch show seasons response from the IDs by season number."""
    return {
        "data": {
            "node": {
                "seasons": [
                    {"id": season_id, "content": {"seasonNumber": number}}
                    for number, season_id in season_ids.items()
                ],
            },
        },
    }


def episodes_response(episodes):
    """Build a JustWatch season episodes response.

    `episodes` maps the episode numbers to their (web offers, Android TV offers).
    """
    return {
        "data": {
            "node": {
                "episodes": [
                    {
                        "id": f"tse{number}",
                        "content": {"episodeNumber": number},
                        "offers": web,
                        "atv": atv,
                    }
                    for number, (web, atv) in episodes.items()
                ],
            },
        },
    }


SEASON_1 = episodes_response(
    {
        1: (
            [
                episode_web_offer(337, ANDOR_E1_WEB, ANDOR_SHOW_PAGE, "Disney Plus"),
                episode_web_offer(
                    1899,
                    f"{LAST_OF_US_E1_WEB}?utm_source=universal_search",
                    f"{LAST_OF_US_E1_WEB}?utm_source=universal_search",
                    "HBO Max",
                ),
                episode_web_offer(
                    350,
                    f"{SEVERANCE_E1_WEB}?at=1000l3V2&playableId=tvs.sbd.4000"
                    "%3AVSEVR0560101&showId=umc.cmc.1srk2goyh2q2zdxcx605w8vtx",
                    f"{SEVERANCE_E1_WEB}?at=1000l3V2",
                    "Apple TV",
                ),
                episode_web_offer(
                    8,
                    "https://www.netflix.com/watch/82946792",
                    f"https://www.netflix.com/title/{NETFLIX_SHOW_ID}",
                    "Netflix",
                ),
                episode_web_offer(
                    1796,
                    "https://www.netflix.com/watch/82946792",
                    f"https://www.netflix.com/title/{NETFLIX_SHOW_ID}",
                    "Netflix Standard with Ads",
                ),
            ],
            [
                tv_offer(
                    337,
                    intent(ANDOR_E1_WEB.removeprefix("https://")),
                ),
                tv_offer(
                    1899,
                    intent(
                        LAST_OF_US_E1_WEB.removeprefix("https://")
                        + "?utm_source=universal_search",
                    ),
                ),
                tv_offer(
                    350,
                    intent(
                        SEVERANCE_E1_WEB.removeprefix("https://")
                        + "?showId=umc.cmc.1srk2goyh2q2zdxcx605w8vtx"
                        "&playableId=tvs.sbd.4000%3AVSEVR0560101",
                    ),
                ),
                # Netflix's Android TV deep link is the show for every episode
                tv_offer(
                    8,
                    intent(
                        f"www.netflix.com/watch/{NETFLIX_SHOW_ID}",
                        "scheme=https;package=com.netflix.ninja;S.source=30",
                    ),
                ),
                tv_offer(
                    1796,
                    intent(
                        f"www.netflix.com/watch/{NETFLIX_SHOW_ID}",
                        "scheme=https;package=com.netflix.ninja;S.source=30",
                    ),
                ),
            ],
        ),
        2: (
            [
                episode_web_offer(
                    337,
                    "https://www.disneyplus.com/play/ef6356d6-19c9-49c0-a633-fe5a4153316a",
                    ANDOR_SHOW_PAGE,
                    "Disney Plus",
                ),
            ],
            [],
        ),
    },
)


@override_settings(JUSTWATCH_ENABLED=True)
@patch("app.providers.justwatch.services.api_request")
class EpisodeOffersTests(SimpleTestCase):
    """Test the JustWatch offers of tv show episodes."""

    def setUp(self):
        """Clear the cached JustWatch data."""
        cache.clear()

    def get_episode_offers(self, season_number=1, episode_number=1):
        """Get the offers of an episode of the test show."""
        return justwatch.get_episode_offers(
            "1399",
            "Test show",
            season_number,
            episode_number,
            "US",
        )

    def respond(self, mock_request):
        """Answer the search, seasons and season episodes requests."""
        mock_request.side_effect = [
            search_response("1399"),
            seasons_response({1: "tss62569", 2: "tss62570"}),
            SEASON_1,
        ]

    def test_episode_links_start_the_episode(self, mock_request):
        """The links are the episode's, not the show's page."""
        self.respond(mock_request)

        providers = self.get_episode_offers()

        self.assertEqual(providers[337]["link"], ANDOR_E1_WEB)
        self.assertEqual(providers[337]["tv_link"], ANDOR_E1_WEB)
        self.assertEqual(
            providers[1899]["link"],
            f"{LAST_OF_US_E1_WEB}?utm_source=universal_search",
        )
        self.assertEqual(providers[1899]["tv_link"], LAST_OF_US_E1_WEB)
        self.assertTrue(providers[350]["link"].startswith(SEVERANCE_E1_WEB))
        self.assertEqual(
            providers[350]["tv_link"],
            f"{SEVERANCE_E1_WEB}?showId=umc.cmc.1srk2goyh2q2zdxcx605w8vtx"
            "&playableId=tvs.sbd.4000%3AVSEVR0560101",
        )

        search, seasons, episodes = (
            call.kwargs["params"] for call in mock_request.call_args_list
        )
        self.assertEqual(
            search["variables"]["searchTitlesFilter"]["objectTypes"], ["SHOW"]
        )
        self.assertEqual(seasons["variables"]["id"], "ts38796")
        self.assertEqual(episodes["variables"]["id"], "tss62569")

    def test_netflix_uses_the_episode_web_link(self, mock_request):
        """Netflix's Android TV link is the episode's web link, not the show."""
        self.respond(mock_request)

        providers = self.get_episode_offers()

        for package_id in (8, 1796):
            self.assertEqual(
                providers[package_id]["link"],
                "https://www.netflix.com/watch/82946792",
            )
            self.assertEqual(
                providers[package_id]["tv_link"],
                "https://www.netflix.com/watch/82946792",
            )
        self.assertEqual(len(providers), 5)

    def test_missing_season_or_episode(self, mock_request):
        """A season or episode JustWatch doesn't have gives no offers."""
        self.respond(mock_request)

        self.assertEqual(self.get_episode_offers(episode_number=9), {})
        self.assertEqual(self.get_episode_offers(season_number=7), {})

    def test_show_with_other_tmdb_id(self, mock_request):
        """A JustWatch show with another TMDB ID gives no offers."""
        mock_request.side_effect = [search_response("42")]

        self.assertEqual(self.get_episode_offers(), {})
        mock_request.assert_called_once()

    def test_seasons_and_episodes_are_cached(self, mock_request):
        """Other episodes reuse the cached season list and season episodes."""
        self.respond(mock_request)

        self.get_episode_offers(1, 1)
        providers = self.get_episode_offers(1, 2)

        self.assertEqual(mock_request.call_count, 3)
        self.assertEqual(
            providers[337]["link"],
            "https://www.disneyplus.com/play/ef6356d6-19c9-49c0-a633-fe5a4153316a",
        )

        # Another season only needs its episodes
        mock_request.side_effect = [episodes_response({})]
        self.get_episode_offers(2, 1)
        self.assertEqual(mock_request.call_count, 4)

    def test_title_offers_keep_the_standard_web_url(self, mock_request):
        """Movies and shows keep the standard web URL as their link."""
        providers = justwatch.process_offers(
            [episode_web_offer(337, ANDOR_E1_WEB, ANDOR_SHOW_PAGE)],
        )

        self.assertEqual(providers[337]["link"], ANDOR_SHOW_PAGE)
        mock_request.assert_not_called()
