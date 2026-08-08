import os
from openai import OpenAI

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY', ''))
    return _client


def generate_horoscope(user, reading_type):
    birth_date  = user.birth_date.strftime('%B %d, %Y') if user.birth_date else 'unknown'
    birth_time  = user.birth_time.strftime('%H:%M') if user.birth_time else 'unknown'
    birth_place = user.birth_place or 'unknown'

    system_prompt = (
        "You are a professional astrologer with deep knowledge of Western astrology, "
        "natal charts, planetary transits, and horoscope interpretation. "
        "Write personalized, insightful, and eloquent horoscope readings."
    )

    user_prompt = (
        f"Please write a detailed personalized horoscope reading for someone born on "
        f"{birth_date} at {birth_time} in {birth_place}.\n\n"
        f"Reading type: {reading_type.name}\n"
        f"Description: {reading_type.description or 'General natal chart reading'}\n\n"
        "Include: sun sign analysis, key personality traits, current planetary influences, "
        "advice for the coming period, and areas of life to focus on. "
        "Write in an engaging, personal tone. Length: 400-600 words."
    )

    model = os.environ.get('AI_MODEL', 'gpt-4o-mini')
    client = _get_client()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': user_prompt},
        ],
        max_tokens=1000,
        temperature=0.8,
    )

    text = response.choices[0].message.content
    usage = {
        'input_tokens':  response.usage.prompt_tokens,
        'output_tokens': response.usage.completion_tokens,
        'model':         model,
    }
    return {'text': text, 'usage': usage}
