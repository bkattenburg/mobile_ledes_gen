
# ---- Mobile detection ----
import streamlit as st
import re
if "user_agent" not in st.session_state:
    ua = st.runtime.scriptrunner.get_script_run_ctx().session_info.client.user_agent if hasattr(st.runtime.scriptrunner.get_script_run_ctx().session_info.client, "user_agent") else ""
    st.session_state["is_mobile"] = bool(re.search("iPhone|Android.*Mobile|iPad", ua))

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


# ---- Mobile-friendly page config ----
try:
    st.set_page_config(
        page_title="LEDES Invoice Generator",
        page_icon="📄",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
except Exception:
    pass


# ---- Mobile-first CSS tweaks ----
st.markdown("""
<style>
@media (max-width: 480px) {
  .block-container { padding-top: 0.5rem; padding-bottom: 4.5rem; }
  h1, h2, h3 { line-height: 1.2; }
  .stButton > button, .stDownloadButton > button { width: 100% !important; padding: 0.9rem 1rem; font-size: 1rem; }
  .stTextInput > div > div > input,
  .stNumberInput input,
  .stSelectbox > div > div { font-size: 1rem; }
  .stCheckbox label, .stRadio label { font-size: 0.98rem; }
}
.stButton > button, .stDownloadButton > button { border-radius: 10px; }
.sticky-footer {
  position: fixed; bottom: 0; left: 0; right: 0;
  padding: 0.6rem 0.9rem;
  background: var(--background-color);
  box-shadow: 0 -6px 18px rgba(0,0,0,0.08);
  z-index: 1000;
}
.sticky-footer .footer-grid { display: grid; grid-template-columns: 1fr; gap: 0.5rem; }
@media (min-width: 700px) {
  .sticky-footer .footer-grid { grid-template-columns: 1fr auto auto; }
}
</style>
""", unsafe_allow_html=True)


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

# Initialize Faker outside of any Streamlit blocks so it's globally available
faker = Faker()

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


# Helper function to get image bytes safely
def _get_logo_image_bytes():
    """Generates a default image or loads from file."""
    from PIL import Image as PILImage, ImageDraw, ImageFont
    
    # Try to load a local image from the 'assets' folder
    try:
        # Update the path to point to the '.jpg' file
        image_path = "assets/nelsonmurdock2.jpg"
        img = PILImage.open(image_path)
        buf = io.BytesIO()
        # Save the image as PNG for compatibility with ReportLab
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except FileNotFoundError:
        # Fallback to generating a simple image if the file is not found
        st.warning("Image file (assets/icon.jpg) not found. A placeholder will be used.")
        img = PILImage.new("RGB", (128, 128), color="white")
        draw = ImageDraw.Draw(img)
        try:
            # Use a default font, as custom fonts might not be available
            font = ImageFont.load_default()
        except IOError:
            font = ImageFont.load_default()
        draw.text((10, 20), "NM", font=font, fill=(0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

def _create_pdf_invoice(df, total_amount, invoice_number, invoice_date, billing_start_date, billing_end_date, client_id, law_firm_id):
    """
    Generates a PDF invoice with a layout that matches the provided example.
    Includes conditional address blocks and a clean header.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=1.0 * inch, rightMargin=1.0 * inch,
        topMargin=1.0 * inch, bottomMargin=1.0 * inch
    )
    styles = getSampleStyleSheet()
    available_width = doc.width
    elements = []

    # --- HEADER: Law Firm | Client (Boxed) ---
    # Section 1: Law firm info, conditionally with logo
    if law_firm_id == DEFAULT_LAW_FIRM_ID:
        law_firm_info = (
            f"<b>Nelson and Murdock</b><br/>{law_firm_id}<br/>"
            "One Park Avenue<br/>Manhattan, NY 10003"
        )
        logo_file_name = "nelsonmurdock2.jpg"
    else:
        law_firm_info = (
            f"<b>Your Law Firm Name</b><br/>{law_firm_id}<br/>"
            "1001 Main Street, Big City, CA 90000"
        )
        logo_file_name = "icon.jpg" # Using a generic placeholder image

    # Dynamically build the logo path from the script's directory
    script_dir = os.path.dirname(__file__)
    logo_path = os.path.join(script_dir, "assets", logo_file_name)

    left_style = ParagraphStyle(name="Left", parent=styles["Normal"], alignment=TA_LEFT, leading=12)
    law_firm_para = Paragraph(law_firm_info, left_style)
    header_left_content = law_firm_para

    if law_firm_id == DEFAULT_LAW_FIRM_ID:
        try:
            img = Image(logo_path, width=0.6 * inch, height=0.6 * inch)
            inner_table_data = [[img, law_firm_para]]
            inner_table = Table(inner_table_data, colWidths=[0.7 * inch, None])
            inner_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (1, 0), (1, 0), 6),
            ]))
            header_left_content = inner_table
        except Exception as e:
            logging.error(f"Error loading logo image from {logo_path}: {e}")
            st.warning("Could not load law firm logo. Using text instead.")
            header_left_content = law_firm_para

    # Section 2: Client info block, left-aligned
    if client_id == DEFAULT_CLIENT_ID:
        client_info = (
            f"<b>A Onit Inc.</b><br/>{client_id}<br/>"
            "1360 Post Oak Blvd<br/>Houston, TX 77056"
        )
    else:
        client_info = (
            f"<b>Your Company Name</b><br/>{client_id}<br/>"
            "1000 Main Street, Big City, CA 90000"
        )
    client_info_style = ParagraphStyle(name="ClientInfoLeft", parent=styles["Normal"], alignment=TA_LEFT)
    client_para = Paragraph(client_info, client_info_style)

    # Combined header table
    header_data = [
        [header_left_content, client_para]
    ]
    header_table = Table(header_data, colWidths=[available_width / 2, available_width / 2])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOX', (0, 0), (0, 0), 1, colors.black),
        ('BOX', (1, 0), (1, 0), 1, colors.black),
        ('LEFTPADDING', (0, 0), (0, 0), 6),
        ('RIGHTPADDING', (1, 0), (1, 0), 6),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'LEFT'),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.10 * inch))

    # -------- Invoice Details (right under Client Info) --------
    right_style = ParagraphStyle(name="Right", parent=styles["Normal"], alignment=TA_RIGHT)
    invoice_details_text = (
        f"<b>Invoice #:</b> {invoice_number}<br/>"
        f"<b>Invoice Date:</b> {invoice_date.strftime('%Y-%m-%d')}<br/>"
        f"<b>Billing Period:</b> {billing_start_date.strftime('%Y-%m-%d')} to {billing_end_date.strftime('%Y-%m-%d')}"
    )
    details_para = Paragraph(invoice_details_text, right_style)
    details_table = Table(
        [['', details_para]],
        colWidths=[available_width / 2, available_width / 2]
    )
    details_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (1, 0), (1, 0), 6),
    ]))
    elements.append(details_table)
    elements.append(Spacer(1, 0.18*inch))

    # --- INVOICE DETAILS TABLE ---
    # Table headers
    data = [['Date', 'Timekeeper', 'Task Code', 'Activity Code', 'Description', 'Hours', 'Rate', 'Total']]
    
    # Add line item rows
    for _, row in df.iterrows():
        # Correctly format rows to include Paragraphs for wrapping text
        date = row['LINE_ITEM_DATE']
        timekeeper = row['TIMEKEEPER_NAME'] if row['TIMEKEEPER_NAME'] else 'N/A'
        task_code = row['TASK_CODE'] if row['TASK_CODE'] else 'N/A'
        activity_code = row['ACTIVITY_CODE'] if row['ACTIVITY_CODE'] else 'N/A'
        description = row['DESCRIPTION']
        hours = row['HOURS']
        rate = row['RATE']
        total = row['LINE_ITEM_TOTAL']
        
        data.append([
            date, 
            timekeeper, 
            task_code, 
            activity_code, 
            Paragraph(description, styles['Normal']),
            f"{hours:.2f}", 
            f"${rate:.2f}", 
            f"${total:.2f}"
        ])

    # Table styling
    table = Table(data, colWidths=[1 * inch, 1.25 * inch, 0.75 * inch, 0.75 * inch, 2.25 * inch, 0.75 * inch, 0.75 * inch, 0.75 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 0.25 * inch))

    # --- TOTAL AMOUNT SECTION ---
    total_table_data = [[
        Paragraph(f"<b>Total Amount Due:</b>", styles['Normal']),
        Paragraph(f"<b>${total_amount:.2f}</b>", styles['Normal'])
    ]]
    total_table = Table(total_table_data, colWidths=[4 * inch, None])
    total_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(total_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def _send_email_with_attachment(recipient_email, subject, body, attachments: list):
    """
    Sends an email with multiple file attachments.
    Gets credentials from Streamlit Secrets.
    Attachments is a list of tuples: [(filename, data_bytes), ...].
    """
    try:
        sender_email = st.secrets.email.email_from
        password = st.secrets.email.email_password
    except AttributeError:
        st.error("Email secrets not found. Please check your .streamlit/secrets.toml file.")
        return

    msg = MIMEMultipart()
    
    # Set the 'From' header with both the desired name and the sender's email address
    from_name = "Onit Invoice Generation"
    msg['From'] = f'"{from_name}" <{sender_email}>'
    
    msg['To'] = recipient_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))
    
    for filename, data in attachments:
        part = MIMEApplication(data, Name=filename)
        part['Content-Disposition'] = f'attachment; filename="{filename}"'
        msg.attach(part)
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, password)
            server.send_message(msg)
        st.success(f"Email sent successfully to {recipient_email}!")
    except Exception as e:
        st.error(f"Error sending email: {e}")

# --- Streamlit App UI ---
st.title("LEDES Invoice Generator")

# ---- Compact summary card ----
st.markdown("### Invoice Summary")
col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="Client ID", value=str(client_id) if 'client_id' in locals() else "-")
with col2:
    st.metric(label="Billing Period", value=f"{billing_start_date} to {billing_end_date}" if 'billing_start_date' in locals() else "-")
with col3:
    st.metric(label="Invoices", value=len(rows) if 'rows' in locals() else 0)

st.write("Generate and optionally email LEDES and PDF invoices.")

# --- Sidebar for user inputs ---
with st.sidebar:
    st.header("File Upload")
    uploaded_timekeeper_file = st.file_uploader("Upload Timekeeper CSV (tk_info.csv)", type="csv")
    timekeeper_data = _load_timekeepers(uploaded_timekeeper_file)

    use_custom_tasks = st.checkbox("Use Custom Line Item Details?", value=False)
    uploaded_custom_tasks_file = None
    if use_custom_tasks:
        uploaded_custom_tasks_file = st.file_uploader("Upload Custom Line Items CSV (custom_details.csv)", type="csv")
    
    task_activity_desc = DEFAULT_TASK_ACTIVITY_DESC
    if use_custom_tasks and uploaded_custom_tasks_file:
        custom_tasks_data = _load_custom_task_activity_data(uploaded_custom_tasks_file)
        if custom_tasks_data:
            task_activity_desc = custom_tasks_data

# This checkbox controls the visibility of the email tab
st.subheader("Output & Delivery Options")
send_email = st.checkbox("Send Invoices via Email", value=True)

# Dynamically create tabs based on the 'send_email' checkbox
if send_email:
    tab1, tab2, tab3 = st.tabs(["Invoice Inputs", "Advanced Settings", "Email Configuration"])
else:
    tab1, tab2 = st.tabs(["Invoice Inputs", "Advanced Settings"])
    
with tab1:
    st.header("Invoice Details")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Billing Information")
        client_id = st.text_input("Client ID:", DEFAULT_CLIENT_ID)
        law_firm_id = st.text_input("Law Firm ID:", DEFAULT_LAW_FIRM_ID)
        matter_number_base = st.text_input("Matter Number:", "2025-XXXXXX")
        invoice_number_base = st.text_input("Invoice Number (Base):", "2025MMM-XXXXXX")
        ledes_version = st.selectbox("LEDES Version:", ["1998B", "XML 2.1"])
        
    with col2:
        st.subheader("Invoice Dates & Description")
        # --- Get the start and end dates of the previous month ---
        today = datetime.date.today()
        first_day_of_current_month = today.replace(day=1)
        last_day_of_previous_month = first_day_of_current_month - datetime.timedelta(days=1)
        first_day_of_previous_month = last_day_of_previous_month.replace(day=1)
        billing_start_date = st.date_input("Billing Start Date", value=first_day_of_previous_month)
        billing_end_date = st.date_input("Billing End Date", value=last_day_of_previous_month)
        invoice_desc = st.text_area(
            "Invoice Description (One per period, each on a new line)", 
            value="Professional Services Rendered", 
            height=150
        )

with tab2:
    st.header("Generation Settings")
    with st.expander("Advanced Settings (mobile-optimized)", expanded=False):
        fees = st.number_input("Number of Fee Line Items", min_value=0, step=1) if st.session_state.get("is_mobile") else st.number_input("Number of Fee Line Items", min_value=1, max_value=10000, value=20, step=1)
        expenses = st.number_input("Number of Expense Line Items", min_value=0, max_value=10000, value=5, step=1)
        max_daily_hours = st.number_input("Max Daily Timekeeper Hours:", min_value=1, max_value=24, value=16, step=1)
    
        st.subheader("Output Settings")
        include_block_billed = st.checkbox("Include Block Billed Line Items", value=True)
        include_pdf = st.checkbox("Include PDF Invoice", value=True)
        generate_multiple = st.checkbox("Generate Multiple Invoices")
        num_invoices = 1
        multiple_periods = False
        if generate_multiple:
            num_invoices = st.number_input("Number of Invoices to Create:", min_value=1, value=1, step=1)
            multiple_periods = st.checkbox("Multiple Billing Periods")
            if multiple_periods:
                num_periods = st.number_input("How Many Billing Periods:", min_value=2, max_value=6, value=2, step=1)
                num_invoices = num_periods

    # This if block is now necessary to place the email content into the dynamic tab
if send_email:
    with tab3:
    with st.expander('Advanced Settings', expanded=True):
            st.header("Email Delivery")
        recipient_email = st.text_input("Recipient Email Address:")
        st.caption(f"Sender Email will be from: {st.secrets.get('email', {}).get('username', 'N/A')}")
else:
    # If not sending email, still need to define these variables
    recipient_email = None
        
st.markdown("---")
generate_button = st.button("Generate Invoice(s)")

# --- Main app logic ---
if generate_button:
    if timekeeper_data is None:
        st.warning("Please upload a valid timekeeper CSV file.")
    elif send_email and not recipient_email:
        st.warning("Please provide a recipient email address to send the invoice.")
    else:
        # NEW: Process descriptions
        descriptions = [d.strip() for d in invoice_desc.split('\n') if d.strip()]
        num_invoices = int(num_invoices)  # Ensure num_invoices is an integer
        
        if multiple_periods and len(descriptions) != num_invoices:
            st.warning(f"You have selected to generate {num_invoices} invoices, but have provided {len(descriptions)} descriptions. Please provide one description per period.")
        else:
            progress_bar = st.progress(0)
            
            # Loop for multiple invoices
            for i in range(num_invoices):
                progress_bar.progress((i + 1) / num_invoices)

                # NEW: Get the correct description for the current invoice
                current_invoice_desc = descriptions[i] if multiple_periods and i < len(descriptions) else descriptions[0]
                
                # Generate invoice data
                rows, total_amount = _generate_invoice_data(
                    fees, expenses, timekeeper_data, client_id, law_firm_id,
                    current_invoice_desc, billing_start_date, billing_end_date,
                    task_activity_desc, MAJOR_TASK_CODES, max_daily_hours, include_block_billed, faker
                )
                df_invoice = pd.DataFrame(rows)
                
                # Filenames
                current_invoice_number = f"{invoice_number_base}-{i+1}"
                current_matter_number = matter_number_base
                
                # Create LEDES 1998B content
                ledes_content = _create_ledes_1998b_content(rows, total_amount, billing_start_date, billing_end_date, current_invoice_number, current_matter_number)
                
                # Prepare attachments
                attachments_to_send = []
                
                # Add LEDES file
                ledes_filename = f"LEDES_1998B_{current_invoice_number}.txt"
                attachments_to_send.append((ledes_filename, ledes_content.encode('utf-8')))

                # Add PDF file if requested
                if include_pdf:
                    pdf_buffer = _create_pdf_invoice(df_invoice, total_amount, current_invoice_number, billing_end_date, billing_start_date, billing_end_date, client_id, law_firm_id)
                    pdf_filename = f"Invoice_{current_invoice_number}.pdf"
                    attachments_to_send.append((pdf_filename, pdf_buffer.getvalue()))
                    pdf_buffer.seek(0)

                # Handle output
                if send_email:
                    _send_email_with_attachment(
                        recipient_email,
                        f"LEDES Invoice for {current_matter_number}",
                        f"Please find the attached invoice files for matter {current_matter_number}.",
                        attachments_to_send
                    )
                    
                else:
                    st.subheader(f"Generated Invoice {i + 1}")
                    
                    # Use a text area for display
                    st.text_area("LEDES 1998B Content", ledes_content, height=200)

                    # Download buttons
                    col1, col2 = st.columns(2)
                    with col1:
                        st.download_button(
                            label="Download LEDES File",
                            data=ledes_content.encode('utf-8'),
                            file_name=ledes_filename,
                            mime="text/plain",
                            key=f"download_ledes_{i}"
                        )
                    with col2:
                        if include_pdf:
                            pdf_buffer = _create_pdf_invoice(df_invoice, total_amount, current_invoice_number, billing_end_date, billing_start_date, billing_end_date, client_id, law_firm_id)
                            st.download_button(
                                label="Download PDF Invoice",
                                data=pdf_buffer.getvalue(),
                                file_name=pdf_filename,
                                mime="application/pdf",
                                key=f"download_pdf_{i}"
                            )
                        
                if multiple_periods:
                    end_of_current_period = billing_start_date - datetime.timedelta(days=1)
                    start_of_current_period = end_of_current_period.replace(day=1)
                    billing_start_date = start_of_current_period
                    billing_end_date = end_of_current_period
            
            st.success("Invoice generation complete!")

# ---- Enhanced mobile typography/spacing ----
st.markdown("""
<style>
:root { --radius: 12px; }
@media (max-width: 480px) {
  .block-container { padding-left: 0.6rem; padding-right: 0.6rem; }
  .stTabs [data-baseweb="tab-list"] { flex-wrap: wrap; row-gap: 0.25rem; }
  .stTabs [data-baseweb="tab"] { font-size: 0.95rem; padding: 0.3rem 0.6rem; }
  .stExpander { border-radius: var(--radius); border: 1px solid rgba(0,0,0,0.07); }
  .summary-card { border-radius: var(--radius); border: 1px solid rgba(0,0,0,0.08); padding: 0.75rem 1rem; background: rgba(0,0,0,0.02); }
  .summary-grid { display: grid; grid-template-columns: 1fr; gap: 0.35rem; }
}
@media (min-width: 481px) {
  .summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem 1rem; }
}
.summary-item { font-size: 0.95rem; }
.summary-item .k { opacity: 0.65; margin-right: 0.4rem; }
</style>
""", unsafe_allow_html=True)
