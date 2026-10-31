#!/bin/sh
set -e

# Migrations are safe to run repeatedly. For multi-replica deployments run
# them as a separate release job and set RUN_MIGRATIONS=0 on the web service.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi

exec gunicorn uems_config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${GUNICORN_WORKERS:-3}" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  --access-logfile - \
  --error-logfile -
