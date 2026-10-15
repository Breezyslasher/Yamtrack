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
                                "standardWebURL": "https://watch.amazon.com/detail?gti=amzn1.dv.gti.78a9f704-5cb5-2a2b-4b42-3b21e11dccf2",
                                "retailPrice": "$3.99",
                                "package": {"packageId": 10},
                            },
                            {
                                "monetizationType": "RENT",
                                "standardWebURL": "https://tv.apple.com/us/movie/lincoln/umc.cmc.2y2l2hb8ec0t3byecg3ez7l2y",
                                "retailPrice": "$3.99",
                                "package": {"packageId": 2},
                            },
                            {
                                "monetizationType": "BUY",
                                "standardWebURL": "https://www.amazon.com/dp/B00F3A7G7M",
                                "retailPrice": "$12.68",
                                "package": {"packageId": 50},
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
                                "standardWebURL": "https://watch.sling.com/1/program/15cbd81254b4d4068e64694b80bdb8fd/watch",
                                "retailPrice": None,
                                "package": {"packageId": 2766},
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
    def test_real_justwatch_response_matches_tmdb_providers(
        self,
        mock_request,
        _mock_metadata,
    ):
        """A recorded JustWatch response should link the matching TMDB providers."""
        mock_request.return_value = JUSTWATCH_LINCOLN_RESPONSE

        response = self.get_providers()

        self.assertEqual(response.status_code, 200)
        apple = response.json()["paid"][0]
        self.assertEqual(apple["provider_id"], 2)
        self.assertEqual(
            apple["link"],
            "https://tv.apple.com/us/movie/lincoln/umc.cmc.2y2l2hb8ec0t3byecg3ez7l2y",
        )
        self.assertEqual(apple["rent_price"], "$3.99")
        self.assertIsNone(apple["buy_price"])
        # Netflix has no JustWatch offer for this title
        self.assertIsNone(response.json()["no_charge"][0]["link"])

    def test_fast_offers_count_as_no_charge(self, _mock_metadata):
        """FAST offers should give the no charge link and no price."""
        offers = justwatch.process_offers(
            JUSTWATCH_LINCOLN_RESPONSE["data"]["popularTitles"]["edges"][1]["node"][
                "offers"
            ],
        )

        self.assertEqual(
            offers,
            {
                2766: {
                    "link": "https://watch.sling.com/1/program/15cbd81254b4d4068e64694b80bdb8fd/watch",
                    "buy_price": None,
                    "rent_price": None,
                },
            },
        )
