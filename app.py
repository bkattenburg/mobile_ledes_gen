import streamlit as st
import pandas as pd
import random
import datetime
import calendar
import io
import os
import logging
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from faker import Faker
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from PIL import Image as PILImage, ImageDraw, ImageFont
import zipfile
from email.message import EmailMessage
import ssl
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any

# --- Constants for Invoice Generator ---
EXPENSE_CODES = {
    "Copying": "E101", "Outside printing": "E102", "Word processing": "E103",
    "Facsimile": "E104", "Telephone": "E105", "Online research": "E106",
    "Delivery services/messengers": "E107", "Postage": "E108", "Local travel": "E109",
    "Out-of-town travel": "E110", "Meals": "E111", "Court fees": "E112",
    "Subpoena fees": "E113", "Witness fees": "E114", "Deposition transcripts": "E115",
    "Trial transcripts": "E116", "Trial exhibits": "E117",
    "Litigation support vendors": "E118", "Experts": "E119",
    "Private investigators": "E120", "Arbitrators/mediators": "E121",
    "Local counsel": "E122", "Other professionals": "E123", "Other": "E124",
}
EXPENSE_DESCRIPTIONS = list(EXPENSE_CODES.keys())
OTHER_EXPENSE_DESCRIPTIONS = [desc for desc in EXPENSE_DESCRIPTIONS if EXPENSE_CODES[desc] != "E101"]

DEFAULT_TASK_ACTIVITY_DESC = [
    ("L100", "A101", "Legal Research: Analyze legal precedents"),
    ("L110", "A101", "Legal Research: Review statutes and regulations"),
    ("L120", "A101", "Legal Research: Draft research memorandum"),
    ("L130", "A102", "Case Assessment: Initial case evaluation"),
    ("L140", "A102", "Case Assessment: Develop case strategy"),
    ("L150", "A102", "Case Assessment: Identify key legal issues"),
    ("L160", "A103", "Fact Investigation: Interview witnesses"),
    ("L190", "A104", "Pleadings: Draft complaint/petition"),
    ("L200", "A104", "Pleadings: Prepare answer/response"),
    ("L210", "A104", "Pleadings: File motion to dismiss"),
    ("L220", "A105", "Discovery: Draft interrogatories"),
    ("L230", "A105", "Discovery: Prepare requests for production"),
    ("L240", "A105", "Discovery: Review opposing party's discovery responses"),
    ("L250", "A106", "Depositions: Prepare for deposition"),
    ("L260", "A106", "Depositions: Attend deposition"),
    ("L300", "A107", "Motions: Argue motion in court"),
    ("L310", "A108", "Settlement/Mediation: Prepare for mediation"),
    ("L320", "A108", "Settlement/Mediation: Attend mediation"),
    ("L330", "A108", "Settlement/Mediation: Draft settlement agreement"),
    ("L340", "A109", "Trial Preparation: Prepare witness for trial"),
    ("L350", "A109", "Trial Preparation: Organize trial exhibits"),
    ("L390", "A110", "Trial: Present closing argument"),
    ("L400", "A111", "Appeals: Research appellate issues"),
    ("L410", "A111", "Appeals: Draft appellate brief"),
    ("L420", "A111", "Appeals: Argue before appellate court"),
    ("L430", "A112", "Client Communication: Client meeting"),
    ("L440", "A112", "Client Communication: Phone call with client"),
    ("L450", "A112", "Client Communication: Email correspondence with client"),
]

MAJOR_TASK_CODES = {"L110", "L120", "L130", "L140", "L150", "L160", "L170", "L180", "L190"}
DEFAULT_CLIENT_ID = "02-4388252"
DEFAULT_LAW_FIRM_ID = "02-1234567"
DEFAULT_INVOICE_DESCRIPTION = "Monthly Legal Services"

# --- Functions from Original Script, adapted for Streamlit ---
def _replace_name_placeholder(description, faker_instance):
    return description.replace("{NAME_PLACEHOLDER}", faker_instance.name())

