from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    name = "apps.payments"
    verbose_name = "Payments & escrow"

    # The pricing table is the only thing here the marketing site renders. Escrow
    # transactions and payouts write on every order — wiring the whole app for cache
    # bumps, as the content apps do, would purge the site all day long.
    CONTENT_MODELS = ["SubscriptionPlan"]

    def ready(self):
        from apps.core.signals import register_content_version_bump_for

        for model_name in self.CONTENT_MODELS:
            register_content_version_bump_for(self.get_model(model_name))
