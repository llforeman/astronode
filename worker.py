import logging
import os
from datetime import datetime

log = logging.getLogger(__name__)


def get_queue(name='default'):
    from rq import Queue
    from extensions import get_redis_client
    return Queue(name, connection=get_redis_client())


def enqueue_reading(reading_id):
    q = get_queue('default')
    job = q.enqueue(
        generate_reading_task,
        reading_id,
        job_timeout='5m',
        on_failure=job_failure_callback,
    )
    from app import create_app
    app = create_app()
    with app.app_context():
        from extensions import db
        from models import Reading
        reading = Reading.query.get(reading_id)
        if reading:
            reading.job_id = job.id
            reading.status = 'generating'
            db.session.commit()
    return job.id


def generate_reading_task(reading_id):
    from app import create_app
    app = create_app()

    with app.app_context():
        from extensions import db
        from models import Reading, User

        # 1. Read what we need
        reading      = Reading.query.get(reading_id)
        if not reading:
            log.error("Reading %s not found", reading_id)
            return

        user         = User.query.get(reading.user_id)
        reading_type = reading.reading_type

        if not user or not user.birth_date:
            reading.status = 'failed'
            db.session.commit()
            return

        # 2. Close DB connection before the long AI call
        db.session.close()

        # 3. Call the AI
        try:
            from ai import generate_horoscope
            result = generate_horoscope(user, reading_type)
        except Exception as e:
            log.error("AI generation failed for reading %s: %s", reading_id, e)
            reading = Reading.query.get(reading_id)
            reading.status = 'failed'
            db.session.commit()
            return

        # 4. Re-fetch and write
        reading = Reading.query.get(reading_id)
        reading.content      = result['text']
        reading.status       = 'completed'
        reading.completed_at = datetime.utcnow()
        db.session.commit()

        # 5. Send by email
        try:
            from emails import send_reading_email
            send_reading_email(user, reading)
            reading = Reading.query.get(reading_id)
            reading.sent_by_email = True
            db.session.commit()
        except Exception as e:
            log.error("Failed to send reading email for reading %s: %s", reading_id, e)

        # 6. Notify user
        from models import Notification
        notif = Notification(
            user_id=user.id,
            message='Your horoscope reading is ready!',
            link=f'/readings/{reading_id}',
        )
        db.session.add(notif)
        db.session.commit()

        return {'status': 'completed', 'reading_id': reading_id}


def job_failure_callback(job, connection, type, value, traceback):
    log.error("Job %s failed: %s", job.id, value, exc_info=(type, value, traceback))