def _replace_description_dates(description):
    pattern = r"\b(\d{2}/\d{2}/\d{4})\b"
    if re.search(pattern, description):
        days_ago = random.randint(15, 90)
        new_date = (datetime.date.today() - datetime.timedelta(days=days_ago)).strftime("%m/%d/%Y")
        return re.sub(pattern, new_date, description)
    return description

def _load_timekeepers(uploaded_file):
    if uploaded_file is None:
        return None
    try:
        df = pd.read_csv(uploaded_file)
        required_cols = ["TIMEKEEPER_NAME", "TIMEKEEPER_CLASSIFICATION", "TIMEKEEPER_ID", "RATE"]
        if not all(col in df.columns for col in required_cols):
            st.error(f"Timekeeper CSV must contain the following columns: {', '.join(required_cols)}")
            return None
        return df.to_dict(orient='records')
    except Exception as e:
        st.error(f"Error loading timekeeper file: {e}")
        return None

def _load_custom_task_activity_data(uploaded_file):
    if uploaded_file is None:
        return None
    try:
        df = pd.read_csv(uploaded_file)
        required_cols = ["TASK_CODE", "ACTIVITY_CODE", "DESCRIPTION"]
        if not all(col in df.columns for col in required_cols):
            st.error(f"Custom Task/Activity CSV must contain the following columns: {', '.join(required_cols)}")
            return None
        if df.empty:
            st.warning("Custom Task/Activity CSV file is empty.")
            return []
        custom_tasks = []
        for _, row in df.iterrows():
            custom_tasks.append((str(row["TASK_CODE"]), str(row["ACTIVITY_CODE"]), str(row["DESCRIPTION"])))
        return custom_tasks
    except Exception as e:
        st.error(f"Error loading custom tasks file: {e}")
        return None
def _create_ledes_line_1998b(row, line_no, inv_total, bill_start, bill_end, invoice_number, matter_number):
    date_obj = datetime.datetime.strptime(row["LINE_ITEM_DATE"], "%Y-%m-%d").date()
    hours = float(row["HOURS"])
    rate = float(row["RATE"])
    line_total = float(row["LINE_ITEM_TOTAL"])
    is_expense = bool(row["EXPENSE_CODE"])
    adj_type = "E" if is_expense else "F"
    task_code = "" if is_expense else row.get("TASK_CODE", "")
    activity_code = "" if is_expense else row.get("ACTIVITY_CODE", "")
    expense_code = row.get("EXPENSE_CODE", "") if is_expense else ""
    timekeeper_id = "" if is_expense else row.get("TIMEKEEPER_ID", "")
    timekeeper_class = "" if is_expense else row.get("TIMEKEEPER_CLASSIFICATION", "")
    timekeeper_name = "" if is_expense else row.get("TIMEKEEPER_NAME", "")
    return [
        bill_end.strftime("%Y%m%d"),
        invoice_number,
        str(row.get("CLIENT_ID", "")),
        matter_number,
        f"{inv_total:.2f}",
        bill_start.strftime("%Y%m%d"),
        bill_end.strftime("%Y%m%d"),
        str(row.get("INVOICE_DESCRIPTION", "")),
        str(line_no),
        adj_type,
        f"{hours:.1f}" if adj_type == "F" else f"{int(hours)}",
        "0.00",
        f"{line_total:.2f}",
        date_obj.strftime("%Y%m%d"),
        task_code,
        expense_code,
        activity_code,
        timekeeper_id,
        str(row.get("DESCRIPTION", "")),
        str(row.get("LAW_FIRM_ID", "")),
        f"{rate:.2f}",
        timekeeper_name,
        timekeeper_class,
        matter_number
    ]

