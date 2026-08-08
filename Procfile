web: python migrate.py && gunicorn app:app --workers 3 --timeout 60
worker: rq worker --url $REDIS_URL default mail
