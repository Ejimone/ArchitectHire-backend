from django.urls import path

from apps.search.views import SearchView

from .views import FooterView, MediaSlotsView, NavigationView, PageContentView, SettingsView
from .views_editorial import (
    BlogDetailView,
    BlogListView,
    CareersView,
    CaseStudyDetailView,
    CaseStudyListView,
    ContactView,
    InspirationLikeView,
    InspirationListView,
    NewsletterView,
    PolicyView,
)

app_name = "cms"

urlpatterns = [
    path("pages/<str:page_key>/", PageContentView.as_view(), name="page"),
    path("nav/", NavigationView.as_view(), name="nav"),
    path("footer/", FooterView.as_view(), name="footer"),
    path("settings/", SettingsView.as_view(), name="settings"),
    path("media/", MediaSlotsView.as_view(), name="media"),
    path("blog/", BlogListView.as_view(), name="blog-list"),
    path("blog/<slug:slug>/", BlogDetailView.as_view(), name="blog-detail"),
    path("case-studies/", CaseStudyListView.as_view(), name="case-study-list"),
    path("case-studies/<slug:slug>/", CaseStudyDetailView.as_view(), name="case-study-detail"),
    path("careers/", CareersView.as_view(), name="careers"),
    path("contact/", ContactView.as_view(), name="contact"),
    path("policies/<slug:slug>/", PolicyView.as_view(), name="policy"),
    path("inspiration/", InspirationListView.as_view(), name="inspiration"),
    path("inspiration/<int:pk>/like/", InspirationLikeView.as_view(), name="inspiration-like"),
    path("newsletter/", NewsletterView.as_view(), name="newsletter"),
    path("search/", SearchView.as_view(), name="search"),
]
