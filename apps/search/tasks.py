from celery import shared_task


@shared_task
def rebuild_search_index():
    from .services import rebuild_index

    return rebuild_index()
