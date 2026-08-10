from rest_framework import serializers

from .models import City, State


class StateListSerializer(serializers.ModelSerializer):
    band = serializers.CharField(read_only=True)
    multiplier = serializers.FloatField(read_only=True)
    typical_timeline = serializers.CharField(read_only=True)

    class Meta:
        model = State
        fields = [
            "code",
            "name",
            "complexity_score",
            "region",
            "largest_city",
            "architect_count",
            "band",
            "multiplier",
            "typical_timeline",
        ]


class StateDetailSerializer(StateListSerializer):
    band_label = serializers.CharField(read_only=True)
    factors = serializers.ListField(read_only=True)

    class Meta(StateListSerializer.Meta):
        fields = StateListSerializer.Meta.fields + [
            "band_label",
            "factors",
            "intro",
            "body1",
            "body2",
            "permit_steps",
        ]


class CitySerializer(serializers.ModelSerializer):
    state = serializers.CharField(source="state.code", read_only=True)
    state_name = serializers.CharField(source="state.name", read_only=True)

    class Meta:
        model = City
        fields = ["name", "slug", "state", "state_name", "county", "architect_count"]


class CityDetailSerializer(CitySerializer):
    class Meta(CitySerializer.Meta):
        fields = CitySerializer.Meta.fields + [
            "intro",
            "body1",
            "body2",
            "permit_facts",
            "service_areas",
        ]
