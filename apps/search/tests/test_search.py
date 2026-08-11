"""Search index model strings and the rebuild task."""

import pytest
from django.core.management import call_command

from apps.search.models import PopularSearch, SearchIndexEntry
from apps.search.tasks import rebuild_search_index


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions,catalog")


def test_search_index_entry_str():
    assert str(SearchIndexEntry(category="Services", title="CAD drafting")) == (
        "Services: CAD drafting"
    )


def test_popular_search_str():
    assert str(PopularSearch(term="ADU permit")) == "ADU permit"


@pytest.mark.django_db
def test_rebuild_task_repopulates_the_index(seeded):
    SearchIndexEntry.objects.all().delete()
    count = rebuild_search_index()
    assert count == SearchIndexEntry.objects.count() > 0
