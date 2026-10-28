from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from .base import YamtrackApiTestCase

TMDB_MOVIE_PROVIDERS = {
    "results": [
        {
            "provider_id": 8,
            "provider_name": "Netflix",
            "logo_path": "/netflix.jpg",
            "display_priority": 5,
            "display_priorities": {"US": 0, "GB": 1},
        },
        {
            "provider_id": 337,
            "provider_name": "Disney Plus",
            "logo_path": "/disney.jpg",
            "display_priority": 2,
            "display_priorities": {"US": 1},
        },
    ],
}

TMDB_TV_PROVIDERS = {
    "results": [
        {
            "provider_id": 8,
            "provider_name": "Netflix",
            "logo_path": "/netflix.jpg",
            "display_priorities": {"US": 0},
        },
        {
            "provider_id": 15,
            "provider_name": "Hulu",
            "logo_path": None,
            "display_priority": 3,
            "display_priorities": {},
        },
    ],
}

JUSTWATCH_PACKAGES = {
    "data": {
        "packages": [
            {"packageId": 8, "clearName": "Netflix", "icon": "/icon/1/s100/nfx.png"},
            {
                "packageId": 2766,
                "clearName": "Sling TV Freestream",
                "icon": "/icon/321/s100/slingfreestream.png",
            },
            {"packageId": None, "clearName": "Broken", "icon": None},
        ],
    },
}


def tmdb_response(_provider, _method, url, **_kwargs):
    """Return the TMDB provider list of the requested media type."""
    if url.endswith("/watch/providers/movie"):
        return TMDB_MOVIE_PROVIDERS
    if url.endswith("/watch/providers/tv"):
        return TMDB_TV_PROVIDERS
    return JUSTWATCH_PACKAGES


@patch("app.providers.services.api_request", side_effect=tmdb_response)
class WatchProviderListTests(YamtrackApiTestCase):
    """Validate the watch provider list endpoint."""

    def setUp(self):
        """Clear cached provider lists between tests."""
        super().setUp()
        cache.clear()

    def get_providers(self, region="US"):
        """Call the provider list endpoint."""
        return self.call_api(
            "get",
            "api_providers",
            params={"region": region},
            headers=self.auth_headers,
        )

    @override_settings(JUSTWATCH_ENABLED=False)
    def test_lists_tmdb_providers_by_region_priority(self, mock_request):
        """Movie and tv providers are merged and sorted for the region."""
        response = self.get_providers("us")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["region"], "US")
        self.assertEqual(
            [p["provider_name"] for p in payload["results"]],
            ["Netflix", "Disney Plus", "Hulu"],
        )
        netflix = payload["results"][0]
        self.assertEqual(netflix["provider_id"], 8)
        self.assertEqual(netflix["display_priority"], 0)
        self.assertEqual(
            netflix["image"], "https://image.tmdb.org/t/p/w500/netflix.jpg"
        )
        # Without a priority for the region, the global one is used
        self.assertEqual(payload["results"][2]["display_priority"], 3)

        params = mock_request.call_args_list[0].kwargs["params"]
        self.assertEqual(params["watch_region"], "US")
        self.assertEqual(mock_request.call_count, 2)

        # Cached per region
        self.get_providers()
        self.assertEqual(mock_request.call_count, 2)

    @override_settings(JUSTWATCH_ENABLED=True)
    def test_adds_justwatch_only_providers(self, _mock_request):
        """JustWatch providers TMDB doesn't list are added after TMDB's."""
        payload = self.get_providers().json()

        names = [p["provider_name"] for p in payload["results"]]
        self.assertEqual(
            names,
            ["Netflix", "Disney Plus", "Hulu", "Sling TV Freestream"],
        )
        sling = payload["results"][-1]
        self.assertEqual(sling["provider_id"], 2766)
        self.assertEqual(
            sling["image"],
            "https://images.justwatch.com/icon/321/s100/slingfreestream.png",
        )

    @override_settings(JUSTWATCH_ENABLED=True)
    def test_justwatch_failure_keeps_tmdb_providers(self, mock_request):
        """A JustWatch failure falls back to the TMDB providers."""

        def fail_justwatch(provider, method, url, **kwargs):
            if provider == "justwatch":
                msg = "JustWatch is down"
                raise RuntimeError(msg)
            return tmdb_response(provider, method, url, **kwargs)

        mock_request.side_effect = fail_justwatch
        with self.assertLogs("api.helpers", level="ERROR"):
            response = self.get_providers()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 3)

    def test_requires_region(self, _mock_request):
        """Without a region or a user preference the request is rejected."""
        response = self.call_api("get", "api_providers", headers=self.auth_headers)
        self.assertEqual(response.status_code, 400)
