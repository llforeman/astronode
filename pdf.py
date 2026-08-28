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
    C_PURPLE   = (53, 15, 76)
    C_COVER_BG = (15, 6, 35)
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

    pdf = _PDF(orientation='P', unit='mm', format='A4')
    pdf.set_margins(16, 10, 16)
    pdf.set_auto_page_break(auto=True, margin=24)

    # Page 1: cover
    pdf.add_page()

    # Page 2: table of contents
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 15)
    pdf.set_text_color(*C_HEADING)
    pdf.ln(4)
    pdf.cell(0, 9, _s('Índice de contenidos'), ln=1)
    _ty = pdf.get_y()
    pdf.set_draw_color(*C_GOLD)
    pdf.set_line_width(0.35)
    pdf.line(16, _ty, 194, _ty)
    pdf.ln(6)
    for _i, _entry in enumerate(_toc_entries, 1):
        pdf.set_font('Helvetica', 'B', 8.5)
        pdf.set_text_color(*C_MUTED)
        pdf.set_x(16)
        pdf.cell(10, 7, f'{_i}.', align='R')
        pdf.set_font('Helvetica', '', 10)
        pdf.set_text_color(*C_TEXT)
        pdf.set_x(28)
        pdf.multi_cell(166, 7, _entry)

    # Page 3+: body
    pdf.add_page()
    pdf.set_font('Helvetica', '', 10.5)
    pdf.set_text_color(*C_TEXT)

    for line in reading.content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('#'):
            text = stripped.lstrip('#').strip()
            pdf.ln(5)
            pdf.set_font('Helvetica', 'B', 12)
            pdf.set_text_color(*C_HEADING)
            _hm = re.match(r'Casa\s+(\d+)', text)
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
