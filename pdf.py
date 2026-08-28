"""Standalone PDF generation for readings.

Called by the worker at reading-creation time so the web instance
only needs to serve pre-built bytes.
"""
import io
import logging
import os
import re
import unicodedata

log = logging.getLogger(__name__)

_UNICODE_MAP = str.maketrans({
    '\u2019': "'", '\u2018': "'",
    '\u201c': '"', '\u201d': '"',
    '\u2032': "'", '\u2033': '"',
    '\u2014': '-', '\u2013': '-',
    '\u2026': '...',
    '\u2022': '-', '\u00b7': '.',
    '\u2605': '*', '\u2606': '*',
    '\u2726': '*', '\u2727': '*',
    '\u00d7': 'x',
})


def _s(text):
    text = unicodedata.normalize('NFC', text)
    return text.translate(_UNICODE_MAP).encode('latin-1', errors='replace').decode('latin-1')


_HOUSE_DESC = {
    1:  "Identidad, apariencia y la forma en que te presentas al mundo.",
    2:  "Recursos materiales, valores personales y autoestima.",
    3:  "Comunicación, mente analítica, hermanos y entorno cercano.",
    4:  "Hogar, familia, raíces y base emocional.",
    5:  "Creatividad, romance, hijos y expresión personal.",
    6:  "Salud, rutina diaria, servicio y trabajo cotidiano.",
    7:  "Relaciones íntimas, asociaciones y el otro en tu vida.",
    8:  "Transformación, sexualidad, herencias y los misterios de la vida.",
    9:  "Filosofía, viajes, educación superior y búsqueda de sentido.",
    10: "Carrera, reputación pública y vocación de vida.",
    11: "Amistades, comunidad, ideales y esperanzas futuras.",
    12: "Inconsciente, espiritualidad, retiro y lo que está oculto.",
}

_HOUSE_TITLE = {
    1:  'Identidad, Cuerpo y Presencia',
    2:  'Recursos, Dinero y Valores',
    3:  'Comunicación, Mente y Hermanos',
    4:  'Hogar, Familia y Raíces',
    5:  'Creatividad, Romance e Hijos',
    6:  'Salud, Trabajo y Rutina',
    7:  'Pareja, Relaciones y Asociaciones',
    8:  'Sexualidad, Transformación y Recursos Compartidos',
    9:  'Filosofía, Viajes y Espiritualidad',
    10: 'Carrera, Reputación y Vocación',
    11: 'Amigos, Comunidad e Ideales',
    12: 'Inconsciente, Karma y Retiro',
}

# Modern rulers (keyed on full Spanish sign name from _SIGNS_ES in ai.py)
_SIGN_RULER = {
    'Aries': 'Mars', 'Tauro': 'Venus', 'Géminis': 'Mercury', 'Cáncer': 'Moon',
    'Leo': 'Sun', 'Virgo': 'Mercury', 'Libra': 'Venus', 'Escorpio': 'Pluto',
    'Sagitario': 'Jupiter', 'Capricornio': 'Saturn', 'Acuario': 'Uranus', 'Piscis': 'Neptune',
}

# Short names without Spanish articles for compact card display
_PLANET_CARD = {
    'Sun': 'Sol', 'Moon': 'Luna', 'Mercury': 'Mercurio',
    'Venus': 'Venus', 'Mars': 'Marte', 'Jupiter': 'Júpiter',
    'Saturn': 'Saturno', 'Uranus': 'Urano', 'Neptune': 'Neptuno',
    'Pluto': 'Plutón', 'North_Node': 'Nodo Norte', 'South_Node': 'Nodo Sur',
    'Chiron': 'Quirón',
}


