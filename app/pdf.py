"""Salary slip PDF (ReportLab) — logo, blue theme, ₹ via bundled DejaVu font."""
import calendar
import os
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .utils import days

STATIC = os.path.join(os.path.dirname(__file__), "static")
LOGO = os.path.join(STATIC, "logo.png")

BLUE = colors.HexColor("#1e3a8a")
BLUE_LIGHT = colors.HexColor("#dbeafe")
BLUE_MID = colors.HexColor("#3b82f6")
ORANGE = colors.HexColor("#ea580c")
GREEN_BG = colors.HexColor("#dcfce7")
GREEN = colors.HexColor("#15803d")
GREY = colors.HexColor("#64748b")

_FONTS_READY = False


def _fonts():
    global _FONTS_READY
    if not _FONTS_READY:
        pdfmetrics.registerFont(TTFont("DejaVu", os.path.join(STATIC, "fonts", "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", os.path.join(STATIC, "fonts", "DejaVuSans-Bold.ttf")))
        for bold, italic, face in ((0, 0, "DejaVu"), (1, 0, "DejaVu-Bold"), (0, 1, "DejaVu"), (1, 1, "DejaVu-Bold")):
            addMapping("DejaVu", bold, italic, face)
        _FONTS_READY = True


def _rs(v):
    v = float(v or 0)
    s = f"{abs(v):,.2f}"
    # Indian grouping: 1,23,456.00
    whole, frac = s.replace(",", "").split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if v < 0 else "") + f"₹{whole}.{frac}"


