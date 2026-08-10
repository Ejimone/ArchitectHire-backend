from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    verbose_name = "Accounts"

    def ready(self):
        from . import schema, signals  # noqa: F401