def _create_ledes_1998b_content(rows, inv_total, bill_start, bill_end, invoice_number, matter_number):
    header = "LEDES1998B[]"
    fields = ("INVOICE_DATE|INVOICE_NUMBER|CLIENT_ID|LAW_FIRM_MATTER_ID|INVOICE_TOTAL|BILLING_START_DATE|"
              "BILLING_END_DATE|INVOICE_DESCRIPTION|LINE_ITEM_NUMBER|EXP/FEE/INV_ADJ_TYPE|"
              "LINE_ITEM_NUMBER_OF_UNITS|LINE_ITEM_ADJUSTMENT_AMOUNT|LINE_ITEM_TOTAL|LINE_ITEM_DATE|"
              "LINE_ITEM_TASK_CODE|LINE_ITEM_EXPENSE_CODE|LINE_ITEM_ACTIVITY_CODE|TIMEKEEPER_ID|"
              "LINE_ITEM_DESCRIPTION|LAW_FIRM_ID|LINE_ITEM_UNIT_COST|TIMEKEEPER_NAME|"
              "TIMEKEEPER_CLASSIFICATION|CLIENT_MATTER_ID[]")
    lines = [header, fields]
    for i, r in enumerate(rows, start=1):
        line = _create_ledes_line_1998b(r, i, inv_total, bill_start, bill_end, invoice_number, matter_number)
        lines.append("|".join(map(str, line)) + "[]")
    return "\n".join(lines)

def _generate_invoice_data(fee_count, expense_count, timekeeper_data, client_id, law_firm_id, invoice_desc, billing_start_date, billing_end_date, task_activity_desc, major_task_codes, max_hours_per_tk_per_day, include_block_billed, faker_instance):
    # This is a port of the original function.
    # It generates a list of dictionaries for a single conceptual invoice.
    rows = []
    delta = billing_end_date - billing_start_date
    num_days = delta.days + 1
    major_items = [item for item in task_activity_desc if item[0] in major_task_codes]
    other_items = [item for item in task_activity_desc if item[0] not in major_task_codes]
    current_invoice_total = 0.0
    daily_hours_tracker = {}
    MAX_DAILY_HOURS = max_hours_per_tk_per_day

    # Fee records
    for _ in range(fee_count):
        if not task_activity_desc: break
        tk_row = random.choice(timekeeper_data)
        timekeeper_id = tk_row["TIMEKEEPER_ID"]
        if major_items and random.random() < 0.7:
            task_code, activity_code, description = random.choice(major_items)
        elif other_items:
            task_code, activity_code, description = random.choice(other_items)
        else: continue
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        line_item_date_str = line_item_date.strftime("%Y-%m-%d")
        current_billed_hours = daily_hours_tracker.get((line_item_date_str, timekeeper_id), 0)
        remaining_hours_capacity = MAX_DAILY_HOURS - current_billed_hours
        if remaining_hours_capacity <= 0: continue
        hours_to_bill = round(random.uniform(0.5, min(8.0, remaining_hours_capacity)), 1)
        if hours_to_bill == 0: continue
        hourly_rate = tk_row["RATE"]
        line_item_total = round(hours_to_bill * hourly_rate, 2)
        current_invoice_total += line_item_total
        daily_hours_tracker[(line_item_date_str, timekeeper_id)] = current_billed_hours + hours_to_bill
        description = _replace_description_dates(description)
        description = _replace_name_placeholder(description, faker_instance)
        row = {
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date_str, "TIMEKEEPER_NAME": tk_row["TIMEKEEPER_NAME"],
            "TIMEKEEPER_CLASSIFICATION": tk_row["TIMEKEEPER_CLASSIFICATION"],
            "TIMEKEEPER_ID": timekeeper_id, "TASK_CODE": task_code,
            "ACTIVITY_CODE": activity_code, "EXPENSE_CODE": "", "DESCRIPTION": description,
            "HOURS": hours_to_bill, "RATE": hourly_rate, "LINE_ITEM_TOTAL": line_item_total
        }
        rows.append(row)

    # Expense records (E101 and others)
    e101_actual_count = random.randint(1, min(3, expense_count))
    for _ in range(e101_actual_count):
        description = "Copying"
        expense_code = "E101"
        hours = random.randint(1, 200)
        rate = round(random.uniform(0.14, 0.25), 2)
        random_day_offset = random.randint(0, num_days - 1)
        line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
        line_item_total = round(hours * rate, 2)
        current_invoice_total += line_item_total
        row = {
            "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id, "LAW_FIRM_ID": law_firm_id,
            "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"), "TIMEKEEPER_NAME": "",
            "TIMEKEEPER_CLASSIFICATION": "", "TIMEKEEPER_ID": "", "TASK_CODE": "",
            "ACTIVITY_CODE": "", "EXPENSE_CODE": expense_code, "DESCRIPTION": description,
            "HOURS": hours, "RATE": rate, "LINE_ITEM_TOTAL": line_item_total
        }
        rows.append(row)

    remaining_expense_count = expense_count - e101_actual_count
    if remaining_expense_count > 0:
        if not OTHER_EXPENSE_DESCRIPTIONS:
            pass
        else:
            for _ in range(remaining_expense_count):
                description = random.choice(OTHER_EXPENSE_DESCRIPTIONS)
                expense_code = EXPENSE_CODES[description]
                hours = 1
                rate = round(random.uniform(25, 200), 2)
                random_day_offset = random.randint(0, num_days - 1)
                line_item_date = billing_start_date + datetime.timedelta(days=random_day_offset)
                line_item_total = round(hours * rate, 2)
                current_invoice_total += line_item_total
                row = {
                    "INVOICE_DESCRIPTION": invoice_desc, "CLIENT_ID": client_id,
                    "LAW_FIRM_ID": law_firm_id, "LINE_ITEM_DATE": line_item_date.strftime("%Y-%m-%d"),
                    "TIMEKEEPER_NAME": "", "TIMEKEEPER_CLASSIFICATION": "",
                    "TIMEKEEPER_ID": "", "TASK_CODE": "", "ACTIVITY_CODE": "",
                    "EXPENSE_CODE": expense_code, "DESCRIPTION": description,
                    "HOURS": hours, "RATE": rate, "LINE_ITEM_TOTAL": line_item_total
                }
                rows.append(row)

    # Block Billing
    if not include_block_billed:
        rows = [row for row in rows if not ("; " in row["DESCRIPTION"])]
    elif include_block_billed:
        if not any('; ' in row['DESCRIPTION'] for row in rows):
            for _, _, desc in task_activity_desc:
                if '; ' in desc and len(rows) > 0:
                    extra = rows[0].copy()
                    extra['DESCRIPTION'] = desc
                    rows.insert(0, extra)
                    break
    return rows, current_invoice_total

