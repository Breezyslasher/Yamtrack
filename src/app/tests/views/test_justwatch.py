import copy
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from app.models import MediaTypes, Sources

MOVIE_METADATA = {
    "media_id": "72976",
    "title": "Lincoln",
    "media_type": MediaTypes.MOVIE.value,
    "source": Sources.TMDB.value,
    "image": "https://image.tmdb.org/t/p/w500/lincoln.jpg",
    "max_progress": 1,
    "related": {"recommendations": []},
    "providers": {
        "US": {
            "flatrate": [
                {
                    "provider_id": 8,
                    "provider_name": "Netflix",
                    "logo_path": "/netflix.jpg",
                    "display_priority": 0,
                },
                {
                    "provider_id": 337,
                    "provider_name": "Disney Plus",
                    "logo_path": "/disney.jpg",
                    "display_priority": 1,
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
            "buy": [
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

NETFLIX_LINK = "https://www.netflix.com/title/70218188"
PLEX_LINK = "https://watch.plex.tv/movie/lincoln"


def build_offer(link, *, no_charge=False, rent=None, buy=None):
    """Build a processed JustWatch offer, with prices by quality."""
    return {
        "provider_name": "JustWatch name",
        "image": "https://images.justwatch.com/icon/1/s100/icon.png",
        "link": link,
        "no_charge": no_charge,
        "paid": bool(rent or buy),
        "prices": {"rent": rent or {}, "buy": buy or {}},
    }


APPLE_LINK = "https://tv.apple.com/us/movie/lincoln/umc.cmc.2y2l2hb8ec0t3byecg3ez7l2y"


# Return a copy like the cache does, as the view adds the links to the providers
@patch(
    "app.providers.services.get_media_metadata",
    side_effect=lambda *_args, **_kwargs: copy.deepcopy(MOVIE_METADATA),
)
class JustWatchStreamingSectionTests(TestCase):
    """Test the JustWatch links of the media details streaming section."""

    def setUp(self):
        """Create a user with a watch provider region and log in."""
        cache.clear()
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.user.watch_provider_region = "US"
        self.user.save()
        self.client.login(**self.credentials)
        self.details_url = reverse(
            "media_details",
            kwargs={
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "72976",
                "title": "lincoln",
            },
        )

    @override_settings(JUSTWATCH_ENABLED=True)
    @patch(
        "app.views.justwatch.get_offers",
        return_value={
            8: build_offer(NETFLIX_LINK, no_charge=True),
            538: {
                **build_offer(PLEX_LINK, no_charge=True),
                "provider_name": "Plex",
            },
        },
    )
    def test_streaming_providers_come_from_justwatch_offers(
        self,
        mock_offers,
        _mock_metadata,
    ):
        """JustWatch offers should replace the TMDB providers, with links."""
        response = self.client.get(self.details_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{NETFLIX_LINK}"')
        self.assertContains(response, 'title="Watch on Netflix"')
        # Only on JustWatch, shown with its JustWatch name and link
        self.assertContains(response, f'href="{PLEX_LINK}"')
        self.assertContains(response, 'title="Watch on Plex"')
        # Listed by TMDB but without a JustWatch offer anymore
        self.assertNotContains(response, "Disney Plus")
        mock_offers.assert_called_once_with(
            MediaTypes.MOVIE.value,
            "72976",
            "Lincoln",
            "US",
        )

    @override_settings(JUSTWATCH_ENABLED=False)
    @patch("app.views.justwatch.get_offers")
    def test_streaming_providers_without_justwatch(self, mock_offers, _mock):
        """Without JustWatch, providers should be shown without links."""
        response = self.client.get(self.details_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Netflix")
        self.assertNotContains(response, "Watch on Netflix")
        mock_offers.assert_not_called()

    @override_settings(JUSTWATCH_ENABLED=True)
    @patch("app.views.justwatch.get_offers", side_effect=Exception("blocked"))
    def test_justwatch_failure_still_renders_providers(self, _mock_offers, _mock):
        """A JustWatch failure should not break the details page."""
        response = self.client.get(self.details_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Netflix")
        self.assertNotContains(response, "Watch on Netflix")

    @override_settings(JUSTWATCH_ENABLED=True)
    @patch(
        "app.views.justwatch.get_offers",
        return_value={
            2: build_offer(
                APPLE_LINK,
                rent={"SD": "$2.99", "HD": "$3.99"},
                buy={"HD": "$12.68"},
            ),
        },
    )
    def test_rent_or_buy_row_shows_links_and_prices(self, _mock_offers, _mock):
        """Paid providers should be listed with their JustWatch link and prices."""
        response = self.client.get(self.details_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rent or buy")
        self.assertContains(response, f'href="{APPLE_LINK}"')
        # Lowest price by default, with its quality
        self.assertContains(response, "Rent $2.99")
        self.assertContains(response, "(SD)")
        self.assertContains(response, "Buy $12.68")

        # The user's preferred quality is used when set
        self.user.watch_price_quality = "HD"
        self.user.save()
        response = self.client.get(self.details_url)
        self.assertContains(response, "Rent $3.99")
        self.assertNotContains(response, "Rent $2.99")

    @override_settings(JUSTWATCH_ENABLED=False)
    def test_rent_or_buy_row_without_justwatch(self, mock_metadata):
        """Paid providers are shown without links or prices when disabled."""
        metadata = copy.deepcopy(MOVIE_METADATA)
        metadata["providers"]["US"].pop("flatrate")
        mock_metadata.side_effect = None
        mock_metadata.return_value = metadata

        response = self.client.get(self.details_url)

        self.assertEqual(response.status_code, 200)
        # The streaming section is shown with only paid providers
        self.assertContains(response, ">Streaming</h2>")
        self.assertContains(response, "Rent or buy")
        self.assertContains(response, "Apple TV")
        self.assertNotContains(response, "Watch on Apple TV")
        self.assertNotContains(response, "Rent $")
