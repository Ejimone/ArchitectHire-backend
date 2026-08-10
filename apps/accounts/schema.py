from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ClerkAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.ClerkAuthentication"
    name = "clerkAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Clerk session token (obtained by the frontend from Clerk).",
        }
