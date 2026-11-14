from django.test import SimpleTestCase

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