def _get_logo_image_bytes():
    """Generates a default image or loads from file."""
    from PIL import Image as PILImage, ImageDraw, ImageFont

    try:
        # Load the image from the assets directory. It's assumed to be there in a deployed app.
        image_path = "assets/nelsonmurdock2.jpg"
        img = PILImage.open(image_path)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except FileNotFoundError:
        st.warning("Image file (assets/nelsonmurdock2.jpg) not found. A placeholder will be used.")
        img = PILImage.new("RGB", (128, 128), color="white")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default()
        except IOError:
            font = ImageFont.load_default()
        draw.text((10, 20), "NM", font=font, fill=(0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception as e:
        st.error(f"Error loading image: {e}")
        return None

def _create_pdf_invoice(df, total_amount, invoice_number, invoice_date, billing_start_date, billing_end_date, client_id, law_firm_id):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=1.0 * inch, rightMargin=1.0 * inch,
        topMargin=1.0 * inch, bottomMargin=1.0 * inch
    )
    styles = getSampleStyleSheet()
    elements = []

    # Header Section
    if law_firm_id == DEFAULT_LAW_FIRM_ID:
        logo_image = _get_logo_image_bytes()
        if logo_image:
            elements.append(Image(logo_image, width=1.0 * inch, height=1.0 * inch))

    # Law Firm and Client Info Table
    firm_info = f"<b>Nelson and Murdock</b><br/>{law_firm_id}<br/>One Park Avenue<br/>Manhattan, NY 10003"
    client_info = f"<b>A Onit Inc.</b><br/>{client_id}<br/>1360 Post Oak Blvd<br/>Houston, TX 77056"

    header_table_data = [[Paragraph(firm_info, styles['Normal']), Paragraph(client_info, styles['Normal'])]]
    header_table = Table(header_table_data, colWidths=[doc.width/2.0, doc.width/2.0])
    header_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(header_table)

    elements.append(Spacer(1, 0.2 * inch))
    elements.append(Paragraph(f"<b>Invoice #:</b> {invoice_number}", styles['Normal']))
    elements.append(Paragraph(f"<b>Invoice Date:</b> {invoice_date.strftime('%B %d, %Y')}", styles['Normal']))
    elements.append(Paragraph(f"<b>Billing Period:</b> {billing_start_date.strftime('%B %d, %Y')} - {billing_end_date.strftime('%B %d, %Y')}", styles['Normal']))
    elements.append(Spacer(1, 0.4 * inch))

    # Table of Invoice Data
    data = [df.columns.tolist()] + df.values.tolist()
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ])

    table = Table(data, colWidths=[1.0*inch, 1.2*inch, 1.0*inch, 1.0*inch, 1.0*inch, 1.0*inch, 1.0*inch])
    table.setStyle(table_style)
    elements.append(table)

    # Footer/Total
    elements.append(Spacer(1, 0.2 * inch))
    total_text = f"<b>TOTAL AMOUNT DUE: ${total_amount:,.2f}</b>"
    elements.append(Paragraph(total_text, styles['Normal']))
    doc.build(elements)
    buffer.seek(0)
    return buffer

