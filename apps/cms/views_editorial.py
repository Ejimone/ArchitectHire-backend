from django.db.models import F
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models_editorial import (
    BlogCategory,
    BlogPost,
    CaseStudy,
    CaseStudyCategory,
    ContactMethod,
    ContactTopic,
    Department,
    InspirationItem,
    InspirationLike,
    JobPosting,
    Perk,
    PolicyPage,
)
from .serializers_editorial import (
    BlogPostDetailSerializer,
    BlogPostListSerializer,
    CaseStudyDetailSerializer,
    CaseStudyListSerializer,
    ContactMethodSerializer,
    ContactSubmissionSerializer,
    InspirationItemSerializer,
    JobPostingSerializer,
    NewsletterSerializer,
    PerkSerializer,
    PolicyPageSerializer,
)


class PublicAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]


class BlogListView(generics.ListAPIView):
    serializer_class = BlogPostListSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

    def get_queryset(self):
        queryset = BlogPost.objects.published().select_related("category", "author")
        category = self.request.query_params.get("category")
        if category and category != "all":
            queryset = queryset.filter(category__slug=category)
        return queryset

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response.data["categories"] = [
            {"name": c.name, "slug": c.slug} for c in BlogCategory.objects.all()
        ]
        featured = (
            BlogPost.objects.published()
            .filter(is_featured=True)
            .select_related("category", "author")
            .first()
        )
        response.data["featured"] = (
            BlogPostListSerializer(featured, context=self.get_serializer_context()).data
            if featured
            else None
        )
        return response


class BlogDetailView(generics.RetrieveAPIView):
    serializer_class = BlogPostDetailSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    lookup_field = "slug"

    def get_queryset(self):
        return (
            BlogPost.objects.published()
            .select_related("category", "author")
            .prefetch_related("content_blocks")
        )


class CaseStudyListView(generics.ListAPIView):
    serializer_class = CaseStudyListSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

    def get_queryset(self):
        queryset = CaseStudy.objects.published().select_related("category")
        category = self.request.query_params.get("category")
        if category and category != "all":
            queryset = queryset.filter(category__slug=category)
        return queryset

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response.data["categories"] = [
            {"name": c.name, "slug": c.slug} for c in CaseStudyCategory.objects.all()
        ]
        featured = (
            CaseStudy.objects.published()
            .filter(is_featured=True)
            .select_related("category")
            .first()
        )
        response.data["featured"] = (
            CaseStudyListSerializer(featured, context=self.get_serializer_context()).data
            if featured
            else None
        )
        return response


class CaseStudyDetailView(generics.RetrieveAPIView):
    serializer_class = CaseStudyDetailSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    lookup_field = "slug"

    def get_queryset(self):
        return CaseStudy.objects.published().select_related("category").prefetch_related("gallery")


class CareersView(PublicAPIView):
    def get(self, request):
        return Response(
            {
                "perks": PerkSerializer(Perk.objects.all(), many=True).data,
                "departments": [d.name for d in Department.objects.all()],
                "jobs": JobPostingSerializer(
                    JobPosting.objects.published().select_related("department"), many=True
                ).data,
            }
        )


class ContactView(PublicAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "contact"

    def get(self, request):
        return Response(
            {
                "methods": ContactMethodSerializer(ContactMethod.objects.all(), many=True).data,
                "topics": [t.label for t in ContactTopic.objects.all()],
            }
        )

    def post(self, request):
        serializer = ContactSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"status": "sent"}, status=status.HTTP_201_CREATED)


class PolicyView(generics.RetrieveAPIView):
    serializer_class = PolicyPageSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    lookup_field = "slug"
    queryset = PolicyPage.objects.prefetch_related("sections")


class InspirationListView(generics.ListAPIView):
    serializer_class = InspirationItemSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

    def get_queryset(self):
        queryset = InspirationItem.objects.published()
        tag = self.request.query_params.get("tag")
        style = self.request.query_params.get("style")
        if tag and tag != "all":
            queryset = queryset.filter(tag__iexact=tag)
        if style and style != "all":
            queryset = queryset.filter(style__iexact=style)
        sort = self.request.query_params.get("sort")
        if sort == "popular":
            queryset = queryset.order_by("-likes_count")
        return queryset


class InspirationLikeView(APIView):
    """POST toggles a like; works for signed-in users and anonymous sessions."""

    permission_classes = [AllowAny]

    def post(self, request, pk):
        try:
            item = InspirationItem.objects.get(pk=pk)
        except InspirationItem.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if request.user.is_authenticated:
            like, created = InspirationLike.objects.get_or_create(item=item, user=request.user)
        else:
            if not request.session.session_key:
                request.session.save()
            like, created = InspirationLike.objects.get_or_create(
                item=item, user=None, session_key=request.session.session_key
            )

        if created:
            InspirationItem.objects.filter(pk=pk).update(likes_count=F("likes_count") + 1)
            liked = True
        else:
            like.delete()
            InspirationItem.objects.filter(pk=pk).update(likes_count=F("likes_count") - 1)
            liked = False

        item.refresh_from_db(fields=["likes_count"])
        return Response({"liked": liked, "likes_count": item.likes_count})


class NewsletterView(PublicAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "newsletter"

    def post(self, request):
        serializer = NewsletterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"status": "subscribed"}, status=status.HTTP_201_CREATED)
