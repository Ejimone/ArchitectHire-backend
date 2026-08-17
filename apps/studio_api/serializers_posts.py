"""Read/write serializers for the Studio's blog authoring surface.

The public blog serializers next door (`apps.cms.serializers_editorial`) are read-only and
deliberately omit primary keys — an editor cannot PATCH what it cannot address, and it has
to see the drafts the public API filters out. So the studio gets its own pair.

Images are carried as **storage names**, not files: the upload endpoint stores the file and
hands back its name, and the name then travels on the same JSON as every other field. That
keeps a hero image and the headline it sits under in one atomic save.
"""

from django.utils.text import slugify
from rest_framework import serializers

from apps.cms.models_editorial import Author, BlogCategory, BlogContentBlock, BlogPost

# Roughly the pace of an adult reading web prose. Only ever a hint in the UI — the author
# can always type their own figure over the top of it.
WORDS_PER_MINUTE = 200


def unique_slug(source: str, *, exclude_pk: int | None = None) -> str:
    """A slug derived from `source` that no other post is already using."""
    base = slugify(source)[:110] or "untitled-post"
    candidate = base
    suffix = 2
    while True:
        clash = BlogPost.objects.filter(slug=candidate)
        if exclude_pk is not None:
            clash = clash.exclude(pk=exclude_pk)
        if not clash.exists():
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


def read_time_for(post: BlogPost) -> str:
    # `values_list` rather than `.all()`: this runs immediately after the body was
    # rewritten, and the post was loaded with `prefetch_related("content_blocks")`, whose
    # cache still holds the blocks as they were before the save.
    words = sum(len(text.split()) for text in post.content_blocks.values_list("text", flat=True))
    return f"{max(1, round(words / WORDS_PER_MINUTE))} min read"


def _url(request, file) -> str:
    if not file:
        return ""
    url = file.url
    return request.build_absolute_uri(url) if request else url


class PostBlockSerializer(serializers.ModelSerializer):
    """One row of the article body.

    `id` is writable so a PATCH can say "this is the block you already have" — see
    `write_blocks`. `image` is the storage name; `image_url` is what a preview renders.
    """

    id = serializers.IntegerField(required=False)
    image = serializers.CharField(required=False, allow_blank=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = BlogContentBlock
        fields = [
            "id",
            "kind",
            "text",
            "attribution",
            "cta_label",
            "cta_href",
            "image",
            "image_url",
        ]

    def get_image_url(self, obj) -> str:
        return _url(self.context.get("request"), obj.image)


def write_blocks(post: BlogPost, blocks: list[dict]) -> None:
    """Replace the article body with `blocks`, in the order given.

    A whole-array write rather than per-row CRUD: the editor holds the entire body in
    front of the author anyway, and one payload means a reorder, an edit and a deletion
    cannot land half-applied. Rows carrying an `id` are updated in place so an existing
    block keeps its primary key (and its uploaded image) across a reorder.
    """
    existing = {block.pk: block for block in post.content_blocks.all()}
    kept: set[int] = set()

    for index, data in enumerate(blocks):
        fields = dict(data)
        pk = fields.pop("id", None)
        block = existing.get(pk) if pk else None
        if block is None:
            block = BlogContentBlock(post=post)
        for name, value in fields.items():
            setattr(block, name, value)
        block.sort_order = index
        block.save()
        kept.add(block.pk)

    for pk, block in existing.items():
        if pk not in kept:
            block.delete()


class PostSummarySerializer(serializers.ModelSerializer):
    """One row of the Posts list. Flat labels, because the list only ever displays them."""

    category = serializers.CharField(source="category.name", default="", read_only=True)
    category_id = serializers.IntegerField(source="category.pk", default=None, read_only=True)
    author = serializers.CharField(source="author.name", default="", read_only=True)
    hero_image_url = serializers.SerializerMethodField()
    block_count = serializers.IntegerField(source="content_blocks.count", read_only=True)

    class Meta:
        model = BlogPost
        fields = [
            "id",
            "slug",
            "title",
            "excerpt",
            "status",
            "category",
            "category_id",
            "author",
            "read_time",
            "is_featured",
            "hero_image_url",
            "published_at",
            "updated_at",
            "block_count",
        ]

    def get_hero_image_url(self, obj) -> str:
        return _url(self.context.get("request"), obj.hero_image)


class PostDetailSerializer(serializers.ModelSerializer):
    """The whole post, body included, in one document.

    `status` and `published_at` are read-only on purpose: going live is an explicit act
    with its own endpoint, so an ordinary save can never publish by accident.
    """

    content_blocks = PostBlockSerializer(many=True, required=False)
    hero_image = serializers.CharField(required=False, allow_blank=True)
    hero_image_url = serializers.SerializerMethodField()
    category = serializers.PrimaryKeyRelatedField(
        queryset=BlogCategory.objects.all(), allow_null=True, required=False
    )
    author = serializers.PrimaryKeyRelatedField(
        queryset=Author.objects.all(), allow_null=True, required=False
    )
    slug = serializers.SlugField(max_length=120, required=False, allow_blank=True)

    class Meta:
        model = BlogPost
        fields = [
            "id",
            "slug",
            "title",
            "dek",
            "excerpt",
            "hero_image",
            "hero_image_url",
            "category",
            "author",
            "read_time",
            "is_featured",
            "status",
            "published_at",
            "created_at",
            "updated_at",
            "content_blocks",
        ]
        read_only_fields = ["status", "published_at", "created_at", "updated_at"]

    def get_hero_image_url(self, obj) -> str:
        return _url(self.context.get("request"), obj.hero_image)

    def validate_slug(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            return value
        clash = BlogPost.objects.filter(slug=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                f"Another post already uses the address “{value}”. Pick a different one."
            )
        return value

    def update(self, instance, validated_data):
        blocks = validated_data.pop("content_blocks", None)
        for name, value in validated_data.items():
            setattr(instance, name, value)
        if not instance.slug:
            instance.slug = unique_slug(instance.title, exclude_pk=instance.pk)
        instance.save()

        if blocks is not None:
            write_blocks(instance, blocks)
        finish_save(instance)
        return instance


def finish_save(post: BlogPost) -> None:
    """The two derived facts a post carries, settled after its body is on disk.

    Both need the blocks written first (word count) or the other rows visible (featured),
    so they cannot live in `Model.save`.
    """
    fields = []
    if not post.read_time.strip():
        post.read_time = read_time_for(post)
        fields.append("read_time")
    if fields:
        post.save(update_fields=fields)

    if post.is_featured:
        # The blog index shows exactly one featured post — `BlogListView` takes the
        # first — so the flag has to behave like a radio button or the UI lies about
        # which article is on the hero card.
        for other in BlogPost.objects.filter(is_featured=True).exclude(pk=post.pk):
            other.is_featured = False
            other.save(update_fields=["is_featured"])
