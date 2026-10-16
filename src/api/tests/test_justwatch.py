from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from app.models import MediaTypes
from app.providers import justwatch

from .base import YamtrackApiTestCase

TMDB_METADATA = {
    "title": "Lincoln",
    "providers": {
        "US": {
            "link": "https://www.themoviedb.org/movie/72976-lincoln/watch?locale=US",
            "flatrate": [
                {
                    "provider_id": 8,
                    "provider_name": "Netflix",
                    "logo_path": "/netflix.jpg",
                    "display_priority": 0,
                },
            ],
            "buy": [
                {
                    "provider_id": 2,
                    "provider_name": "Apple TV",
                    "logo_path": "/apple.jpg",
                    "display_priority": 4,
                },
            ],
            "rent": [
                {
                    "provider_id": 2,
                    "provider_name": "Apple TV",
                    "logo_path": "/apple.jpg",
                    "display_priority": 4,
                },
            ],
        },
    },
}


def build_justwatch_response(tmdb_id):
    """Build a fake JustWatch search response for a title with the TMDB ID."""
    return {
        "data": {
            "popularTitles": {
                "edges": [
                    {
                        "node": {
                            "objectType": "MOVIE",
                            "content": {
                                "title": "Lincoln",
                                "originalReleaseYear": 2012,
                                "externalIds": {"tmdbId": tmdb_id},
                            },
                            "offers": [
                                {
                                    "monetizationType": "FLATRATE",
                                    "standardWebURL": "https://www.netflix.com/title/70218188",
                                    "retailPrice": None,
                                    "package": {"packageId": 8},
                                },
                                {
                                    "monetizationType": "BUY",
                                    "standardWebURL": "https://tv.apple.com/movie/lincoln",
                                    "retailPrice": "$14.99",
                                    "package": {"packageId": 2},
                                },
                                {
                                    "monetizationType": "RENT",
                                    "standardWebURL": "https://tv.apple.com/movie/lincoln",
                                    "retailPrice": "$3.99",
                                    "package": {"packageId": 2},
                                },
                            ],
                        },
                    },
                ],
            },
        },
    }


# Real JustWatch response for "Lincoln" in the US, trimmed to two titles
JUSTWATCH_LINCOLN_RESPONSE = {
    "data": {
        "popularTitles": {
            "edges": [
                {
                    "node": {
                        "objectType": "MOVIE",
                        "content": {
                            "title": "Lincoln",
                            "originalReleaseYear": 2012,
                            "externalIds": {"tmdbId": "72976"},
                        },
                        "offers": [
                            {
                                "monetizationType": "RENT",
                                "presentationType": "SD",
                                "standardWebURL": "https://watch.amazon.com/detail?gti=amzn1.dv.gti.78a9f704-5cb5-2a2b-4b42-3b21e11dccf2",
                                "retailPrice": "$3.99",
                                "package": {
                                    "packageId": 10,
                                    "clearName": "Amazon Video",
                                    "icon": "/icon/430997/s100/amazon.png",
                                },
                            },
                            {
                                "monetizationType": "BUY",
                                "presentationType": "HD",
                                "standardWebURL": "https://watch.amazon.com/detail?gti=amzn1.dv.gti.78a9f704-5cb5-2a2b-4b42-3b21e11dccf2",
                                "retailPrice": "$14.99",
                                "package": {
                                    "packageId": 10,
                                    "clearName": "Amazon Video",
                                    "icon": "/icon/430997/s100/amazon.png",
                                },
                            },
                            {
                                "monetizationType": "BUY",
                                "presentationType": "SD",
                                "standardWebURL": "https://watch.amazon.com/detail?gti=amzn1.dv.gti.78a9f704-5cb5-2a2b-4b42-3b21e11dccf2",
                                "retailPrice": "$12.99",
                                "package": {
                                    "packageId": 10,
                                    "clearName": "Amazon Video",
                                    "icon": "/icon/430997/s100/amazon.png",
                                },
                            },
                            {
                                "monetizationType": "RENT",
                                "presentationType": "HD",
                                "standardWebURL": "https://tv.apple.com/us/movie/lincoln/umc.cmc.2y2l2hb8ec0t3byecg3ez7l2y",
                                "retailPrice": "$3.99",
                                "package": {
                                    "packageId": 2,
                                    "clearName": "Apple TV Store",
                                    "icon": "/icon/190848813/s100/itunes.png",
                                },
                            },
                            {
                                "monetizationType": "BUY",
                                "presentationType": "DVD",
                                "standardWebURL": "https://www.amazon.com/dp/B00F3A7G7M",
                                "retailPrice": "$12.68",
                                "package": {
                                    "packageId": 50,
                                    "clearName": "Amazon DVD / Blu-ray",
                                    "icon": "/icon/1234/s100/amazondvdbr.png",
                                },
                            },
                        ],
                    },
                },
                {
                    "node": {
                        "objectType": "MOVIE",
                        "content": {
                            "title": "The Lincoln Lawyer",
                            "originalReleaseYear": 2011,
                            "externalIds": {"tmdbId": "50348"},
                        },
                        "offers": [
                            {
                                "monetizationType": "FAST",
                                "presentationType": "HD",
                                "standardWebURL": "https://watch.sling.com/1/program/15cbd81254b4d4068e64694b80bdb8fd/watch",
                                "retailPrice": None,
                                "package": {
                                    "packageId": 2766,
                                    "clearName": "Sling TV Freestream",
                                    "icon": "/icon/321/s100/slingfreestream.png",
                                },
                            },
                        ],
                    },
                },
            ],
        },
    },
}


