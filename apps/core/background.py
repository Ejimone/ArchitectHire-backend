"""Run fire-and-forget work off the request thread, without requiring a Celery worker.

The deployment has no worker component, so `task.delay()` succeeds (the broker is up,
it is the same Redis that backs the cache) and the task then sits in the queue forever.
Nothing raises, nothing logs, and the work silently never happens — that is how every
notification and every frontend cache purge went missing in production.

This module is the replacement. Work is submitted to a small thread pool owned by the
web process, so it runs whether or not a worker exists. Celery stays available as an
opt-in accelerator (see ``NOTIFY_VIA_CELERY``), not as a prerequisite.

Two design points worth keeping:

* **ThreadPoolExecutor, not ``Thread(daemon=True)``.** Pool threads are non-daemon and
  CPython registers an atexit hook that drains the queue and joins them, so a gunicorn
  worker recycle finishes in-flight jobs instead of killing them mid-send. That only
  holds if every job terminates, hence the hard network timeouts on the callers
  (``EMAIL_TIMEOUT``, the webpush timeout, ``urlopen(timeout=...)``).
* **Separate pools.** The revalidate flush deliberately sleeps for its debounce window.
  Sharing one pool would let that sleep starve a user-facing notification.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import connections, transaction

logger = logging.getLogger(__name__)

# Sized *from* the psycopg pool, not guessed against it. Every job here opens a database
# connection, so this width and `DB_POOL_MAX` are one number in two places — and they had
# already drifted apart: this was a flat 4 justified by a comment claiming max_size=20,
# while the real default fell to 3. Four notify threads against a pool of three means the
# background work can hold every connection a worker has and the request thread waits out
# `timeout` for one, which reads as an unexplained 10-second stall.
#
# Leaving one connection for the request thread is the whole rule; the `max(1, ...)`
# only guards a deployment that pins DB_POOL_MAX to 1.
NOTIFY_POOL = ThreadPoolExecutor(
    max_workers=max(1, settings.DATABASES["default"]["OPTIONS"]["pool"]["max_size"] - 1),
    thread_name_prefix="ah-notify",
)
# Serial: the flush sleeps through the debounce window and one purge at a time is
# exactly what we want anyway.
REVALIDATE_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ah-revalidate")


def _guarded(name, fn, *args, **kwargs):
    """Run `fn`, swallowing (but reporting) failures so one bad job can't kill a pool thread."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        # logger.exception is enough to reach Sentry — its default LoggingIntegration
        # promotes ERROR-level records to events, so no explicit capture call is needed.
        logger.exception("Background job %s failed", name)
        return None


def _guarded_on_pool_thread(name, fn, *args, **kwargs):
    """`_guarded`, plus hand the thread's DB connection back when the job finishes.

    Only ever the pool's entry point, never the inline path: `close_all()` acts on the
    *calling* thread, so running it inline would close the connection the caller (a
    request, or a TestCase's wrapping transaction) is still using.
    """
    try:
        return _guarded(name, fn, *args, **kwargs)
    finally:
        # CONN_MAX_AGE=0 relies on the `request_finished` signal to close connections,
        # and that signal never fires for a background thread — so without this, each
        # pool thread parks a psycopg pool slot for the life of the process.
        connections.close_all()


def run_in_background(pool, name, fn, *args, **kwargs) -> None:
    """Submit `fn` to `pool`. Runs inline when eager (tests) or if the pool is shut down."""
    if getattr(settings, "BACKGROUND_TASKS_EAGER", False):
        _guarded(name, fn, *args, **kwargs)
        return
    try:
        pool.submit(_guarded_on_pool_thread, name, fn, *args, **kwargs)
    except RuntimeError:
        # Interpreter is shutting down and the pool refuses new work. Inline is slower
        # but it is the difference between a delivered notification and a lost one.
        logger.warning("Pool closed; running %s inline", name)
        _guarded(name, fn, *args, **kwargs)


def post_commit_background(pool, name, fn, *args, **kwargs) -> None:
    """Submit `fn` once the current transaction commits.

    Outside a transaction (DRF views here are not atomic) `on_commit` fires immediately,
    so this is safe to use unconditionally. Inside one — the Django admin wraps every
    save in `atomic` — it is what stops a job reading the pre-commit snapshot.
    """
    transaction.on_commit(lambda: run_in_background(pool, name, fn, *args, **kwargs))
