from http import HTTPStatus as HTTP  # noqa: N814

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from api.examples import WATCH_PROVIDER_LIST_EXAMPLE, WATCH_PROVIDERS_EXAMPLE
from api.helpers import (
    add_justwatch_links,
    check_valid_type,
    group_watch_providers,
    list_watch_providers,
    parse_watch_price_quality,
    parse_watch_provider_region,
)
from api.schemas import (
    BadRequestResponse,
    MediaIdParam,
    MediaTypeParam,
    NotFoundResponse,
    SeasonNumberParam,
    SourceCompleteParam,
    WatchPriceQualityParam,
    WatchProviderRegionParam,
)
from api.serializers import (
    WatchProviderListResponseSerializer,
    WatchProvidersResponseSerializer,
)
from app.models import MediaTypes, Sources
from app.providers import services


# /api/v1/media/[media_type]/[source]/[media_id]/providers/
class MediaWatchProvidersView(drf_views.APIView):
    """Media watch providers view."""

    serializer_class = WatchProvidersResponseSerializer

    @extend_schema(
        operation_id="media_providers_get",
        summary="Get media watch providers",
        parameters=[
            MediaTypeParam,
            SourceCompleteParam,
            MediaIdParam,
            WatchProviderRegionParam,
            WatchPriceQualityParam,
        ],
        responses={
            200: OpenApiResponse(
                WatchProvidersResponseSerializer,
                description="Successful response",
                examples=[WATCH_PROVIDERS_EXAMPLE],
            ),
            400: BadRequestResponse,
            404: NotFoundResponse,
        },
    )
    def get(self, request, media_type, source, media_id):
        """Retrieve no charge and paid watch providers for a specific media."""
        if not check_valid_type(media_type):
            return Response(
                {"detail": "Unsupported media type."},
                status=HTTP.BAD_REQUEST,
            )

        if media_type not in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
            return Response(
                {
                    "detail": (
                        "Watch providers are supported only for 'movie' and 'tv' "
                        "media types."
                    ),
                },
                status=HTTP.BAD_REQUEST,
            )

        if source != Sources.TMDB.value:
            return Response(
                {
                    "detail": f"Cannot query `{source}` for `{media_type}` media type",
                },
                status=HTTP.BAD_REQUEST,
            )

        region = parse_watch_provider_region(request)
        quality = parse_watch_price_quality(request)

        media_metadata = services.get_media_metadata(media_type, media_id, source)

        providers = add_justwatch_links(
            group_watch_providers(media_metadata.get("providers"), region),
            media_type,
            media_id,
            media_metadata.get("title"),
            quality,
        )
        return Response(providers, status=HTTP.OK)


# /api/v1/media/[media_type]/[source]/[media_id]/[season_number]/providers/
class MediaSeasonWatchProvidersView(drf_views.APIView):
    """Season watch providers view."""

    serializer_class = WatchProvidersResponseSerializer

    @extend_schema(
        operation_id="season_providers_get",
        summary="Get season watch providers",
        parameters=[
            MediaTypeParam,
            SourceCompleteParam,
            MediaIdParam,
            SeasonNumberParam,
            WatchProviderRegionParam,
        ],
        responses={
            200: OpenApiResponse(
                WatchProvidersResponseSerializer,
                description="Successful response",
                examples=[WATCH_PROVIDERS_EXAMPLE],
            ),
            400: BadRequestResponse,
            404: NotFoundResponse,
        },
    )
    def get(self, request, media_type, source, media_id, season_number):
        """Retrieve no charge and paid watch providers for a tv serie season."""
        if not check_valid_type(media_type):
            return Response(
                {"detail": "Unsupported media type."},
                status=HTTP.BAD_REQUEST,
            )

        if media_type != MediaTypes.TV.value:
            return Response(
                {
                    "detail": "Seasons are supported only for 'tv' media type.",
                },
                status=HTTP.BAD_REQUEST,
            )

        if source != Sources.TMDB.value:
            return Response(
                {
                    "detail": f"Cannot query `{source}` for `{media_type}` media type",
                },
                status=HTTP.BAD_REQUEST,
            )

        region = parse_watch_provider_region(request)

        season_metadata = services.get_media_metadata(
            MediaTypes.SEASON.value,
            media_id,
            source,
            [season_number],
        )

        providers = group_watch_providers(season_metadata.get("providers"), region)
        return Response(providers, status=HTTP.OK)


# /api/v1/providers/
class WatchProviderListView(drf_views.APIView):
    """Watch provider list view."""

    serializer_class = WatchProviderListResponseSerializer

    @extend_schema(
        operation_id="providers_get",
        summary="List every watch provider of a region",
        parameters=[WatchProviderRegionParam],
        responses={
            200: OpenApiResponse(
                WatchProviderListResponseSerializer,
                description="Successful response",
                examples=[WATCH_PROVIDER_LIST_EXAMPLE],
            ),
            400: BadRequestResponse,
        },
    )
    def get(self, request):
        """List the watch providers of a region from TMDB and JustWatch."""
        region = parse_watch_provider_region(request)
        providers = list_watch_providers(region)
        return Response({"region": region, "results": providers}, status=HTTP.OK)
