from rest_framework import serializers

from .models_editorial import (
    Author,
    BlogContentBlock,
    BlogPost,
    CaseStudy,
    CaseStudyImage,
    ContactMethod,
    ContactSubmission,
    ContactTopic,
    InspirationItem,
    JobPosting,
    NewsletterSubscriber,
    Perk,
    PolicyPage,
    PolicySection,
)


class AuthorSerializer(serializers.ModelSerializer):
    photo = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = Author
        fields = ["name", "role", "bio", "photo"]


class BlogContentBlockSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = BlogContentBlock
        fields = ["kind", "text", "attribution", "cta_label", "cta_href", "image"]


class BlogPostListSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source="category.name", default="", read_only=True)
    category_slug = serializers.CharField(source="category.slug", default="", read_only=True)
    author = serializers.CharField(source="author.name", default="", read_only=True)
    hero_image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = BlogPost
        fields = [
            "slug",
            "title",
            "excerpt",
            "category",
            "category_slug",
            "author",
            "read_time",
            "is_featured",
            "hero_image",
            "published_at",
        ]


class BlogPostDetailSerializer(BlogPostListSerializer):
    author = AuthorSerializer(read_only=True)
    content_blocks = BlogContentBlockSerializer(many=True, read_only=True)
    related = serializers.SerializerMethodField()

    class Meta(BlogPostListSerializer.Meta):
        fields = [*BlogPostListSerializer.Meta.fields, "dek", "content_blocks", "related"]

    def get_related(self, obj):
        related = (
            BlogPost.objects.published()
            .exclude(pk=obj.pk)
            .filter(category=obj.category)
            .order_by("-published_at")[:3]
        )
        return BlogPostListSerializer(related, many=True, context=self.context).data


class CaseStudyImageSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = CaseStudyImage
        fields = ["image", "caption"]


class CaseStudyListSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source="category.name", default="", read_only=True)
    category_slug = serializers.CharField(source="category.slug", default="", read_only=True)
    hero_image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = CaseStudy
        fields = [
            "slug",
            "title",
            "location",
            "excerpt",
            "category",
            "category_slug",
            "card_stats",
            "is_featured",
            "hero_image",
        ]


class CaseStudyDetailSerializer(CaseStudyListSerializer):
    gallery = CaseStudyImageSerializer(many=True, read_only=True)
    related = serializers.SerializerMethodField()

    class Meta(CaseStudyListSerializer.Meta):
        fields = [
            *CaseStudyListSerializer.Meta.fields,
            "dek",
            "brief",
            "challenge1",
            "challenge2",
            "match_narrative",
            "match_points",
            "quote",
            "quote_by",
            "outcome1",
            "outcome2",
            "glance",
            "architect_name",
            "architect_role",
            "architect_bio",
            "architect_tags",
            "gallery",
            "related",
        ]

    def get_related(self, obj):
        related = CaseStudy.objects.published().exclude(pk=obj.pk).order_by("-published_at")[:3]
        return CaseStudyListSerializer(related, many=True, context=self.context).data


class JobPostingSerializer(serializers.ModelSerializer):
    department = serializers.CharField(source="department.name", default="", read_only=True)

    class Meta:
        model = JobPosting
        fields = ["title", "department", "location", "employment_type", "description", "apply_href"]


class PerkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Perk
        fields = ["title", "description"]


class ContactMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMethod
        fields = ["kind", "title", "description", "link_label", "href"]


class ContactSubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactSubmission
        fields = ["name", "email", "topic", "message"]

    def validate_topic(self, value):
        if value and not ContactTopic.objects.filter(label=value).exists():
            raise serializers.ValidationError("Unknown topic.")
        return value


class PolicySectionSerializer(serializers.ModelSerializer):
    paragraphs = serializers.SerializerMethodField()

    class Meta:
        model = PolicySection
        fields = ["anchor", "heading", "paragraphs"]

    def get_paragraphs(self, obj):
        return [p.strip() for p in obj.body.split("\n\n") if p.strip()]


class PolicyPageSerializer(serializers.ModelSerializer):
    sections = PolicySectionSerializer(many=True, read_only=True)

    class Meta:
        model = PolicyPage
        fields = ["slug", "title", "effective_date", "sections"]


class InspirationItemSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = InspirationItem
        fields = [
            "id",
            "title",
            "tag",
            "style",
            "image",
            "palette",
            "masonry_height",
            "likes_count",
        ]


class NewsletterSerializer(serializers.Serializer):
    """Plain serializer: subscribing twice is a silent success, not a unique error."""

    email = serializers.EmailField()
    source = serializers.CharField(required=False, allow_blank=True, max_length=40)

    def create(self, validated_data):
        subscriber, _ = NewsletterSubscriber.objects.get_or_create(
            email=validated_data["email"].lower(),
            defaults={"source": validated_data.get("source") or "blog"},
        )
        return subscriber