@dataclass
class InvoiceOutput:
    df: pd.DataFrame
    total_amount: float
    ledes_content: str
    ledes_filename: str
    pdf_buffer: io.BytesIO
    pdf_filename: str
    client_id: str

def _generate_multiple_invoices(num_invoices, starting_date, fee_count, expense_count, timekeeper_data, client_id, law_firm_id, invoice_desc, include_block_billed, max_hours_per_tk_per_day, include_pdf):
    faker = Faker()
    outputs = []
    
    # Calculate initial dates for the most recent period
    billing_end_date = starting_date
    billing_start_date = billing_end_date.replace(day=1)
    
    for i in range(1, num_invoices + 1):
        # Generate data for the current period
        rows, total_amount = _generate_invoice_data(
            fee_count=fee_count,
            expense_count=expense_count,
            timekeeper_data=timekeeper_data,
            client_id=client_id,
            law_firm_id=law_firm_id,
            invoice_desc=invoice_desc,
            billing_start_date=billing_start_date,
            billing_end_date=billing_end_date,
            task_activity_desc=DEFAULT_TASK_ACTIVITY_DESC,
            major_task_codes=MAJOR_TASK_CODES,
            max_hours_per_tk_per_day=max_hours_per_tk_per_day,
            include_block_billed=include_block_billed,
            faker_instance=faker
        )
        
        df_invoice = pd.DataFrame(rows)
        
        invoice_number = f"{billing_end_date.year}{billing_end_date.month:02d}-{random.randint(10000, 99999)}"
        ledes_content = _create_ledes_1998b_content(rows, total_amount, billing_start_date, billing_end_date, invoice_number, client_id)
        
        ledes_filename = f"Invoice_{invoice_number}.txt"
        
        pdf_buffer = None
        pdf_filename = None
        if include_pdf:
            pdf_buffer = _create_pdf_invoice(df_invoice, total_amount, invoice_number, billing_end_date, billing_start_date, billing_end_date, client_id, law_firm_id)
            pdf_filename = f"Invoice_{invoice_number}.pdf"
            
        outputs.append(InvoiceOutput(
            df=df_invoice,
            total_amount=total_amount,
            ledes_content=ledes_content,
            ledes_filename=ledes_filename,
            pdf_buffer=pdf_buffer,
            pdf_filename=pdf_filename,
            client_id=client_id
        ))

        # Update dates for the next loop to go backwards in time
        billing_end_date = billing_start_date - datetime.timedelta(days=1)
        billing_start_date = billing_end_date.replace(day=1)

    return outputs