@patch("api.views.services.get_media_metadata", return_value=TMDB_METADATA)
class JustWatchLinksTests(YamtrackApiTestCase):
    """Validate the JustWatch direct links of the watch providers endpoint."""

    def setUp(self):
        """Clear cached provider data between tests."""
        super().setUp()
        cache.clear()

    def get_providers(self):
        """Call the watch providers endpoint for the test movie."""
        return self.call_api(
            "get",
            "api_media_providers",
            args=(MediaTypes.MOVIE.value, "tmdb", "72976"),
            params={"region": "US"},
            headers=self.auth_headers,
        )

    @override_settings(JUSTWATCH_ENABLED=True)
    @patch("app.providers.justwatch.services.api_request")
    def test_providers_include_justwatch_links_and_prices(
        self,
        mock_request,
        _mock_metadata,
    ):
        """Providers should get the JustWatch link and prices when enabled."""
        mock_request.return_value = build_justwatch_response("72976")

        response = self.get_providers()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        netflix = payload["no_charge"][0]
        self.assertEqual(netflix["link"], "https://www.netflix.com/title/70218188")
        self.assertIsNone(netflix["buy_price"])
        apple = payload["paid"][0]
        self.assertEqual(apple["link"], "https://tv.apple.com/movie/lincoln")
        self.assertEqual(apple["buy_price"], "$14.99")
        self.assertEqual(apple["rent_price"], "$3.99")

        request_headers = mock_request.call_args.kwargs["headers"]
        self.assertIn("Mozilla", request_headers["User-Agent"])
        self.assertEqual(request_headers["Origin"], "https://www.justwatch.com")

        variables = mock_request.call_args.kwargs["params"]["variables"]
        self.assertEqual(variables["country"], "US")
        self.assertEqual(variables["searchTitlesFilter"]["searchQuery"], "Lincoln")
        self.assertEqual(variables["searchTitlesFilter"]["objectTypes"], ["MOVIE"])

        # Offers are cached per media and region
        self.get_providers()
        mock_request.assert_called_once()

    @override_settings(JUSTWATCH_ENABLED=False)
    @patch("app.providers.justwatch.services.api_request")
    def test_justwatch_disabled_by_default(self, mock_request, _mock_metadata):
        """Without the setting, JustWatch is not queried and links are null."""
        response = self.get_providers()

        self.assertEqual(response.status_code, 200)
        for group in ("no_charge", "paid"):
            for provider in response.json()[group]:
                self.assertIsNone(provider["link"])
                self.assertIsNone(provider["buy_price"])
                self.assertIsNone(provider["rent_price"])
        mock_request.assert_not_called()

    @override_settings(JUSTWATCH_ENABLED=True)
    @patch("app.providers.justwatch.services.api_request")
    def test_justwatch_result_with_other_tmdb_id_is_ignored(
        self,
        mock_request,
        _mock_metadata,
    ):
        """A JustWatch title with another TMDB ID should not give links."""
        mock_request.return_value = build_justwatch_response("12345")

        response = self.get_providers()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["no_charge"][0]["link"])

    @override_settings(JUSTWATCH_ENABLED=True)
    @patch(
        "app.providers.justwatch.services.api_request",
        side_effect=Exception("blocked"),
    )
    def test_justwatch_failure_keeps_tmdb_providers(self, _mock_request, _mock):
        """A JustWatch failure should return the TMDB providers without links."""
        response = self.get_providers()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["no_charge"][0]["provider_name"], "Netflix")
        self.assertIsNone(payload["no_charge"][0]["link"])
        self.assertEqual(
            payload["link"],
            "https://www.themoviedb.org/movie/72976-lincoln/watch?locale=US",
        )

    @override_settings(JUSTWATCH_ENABLED=True)
    @patch("app.providers.justwatch.services.api_request")
    def test_justwatch_offers_replace_tmdb_providers(
        self,
        mock_request,
        _mock_metadata,
    ):
        """JustWatch offers should replace the TMDB providers when it has the media."""
        mock_request.return_value = JUSTWATCH_LINCOLN_RESPONSE

        response = self.get_providers()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        # Netflix is listed by TMDB but JustWatch has no offer anymore
        self.assertEqual(payload["no_charge"], [])
        self.assertEqual(
            payload["paid"],
            [
                # Listed by TMDB, keeps its TMDB name, logo and order
                {
                    "provider_id": 2,
                    "provider_name": "Apple TV",
                    "image": "https://image.tmdb.org/t/p/w500/apple.jpg",
                    "display_priority": 4,
                    "link": "https://tv.apple.com/us/movie/lincoln/umc.cmc.2y2l2hb8ec0t3byecg3ez7l2y",
                    "rent_price": "$3.99",
                    "rent_quality": "HD",
                    "buy_price": None,
                    "buy_quality": None,
                    "prices": {"rent": {"HD": "$3.99"}, "buy": {}},
                },
                # Only on JustWatch, uses its name and icon, with the lowest price
                {
                    "provider_id": 10,
                    "provider_name": "Amazon Video",
                    "image": "https://images.justwatch.com/icon/430997/s100/amazon.png",
                    "display_priority": 1000,
                    "link": "https://watch.amazon.com/detail?gti=amzn1.dv.gti.78a9f704-5cb5-2a2b-4b42-3b21e11dccf2",
                    "rent_price": "$3.99",
                    "rent_quality": "SD",
                    "buy_price": "$12.99",
                    "buy_quality": "SD",
                    "prices": {
                        "rent": {"SD": "$3.99"},
                        "buy": {"HD": "$14.99", "SD": "$12.99"},
                    },
                },
            ],
        )

    def test_fast_offers_count_as_no_charge(self, _mock_metadata):
        """FAST offers should be no charge offers without price."""
        offers = justwatch.process_offers(
            JUSTWATCH_LINCOLN_RESPONSE["data"]["popularTitles"]["edges"][1]["node"][
                "offers"
            ],
        )

        self.assertEqual(
            offers,
            {
                2766: {
                    "provider_name": "Sling TV Freestream",
                    "image": "https://images.justwatch.com/icon/321/s100/slingfreestream.png",
                    "link": "https://watch.sling.com/1/program/15cbd81254b4d4068e64694b80bdb8fd/watch",
                    "no_charge": True,
                    "paid": False,
                    "prices": {"rent": {}, "buy": {}},
                },
            },
        )

    def test_lowest_price_handles_formats(self, _mock_metadata):
        """Prices should compare by value, keeping the current one if unparsable."""
        self.assertEqual(justwatch.lowest_price("$14.99", "$3.99"), "$3.99")
        self.assertEqual(justwatch.lowest_price("3,99 €", "12,99 €"), "3,99 €")
        self.assertEqual(justwatch.lowest_price(None, "$3.99"), "$3.99")
        self.assertEqual(justwatch.lowest_price("$3.99", "Free"), "$3.99")

    @override_settings(JUSTWATCH_ENABLED=True)
    @patch("app.providers.justwatch.services.api_request")
    def test_quality_param_picks_price_quality(self, mock_request, _mock_metadata):
        """The quality parameter should pick the price quality with fallback."""
        mock_request.return_value = JUSTWATCH_LINCOLN_RESPONSE

        hd = self.call_api(
            "get",
            "api_media_providers",
            args=(MediaTypes.MOVIE.value, "tmdb", "72976"),
            params={"region": "US", "quality": "HD"},
            headers=self.auth_headers,
        )
        uhd = self.call_api(
            "get",
            "api_media_providers",
            args=(MediaTypes.MOVIE.value, "tmdb", "72976"),
            params={"region": "US", "quality": "4K"},
            headers=self.auth_headers,
        )

        amazon_hd = hd.json()["paid"][1]
        self.assertEqual(amazon_hd["buy_price"], "$14.99")
        self.assertEqual(amazon_hd["buy_quality"], "HD")
        # Amazon only rents in SD, so HD falls back to it
        self.assertEqual(amazon_hd["rent_price"], "$3.99")
        self.assertEqual(amazon_hd["rent_quality"], "SD")
        # No 4K offer, so 4K falls back to HD
        self.assertEqual(uhd.json()["paid"][1]["buy_quality"], "HD")

    @override_settings(JUSTWATCH_ENABLED=True)
    @patch("app.providers.justwatch.services.api_request")
    def test_quality_defaults_to_user_preference(self, mock_request, _mock):
        """Without the parameter, the user's preference should be used."""
        mock_request.return_value = JUSTWATCH_LINCOLN_RESPONSE
        self.user1.watch_price_quality = "HD"
        self.user1.save()

        response = self.get_providers()

        self.assertEqual(response.json()["paid"][1]["buy_price"], "$14.99")

    def test_invalid_quality_returns_bad_request(self, _mock_metadata):
        """An unknown quality should be rejected."""
        response = self.call_api(
            "get",
            "api_media_providers",
            args=(MediaTypes.MOVIE.value, "tmdb", "72976"),
            params={"region": "US", "quality": "8K"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_pick_price_fallbacks(self, _mock_metadata):
        """Prices should fall back to lower, then higher qualities."""
        prices = {"SD": "$9.99", "HD": "$14.99"}

        self.assertEqual(justwatch.pick_price(prices, "lowest"), ("$9.99", "SD"))
        self.assertEqual(justwatch.pick_price(prices, "HD"), ("$14.99", "HD"))
        self.assertEqual(justwatch.pick_price(prices, "4K"), ("$14.99", "HD"))
        self.assertEqual(
            justwatch.pick_price({"HD": "$14.99"}, "SD"),
            ("$14.99", "HD"),
        )
        self.assertEqual(justwatch.pick_price({}, "HD"), (None, None))
