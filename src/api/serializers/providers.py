from rest_framework import serializers


class WatchProviderSerializer(serializers.Serializer):
    """Serializer for a single watch provider."""

    provider_id = serializers.IntegerField()
    provider_name = serializers.CharField()
    image = serializers.URLField(allow_null=True)
    display_priority = serializers.IntegerField(allow_null=True)
    link = serializers.URLField(
        allow_null=True,
        help_text=(
            "Direct link to the media on the provider, from JustWatch. Null unless "
            "JUSTWATCH_ENABLED is set and JustWatch has the media."
        ),
    )
    rent_price = serializers.CharField(
        allow_null=True,
        help_text="Formatted price to rent the media, from JustWatch.",
    )
    rent_quality = serializers.CharField(
        allow_null=True,
        help_text="Video quality (SD, HD or 4K) of the rent price.",
    )
    buy_price = serializers.CharField(
        allow_null=True,
        help_text="Formatted price to buy the media, from JustWatch.",
    )
    buy_quality = serializers.CharField(
        allow_null=True,
        help_text="Video quality (SD, HD or 4K) of the buy price.",
    )
    prices = serializers.DictField(
        child=serializers.DictField(child=serializers.CharField()),
        allow_null=True,
        help_text=(
            "All rent and buy prices by video quality, e.g. "
            '{"rent": {"SD": "$3.99", "HD": "$3.99"}, "buy": {"HD": "$14.99"}}.'
        ),
    )


class WatchProvidersResponseSerializer(serializers.Serializer):
    """Serializer for watch providers endpoint."""

    region = serializers.CharField()
    link = serializers.URLField(allow_null=True)
    no_charge = WatchProviderSerializer(many=True)
    paid = WatchProviderSerializer(many=True)


class WatchProviderListItemSerializer(serializers.Serializer):
    """Serializer for a provider of the watch provider list."""

    provider_id = serializers.IntegerField()
    provider_name = serializers.CharField()
    image = serializers.URLField(allow_null=True)
    display_priority = serializers.IntegerField(allow_null=True)


class WatchProviderListResponseSerializer(serializers.Serializer):
    """Serializer for the watch provider list endpoint."""

    region = serializers.CharField()
    results = WatchProviderListItemSerializer(many=True)