# Streamlit App
st.set_page_config(layout="wide", page_title="LEDES Invoice Generator")
st.title("LEDES Invoice Generator")

st.sidebar.title("File Uploads")

with st.sidebar.expander("Upload CSVs"):
    timekeeper_file = st.file_uploader("Upload Timekeeper CSV", type="csv")
    custom_tasks_file = st.file_uploader("Upload Custom Task CSV (Optional)", type="csv")

st.sidebar.markdown("---")
st.sidebar.info("Upload Timekeeper CSV to use custom timekeepers. Without a custom file, the generator will use mock data.")

# Main content area with tabs
tab1, tab2, tab3 = st.tabs(["Invoice Inputs", "Advanced Settings", "Email Configuration"])

with tab1:
    st.header("Invoice Generation Details")
    
    with st.expander("Billing Information"):
        law_firm_id = st.text_input("Law Firm ID", value=DEFAULT_LAW_FIRM_ID)
        client_id = st.text_input("Client ID", value=DEFAULT_CLIENT_ID)
        matter_number = st.text_input("Matter Number", value="01-22-LIT-001")
        invoice_desc = st.text_input("Invoice Description", value=DEFAULT_INVOICE_DESCRIPTION)

    with st.expander("Invoice Dates & Description"):
        num_invoices = st.number_input("Number of Invoices to Generate", min_value=1, max_value=12, value=1)
        st.caption("Generates invoices for consecutive months, ending with the selected date.")
        start_date = st.date_input("Billing Period End Date", value=datetime.date.today().replace(day=1) - datetime.timedelta(days=1))
        
    with st.expander("Line Item Counts"):
        fee_count = st.number_input("Number of Fee Line Items", min_value=1, max_value=500, value=100)
        expense_count = st.number_input("Number of Expense Line Items", min_value=0, max_value=100, value=10)

with tab2:
    st.header("Generation Settings")

    with st.expander("Additional Data Sources"):
        timekeeper_data = _load_timekeepers(timekeeper_file)
        if timekeeper_data is None:
            timekeeper_data = [
                {"TIMEKEEPER_NAME": "Toby M. Wright", "TIMEKEEPER_CLASSIFICATION": "Partner", "TIMEKEEPER_ID": "TW123", "RATE": 533.00},
                {"TIMEKEEPER_NAME": "Wendy Green", "TIMEKEEPER_CLASSIFICATION": "Associate", "TIMEKEEPER_ID": "WG456", "RATE": 475.00},
                {"TIMEKEEPER_NAME": "Sheila Jackson", "TIMEKEEPER_CLASSIFICATION": "Paralegal", "TIMEKEEPER_ID": "SJ789", "RATE": 250.00},
                {"TIMEKEEPER_NAME": "Rita McAvoy", "TIMEKEEPER_CLASSIFICATION": "Partner", "TIMEKEEPER_ID": "RM101", "RATE": 600.00},
                {"TIMEKEEPER_NAME": "Nelson L. Gonzalez", "TIMEKEEPER_CLASSIFICATION": "Associate", "TIMEKEEPER_ID": "NG202", "RATE": 490.00},
                {"TIMEKEEPER_NAME": "Marie Henderson", "TIMEKEEPER_CLASSIFICATION": "Associate", "TIMEKEEPER_ID": "MH303", "RATE": 480.00},
            ]
        custom_task_activity_data = _load_custom_task_activity_data(custom_tasks_file)
        if custom_task_activity_data:
            task_activity_desc = custom_task_activity_data
        else:
            task_activity_desc = DEFAULT_TASK_ACTIVITY_DESC

    with st.expander("Generation Logic"):
        max_hours_per_tk_per_day = st.slider("Maximum Hours per Timekeeper per Day", min_value=1, max_value=24, value=8)
        include_block_billed = st.checkbox("Include Block Billed Line Items?", value=True, help="Block billed items combine multiple tasks into one line item.")
        include_pdf = st.checkbox("Include PDF Invoice?", value=True)

