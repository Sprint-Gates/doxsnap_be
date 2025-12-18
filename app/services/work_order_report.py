import io
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
import os
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import smtplib

from app.config import settings


class WorkOrderReportService:
    """Service for generating work order reports and sending emails"""

    def __init__(self):
        self.smtp_server = settings.smtp_server
        self.smtp_port = settings.smtp_port
        self.username = settings.smtp_username
        self.password = settings.smtp_password
        self.support_email = settings.company_support_email

    def generate_pdf(self, work_order: Dict[str, Any], include_checklist: bool = True) -> bytes:
        """Generate a professional PDF report for a work order"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=0.5*inch,
            leftMargin=0.5*inch,
            topMargin=0.4*inch,
            bottomMargin=0.4*inch
        )

        elements = []
        styles = getSampleStyleSheet()

        # Colors
        primary = colors.HexColor('#1a56db')
        dark = colors.HexColor('#1e293b')
        gray = colors.HexColor('#64748b')
        light_gray = colors.HexColor('#f1f5f9')
        border = colors.HexColor('#e2e8f0')
        success = colors.HexColor('#16a34a')

        # Styles
        title_style = ParagraphStyle('Title', fontSize=14, fontName='Helvetica-Bold', textColor=dark)
        subtitle_style = ParagraphStyle('Subtitle', fontSize=9, textColor=gray)
        section_style = ParagraphStyle('Section', fontSize=9, fontName='Helvetica-Bold', textColor=primary, spaceBefore=8, spaceAfter=4)
        label_style = ParagraphStyle('Label', fontSize=8, textColor=gray)
        value_style = ParagraphStyle('Value', fontSize=9, textColor=dark)
        small_style = ParagraphStyle('Small', fontSize=7, textColor=gray)

        # Extract data
        wo_number = work_order.get('wo_number', 'N/A')
        title = work_order.get('title', 'N/A')
        status = work_order.get('status', 'N/A').replace('_', ' ').title()
        priority = work_order.get('priority', 'N/A').title()
        wo_type = work_order.get('work_order_type', 'N/A').replace('_', ' ').title()
        description = work_order.get('description', '')
        notes = work_order.get('notes', '')

        # === HEADER ===
        header_data = [[
            Paragraph(f"<b>{wo_number}</b>", ParagraphStyle('WO', fontSize=12, fontName='Helvetica-Bold', textColor=primary)),
            Paragraph(f"<b>{status}</b>", ParagraphStyle('Status', fontSize=10, fontName='Helvetica-Bold', textColor=dark, alignment=TA_RIGHT))
        ]]
        header_table = Table(header_data, colWidths=[5*inch, 2.5*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(header_table)

        # Title
        elements.append(Paragraph(title, title_style))
        elements.append(Spacer(1, 2))

        # Type & Priority line
        elements.append(Paragraph(f"{wo_type}  •  {priority} Priority", subtitle_style))
        elements.append(Spacer(1, 6))
        elements.append(HRFlowable(width="100%", thickness=1, color=border))
        elements.append(Spacer(1, 6))

        # === INFO GRID ===
        # Build location
        loc_parts = []
        if work_order.get('branch'):
            loc_parts.append(work_order['branch'].get('name', ''))
        if work_order.get('floor'):
            loc_parts.append(work_order['floor'].get('name', ''))
        if work_order.get('room'):
            loc_parts.append(work_order['room'].get('name', ''))
        location = ' › '.join(filter(None, loc_parts)) or '-'

        # Equipment
        equipment = '-'
        if work_order.get('equipment'):
            eq = work_order['equipment']
            equipment = eq.get('name', '')
            if work_order.get('sub_equipment'):
                equipment += f" › {work_order['sub_equipment'].get('name', '')}"

        # Schedule
        scheduled = '-'
        if work_order.get('scheduled_start'):
            scheduled = self._format_date(work_order.get('scheduled_start'))
            if work_order.get('scheduled_end'):
                scheduled += f" - {self._format_date(work_order.get('scheduled_end'))}"

        # Technicians
        techs = work_order.get('technicians', [])
        tech_names = ', '.join([t.get('name', '') for t in techs]) if techs else '-'

        # Create 2-column info grid
        info_data = [
            [Paragraph("<b>Location</b>", label_style), Paragraph("<b>Equipment</b>", label_style)],
            [Paragraph(location, value_style), Paragraph(equipment, value_style)],
            [Paragraph("<b>Scheduled</b>", label_style), Paragraph("<b>Assigned To</b>", label_style)],
            [Paragraph(scheduled, value_style), Paragraph(tech_names, value_style)],
        ]

        info_table = Table(info_data, colWidths=[3.75*inch, 3.75*inch])
        info_table.setStyle(TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(info_table)

        # Description & Notes - clean up PM template descriptions
        if description:
            # Check if this is a PM checklist description (skip it since checklist is shown separately)
            is_pm_checklist = 'PREVENTIVE MAINTENANCE CHECKLIST' in description or 'TASKS TO COMPLETE' in description

            if not is_pm_checklist:
                elements.append(Spacer(1, 4))
                elements.append(Paragraph("<b>Description</b>", label_style))
                # Clean up any special characters
                clean_desc = description.replace('■', '').replace('  ', ' ').strip()
                elements.append(Paragraph(clean_desc, value_style))

        if notes:
            elements.append(Spacer(1, 4))
            elements.append(Paragraph("<b>Notes</b>", label_style))
            elements.append(Paragraph(notes, value_style))

        # === CHECKLIST ===
        checklist_items = work_order.get('checklist_items', [])
        time_entries = work_order.get('time_entries', [])
        total_hours = sum(float(e.get('hours_worked', 0) or 0) for e in time_entries)

        if include_checklist and checklist_items:
            elements.append(Spacer(1, 8))
            elements.append(HRFlowable(width="100%", thickness=1, color=border))
            elements.append(Spacer(1, 6))

            completed = sum(1 for i in checklist_items if i.get('is_completed'))
            total = len(checklist_items)
            pct = int(completed/total*100) if total > 0 else 0

            # Show hours in header if available
            hours_text = f"  •  {total_hours:.1f} hrs" if total_hours > 0 else ""
            elements.append(Paragraph(f"CHECKLIST  <font color='#64748b'>({completed}/{total} complete - {pct}%{hours_text})</font>", section_style))

            # Checklist table - use Paragraphs for text wrapping
            cl_data = [['#', 'Task', 'Done']]
            for item in checklist_items:
                done = item.get('is_completed', False)
                desc = item.get('description', '')
                completed_at = item.get('completed_at', '')

                # Format completed time
                completed_info = ''
                if done:
                    completed_info = 'Yes'
                    if completed_at:
                        completed_info = self._format_date(completed_at)

                # Use Paragraph for text wrapping
                task_para = Paragraph(desc, ParagraphStyle('Task', fontSize=8, textColor=dark, leading=10))

                cl_data.append([
                    str(item.get('item_number', '')),
                    task_para,
                    completed_info if done else '-'
                ])

            cl_table = Table(cl_data, colWidths=[0.3*inch, 6.5*inch, 0.7*inch])
            cl_table.setStyle(TableStyle([
                # Header
                ('BACKGROUND', (0, 0), (-1, 0), light_gray),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 7),
                ('TEXTCOLOR', (0, 0), (-1, 0), gray),
                # Body
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('TEXTCOLOR', (0, 1), (-1, -1), dark),
                # Alignment
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (2, 0), (2, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                # Grid
                ('LINEBELOW', (0, 0), (-1, 0), 0.5, border),
                ('LINEBELOW', (0, 1), (-1, -2), 0.5, border),
                # Padding
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                # Color done status
                *[('TEXTCOLOR', (2, i+1), (2, i+1), success)
                  for i, item in enumerate(checklist_items) if item.get('is_completed')],
            ]))
            elements.append(cl_table)

        # === ISSUED ITEMS (SPARE PARTS) ===
        issued_items = work_order.get('issued_items', [])
        if issued_items:
            elements.append(Spacer(1, 8))
            total_parts_cost = sum(item.get('total_cost', 0) for item in issued_items)
            elements.append(Paragraph(f"ISSUED ITEMS  <font color='#64748b'>(Total: ${total_parts_cost:.2f})</font>", section_style))

            sp_data = [['Item #', 'Description', 'Qty', 'Unit Cost', 'Total']]
            for item in issued_items:
                desc = item.get('description', '-')
                # Truncate long descriptions
                if len(desc) > 40:
                    desc = desc[:37] + '...'
                sp_data.append([
                    item.get('item_number', '-'),
                    desc,
                    f"{item.get('quantity', 0):.0f}",
                    f"${item.get('unit_cost', 0):.2f}",
                    f"${item.get('total_cost', 0):.2f}"
                ])

            sp_table = Table(sp_data, colWidths=[1.2*inch, 3.5*inch, 0.5*inch, 0.9*inch, 1.4*inch])
            sp_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), light_gray),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('TEXTCOLOR', (0, 0), (-1, 0), gray),
                ('TEXTCOLOR', (0, 1), (-1, -1), dark),
                ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
                ('LINEBELOW', (0, 0), (-1, -1), 0.5, border),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            elements.append(sp_table)

        # === TIME ENTRIES ===
        if time_entries:
            elements.append(Spacer(1, 8))
            elements.append(Paragraph(f"TIME LOG  <font color='#64748b'>({total_hours:.1f} hrs total)</font>", section_style))

            te_data = [['Technician', 'Date', 'Hours', 'Work Performed']]
            for entry in time_entries:
                work_desc = entry.get('work_description', '')[:40]
                te_data.append([
                    entry.get('technician_name', '-'),
                    self._format_date(entry.get('start_time')),
                    f"{entry.get('hours_worked', 0):.1f}",
                    work_desc
                ])

            te_table = Table(te_data, colWidths=[1.5*inch, 1*inch, 0.6*inch, 4.4*inch])
            te_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), light_gray),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('TEXTCOLOR', (0, 0), (-1, 0), gray),
                ('TEXTCOLOR', (0, 1), (-1, -1), dark),
                ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                ('LINEBELOW', (0, 0), (-1, -1), 0.5, border),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            elements.append(te_table)

        # === COSTS ===
        if work_order.get('is_billable'):
            est = work_order.get('estimated_total_cost', 0) or 0
            act = work_order.get('actual_total_cost', 0) or 0
            elements.append(Spacer(1, 8))
            elements.append(Paragraph(f"COSTS  <font color='#64748b'>Est: ${est:.2f}  |  Actual: ${act:.2f}</font>", section_style))

        # === CLIENT COMPLETION (RATING, COMMENTS, SIGNATURE) ===
        completion = work_order.get('completion')
        if completion:
            elements.append(Spacer(1, 8))
            elements.append(HRFlowable(width="100%", thickness=1, color=border))
            elements.append(Spacer(1, 6))
            elements.append(Paragraph("CLIENT SIGN-OFF", section_style))

            # Rating with stars
            rating = completion.get('rating')
            if rating:
                stars = '★' * rating + '☆' * (5 - rating)
                rating_color = success if rating >= 4 else (colors.HexColor('#eab308') if rating >= 3 else colors.HexColor('#ef4444'))
                elements.append(Paragraph(f"<b>Rating:</b>  <font color='{rating_color}'>{stars}</font>  ({rating}/5)", value_style))
                elements.append(Spacer(1, 4))

            # Client comments
            comments = completion.get('comments')
            if comments:
                elements.append(Paragraph("<b>Client Comments:</b>", label_style))
                elements.append(Paragraph(comments, value_style))
                elements.append(Spacer(1, 4))

            # Signature section
            signed_by = completion.get('signed_by_name')
            signed_at = completion.get('signed_at')
            signature_path = completion.get('signature_path')

            if signed_by or signature_path:
                elements.append(Spacer(1, 4))

                # Try to include signature image
                if signature_path and os.path.exists(signature_path):
                    try:
                        sig_img = Image(signature_path, width=2*inch, height=0.75*inch)
                        sig_img.hAlign = 'LEFT'
                        elements.append(sig_img)
                    except Exception as e:
                        elements.append(Paragraph("<i>Signature on file</i>", small_style))

                # Signature info
                sig_info_parts = []
                if signed_by:
                    sig_info_parts.append(f"<b>Signed by:</b> {signed_by}")
                if signed_at:
                    sig_info_parts.append(f"<b>Date:</b> {self._format_datetime(signed_at)}")

                if sig_info_parts:
                    elements.append(Paragraph("  |  ".join(sig_info_parts), small_style))

        # === FOOTER ===
        elements.append(Spacer(1, 12))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=border))
        elements.append(Spacer(1, 4))
        footer = Paragraph(
            f"Generated {datetime.now().strftime('%b %d, %Y at %I:%M %p')}  •  DoxSnap CAFM",
            ParagraphStyle('Footer', fontSize=7, textColor=gray, alignment=TA_CENTER)
        )
        elements.append(footer)

        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        return buffer.read()

    def _format_date(self, dt_string: Optional[str]) -> str:
        """Format datetime string for display"""
        if not dt_string:
            return '-'
        try:
            dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
            return dt.strftime('%b %d, %Y')
        except:
            return str(dt_string)[:10] if dt_string else '-'

    def _format_datetime(self, dt_string: Optional[str]) -> str:
        """Format datetime string with time"""
        if not dt_string:
            return '-'
        try:
            dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
            return dt.strftime('%b %d, %Y %I:%M %p')
        except:
            return dt_string

    def send_work_order_email(
        self,
        recipient_email: str,
        work_order: Dict[str, Any],
        pdf_data: bytes,
        message: Optional[str] = None,
        sender_name: Optional[str] = None
    ) -> bool:
        """Send work order report via email with PDF attachment"""
        try:
            wo_number = work_order.get('wo_number', 'Unknown')
            title = work_order.get('title', 'Work Order Report')

            msg = MIMEMultipart()
            msg['Subject'] = f"Work Order Report: {wo_number}"
            msg['From'] = self.support_email
            msg['To'] = recipient_email

            custom_message = ""
            if message:
                custom_message = f"<p><strong>Message:</strong> {message}</p><hr style='border:none;border-top:1px solid #e2e8f0;margin:16px 0'>"

            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f8fafc; }}
        .container {{ max-width: 500px; margin: 0 auto; background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }}
        .header {{ background: #1a56db; color: white; padding: 20px; }}
        .header h1 {{ margin: 0; font-size: 18px; font-weight: 600; }}
        .header .wo {{ opacity: 0.9; font-size: 14px; margin-top: 4px; }}
        .content {{ padding: 20px; }}
        .info {{ background: #f8fafc; border-radius: 6px; padding: 12px; margin: 12px 0; }}
        .info-row {{ display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }}
        .info-label {{ color: #64748b; }}
        .info-value {{ color: #1e293b; font-weight: 500; }}
        .note {{ background: #eff6ff; border-left: 3px solid #1a56db; padding: 12px; margin: 16px 0; font-size: 13px; color: #1e40af; }}
        .footer {{ background: #f8fafc; padding: 16px; text-align: center; font-size: 11px; color: #64748b; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{title}</h1>
            <div class="wo">{wo_number}</div>
        </div>
        <div class="content">
            {custom_message}
            <div class="info">
                <div class="info-row">
                    <span class="info-label">Status</span>
                    <span class="info-value">{work_order.get('status', 'N/A').replace('_', ' ').title()}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Type</span>
                    <span class="info-value">{work_order.get('work_order_type', 'N/A').title()}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Priority</span>
                    <span class="info-value">{work_order.get('priority', 'N/A').title()}</span>
                </div>
            </div>
            <div class="note">
                📎 The complete work order report is attached as a PDF.
            </div>
        </div>
        <div class="footer">
            DoxSnap CAFM • {datetime.now().strftime('%b %d, %Y')}
        </div>
    </div>
</body>
</html>
"""

            html_part = MIMEText(html_content, 'html')
            msg.attach(html_part)

            filename = f"WO_{wo_number}_{datetime.now().strftime('%Y%m%d')}.pdf"
            pdf_attachment = MIMEApplication(pdf_data, _subtype='pdf', Name=filename)
            pdf_attachment.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(pdf_attachment)

            return self._send_email(msg, recipient_email)

        except Exception as e:
            print(f"Error sending work order email: {str(e)}")
            return False

    def _send_email(self, msg: MIMEMultipart, recipient_email: str) -> bool:
        """Send email using SMTP"""
        try:
            if not self.username or not self.password:
                print("Email configuration incomplete")
                return False

            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.username, self.password)
            server.sendmail(self.support_email, recipient_email, msg.as_string())
            server.quit()

            print(f"Email sent successfully to {recipient_email}")
            return True

        except Exception as e:
            print(f"Failed to send email: {str(e)}")
            return False