def salary_slip_pdf(p, st, da_list):
    _fonts()
    emp = p.employee
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Salary slip {emp.name} {p.period_label}")
    W = doc.width
    base = ParagraphStyle("b", fontName="DejaVu", fontSize=9, leading=12)
    small = ParagraphStyle("s", parent=base, fontSize=8, textColor=GREY, leading=10)
    white_big = ParagraphStyle("wb", parent=base, fontName="DejaVu-Bold", fontSize=17, leading=21, textColor=colors.white)
    white = ParagraphStyle("w", parent=base, fontSize=8.5, leading=11, textColor=colors.HexColor("#dbeafe"))
    white_right = ParagraphStyle("wr", parent=white, alignment=TA_RIGHT)
    white_right_big = ParagraphStyle("wrb", parent=white_big, fontSize=12, leading=15, alignment=TA_RIGHT)

    story = []

    # ---- Header band: logo + company + slip title ----
    company_lines = [Paragraph(st["company_name"], white_big)]
    if st.get("company_address"):
        company_lines.append(Paragraph(st["company_address"].replace("\n", "<br/>"), white))
    if st.get("company_phone"):
        company_lines.append(Paragraph(f"Ph: {st['company_phone']}", white))
    logo = Image(LOGO, width=24 * mm, height=24 * mm) if os.path.exists(LOGO) else ""
    title = [Paragraph("SALARY SLIP", white_right_big),
             Paragraph(p.period_label, white_right)]
    head = Table([[logo, company_lines, title]], colWidths=[28 * mm, W - 28 * mm - 50 * mm, 50 * mm])
    head.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLUE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 4 * mm),
        ("LINEBELOW", (0, 0), (-1, 0), 3, ORANGE),
    ]))
    story += [head, Spacer(1, 5 * mm)]

    # ---- Employee details ----
    def kv(k, v):
        return [Paragraph(k, small), Paragraph(f"<b>{v}</b>", base)]
    info = [
        kv("Employee", emp.name) + kv("Designation", emp.emp_type),
        kv("Phone", emp.phone or "-") + kv("Vehicle no.", emp.vehicle_no or "-"),
        kv("Pay basis", f"{p.pay_type} @ {_rs(p.rate)}" + (" / day" if p.pay_type == "Daily" else " / month"))
        + kv("Paid on", f"{p.paid_on.strftime('%d-%m-%Y') if p.paid_on else '-'} ({p.payment_mode})"),
        kv("Paid days", f"{days(p.paid_days)} of {p.days_in_month}" + ("" if p.is_full_month else f" ({p.start:%d %b} – {p.end:%d %b})"))
        + kv("Overtime", f"{days(p.ot_hours)} hrs"),
    ]
    cw = [24 * mm, W / 2 - 24 * mm, 24 * mm, W / 2 - 24 * mm]
    t = Table(info, colWidths=cw)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e2e8f0")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
    ]))
    story += [t, Spacer(1, 5 * mm)]

    # ---- Earnings / deductions ----
    hdr = ParagraphStyle("h", parent=base, fontName="DejaVu-Bold", textColor=colors.white)
    r = ParagraphStyle("r", parent=base, alignment=TA_RIGHT)
    rb = ParagraphStyle("rb", parent=r, fontName="DejaVu-Bold")
    bold = ParagraphStyle("bo", parent=base, fontName="DejaVu-Bold")

    earn = [("Basic earned", p.earned,
             (f"{_rs(p.rate)} ÷ {p.days_in_month} × {days(p.paid_days)}" if p.is_full_month else f"{days(p.paid_days)} days at monthly rate {_rs(p.rate)}")
             if p.pay_type == "Monthly"
             else f"{_rs(p.rate)} × {days(p.paid_days)} days")]
    if p.ot_amount:
        earn.append(("Overtime", p.ot_amount, f"{days(p.ot_hours)} hrs × {_rs(emp.ot_rate)}"))
    if p.da_amount:
        earn.append(("Day allowance (DA)", p.da_amount, f"{len(da_list)} day(s) — see below"))
    if p.bonus:
        earn.append(("Bonus", p.bonus, ""))
    ded = [("Advance recovery", p.advance_deducted), ("Other deductions", p.other_deductions)]

    rows = [[Paragraph("EARNINGS", hdr), "", Paragraph("AMOUNT", ParagraphStyle("hr", parent=hdr, alignment=TA_RIGHT)),
             Paragraph("DEDUCTIONS", hdr), Paragraph("AMOUNT", ParagraphStyle("hr2", parent=hdr, alignment=TA_RIGHT))]]
    for i in range(max(len(earn), len(ded))):
        e = earn[i] if i < len(earn) else None
        d = ded[i] if i < len(ded) else None
        rows.append([
            Paragraph(e[0], base) if e else "",
            Paragraph(e[2], small) if e else "",
            Paragraph(_rs(e[1]), r) if e else "",
            Paragraph(d[0], base) if d else "",
            Paragraph(_rs(d[1]), r) if d else "",
        ])
    rows.append([Paragraph("Gross earnings", bold), "", Paragraph(_rs(p.gross), rb),
                 Paragraph("Total deductions", bold), Paragraph(_rs(p.total_deductions), rb)])
    t2 = Table(rows, colWidths=[34 * mm, 42 * mm, 26 * mm, W - 128 * mm, 26 * mm])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE_MID),
        ("BACKGROUND", (0, -1), (-1, -1), BLUE_LIGHT),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, BLUE),
        ("LINEAFTER", (2, 0), (2, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [t2, Spacer(1, 4 * mm)]

    # ---- Net paid ----
    net_style = ParagraphStyle("n", parent=base, fontName="DejaVu-Bold", fontSize=14, leading=18, textColor=GREEN)
    net = Table([[Paragraph("NET SALARY PAID", ParagraphStyle("nl", parent=base, fontName="DejaVu-Bold", fontSize=11, textColor=GREEN)),
                  Paragraph(_rs(p.net_paid), ParagraphStyle("nr", parent=net_style, alignment=TA_RIGHT))]],
                colWidths=[W - 60 * mm, 60 * mm])
    net.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GREEN_BG),
        ("BOX", (0, 0), (-1, -1), 1, GREEN),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [net, Spacer(1, 2 * mm)]
    story.append(Paragraph(
        f"Advance balance after this salary: <b>{_rs(p.advance_balance_after)}</b>"
        f" &nbsp;&nbsp;(due before: {_rs(p.advance_due)}, recovered now: {_rs(p.advance_deducted)})",
        base))
    if p.remarks:
        story.append(Paragraph(f"Remarks: {p.remarks}", base))
    story.append(Spacer(1, 4 * mm))

    # ---- DA details ----
    if da_list:
        story.append(Paragraph("<b>Day allowance (DA) details</b>", ParagraphStyle("dh", parent=base, textColor=ORANGE, fontSize=10)))
        story.append(Spacer(1, 1.5 * mm))
        drows = [[Paragraph("<b>Date</b>", base), Paragraph("<b>Trip / remarks</b>", base), Paragraph("<b>DA</b>", r)]]
        for a in da_list:
            drows.append([Paragraph(a.date.strftime("%d %b %Y (%a)"), base), Paragraph(a.remarks or "-", base),
                          Paragraph(_rs(a.da_amount), r)])
        drows.append([Paragraph("<b>Total DA</b>", base), "", Paragraph(_rs(sum(a.da_amount for a in da_list)), rb)])
        dt = Table(drows, colWidths=[38 * mm, W - 38 * mm - 30 * mm, 30 * mm], repeatRows=1)
        dt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ffedd5")),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#fed7aa")),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, ORANGE),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#fdba74")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story += [dt, Spacer(1, 4 * mm)]

    if st.get("slip_note"):
        story += [Paragraph(st["slip_note"], ParagraphStyle("note", parent=base, textColor=BLUE, fontName="DejaVu-Bold")),
                  Spacer(1, 2 * mm)]

    # ---- Signatures ----
    story.append(Spacer(1, 16 * mm))
    sig = Table([[Paragraph("Employee signature", small), Paragraph(f"For {st['company_name']}<br/>Authorised signatory",
                                                                    ParagraphStyle("sr", parent=small, alignment=TA_RIGHT))]],
                colWidths=[W / 2, W / 2])
    sig.setStyle(TableStyle([("LINEABOVE", (0, 0), (0, 0), 0.5, GREY), ("LINEABOVE", (1, 0), (1, 0), 0.5, GREY),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [sig, Spacer(1, 4 * mm),
              Paragraph("This is a computer-generated salary slip.", ParagraphStyle("f", parent=small, alignment=1))]
    doc.build(story)
    return buf.getvalue()
