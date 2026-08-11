import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import current_user
from extensions import limiter

public_bp = Blueprint('public', __name__)


@public_bp.route('/')
def landing():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('public/landing.html')


@public_bp.route('/pricing')
def pricing():
    return render_template('public/pricing.html')


@public_bp.route('/privacy')
def privacy():
    return render_template('public/legal.html', title='Privacy Policy', body='Privacy policy coming soon.')


@public_bp.route('/terms')
def terms():
    return render_template('public/legal.html', title='Terms of Service', body='Terms of service coming soon.')


@public_bp.route('/refunds')
def refunds():
    return render_template('public/legal.html', title='Refund Policy', body='Refund policy coming soon.')


@public_bp.route('/chart', methods=['GET', 'POST'])
@limiter.limit("200 per hour")
def chart():
    result     = None
    error      = None
    form_data  = {}

    if request.method == 'POST':
        birth_date_str  = request.form.get('birth_date', '').strip()
        birth_time_str  = request.form.get('birth_time', '').strip()
        birth_place     = request.form.get('birth_place', '').strip()
        birth_lat_str   = request.form.get('birth_lat', '').strip()
        birth_lng_str   = request.form.get('birth_lng', '').strip()

        try:
            birth_lat = float(birth_lat_str) if birth_lat_str else None
            birth_lng = float(birth_lng_str) if birth_lng_str else None
        except ValueError:
            birth_lat = birth_lng = None

        form_data = {
            'birth_date': birth_date_str, 'birth_time': birth_time_str,
            'birth_place': birth_place, 'birth_lat': birth_lat_str, 'birth_lng': birth_lng_str,
        }

        if not birth_date_str or not birth_time_str or not birth_place:
            error = 'All fields are required.'
        else:
            try:
                birth_date = datetime.date.fromisoformat(birth_date_str)
                h, m       = birth_time_str.split(':')
                birth_time = datetime.time(int(h), int(m))
            except (ValueError, AttributeError):
                error = 'Invalid date or time format.'
                birth_date = birth_time = None

            if not error:
                try:
                    from ai import compute_chart
                    result = compute_chart(birth_date, birth_time, birth_place,
                                          lat=birth_lat, lng=birth_lng)
                    result['birth_place'] = birth_place
                    result['birth_date']  = birth_date
                    result['birth_time']  = birth_time

                    # Store in session so logged-in users can save it as a profile
                    session['chart_prefill'] = {
                        'birth_date':  birth_date_str,
                        'birth_time':  birth_time_str,
                        'birth_place': birth_place,
                        'birth_lat':   birth_lat_str,
                        'birth_lng':   birth_lng_str,
                    }
                except Exception as e:
                    error = f'Could not compute chart: {str(e)}'

    return render_template('public/chart.html', result=result, error=error, form_data=form_data)
