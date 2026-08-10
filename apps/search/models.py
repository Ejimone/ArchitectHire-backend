from django.db import models

from apps.core.models import OrderableModel, TimeStampedModel


class SearchIndexEntry(TimeStampedModel):
    """Server-generated site search index (design: Search.dc.html's 40+ entry INDEX)."""

    class Category(models.TextChoices):
        SERVICES = "Services", "Services"
        PROJECT_TYPES = "Project types", "Project types"
        CITIES = "Cities", "Cities"
        GUIDES = "Guides", "Guides"
        CASE_STUDIES = "Case studies", "Case studies"
        PAGES = "Pages", "Pages"

    category = models.CharField(max_length=20, choices=Category.choices)
    title = models.CharField(max_length=160)
    subtitle = models.CharField(max_length=255, blank=True)
    href = models.CharField(max_length=255)
    keywords = models.TextField(blank=True)

    class Meta:
        ordering = ["category", "title"]
        verbose_name_plural = "search index entries"

    def __str__(self):
        return f"{self.category}: {self.title}"


class PopularSearch(OrderableModel, TimeStampedModel):
    term = models.CharField(max_length=80, unique=True)
    href = models.CharField(max_length=255, blank=True)

    class Meta(OrderableModel.Meta):
        verbose_name_plural = "popular searches"

    def __str__(self):
        return self.term
