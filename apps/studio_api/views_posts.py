"""Blog authoring for the Studio: list, write, publish.

Blog posts deliberately do **not** go through `ContentDraft`. `BlogPost` already inherits
`PublishableModel`, so the post's own `status` is its draft state — one mechanism, visible
in the admin and in the studio alike. Routing it through the staging queue instead would
mean inventing a way to point a not-yet-created block row at a not-yet-created post, and
would put "half of an unfinished article" in the same publish button as a headline tweak.

Everything else — auth, staff check, throttle, parsers — comes from `StudioView`.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.response import Response

from apps.cms.models_editorial import Author, BlogCategory, BlogContentBlock, BlogPost

from .serializers_posts import (
    PostDetailSerializer,
    PostSummarySerializer,
    finish_save,
    unique_slug,
    write_blocks,
)
from .views import StudioView


def posts_queryset():
    return BlogPost.objects.select_related("category", "author").prefetch_related("content_blocks")


def taxonomy(request=None) -> dict:
    """The dropdown contents, sent alongside every list so the editor needs no second call."""
    return {
        "categories": [
            {"id": c.pk, "name": c.name, "slug": c.slug}
            for c in BlogCategory.objects.all().order_by("sort_order", "name")
        ],
        "authors": [
            {
                "id": a.pk,
                "name": a.name,
                "role": a.role,
                # The editor's live preview draws the byline; without this it always drew
                # the placeholder, even for an author whose portrait is set.
                "photo": (
                    request.build_absolute_uri(a.photo.url) if (request and a.photo) else None
                ),
            }
            for a in Author.objects.all().order_by("name")
        ],
        "kinds": [
            {"value": value, "label": label} for value, label in BlogContentBlock.Kind.choices
        ],
    }


def detail_response(request, post, http_status=status.HTTP_200_OK) -> Response:
    data = PostDetailSerializer(post, context={"request": request}).data
    return Response(data, status=http_status)


class PostListView(StudioView):
    """GET every post — drafts included — and POST a new empty one."""

    def get(self, request):
        queryset = posts_queryset()
        if q := request.query_params.get("q", "").strip():
            queryset = queryset.filter(title__icontains=q)
        if state := request.query_params.get("status", "").strip():
            if state in {BlogPost.Status.DRAFT, BlogPost.Status.PUBLISHED}:
                queryset = queryset.filter(status=state)
        if category := request.query_params.get("category", "").strip():
            queryset = queryset.filter(category__slug=category)
        # `Meta.ordering` sorts by `published_at`, which is null for every draft — and a
        # draft is precisely the post the author is coming back to, so surface the most
        # recently touched first instead.
        queryset = queryset.order_by("-updated_at")

        rows = PostSummarySerializer(queryset, many=True, context={"request": request}).data
        return Response({"results": rows, "count": len(rows), **taxonomy(request)})

    def post(self, request):
        title = (request.data.get("title") or "Untitled post").strip() or "Untitled post"
        post = BlogPost(
            title=title,
            slug=unique_slug(title),
            # `PublishableModel.status` defaults to *published*, which is right for a row
            # a developer seeds and wrong for one an editor is about to start writing.
            status=BlogPost.Status.DRAFT,
            published_at=None,
        )
        post.save()
        return detail_response(request, post, status.HTTP_201_CREATED)


class PostDetailView(StudioView):
    """Read, write and delete one post."""

    def get_post(self, pk) -> BlogPost | None:
        return posts_queryset().filter(pk=pk).first()

    def get(self, request, pk=None):
        post = self.get_post(pk)
        if post is None:
            return Response({"detail": "No such post."}, status=status.HTTP_404_NOT_FOUND)
        return detail_response(request, post)

    def patch(self, request, pk=None):
        post = self.get_post(pk)
        if post is None:
            return Response({"detail": "No such post."}, status=status.HTTP_404_NOT_FOUND)
        serializer = PostDetailSerializer(
            post, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            post = serializer.save()
        return detail_response(request, self.get_post(post.pk))

    def delete(self, request, pk=None):
        post = self.get_post(pk)
        if post is None:
            return Response({"detail": "No such post."}, status=status.HTTP_404_NOT_FOUND)
        post.delete()  # blocks cascade
        return Response({"deleted": pk})


class PostPublishView(StudioView):
    """Put a post on the site, or take it back off.

    `published_at` is settable so an article written today can carry the date it was
    actually researched — the blog index sorts on it.
    """

    def post(self, request, pk=None):
        post = posts_queryset().filter(pk=pk).first()
        if post is None:
            return Response({"detail": "No such post."}, status=status.HTTP_404_NOT_FOUND)

        if not post.title.strip():
            return Response(
                {"detail": "Give the post a title before publishing it."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not post.content_blocks.exists():
            return Response(
                {"detail": "The post has no body yet. Add at least one block first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        post.status = BlogPost.Status.PUBLISHED
        post.published_at = request.data.get("published_at") or post.published_at or timezone.now()
        post.save(update_fields=["status", "published_at"])
        return detail_response(request, post)


class PostUnpublishView(StudioView):
    def post(self, request, pk=None):
        post = posts_queryset().filter(pk=pk).first()
        if post is None:
            return Response({"detail": "No such post."}, status=status.HTTP_404_NOT_FOUND)
        post.status = BlogPost.Status.DRAFT
        # `published_at` is kept: it is the article's date, not a record of the button.
        post.save(update_fields=["status"])
        return detail_response(request, post)


class PostDuplicateView(StudioView):
    """Copy a post and its body into a fresh draft — how a follow-up article gets started."""

    def post(self, request, pk=None):
        source = posts_queryset().filter(pk=pk).first()
        if source is None:
            return Response({"detail": "No such post."}, status=status.HTTP_404_NOT_FOUND)

        title = f"{source.title} (copy)"[:160]
        with transaction.atomic():
            copy = BlogPost(
                title=title,
                slug=unique_slug(title),
                dek=source.dek,
                excerpt=source.excerpt,
                hero_image=source.hero_image.name if source.hero_image else "",
                category=source.category,
                author=source.author,
                read_time=source.read_time,
                # Only one post may be featured, and a copy is never the one.
                is_featured=False,
                status=BlogPost.Status.DRAFT,
                published_at=None,
            )
            copy.save()
            write_blocks(
                copy,
                [
                    {
                        "kind": block.kind,
                        "text": block.text,
                        "attribution": block.attribution,
                        "cta_label": block.cta_label,
                        "cta_href": block.cta_href,
                        "image": block.image.name if block.image else "",
                    }
                    for block in source.content_blocks.all()
                ],
            )
            finish_save(copy)
        return detail_response(request, copy, status.HTTP_201_CREATED)


class CategoryCreateView(StudioView):
    """Add a blog category without leaving the editor's dropdown."""

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response(
                {"detail": "A category needs a name."}, status=status.HTTP_400_BAD_REQUEST
            )
        existing = BlogCategory.objects.filter(name__iexact=name).first()
        if existing:
            return Response({"id": existing.pk, "name": existing.name, "slug": existing.slug})
        slug = slugify(name)[:40] or "category"
        if BlogCategory.objects.filter(slug=slug).exists():
            slug = f"{slug[:36]}-{BlogCategory.objects.count() + 1}"
        category = BlogCategory.objects.create(name=name[:40], slug=slug)
        return Response(
            {"id": category.pk, "name": category.name, "slug": category.slug},
            status=status.HTTP_201_CREATED,
        )


class AuthorCreateView(StudioView):
    """Add a bylined author without leaving the editor's dropdown."""

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response(
                {"detail": "An author needs a name."}, status=status.HTTP_400_BAD_REQUEST
            )
        existing = Author.objects.filter(name__iexact=name).first()
        if existing:
            return Response({"id": existing.pk, "name": existing.name, "role": existing.role})
        author = Author.objects.create(
            name=name[:80],
            role=(request.data.get("role") or "").strip()[:120],
            bio=(request.data.get("bio") or "").strip(),
        )
        return Response(
            {"id": author.pk, "name": author.name, "role": author.role},
            status=status.HTTP_201_CREATED,
        )
