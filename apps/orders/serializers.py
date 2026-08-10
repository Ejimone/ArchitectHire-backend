from rest_framework import serializers

from .calculators import DRAFTING_SERVICES, RENDER_TIERS, drafting_quote, render_quote
from .models import Order


class RenderQuoteSerializer(serializers.Serializer):
    deliverable = serializers.CharField()
    tier = serializers.ChoiceField(choices=RENDER_TIERS)
    qty = serializers.IntegerField(min_value=1, max_value=10)
    rush = serializers.BooleanField(default=False)


class DraftingQuoteSerializer(serializers.Serializer):
    service = serializers.ChoiceField(choices=DRAFTING_SERVICES)
    size = serializers.IntegerField(min_value=1)
    stamp = serializers.BooleanField(default=False)
    rush = serializers.BooleanField(default=False)


class OrderQuoteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["render", "drafting"])
    render = RenderQuoteSerializer(required=False)
    drafting = DraftingQuoteSerializer(required=False)

    def validate(self, attrs):
        kind = attrs["kind"]
        if kind == "render" and "render" not in attrs:
            raise serializers.ValidationError({"render": "Required for kind=render."})
        if kind == "drafting" and "drafting" not in attrs:
            raise serializers.ValidationError({"drafting": "Required for kind=drafting."})
        try:
            if kind == "render":
                attrs["quote"] = render_quote(**attrs["render"])
            else:
                attrs["quote"] = drafting_quote(**attrs["drafting"])
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return attrs


class OrderCreateSerializer(OrderQuoteSerializer):
    customer_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    customer_email = serializers.EmailField()
    notes = serializers.CharField(required=False, allow_blank=True)
    have = serializers.CharField(max_length=40, required=False, allow_blank=True)

    def create(self, validated_data):
        quote = validated_data["quote"]
        request = self.context.get("request")
        user = getattr(request, "user", None)
        config = {**quote.config, "have": validated_data.get("have", "")}
        return Order.objects.create(
            user=user if (user and user.is_authenticated) else None,
            kind=quote.kind,
            config=config,
            customer_name=validated_data.get("customer_name", ""),
            customer_email=validated_data["customer_email"],
            notes=validated_data.get("notes", ""),
            subtotal=quote.subtotal,
            stamp_amount=quote.stamp_amount,
            rush_amount=quote.rush_amount,
            total=quote.total,
        )


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = [
            "id",
            "kind",
            "config",
            "customer_name",
            "customer_email",
            "notes",
            "subtotal",
            "stamp_amount",
            "rush_amount",
            "total",
            "status",
            "created_at",
        ]
        read_only_fields = fields