with tab3:
    st.header("Email Delivery")
    
    with st.expander("Email Details"):
        send_email = st.checkbox("Enable Email Delivery?", help="Check this to send the generated files via email.")
        to_addr = st.text_input("Recipient Email Address", disabled=not send_email)
        email_from = st.text_input("Sender Email Address", disabled=not send_email)
        email_password = st.text_input("Sender Password (or App Password)", type="password", disabled=not send_email)
        email_subject = st.text_input("Email Subject", value="Legal Invoice from your firm", disabled=not send_email)
        email_body = st.text_area("Email Body", value="Attached are the requested invoices.", disabled=not send_email)
        
    with st.expander("SMTP Settings (Optional Test)"):
        diag_col1, diag_col2 = st.columns(2)
        with diag_col1:
            smtp_server = st.text_input("SMTP Server", value="smtp.gmail.com")
            smtp_port = st.number_input("SMTP Port", value=465, min_value=1)
            smtp_use_tls = st.checkbox("Use STARTTLS?", value=False)
            if st.button("Test SMTP Connection"):
                try:
                    if smtp_use_tls:
                        server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
                        server.starttls()
                        server.ehlo()
                        server.login(email_from, email_password)
                    else:
                        context = ssl.create_default_context()
                        with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=15) as server:
                            server.login(email_from, email_password)
                    st.success("SMTP connection & login OK.")
                except Exception as e:
                    st.error(f"SMTP test failed: {e!r}")
                    st.caption("Tips: For Gmail, use an App Password and ensure EMAIL_FROM matches the authenticated account.")

        with diag_col2:
            if st.button("Send test to myself"):
                try:
                    _send_email_with_attachments(email_from, attachments=[])
                    st.success(f"Test email sent to {email_from}. Check your inbox and spam folder.")
                except Exception as e:
                    st.error(f"Test send failed: {e!r}")

    if send_email and st.button("Send Email Now"):
        try:
            _send_email_with_attachments(to_addr, attachments=outputs)
            st.success(f"Email sent to {to_addr}")
        except Exception as e:
            st.error(f"Email failed: {e!r}")
            st.caption("Common fixes: set SMTP_USE_TLS=true + SMTP_PORT=587 (STARTTLS) or use SSL on 465. For Gmail, use an App Password.")

# The generation logic and output display
if st.button("Generate Invoices"):
    outputs = _generate_multiple_invoices(
        num_invoices=num_invoices,
        starting_date=start_date,
        fee_count=fee_count,
        expense_count=expense_count,
        timekeeper_data=timekeeper_data,
        client_id=client_id,
        law_firm_id=law_firm_id,
        invoice_desc=invoice_desc,
        include_block_billed=include_block_billed,
        max_hours_per_tk_per_day=max_hours_per_tk_per_day,
        include_pdf=include_pdf
    )

    if not outputs:
        st.error("No invoices were generated. Please check your inputs.")
    else:
        for i, output in enumerate(outputs):
            st.subheader(f"Invoice {i+1}: {output.ledes_filename}")
            
            # Use columns to align the download buttons
            col1, col2 = st.columns(2)
            
            with col1:
                st.download_button(
                    label="Download LEDES File",
                    data=output.ledes_content.encode('utf-8'),
                    file_name=output.ledes_filename,
                    mime="text/plain",
                    key=f"download_ledes_{i}"
                )
            with col2:
                if output.pdf_buffer:
                    st.download_button(
                        label="Download PDF Invoice",
                        data=output.pdf_buffer.getvalue(),
                        file_name=output.pdf_filename,
                        mime="application/pdf",
                        key=f"download_pdf_{i}"
                    )

        st.success("Invoice generation complete!")
