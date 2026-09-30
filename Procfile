web: python migrate.py && gunicorn app:app --workers 2 --threads 4 --timeout 60 --preload
worker: rq worker --url $REDIS_URL default mail
