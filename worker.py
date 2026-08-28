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
        job_timeout='15m',
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
        from models import Reading, User, Profile

        # 1. Read what we need
        reading = Reading.query.get(reading_id)
        if not reading:
            log.error("Reading %s not found", reading_id)
            return

        user         = User.query.get(reading.user_id)
        reading_type = reading.reading_type

        # Use profile if set, fall back to user's self profile
        if reading.profile_id:
            subject = Profile.query.get(reading.profile_id)
        else:
            subject = Profile.query.filter_by(user_id=reading.user_id, is_self=True).first() or user

        if not subject or not subject.birth_date:
            reading.status = 'failed'
            db.session.commit()
            return

        # Load second profile for synastry / davison
        params    = reading.params or {}
        profile_b = None
        if params.get('profile_id_b'):
            profile_b = Profile.query.get(params['profile_id_b'])

        # 2. Close DB connection before the long AI call
        db.session.close()

        # 3. Route to the correct generator
        try:
            from ai import generate_reading
            result = generate_reading(subject, reading_type,
                                      params=params, profile_b=profile_b)
        except Exception as e:
            log.error("AI generation failed for reading %s: %s", reading_id, e)
            reading = Reading.query.get(reading_id)
            reading.status = 'failed'
            db.session.commit()
            return

        # 4. Generate wheel PNG — kerykeion is done, collect before loading cairosvg
        import gc
        gc.collect()
        chart_png = None
        if result.get('chart_image'):
            try:
                from ai import _svg_to_wheel_png
                chart_png = _svg_to_wheel_png(result['chart_image'])
            except Exception as e:
                log.warning("PNG generation failed for reading %s: %s", reading_id, e)

        # 5. Merge chart data into reading.params for PDF use
        chart_data = {k: result[k] for k in ('positions', 'elementos', 'modalidades', 'aspectos', 'regente') if k in result}

        # 6. Generate PDF
        pdf_bytes = None
        try:
            from pdf import generate_reading_pdf
            reading_tmp = Reading.query.get(reading_id)
            reading_tmp.content     = result['text']
            reading_tmp.chart_image = result.get('chart_image')
            reading_tmp.params      = {**(reading_tmp.params or {}), **chart_data}
            static_dir = os.path.join(os.path.dirname(__file__), 'static')
            pdf_bytes = generate_reading_pdf(reading_tmp, static_dir, chart_png=chart_png)
        except Exception as e:
            log.warning("PDF generation failed for reading %s: %s", reading_id, e)

        # 7. Re-fetch and write
        reading = Reading.query.get(reading_id)
        reading.content      = result['text']
        reading.chart_image  = result.get('chart_image')
        reading.chart_png    = chart_png
        reading.pdf_content  = pdf_bytes
        reading.params       = {**(reading.params or {}), **chart_data}
        reading.status       = 'completed'
        reading.completed_at = datetime.utcnow()
        db.session.commit()

        # 6. Send by email
        try:
            from emails import send_reading_email
            with app.test_request_context('/'):
                send_reading_email(user, reading)
            reading = Reading.query.get(reading_id)
            reading.sent_by_email = True
            db.session.commit()
        except Exception as e:
            log.error("Failed to send reading email for reading %s: %s", reading_id, e)

        # 7. Notify user
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
    log.error("Job %s failed: %s", job.id, value)
