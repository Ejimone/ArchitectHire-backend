"""Studio API routes, mounted at /api/v1/studio/.

`page_key` and `scope` use `<path:...>` because scope keys contain colons and slashes
never appear in them, but `<str:...>` would still stop at the first `/` a future
parameterised key introduces. `model_label` is matched loosely and validated against the
allowlist in `drafts.resolve_model`, not by the URL pattern.
"""

from django.urls import path, re_path

from . import views, views_posts, views_records

app_name = "studio_api"

urlpatterns = [
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    path("schema/", views.SchemaView.as_view(), name="schema"),
    path("chrome/", views.ChromeView.as_view(), name="chrome"),
    path("pages/", views.PageListView.as_view(), name="pages"),
    path("pages/<path:page_key>/", views.PageDetailView.as_view(), name="page-detail"),
    path("copy/<str:scope>/<str:key>/", views.CopyView.as_view(), name="copy"),
    path("seo/<path:page_key>/", views.SeoView.as_view(), name="seo"),
    path("rows/<str:model_label>/", views.RowCreateView.as_view(), name="row-create"),
    path("rows/<str:model_label>/reorder/", views.ReorderView.as_view(), name="row-reorder"),
    # Signed, because a row that is still only a draft is addressed by the negative of
    # its draft id — `<int:>` would not match it.
    re_path(
        r"^rows/(?P<model_label>[\w.]+)/(?P<pk>-?\d+)/$",
        views.RowDetailView.as_view(),
        name="row-detail",
    ),
    # Blog authoring. `categories/` and `authors/` sit above `<int:pk>/` for readability
    # only — a word never matches `<int:>`, so the order is not load-bearing.
    path("posts/", views_posts.PostListView.as_view(), name="posts"),
    path("posts/categories/", views_posts.CategoryCreateView.as_view(), name="post-categories"),
    path("posts/authors/", views_posts.AuthorCreateView.as_view(), name="post-authors"),
    path("posts/<int:pk>/", views_posts.PostDetailView.as_view(), name="post-detail"),
    path("posts/<int:pk>/publish/", views_posts.PostPublishView.as_view(), name="post-publish"),
    path(
        "posts/<int:pk>/unpublish/",
        views_posts.PostUnpublishView.as_view(),
        name="post-unpublish",
    ),
    path(
        "posts/<int:pk>/duplicate/",
        views_posts.PostDuplicateView.as_view(),
        name="post-duplicate",
    ),
    # Collections: every non-block record type (case studies, jobs, catalog, cities…).
    path("records/", views_records.RecordsIndexView.as_view(), name="records"),
    path("records/<str:label>/", views_records.RecordListView.as_view(), name="record-list"),
    re_path(
        r"^records/(?P<label>[\w.-]+)/(?P<pk>-?\d+)/$",
        views_records.RecordDetailView.as_view(),
        name="record-detail",
    ),
    path("media/", views.MediaView.as_view(), name="media"),
    # `sync/` before the slot-key catch-all: `<path:>` would otherwise swallow it.
    path("media/sync/", views.MediaSyncView.as_view(), name="media-sync"),
    path("media/<path:slot_key>/", views.MediaSlotView.as_view(), name="media-slot"),
    path("uploads/", views.UploadView.as_view(), name="uploads"),
    path("queue/", views.QueueView.as_view(), name="queue"),
    path("publish/", views.PublishView.as_view(), name="publish"),
    path("discard/", views.DiscardView.as_view(), name="discard"),
    path("revisions/", views.RevisionListView.as_view(), name="revisions"),
    path("revisions/<int:pk>/revert/", views.RevisionRevertView.as_view(), name="revision-revert"),
]
