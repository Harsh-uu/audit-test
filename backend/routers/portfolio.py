from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional, List
import logging

from deps import get_db, get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


def _s(oid):
    return str(oid) if oid else None


async def _build_portfolio_data(user_id: str, db):
    """Aggregate evidence data for a single user across all signed-off meetings."""
    user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user_doc:
        return None

    user_data = {
        "id": str(user_doc["_id"]),
        "name": user_doc.get("name", ""),
        "email": user_doc.get("email", ""),
        "role": user_doc.get("role", ""),
    }

    # Signed-off meetings where this user is an attendee
    raw_meetings = []
    async for meeting in db.meetings.find(
        {"attendees.user_id": user_id, "status": {"$in": ["signed_off", "shared"]}, "analysis_id": {"$exists": True}}
    ).sort("date", -1):
        if not meeting.get("analysis_id"):
            continue
        adoc = await db.analyses.find_one({"_id": ObjectId(meeting["analysis_id"])})
        if adoc:
            raw_meetings.append({"meeting": meeting, "analysis": adoc})

    # ── Aggregate by standard ──────────────────────────────────────────────
    cqc_agg = {}
    care_cert_agg = {}
    custom_agg = {}

    for item in raw_meetings:
        mtg = item["meeting"]
        ana = item["analysis"]
        mdate = mtg.get("date", "")
        mid = str(mtg["_id"])

        for m in ana.get("cqc_mappings", []):
            key = m.get("regulation_ref", "—")
            if key not in cqc_agg:
                cqc_agg[key] = {
                    "regulation_ref": m.get("regulation_ref", ""),
                    "regulation_name": m.get("regulation_name", ""),
                    "key_questions": m.get("key_questions", []),
                    "evidence_count": 0, "likely_count": 0, "needs_review_count": 0,
                    "meeting_refs": [], "latest_excerpt": None,
                }
            e = cqc_agg[key]
            e["evidence_count"] += 1
            if m.get("confidence") == "likely_evidence":
                e["likely_count"] += 1
            elif m.get("confidence") == "needs_review":
                e["needs_review_count"] += 1
            if mdate and {"date": mdate, "id": mid, "title": mtg.get("title", "")} not in e["meeting_refs"]:
                e["meeting_refs"].append({"date": mdate, "id": mid, "title": mtg.get("title", "")})
            if m.get("transcript_excerpt"):
                e["latest_excerpt"] = m["transcript_excerpt"][:200]

        for m in ana.get("care_cert_mappings", []):
            key = m.get("standard_ref", "—") + "::" + m.get("outcome_ref", "")
            if key not in care_cert_agg:
                care_cert_agg[key] = {
                    "standard_ref": m.get("standard_ref", ""),
                    "standard_name": m.get("standard_name", ""),
                    "outcome_ref": m.get("outcome_ref", ""),
                    "outcome_name": m.get("outcome_name", ""),
                    "evidence_count": 0, "likely_count": 0, "needs_review_count": 0,
                    "meeting_refs": [], "latest_excerpt": None,
                }
            e = care_cert_agg[key]
            e["evidence_count"] += 1
            if m.get("confidence") == "likely_evidence":
                e["likely_count"] += 1
            elif m.get("confidence") == "needs_review":
                e["needs_review_count"] += 1
            if mdate and {"date": mdate, "id": mid, "title": mtg.get("title", "")} not in e["meeting_refs"]:
                e["meeting_refs"].append({"date": mdate, "id": mid, "title": mtg.get("title", "")})
            if m.get("transcript_excerpt"):
                e["latest_excerpt"] = m["transcript_excerpt"][:200]

        for m in ana.get("custom_mappings", []):
            key = m.get("document_id", "") + "::" + m.get("criterion_ref", "—")
            if key not in custom_agg:
                custom_agg[key] = {
                    "document_id": m.get("document_id", ""),
                    "document_name": m.get("document_name", ""),
                    "criterion_ref": m.get("criterion_ref", ""),
                    "criterion_name": m.get("criterion_name", ""),
                    "evidence_count": 0, "likely_count": 0, "needs_review_count": 0,
                    "meeting_refs": [], "latest_excerpt": None,
                }
            e = custom_agg[key]
            e["evidence_count"] += 1
            if m.get("confidence") == "likely_evidence":
                e["likely_count"] += 1
            elif m.get("confidence") == "needs_review":
                e["needs_review_count"] += 1
            if mdate and {"date": mdate, "id": mid, "title": mtg.get("title", "")} not in e["meeting_refs"]:
                e["meeting_refs"].append({"date": mdate, "id": mid, "title": mtg.get("title", "")})
            if m.get("transcript_excerpt"):
                e["latest_excerpt"] = m["transcript_excerpt"][:200]

    meetings_list = []
    for item in raw_meetings:
        mtg = item["meeting"]
        ana = item["analysis"]
        meetings_list.append({
            "id": str(mtg["_id"]),
            "title": mtg.get("title", ""),
            "date": mtg.get("date", ""),
            "status": mtg.get("status", ""),
            "sign_off_manager_name": mtg.get("sign_off_manager_name", ""),
            "cqc_count": len(ana.get("cqc_mappings", [])),
            "care_cert_count": len(ana.get("care_cert_mappings", [])),
            "custom_count": len(ana.get("custom_mappings", [])),
        })

    cqc_summary = sorted(cqc_agg.values(), key=lambda x: -x["evidence_count"])
    care_cert_summary = sorted(care_cert_agg.values(), key=lambda x: -x["evidence_count"])
    custom_summary = sorted(custom_agg.values(), key=lambda x: -x["evidence_count"])

    stats = {
        "total_meetings": len(raw_meetings),
        "cqc_count": len(cqc_agg),
        "care_cert_count": len(care_cert_agg),
        "custom_count": len(custom_agg),
        "last_meeting_date": meetings_list[0]["date"] if meetings_list else None,
    }

    return {
        "user": user_data,
        "stats": stats,
        "cqc_summary": cqc_summary,
        "care_cert_summary": care_cert_summary,
        "custom_summary": custom_summary,
        "meetings": meetings_list,
    }


