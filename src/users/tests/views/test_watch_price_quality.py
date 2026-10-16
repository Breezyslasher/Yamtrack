from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from users.models import WatchPriceQualityChoices


class WatchPriceQualityPreferenceTests(TestCase):
    """Tests for the rent and buy price quality preference."""

    def setUp(self):
        """Create and log in a user."""
        patcher = patch(
            "users.views.tmdb.watch_provider_regions",
            return_value=[("UNSET", "Disabled"), ("US", "United States")],
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.credentials = {"username": "testuser", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_default_is_lowest_price(self):
        """New users should see the lowest price of any quality."""
        self.assertEqual(
            self.user.watch_price_quality,
            WatchPriceQualityChoices.LOWEST,
        )

    def test_post_saves_quality(self):
        """The preferences form should save a valid quality."""
        self.client.post(reverse("preferences"), {"watch_price_quality": "HD"})

        self.user.refresh_from_db()
        self.assertEqual(self.user.watch_price_quality, "HD")

    def test_post_ignores_invalid_quality(self):
        """An invalid quality should keep the current preference."""
        self.client.post(reverse("preferences"), {"watch_price_quality": "8K"})

        self.user.refresh_from_db()
        self.assertEqual(
            self.user.watch_price_quality,
            WatchPriceQualityChoices.LOWEST,
        )

    @override_settings(JUSTWATCH_ENABLED=True)
    def test_setting_shown_when_justwatch_enabled(self):
        """The setting is shown when JustWatch provides the prices."""
        response = self.client.get(reverse("preferences"))

        self.assertContains(response, 'name="watch_price_quality"')

    @override_settings(JUSTWATCH_ENABLED=False)
    def test_setting_hidden_without_justwatch(self):
        """The setting is hidden when there are no prices to show."""
        response = self.client.get(reverse("preferences"))

        self.assertNotContains(response, 'name="watch_price_quality"')