def generate_reading_pdf(reading, static_dir, chart_png=None):
    """
    Build the PDF for a reading and return bytes.

    Args:
        reading:    Reading ORM object (needs .content, .reading_type,
                    .profile, .created_at)
        static_dir: absolute path to the app's static/ folder (for logos)
        chart_png:  PNG bytes for the cover chart (optional)

    Returns:
        bytes — the PDF
    """
    from fpdf import FPDF

    _logo_path        = os.path.join(static_dir, 'logo.png')
    _has_logo         = os.path.exists(_logo_path)
    _logo_purple_path = os.path.join(static_dir, 'logopurple.png')
    _has_logo_purple  = os.path.exists(_logo_purple_path)

    # ── document metadata ──────────────────────────────────────────
    doc_title     = _s(reading.reading_type.name)
    _meta_parts   = []
    if reading.profile:
        _lbl = reading.profile.name
        if reading.profile.is_self:
            _lbl += ' (tu)'
        _meta_parts.append(_lbl)
    _profile_label = _s('  |  '.join(_meta_parts))

    _birth_lines = []
    if reading.profile:
        _p = reading.profile
        _bdate = _p.birth_date.strftime('%d/%m/%Y') if _p.birth_date else None
        _btime = _p.birth_time.strftime('%H:%M')    if _p.birth_time else None
        if _bdate and _btime:
            _birth_lines.append(_s(f'{_bdate}  {_btime}h'))
        elif _bdate:
            _birth_lines.append(_s(_bdate))
        if _p.birth_place:
            _birth_lines.append(_s(_p.birth_place))

    # ── colour palette ─────────────────────────────────────────────
    C_COVER_BG = (15, 6, 35)
    C_PURPLE   = (53, 15, 76)
    C_GOLD     = (212, 175, 55)
    C_TEXT     = (28, 22, 38)
    C_HEADING  = (53, 15, 76)
    C_MUTED    = (120, 105, 140)

    # ── house descriptions (latin-1 safe) ──────────────────────────
    _hd = {k: _s(v) for k, v in _HOUSE_DESC.items()}

    # ── table of contents ──────────────────────────────────────────
    _toc_entries = []
    for _ln in reading.content.split('\n'):
        if _ln.strip().startswith('#'):
            _t = _ln.strip().lstrip('#').strip()
            _hm_t = re.match(r'Casa\s+(\d+)', _t)
            if _hm_t:
                _d = _hd.get(int(_hm_t.group(1)))
                _t = f'{_t}: {_d}' if _d else _t
            _toc_entries.append(_s(_t))

    class _PDF(FPDF):
        def header(self):
            if self.page_no() == 1:
                self.set_fill_color(*C_COVER_BG)
                self.rect(0, 0, 210, 297, 'F')
                if _has_logo:
                    self.image(_logo_path, x=16, y=14, w=80)
                self.set_font('Helvetica', 'B', 9)
                self.set_text_color(255, 255, 255)
                self.set_xy(100, 16)
                self.cell(94, 5, doc_title, align='R', ln=1)
                self.set_font('Helvetica', '', 8)
                self.set_text_color(255, 255, 255)
                self.set_x(100)
                self.cell(94, 5, _profile_label, align='R', ln=1)
                self.set_font('Helvetica', '', 7.5)
                self.set_text_color(255, 255, 255)
                for _bl in _birth_lines:
                    self.set_x(100)
                    self.cell(94, 4.5, _bl, align='R', ln=1)
                self.set_draw_color(*C_GOLD)
                self.set_line_width(0.4)
                self.line(0, 52, 210, 52)
                if chart_png:
                    _cw = 228
                    _cx = (210 - _cw) / 2 + _cw * 0.125
                    _w_px = int.from_bytes(chart_png[16:20], 'big')
                    _h_px = int.from_bytes(chart_png[20:24], 'big')
                    _ch = _cw * _h_px / _w_px
                    _cy = 52 + (297 - 52 - _ch) / 2
                    self.image(io.BytesIO(chart_png), x=_cx, y=_cy, w=_cw)
                self.set_y(300)
            else:
                self.set_draw_color(*C_GOLD)
                self.set_line_width(0.25)
                self.line(16, 13, 194, 13)
                self.set_y(18)

        def footer(self):
            if self.page_no() == 1:
                return
            self.set_draw_color(*C_GOLD)
            self.set_line_width(0.25)
            self.line(16, 275, 194, 275)
            if _has_logo_purple:
                self.image(_logo_purple_path, x=16, y=279, w=44)
            self.set_xy(70, 279)
            self.set_font('Helvetica', '', 7.5)
            self.set_text_color(*C_MUTED)
            self.cell(70, 10, str(self.page_no()), align='C')
            self.set_xy(140, 279)
            self.set_font('Helvetica', '', 7)
            self.cell(54, 10, doc_title, align='R')

    # ── chart data from reading.params ────────────────────────────
    _params    = reading.params or {}
    _positions = _params.get('positions', {})
    _elementos = _params.get('elementos', {})
    _modalidades = _params.get('modalidades', {})
    _aspectos  = _params.get('aspectos', [])
    _casa_cusps = {int(k): v for k, v in (_params.get('cusps') or {}).items()}

    # ── planet order for Ficha Técnica ─────────────────────────────
    _PLANET_ORDER = [
        'Sun', 'Moon', 'Mercury', 'Venus', 'Mars',
        'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto',
        'Chiron', 'North_Node', 'South_Node', 'Ascendant', 'MC',
    ]

    # ── element / modality colours (RGB) ──────────────────────────
    _EL_COLOR  = {'fuego': (200, 60, 40), 'tierra': (130, 100, 60),
                  'aire': (80, 160, 200), 'agua': (50, 100, 180)}
    _MOD_COLOR = {'cardinal': (150, 50, 150), 'fijo': (50, 130, 80),
                  'mutable': (200, 140, 30)}

    # ── aspect type colours ────────────────────────────────────────
    _ASP_COLOR = {
        'conjunción': C_HEADING, 'trígono': (40, 140, 80),
        'sextil': (60, 160, 120), 'cuadratura': (180, 50, 50),
        'oposición': (180, 80, 30),
    }

    def _section_header(title, *, new_page=True):
        if new_page:
            pdf.add_page()
        pdf.set_font('Helvetica', 'B', 15)
        pdf.set_text_color(*C_HEADING)
        pdf.ln(4)
        pdf.cell(0, 9, _s(title), ln=1)
        _y = pdf.get_y()
        pdf.set_draw_color(*C_GOLD)
        pdf.set_line_width(0.35)
        pdf.line(16, _y, 194, _y)
        pdf.ln(6)

    _ANGLES = {'Ascendant', 'MC', 'Medium_Coeli', 'Descendant', 'Imum_Coeli'}

    def _render_casa_card(casa_num):
        pdf.add_page()
        cusp_sign = _casa_cusps.get(casa_num, '')
        # Planets in this house (exclude chart angles)
        planets_here = []
        for _pk, _pp in _positions.items():
            if _pp.get('casa') == casa_num and _pk not in _ANGLES:
                _deg = _pp.get('grado', '').split()[0] if _pp.get('grado') else ''
                _pname = _s(_PLANET_CARD.get(_pk, _pp.get('planeta_es', _pk)))
                planets_here.append(f'{_pname} ({_s(_deg)})' if _deg else _pname)
        # Ruler of cusp sign
        ruler_txt = ''
        _rkey = _SIGN_RULER.get(cusp_sign, '')
        if _rkey:
            _rp    = _positions.get(_rkey, {})
            _rname = _s(_PLANET_CARD.get(_rkey, _rkey))
            _rdig  = _s(_rp.get('dignidad', '') or '')
            _rcasa = _rp.get('casa')
            ruler_txt = _rname
            if _rdig:
                ruler_txt += f' ({_rdig})'
            if _rcasa:
                ruler_txt += f' -- Casa {_rcasa}'
        rows = []
        if cusp_sign:
            rows.append(('Signo en Cuspide', _s(cusp_sign)))
        rows.append(('Planetas Presentes',
                     ', '.join(planets_here) if planets_here else '(ninguno)'))
        if ruler_txt:
            rows.append(('Regente de la Casa', ruler_txt))
        if _hd.get(casa_num):
            rows.append(('Foco Principal', _hd[casa_num]))
        # Header — same dark style as Síntesis Evolutiva
        _title = _s(f'Casa {casa_num}: {_HOUSE_TITLE.get(casa_num, "")}')
        _y0 = pdf.get_y()
        pdf.set_fill_color(*C_COVER_BG)
        pdf.rect(16, _y0, 178, 16, 'F')
        pdf.set_font('Helvetica', 'B', 13)
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(16, _y0 + 4)
        pdf.cell(178, 8, _title, align='C', ln=1)
        pdf.ln(10)
        # Info rows — centered, small muted label above normal value
        for _lbl, _val in rows:
            pdf.set_x(16)
            pdf.set_font('Helvetica', 'B', 7.5)
            pdf.set_text_color(*C_MUTED)
            pdf.cell(178, 5, _s(_lbl.upper()), align='C', ln=1)
            pdf.set_x(16)
            pdf.set_font('Helvetica', '', 10.5)
            pdf.set_text_color(*C_TEXT)
            pdf.multi_cell(178, 5.5, _val, align='C')
            pdf.ln(4)
        # Gold rule before body text
        pdf.ln(2)
        _y = pdf.get_y()
        pdf.set_draw_color(*C_GOLD)
        pdf.set_line_width(0.35)
        pdf.line(16, _y, 194, _y)
        pdf.ln(6)
        pdf.set_font('Helvetica', '', 10.5)
        pdf.set_text_color(*C_TEXT)

    pdf = _PDF(orientation='P', unit='mm', format='A4')
    pdf.set_margins(16, 10, 16)
    pdf.set_auto_page_break(auto=True, margin=24)

    # ── Page 1: cover ─────────────────────────────────────────────
    pdf.add_page()

    # ── Page 2: Ficha Técnica ─────────────────────────────────────
    if _positions:
        _section_header('Ficha Técnica')

        # Table header
        _cols = [38, 32, 16, 46, 10, 32]  # widths mm
        _hdrs = ['Planeta', 'Signo', 'Casa', 'Grado', 'R', 'Dignidad']
        pdf.set_fill_color(*C_HEADING)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Helvetica', 'B', 8)
        for _w, _h in zip(_cols, _hdrs):
            pdf.cell(_w, 6, _h, border=0, align='C', fill=True)
        pdf.ln()

        # Table rows
        _row_alt = False
        for _pname in _PLANET_ORDER:
            _p = _positions.get(_pname)
            if not _p:
                continue
            _row_alt = not _row_alt
            if _row_alt:
                pdf.set_fill_color(240, 236, 248)
            else:
                pdf.set_fill_color(255, 255, 255)
            pdf.set_text_color(*C_TEXT)
            pdf.set_font('Helvetica', 'B' if _pname in ('Sun', 'Moon', 'Ascendant') else '', 8)
            _vals = [
                _s(_p.get('planeta_es', _pname)),
                _s(_p.get('signo', '')),
                str(_p.get('casa', '')),
                _s(_p.get('grado', '')),
                'R' if _p.get('retrogrado') else '',
                _s(_p.get('dignidad', '') or ''),
            ]
            for _w, _v in zip(_cols, _vals):
                pdf.cell(_w, 5.5, _v, border=0, align='C', fill=True)
            pdf.ln()

        pdf.ln(8)

        # ── Elements & Modalities side by side ────────────────────
        if _elementos or _modalidades:
            _bx = 16     # left x
            _mid = 110   # mid x for modalities
            _bar_max = 70
            _total_el  = sum(_elementos.values())  or 1
            _total_mod = sum(_modalidades.values()) or 1

            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(*C_HEADING)
            pdf.set_x(_bx)
            pdf.cell(80, 6, _s('Elementos'), ln=0)
            pdf.set_x(_mid)
            pdf.cell(80, 6, _s('Modalidades'), ln=1)
            pdf.ln(1)

            _el_items  = list(_elementos.items())
            _mod_items = list(_modalidades.items())
            _nrows = max(len(_el_items), len(_mod_items))

            for _i in range(_nrows):
                _y0 = pdf.get_y()

                # Element bar
                if _i < len(_el_items):
                    _el_name, _el_cnt = _el_items[_i]
                    _bw = _bar_max * _el_cnt / _total_el
                    _col = _EL_COLOR.get(_el_name, C_MUTED)
                    pdf.set_fill_color(*_col)
                    pdf.rect(_bx, _y0 + 1, _bw, 4, 'F')
                    pdf.set_xy(_bx + _bw + 2, _y0)
                    pdf.set_font('Helvetica', '', 7.5)
                    pdf.set_text_color(*C_TEXT)
                    pdf.cell(30, 6, _s(f'{_el_name.capitalize()} {round(100*_el_cnt/_total_el)}%'))

                # Modality bar
                if _i < len(_mod_items):
                    _mod_name, _mod_cnt = _mod_items[_i]
                    _bw = _bar_max * _mod_cnt / _total_mod
                    _col = _MOD_COLOR.get(_mod_name, C_MUTED)
                    pdf.set_fill_color(*_col)
                    pdf.rect(_mid, _y0 + 1, _bw, 4, 'F')
                    pdf.set_xy(_mid + _bw + 2, _y0)
                    pdf.set_font('Helvetica', '', 7.5)
                    pdf.set_text_color(*C_TEXT)
                    pdf.cell(30, 6, _s(f'{_mod_name.capitalize()} {round(100*_mod_cnt/_total_mod)}%'))

                pdf.set_y(_y0 + 7)

        # ── Top aspects ───────────────────────────────────────────
        if _aspectos:
            pdf.ln(6)
            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(*C_HEADING)
            pdf.cell(0, 6, _s('Aspectos principales'), ln=1)
            _ay = pdf.get_y()
            pdf.set_draw_color(*C_GOLD)
            pdf.set_line_width(0.25)
            pdf.line(16, _ay, 194, _ay)
            pdf.ln(3)

            _asp_shown = [a for a in _aspectos if a.get('tier', 9) <= 2][:10]
            _acols = [42, 28, 42, 62]  # Planeta A | Aspecto | Planeta B | Casas
            _ahdrs = ['Planeta A', 'Aspecto', 'Planeta B', 'Casas']
            pdf.set_fill_color(*C_HEADING)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font('Helvetica', 'B', 7.5)
            for _w, _h in zip(_acols, _ahdrs):
                pdf.cell(_w, 5.5, _h, border=0, align='C', fill=True)
            pdf.ln()

            _arow_alt = False
            for _asp in _asp_shown:
                _arow_alt = not _arow_alt
                pdf.set_fill_color(240, 236, 248) if _arow_alt else pdf.set_fill_color(255, 255, 255)
                pdf.set_text_color(*C_TEXT)
                pdf.set_font('Helvetica', '', 7.5)
                _asp_name = _asp.get('aspecto', '')
                _asp_col  = _ASP_COLOR.get(_asp_name, C_TEXT)
                _casa_txt = ''
                if _asp.get('casa_a') and _asp.get('casa_b'):
                    _casa_txt = _s(f"Casa {_asp['casa_a']} — Casa {_asp['casa_b']}")
                pdf.cell(_acols[0], 5, _s(_asp.get('a_es', '')), border=0, align='C', fill=True)
                pdf.set_text_color(*_asp_col)
                pdf.cell(_acols[1], 5, _s(_asp_name), border=0, align='C', fill=True)
                pdf.set_text_color(*C_TEXT)
                pdf.cell(_acols[2], 5, _s(_asp.get('b_es', '')), border=0, align='C', fill=True)
                pdf.cell(_acols[3], 5, _casa_txt, border=0, align='C', fill=True)
                pdf.ln()

    # ── Page 3: Table of contents ──────────────────────────────────
    _section_header('Índice de contenidos')
    for _i, _entry in enumerate(_toc_entries, 1):
        pdf.set_font('Helvetica', 'B', 8.5)
        pdf.set_text_color(*C_MUTED)
        pdf.set_x(16)
        pdf.cell(10, 7, f'{_i}.', align='R')
        pdf.set_font('Helvetica', '', 10)
        pdf.set_text_color(*C_TEXT)
        pdf.set_x(28)
        pdf.multi_cell(166, 7, _entry)

    # ── Page 4+: body ─────────────────────────────────────────────
    pdf.add_page()
    pdf.set_font('Helvetica', '', 10.5)
    pdf.set_text_color(*C_TEXT)

    for line in reading.content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('#'):
            text = stripped.lstrip('#').strip()
            _is_synthesis = 'ntesis' in text  # Síntesis Evolutiva
            if _is_synthesis:
                # Styled break for synthesis conclusion
                pdf.add_page()
                pdf.set_fill_color(*C_COVER_BG)
                pdf.rect(16, pdf.get_y(), 178, 14, 'F')
                pdf.set_font('Helvetica', 'B', 13)
                pdf.set_text_color(255, 255, 255)
                pdf.set_xy(16, pdf.get_y() + 3)
                pdf.cell(178, 8, _s(text), align='C', ln=1)
                pdf.ln(4)
                pdf.set_font('Helvetica', '', 10.5)
                pdf.set_text_color(*C_TEXT)
                continue
            _hm = re.match(r'Casa\s+(\d+)', text)
            if _hm and _casa_cusps:
                _render_casa_card(int(_hm.group(1)))
                continue
            pdf.ln(5)
            pdf.set_font('Helvetica', 'B', 12)
            pdf.set_text_color(*C_HEADING)
            if _hm:
                _hdesc = _hd.get(int(_hm.group(1)))
                _heading_text = _s(f'{text}: {_hdesc}') if _hdesc else _s(text)
            else:
                _heading_text = _s(text)
            pdf.multi_cell(0, 7, _heading_text)
            _y = pdf.get_y()
            pdf.set_draw_color(*C_GOLD)
            pdf.set_line_width(0.3)
            pdf.line(16, _y, 194, _y)
            pdf.ln(2)
            pdf.set_font('Helvetica', '', 10.5)
            pdf.set_text_color(*C_TEXT)
        elif stripped and stripped.isupper() and len(stripped) > 4:
            pdf.ln(5)
            pdf.set_font('Helvetica', 'B', 11)
            pdf.set_text_color(*C_HEADING)
            pdf.multi_cell(0, 7, _s(stripped))
            pdf.ln(1)
            pdf.set_font('Helvetica', '', 10.5)
            pdf.set_text_color(*C_TEXT)
        elif stripped == '':
            pdf.ln(3)
        else:
            pdf.set_font('Helvetica', '', 10.5)
            pdf.set_text_color(*C_TEXT)
            pdf.multi_cell(0, 6, _s(line))

    return bytes(pdf.output())