@router.get("/{user_id}")
async def get_portfolio(user_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"] and current_user["id"] != user_id:
        raise HTTPException(status_code=403, detail="You can only view your own portfolio")

    data = await _build_portfolio_data(user_id, db)
    if data is None:
        raise HTTPException(status_code=404, detail="User not found")
    return data


@router.get("/{user_id}/export-pdf")
async def export_portfolio_pdf(user_id: str, db=Depends(get_db), current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"] and current_user["id"] != user_id:
        raise HTTPException(status_code=403, detail="You can only export your own portfolio")

    data = await _build_portfolio_data(user_id, db)
    if data is None:
        raise HTTPException(status_code=404, detail="User not found")

    pdf_bytes = _generate_portfolio_pdf(data)
    safe_name = "".join(c for c in data["user"]["name"] if c.isalnum() or c in " _-").strip().replace(" ", "_")
    filename = f"portfolio_{safe_name}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _generate_portfolio_pdf(data: dict) -> bytes:
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from datetime import datetime as _dt

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)

    NAVY   = colors.HexColor("#1E3A8A")
    TEAL   = colors.HexColor("#0D9488")
    EMERALD = colors.HexColor("#059669")
    MID_GRAY = colors.HexColor("#6B7280")
    LIGHT  = colors.HexColor("#F8FAFC")
    PURPLE_BG = colors.HexColor("#EDE9FE")
    BLUE_BG   = colors.HexColor("#EFF6FF")
    TEAL_BG   = colors.HexColor("#F0FDF4")

    title_s  = ParagraphStyle("T",  fontName="Helvetica-Bold", fontSize=18, textColor=NAVY, spaceAfter=2)
    h2_s     = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=11, textColor=NAVY, spaceAfter=3, spaceBefore=10)
    h3_s     = ParagraphStyle("H3", fontName="Helvetica-Bold", fontSize=9,  textColor=NAVY, spaceAfter=2, spaceBefore=6)
    body_s   = ParagraphStyle("B",  fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#374151"), spaceAfter=2, leading=12)
    small_s  = ParagraphStyle("S",  fontName="Helvetica", fontSize=8, textColor=MID_GRAY, spaceAfter=1, leading=11)
    italic_s = ParagraphStyle("I",  fontName="Helvetica-Oblique", fontSize=8, textColor=MID_GRAY, leading=11, spaceAfter=2)

    def section_hdr(title, bg=NAVY):
        t = Table([[Paragraph(f'<font color="white"><b>{title}</b></font>',
                    ParagraphStyle("SH", fontName="Helvetica-Bold", fontSize=10, textColor=colors.white))]],
                  colWidths=[170*mm])
        t.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,-1), bg),
                                ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
                                ("LEFTPADDING",(0,0),(-1,-1),8)]))
        return t

    def conf_str(c):
        return {"likely_evidence": "Likely Evidence", "needs_review": "Needs Review", "not_enough_evidence": "Not Enough"}.get(c, c)

    story = []
    user = data["user"]
    stats = data["stats"]

    # ── Header ───────────────────────────────────────────────────────────
    story.append(Paragraph("Supervision 2.0 — Staff Evidence Portfolio", small_s))
    story.append(Paragraph(user["name"], title_s))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=4))

    meta = [
        ["Role", user["role"].title(), "Email", user["email"]],
        ["Meetings", str(stats["total_meetings"]), "Last Supervision", str(stats.get("last_meeting_date") or "—")],
    ]
    mt = Table(meta, colWidths=[28*mm, 57*mm, 28*mm, 57*mm])
    mt.setStyle(TableStyle([
        ("FONTNAME",(0,0),(-1,-1),"Helvetica"),("FONTSIZE",(0,0),(-1,-1),9),
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTNAME",(2,0),(2,-1),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,0),(0,-1),MID_GRAY),("TEXTCOLOR",(2,0),(2,-1),MID_GRAY),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("BACKGROUND",(0,0),(-1,-1),LIGHT),("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#E5E7EB")),
    ]))
    story.append(mt)
    story.append(Spacer(1, 4*mm))

    # Stats bar
    stat_rows = [["CQC Regulations Evidenced", "Care Cert Standards", "Custom Criteria", "Total Evidence Items"]]
    total_ev = (sum(s["evidence_count"] for s in data["cqc_summary"]) +
                sum(s["evidence_count"] for s in data["care_cert_summary"]) +
                sum(s["evidence_count"] for s in data["custom_summary"]))
    stat_rows.append([str(stats["cqc_count"]), str(stats["care_cert_count"]), str(stats["custom_count"]), str(total_ev)])
    st = Table(stat_rows, colWidths=[42*mm, 42*mm, 43*mm, 43*mm])
    st.setStyle(TableStyle([
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,0),8),("TEXTCOLOR",(0,0),(-1,0),MID_GRAY),
        ("FONTNAME",(0,1),(-1,1),"Helvetica-Bold"),("FONTSIZE",(0,1),(-1,1),16),("TEXTCOLOR",(0,1),(0,1),NAVY),
        ("TEXTCOLOR",(1,1),(1,1),EMERALD),("TEXTCOLOR",(2,1),(2,1),TEAL),("TEXTCOLOR",(3,1),(3,1),MID_GRAY),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("BACKGROUND",(0,0),(-1,-1),LIGHT),("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#E5E7EB")),
    ]))
    story.append(st)

    # ── CQC Evidence ─────────────────────────────────────────────────────
    if data["cqc_summary"]:
        story.append(Spacer(1, 5*mm))
        story.append(section_hdr("CQC Regulatory Evidence", bg=colors.HexColor("#4C1D95")))
        story.append(Spacer(1, 2*mm))
        for s in data["cqc_summary"]:
            kq = ", ".join(s.get("key_questions", []))
            rows = [[
                Paragraph(f'<b>{s["regulation_ref"]}</b> — {s["regulation_name"]}', body_s),
                Paragraph(f'<b>{s["evidence_count"]}</b> item(s)', small_s),
            ]]
            if kq:
                rows.append([Paragraph(f'Key Questions: {kq}', small_s), ""])
            rows.append([Paragraph(f'Likely: {s["likely_count"]}  |  Needs Review: {s["needs_review_count"]}', small_s), ""])
            dates = ", ".join(sorted(set(r["date"][:10] for r in s.get("meeting_refs", []))))
            if dates:
                rows.append([Paragraph(f'Meetings: {dates}', small_s), ""])
            if s.get("latest_excerpt"):
                rows.append([Paragraph(f'"{s["latest_excerpt"]}"', italic_s), ""])
            t = Table(rows, colWidths=[140*mm, 30*mm])
            t.setStyle(TableStyle([
                ("BACKGROUND",(0,0),(-1,-1),PURPLE_BG),("SPAN",(0,1),(1,1)),("SPAN",(0,2),(1,2)),
                ("SPAN",(0,3),(1,3)),("SPAN",(0,4),(1,4)),
                ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
                ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),
                ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#E5E7EB")),
            ]))
            story.append(t)
            story.append(Spacer(1, 1.5*mm))

    # ── Care Certificate Evidence ─────────────────────────────────────────
    if data["care_cert_summary"]:
        story.append(Spacer(1, 4*mm))
        story.append(section_hdr("Care Certificate Evidence", bg=colors.HexColor("#1E40AF")))
        story.append(Spacer(1, 2*mm))
        for s in data["care_cert_summary"]:
            rows = [[
                Paragraph(f'<b>{s["standard_ref"]}</b> — {s["standard_name"]}', body_s),
                Paragraph(f'<b>{s["evidence_count"]}</b> item(s)', small_s),
            ]]
            if s.get("outcome_ref"):
                rows.append([Paragraph(f'Outcome {s["outcome_ref"]}: {s.get("outcome_name", "")}', small_s), ""])
            rows.append([Paragraph(f'Likely: {s["likely_count"]}  |  Needs Review: {s["needs_review_count"]}', small_s), ""])
            dates = ", ".join(sorted(set(r["date"][:10] for r in s.get("meeting_refs", []))))
            if dates:
                rows.append([Paragraph(f'Meetings: {dates}', small_s), ""])
            if s.get("latest_excerpt"):
                rows.append([Paragraph(f'"{s["latest_excerpt"]}"', italic_s), ""])
            t = Table(rows, colWidths=[140*mm, 30*mm])
            t.setStyle(TableStyle([
                ("BACKGROUND",(0,0),(-1,-1),BLUE_BG),("SPAN",(0,1),(1,1)),("SPAN",(0,2),(1,2)),
                ("SPAN",(0,3),(1,3)),("SPAN",(0,4),(1,4)),
                ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
                ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),
                ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#E5E7EB")),
            ]))
            story.append(t)
            story.append(Spacer(1, 1.5*mm))

    # ── Custom / Organisational Evidence ─────────────────────────────────
    if data["custom_summary"]:
        story.append(Spacer(1, 4*mm))
        story.append(section_hdr("Organisational Standards Evidence", bg=colors.HexColor("#065F46")))
        story.append(Spacer(1, 2*mm))
        for s in data["custom_summary"]:
            rows = [[
                Paragraph(f'<b>{s["criterion_ref"]}</b> — {s["criterion_name"]}', body_s),
                Paragraph(f'<b>{s["evidence_count"]}</b> item(s)', small_s),
            ]]
            if s.get("document_name"):
                rows.append([Paragraph(f'Document: {s["document_name"]}', small_s), ""])
            rows.append([Paragraph(f'Likely: {s["likely_count"]}  |  Needs Review: {s["needs_review_count"]}', small_s), ""])
            dates = ", ".join(sorted(set(r["date"][:10] for r in s.get("meeting_refs", []))))
            if dates:
                rows.append([Paragraph(f'Meetings: {dates}', small_s), ""])
            if s.get("latest_excerpt"):
                rows.append([Paragraph(f'"{s["latest_excerpt"]}"', italic_s), ""])
            t = Table(rows, colWidths=[140*mm, 30*mm])
            t.setStyle(TableStyle([
                ("BACKGROUND",(0,0),(-1,-1),TEAL_BG),("SPAN",(0,1),(1,1)),("SPAN",(0,2),(1,2)),
                ("SPAN",(0,3),(1,3)),("SPAN",(0,4),(1,4)),
                ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
                ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),
                ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#E5E7EB")),
            ]))
            story.append(t)
            story.append(Spacer(1, 1.5*mm))

    # ── Meeting History ───────────────────────────────────────────────────
    if data["meetings"]:
        story.append(Spacer(1, 4*mm))
        story.append(section_hdr("Meeting History", bg=colors.HexColor("#374151")))
        story.append(Spacer(1, 2*mm))
        hdr = [["Date", "Meeting Title", "CQC", "Care Cert", "Custom", "Manager"]]
        rows = hdr + [
            [m["date"][:10] if m.get("date") else "—",
             m.get("title", ""),
             str(m["cqc_count"]),
             str(m["care_cert_count"]),
             str(m["custom_count"]),
             m.get("sign_off_manager_name", "—")]
            for m in data["meetings"]
        ]
        tbl = Table(rows, colWidths=[22*mm, 75*mm, 14*mm, 17*mm, 14*mm, 28*mm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),NAVY),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, LIGHT]),
            ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#E5E7EB")),
            ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
            ("LEFTPADDING",(0,0),(-1,-1),5),
        ]))
        story.append(tbl)

    # ── Footer ───────────────────────────────────────────────────────────
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID_GRAY))
    story.append(Paragraph(
        f"Generated by Supervision 2.0 on {_dt.now().strftime('%d %b %Y %H:%M')} UTC. Confidential.",
        small_s
    ))

    doc.build(story)
    return buf.getvalue()
