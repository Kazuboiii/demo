"""Report exporters (CSV, Excel, PDF) for the central reporting engine.

The exporter receives the exact report dictionary returned by
:func:`reports.engine.run_report`, so a downloaded file always matches the
on-screen table and its totals.
"""

import csv
import io
from datetime import datetime
from xml.sax.saxutils import escape


def _display(column, value):
    if value is None or value == "":
        return ""
    kind = column.get("type")
    if kind == "boolean":
        return "Yes" if value else "No"
    if kind == "money":
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)
    if kind == "number":
        try:
            number = float(value)
            return str(int(number)) if number.is_integer() else f"{number:,.2f}"
        except (TypeError, ValueError):
            return str(value)
    if kind == "datetime":
        text = str(value)
        try:
            return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return text
    return str(value)


def _raw(column, value):
    if value is None:
        return ""
    if column.get("type") in ("money", "number"):
        try:
            number = float(value)
            return int(number) if number.is_integer() and column.get("type") == "number" else number
        except (TypeError, ValueError):
            return value
    if column.get("type") == "boolean":
        return "Yes" if value else "No"
    return _display(column, value)


def _filename(report, extension):
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return f"{report['key']}-{stamp}.{extension}"


def _meta_lines(report):
    division = report["division"]["name"] if report.get("division") else "All accessible divisions"
    filters = report.get("filters", {})
    parts = [f"Division: {division}"]
    if filters.get("start") or filters.get("end"):
        parts.append(f"Period: {filters.get('start') or 'start'} to {filters.get('end') or 'today'}")
    if filters.get("status"):
        parts.append(f"Status: {filters['status']}")
    if filters.get("search"):
        parts.append(f"Search: {filters['search']}")
    parts.append(f"Generated: {report.get('generated_at', '')}")
    return parts


def to_csv(report):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([report["title"]])
    for line in _meta_lines(report):
        writer.writerow([line])
    writer.writerow([])
    columns = report["columns"]
    writer.writerow([column["label"] for column in columns])
    for row in report["rows"]:
        writer.writerow([_display(column, row.get(column["key"])) for column in columns])
    if report["totals"]:
        writer.writerow([])
        totals_row = []
        for index, column in enumerate(columns):
            if index == 0:
                totals_row.append("TOTAL")
            elif column["key"] in report["totals"]:
                totals_row.append(_display(column, report["totals"][column["key"]]))
            else:
                totals_row.append("")
        writer.writerow(totals_row)
    data = buffer.getvalue().encode("utf-8-sig")
    return data, "text/csv; charset=utf-8", _filename(report, "csv")


def to_xlsx(report):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = report["title"][:31]
    columns = report["columns"]

    sheet.cell(row=1, column=1, value=report["title"]).font = Font(bold=True, size=14)
    for offset, line in enumerate(_meta_lines(report), start=2):
        sheet.cell(row=offset, column=1, value=line).font = Font(size=9, color="555555")

    header_row = 2 + len(_meta_lines(report)) + 1
    header_fill = PatternFill("solid", fgColor="0F172A")
    header_font = Font(bold=True, color="FFFFFF")
    for index, column in enumerate(columns, start=1):
        cell = sheet.cell(row=header_row, column=index, value=column["label"])
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row_index, row in enumerate(report["rows"], start=header_row + 1):
        for column_index, column in enumerate(columns, start=1):
            cell = sheet.cell(row=row_index, column=column_index, value=_raw(column, row.get(column["key"])))
            if column.get("type") == "money":
                cell.number_format = "#,##0.00"
            elif column.get("type") == "number":
                cell.number_format = "#,##0.##"

    if report["totals"]:
        total_row = header_row + len(report["rows"]) + 2
        sheet.cell(row=total_row, column=1, value="TOTAL").font = Font(bold=True)
        for column_index, column in enumerate(columns, start=1):
            if column["key"] in report["totals"]:
                cell = sheet.cell(
                    row=total_row,
                    column=column_index,
                    value=_raw(column, report["totals"][column["key"]]),
                )
                cell.font = Font(bold=True)
                if column.get("type") == "money":
                    cell.number_format = "#,##0.00"
                elif column.get("type") == "number":
                    cell.number_format = "#,##0.##"

    for index, column in enumerate(columns, start=1):
        longest = len(str(column["label"]))
        for row in report["rows"][:200]:
            longest = max(longest, len(_display(column, row.get(column["key"]))))
        sheet.column_dimensions[get_column_letter(index)].width = min(max(12, longest + 2), 42)
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return (
        buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        _filename(report, "xlsx"),
    )


def to_pdf(report):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    columns = report["columns"]
    page_size = landscape(A4) if len(columns) > 6 else A4
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=report["title"],
        author="HOMS",
    )
    styles = getSampleStyleSheet()
    heading = ParagraphStyle(
        "ReportHeading", parent=styles["Heading1"], fontSize=15, spaceAfter=4
    )
    meta = ParagraphStyle(
        "ReportMeta", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#555555")
    )
    story = [Paragraph(escape(report["title"]), heading)]
    for line in _meta_lines(report):
        story.append(Paragraph(escape(line), meta))
    story.append(Spacer(1, 8))

    header = [escape(column["label"]) for column in columns]
    data = [header]
    for row in report["rows"]:
        data.append([escape(_display(column, row.get(column["key"]))) for column in columns])
    if report["totals"]:
        totals_row = []
        for index, column in enumerate(columns):
            if index == 0:
                totals_row.append("TOTAL")
            elif column["key"] in report["totals"]:
                totals_row.append(escape(_display(column, report["totals"][column["key"]])))
            else:
                totals_row.append("")
        data.append(totals_row)

    table = Table(data, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2E8F0")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(table)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"{report['count']} row(s). Totals are summed from the displayed source rows.",
        meta,
    ))
    document.build(story)
    return buffer.getvalue(), "application/pdf", _filename(report, "pdf")


EXPORTERS = {"csv": to_csv, "xlsx": to_xlsx, "pdf": to_pdf}


def export_report(report, fmt):
    exporter = EXPORTERS.get((fmt or "").lower())
    if exporter is None:
        raise ValueError("Unsupported export format. Use csv, xlsx or pdf.")
    return exporter(report)
