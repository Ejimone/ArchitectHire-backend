from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PublishableQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=PublishableModel.Status.PUBLISHED)


class PublishableModel(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PUBLISHED)
    published_at = models.DateTimeField(null=True, blank=True)

    objects = PublishableQuerySet.as_manager()

    class Meta:
        abstract = True

    def publish(self):
        self.status = self.Status.PUBLISHED
        self.published_at = timezone.now()
        self.save(update_fields=["status", "published_at"])


class OrderableModel(models.Model):
    sort_order = models.PositiveIntegerField(default=0, db_index=True)

    class Meta:
        abstract = True
        ordering = ["sort_order", "id"]
