#!/bin/sh
# Apply migrations before the web server accepts traffic.
#
# Deploys here are a `git push`: a hook on the VM pulls, rebuilds the image and
# restarts the container. Nothing in that sequence ran `manage.py migrate`, so a
# push that carried a migration shipped the code and left the schema — and any
# data migration — behind. That is how a release of seeded photography reached
# production and changed nothing at all.
#
# Only the web container migrates. The celery worker and beat containers start
# from the same image with their own commands, and three processes racing the
# same migration is how you get "relation already exists" on a good day and a
# half-applied schema on a bad one. One writer, checked by the command it was
# asked to run.
#
# A failed migration must never take the site down. The database can be a second
# or two behind the web container on a cold boot, so this retries — and if it
# still cannot migrate, it says so loudly and starts the server anyway. Serving
# the previous release beats serving nothing while someone reads the logs.

set -e

case "$1" in
  gunicorn)
    n=1
    while [ "$n" -le 3 ]; do
      if python manage.py migrate --noinput; then
        break
      fi
      if [ "$n" -eq 3 ]; then
        echo "entrypoint: migrations failed after $n attempts — starting the server" \
             "anyway on the schema that is already there. Fix and redeploy." >&2
        break
      fi
      echo "entrypoint: migrate attempt $n failed, retrying in 3s" >&2
      n=$((n + 1))
      sleep 3
    done
    ;;
esac

exec "$@"
