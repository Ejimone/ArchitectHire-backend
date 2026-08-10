from django.urls import path

from .views import (
    AddonsView,
    CategoriesView,
    DraftingPricingView,
    PlansView,
    ProjectTypesView,
    RenderMatrixView,
)

app_name = "catalog"

urlpatterns = [
    path("categories/", CategoriesView.as_view(), name="categories"),
    path("addons/", AddonsView.as_view(), name="addons"),
    path("plans/", PlansView.as_view(), name="plans"),
    path("project-types/", ProjectTypesView.as_view(), name="project-types"),
    path("pricing/render-matrix/", RenderMatrixView.as_view(), name="render-matrix"),
    path("pricing/drafting/", DraftingPricingView.as_view(), name="drafting-pricing"),
]
