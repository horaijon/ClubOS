"""Printable summaries of the same event snapshot displayed in the workspace."""
from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = "#171927"
INDIGO = "#5445AF"


def money(paise):
    return f"INR {paise / 100:,.2f}"


class Report:
    def __init__(self, title, subtitle):
        self.buffer = BytesIO()
        self.doc = SimpleDocTemplate(self.buffer, pagesize=A4, leftMargin=46, rightMargin=46,
                                     topMargin=55, bottomMargin=46, title=title, author="ClubOS")
        self.story = []
        self.text(title, 25, True)
        self.text(subtitle, 10)
        self.story.append(Spacer(1, 12))

    def para(self, value, size, bold=False, color=INK):
        style = ParagraphStyle("body", fontName="Helvetica-Bold" if bold else "Helvetica",
                               fontSize=size, leading=size*1.42, textColor=colors.HexColor(color), spaceAfter=5)
        return Paragraph(escape(str(value)).replace("\n","<br/>"), style)

    def text(self, value, size=11, bold=False):
        self.story.append(self.para(value, size, bold))

    def table(self, title, headers, rows, proportions):
        self.story.append(Spacer(1, 10))
        self.text(title, 14, True)
        data = [[self.para(h,9,True,"#FFFFFF") for h in headers]] + [
            [self.para(cell,9) for cell in row] for row in rows]
        if len(data) == 1:
            self.text("No records yet.",10)
            return
        table = Table(data, colWidths=[self.doc.width*p for p in proportions], repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor(INDIGO)),
                                   ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F1F1F6")]),
                                   ("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),8),
                                   ("TOPPADDING",(0,0),(-1,-1),6)]))
        self.story.append(table)

    def finish(self):
        def frame(canvas, doc):
            canvas.setFillColor(colors.HexColor(INDIGO))
            canvas.setFont("Helvetica-Bold",10)
            canvas.drawString(46,A4[1]-32,"ClubOS")
            canvas.setFont("Helvetica",9)
            canvas.drawRightString(A4[0]-46,25,f"{date.today().isoformat()}   /   {doc.page}")
        self.doc.build(self.story,onFirstPage=frame,onLaterPages=frame)
        return self.buffer.getvalue()


def event_report(w, sponsor=None):
    e, m = w["event"], w["metrics"]
    title = sponsor["name"] + " partnership" if sponsor else e["name"] + " event report"
    report = Report(title, f"{e['club']}   /   {e['start_date']}   /   {e['venue']}")
    if e.get("is_demo"):
        report.text("Demonstration workspace with fictional sponsors and sample records.",10)
    if e.get("goals"):
        report.text(e["goals"])
    report.table("Participation and execution",["Registered","Target","Checked in","Tasks complete"],
                 [[m["registered"],m["target"],sum(bool(p["checked_in"]) for p in w["participants"]),
                   f"{m['completed']} of {m['total_tasks']}"]],[.25]*4)
    sponsors = [sponsor] if sponsor else w["sponsors"]
    report.table("Sponsorship ledger",["Sponsor","Stage","Commitment","Received"],[
        [s["name"],s["stage"],money(s["committed"]),money(s["received"])] for s in sponsors],[.34,.22,.22,.22])
    if not sponsor:
        report.table("Financial position",["Projected funding","Planned expenses","Projected balance","Cash balance"],
                     [[money(m[k]) for k in ("projected_funding","planned","balance","cash_balance")]],[.25]*4)
        report.table("Expenses",["Category","Planned","Actual"],[
            [b["category"],money(b["planned"]),money(b["actual"])] for b in w["budget"]],[.50,.25,.25])
        report.table("Risk register",["Issue","Severity","Status"],[[r["title"],r["severity"],r["status"]] for r in w["risks"]],[.60,.20,.20])
    linked = [t for t in w["tasks"] if t.get("sponsor_id") and (not sponsor or t["sponsor_id"]==sponsor["id"])]
    report.table("Sponsor obligations",["Deliverable","Owner","Due","Status"],[
        [t["title"],t["owner"],t["due_date"],t["status"]] for t in linked],[.42,.21,.19,.18])
    if sponsor:
        report.text(f"Thank you to the {sponsor['name']} team for reviewing this record of our partnership.")
    else:
        report.table("Automation impact",["Logged actions","Estimated manual minutes saved"],[[m["actions"],m["minutes_saved"]]],[.4,.6])
        if w["risks"]:
            report.text("Next steps",14,True)
            for r in w["risks"][:3]:
                report.text(r.get("recommendation") or r["description"],10)
    return report.finish()
