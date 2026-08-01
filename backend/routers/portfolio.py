from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
import logging

from deps import get_current_user, get_manager_scope, get_scoped_staff_ids
import database
from utils.redaction import apply_redactions_deep as _apply_redactions_deep

router = APIRouter()
logger = logging.getLogger(__name__)


async def _build_portfolio_data(user_id: str, org_id: str):
    """Aggregate evidence data for a single user across all signed-off meetings."""
    async with database.with_org(org_id) as conn:
        user_row = await conn.fetchrow("SELECT * FROM users WHERE id = $1 AND org_id = $2", user_id, org_id)
    if not user_row:
        return None

    user_doc = dict(user_row)
    user_data = {
        "id": user_doc["id"],
        "name": user_doc.get("name", ""),
        "email": user_doc.get("email", ""),
        "role": user_doc.get("role", ""),
        "team_id": user_doc.get("team_id"),
        "setting_id": user_doc.get("setting_id"),
    }

    # Enrich with team/setting names
    if user_data.get("team_id"):
        try:
            async with database.with_org(org_id) as conn:
                team_row = await conn.fetchrow(
                    "SELECT name FROM teams WHERE id = $1 AND org_id = $2",
                    user_data["team_id"], org_id,
                )
            user_data["team_name"] = team_row["name"] if team_row else None
        except Exception:
            user_data["team_name"] = None
    else:
        user_data["team_name"] = None

    if user_data.get("setting_id"):
        try:
            async with database.with_org(org_id) as conn:
                setting_row = await conn.fetchrow(
                    "SELECT name FROM org_settings WHERE id = $1 AND org_id = $2",
                    user_data["setting_id"], org_id,
                )
            user_data["setting_name"] = setting_row["name"] if setting_row else None
        except Exception:
            user_data["setting_name"] = None
    else:
        user_data["setting_name"] = None

    # Signed-off meetings where this user is an attendee (supervisee, not supervisor)
    async with database.with_org(org_id) as conn:
        meetings_rows = await conn.fetch(
            """SELECT * FROM meetings
               WHERE org_id = $1
                 AND status IN ('signed_off', 'shared')
                 AND analysis_id IS NOT NULL
                 AND (sign_off_manager_id IS NULL OR sign_off_manager_id != $2)
                 AND EXISTS (
                     SELECT 1 FROM jsonb_array_elements(attendees) elem
                     WHERE elem->>'user_id' = $2
                 )
               ORDER BY date DESC
               LIMIT 500""",
            org_id, user_id,
        )

    meetings_list = [dict(r) for r in meetings_rows]

    analysis_ids = [m["analysis_id"] for m in meetings_list if m.get("analysis_id")]
    analyses_map = {}
    if analysis_ids:
        async with database.with_org(org_id) as conn:
            analysis_rows = await conn.fetch(
                "SELECT * FROM analyses WHERE id = ANY($1::text[])",
                analysis_ids,
            )
        analyses_map = {r["id"]: dict(r) for r in analysis_rows}

    raw_meetings = []
    for meeting in meetings_list:
        aid = meeting.get("analysis_id")
        if not aid:
            continue
        adoc = analyses_map.get(aid)
        if adoc:
            redactions = meeting.get("pii_redactions") or []
            if redactions:
                adoc = _apply_redactions_deep(dict(adoc), redactions)
            raw_meetings.append({"meeting": meeting, "analysis": adoc})

    # ── Aggregate by standard ──────────────────────────────────────────────
    cqc_agg = {}
    care_cert_agg = {}
    custom_agg = {}

    for item in raw_meetings:
        mtg = item["meeting"]
        ana = item["analysis"]
        mdate = mtg.get("date", "")
        mid = mtg["id"]

        for m in (ana.get("cqc_mappings") or []):
            key = m.get("regulation_ref", "—")
            if key not in cqc_agg:
                cqc_agg[key] = {
                    "regulation_ref": m.get("regulation_ref", ""),
                    "regulation_name": m.get("regulation_name", ""),
                    "key_questions": m.get("key_questions", []),
                    "evidence_count": 0, "likely_count": 0, "needs_review_count": 0,
                    "meeting_refs": [], "latest_excerpt": None, "source_meeting_id": None,
                }
            e = cqc_agg[key]
            e["evidence_count"] += 1
            if m.get("confidence") == "likely_evidence":
                e["likely_count"] += 1
            elif m.get("confidence") == "needs_review":
                e["needs_review_count"] += 1
            ref_entry = {"date": mdate, "id": mid, "title": mtg.get("title", "")}
            if ref_entry not in e["meeting_refs"]:
                e["meeting_refs"].append(ref_entry)
            if m.get("transcript_excerpt"):
                e["latest_excerpt"] = m["transcript_excerpt"][:200]
                e["source_meeting_id"] = mid

        for m in (ana.get("care_cert_mappings") or []):
            key = m.get("standard_ref", "—") + "::" + m.get("outcome_ref", "")
            if key not in care_cert_agg:
                care_cert_agg[key] = {
                    "standard_ref": m.get("standard_ref", ""),
                    "standard_name": m.get("standard_name", ""),
                    "outcome_ref": m.get("outcome_ref", ""),
                    "outcome_name": m.get("outcome_name", ""),
                    "evidence_count": 0, "likely_count": 0, "needs_review_count": 0,
                    "meeting_refs": [], "latest_excerpt": None, "source_meeting_id": None,
                }
            e = care_cert_agg[key]
            e["evidence_count"] += 1
            if m.get("confidence") == "likely_evidence":
                e["likely_count"] += 1
            elif m.get("confidence") == "needs_review":
                e["needs_review_count"] += 1
            ref_entry = {"date": mdate, "id": mid, "title": mtg.get("title", "")}
            if ref_entry not in e["meeting_refs"]:
                e["meeting_refs"].append(ref_entry)
            if m.get("transcript_excerpt"):
                e["latest_excerpt"] = m["transcript_excerpt"][:200]
                e["source_meeting_id"] = mid

        for m in (ana.get("custom_mappings") or []):
            key = m.get("document_id", "") + "::" + m.get("criterion_ref", "—")
            if key not in custom_agg:
                custom_agg[key] = {
                    "document_id": m.get("document_id", ""),
                    "document_name": m.get("document_name", ""),
                    "criterion_ref": m.get("criterion_ref", ""),
                    "criterion_name": m.get("criterion_name", ""),
                    "evidence_count": 0, "likely_count": 0, "needs_review_count": 0,
                    "meeting_refs": [], "latest_excerpt": None, "source_meeting_id": None,
                }
            e = custom_agg[key]
            e["evidence_count"] += 1
            if m.get("confidence") == "likely_evidence":
                e["likely_count"] += 1
            elif m.get("confidence") == "needs_review":
                e["needs_review_count"] += 1
            ref_entry = {"date": mdate, "id": mid, "title": mtg.get("title", "")}
            if ref_entry not in e["meeting_refs"]:
                e["meeting_refs"].append(ref_entry)
            if m.get("transcript_excerpt"):
                e["latest_excerpt"] = m["transcript_excerpt"][:200]
                e["source_meeting_id"] = mid

    meetings_summary = []
    for item in raw_meetings:
        mtg = item["meeting"]
        ana = item["analysis"]
        meetings_summary.append({
            "id": mtg["id"],
            "title": mtg.get("title", ""),
            "date": mtg.get("date", ""),
            "status": mtg.get("status", ""),
            "sign_off_manager_name": mtg.get("sign_off_manager_name", ""),
            "cqc_count": len(ana.get("cqc_mappings") or []),
            "care_cert_count": len(ana.get("care_cert_mappings") or []),
            "custom_count": len(ana.get("custom_mappings") or []),
        })

    cqc_summary = sorted(cqc_agg.values(), key=lambda x: -x["evidence_count"])
    care_cert_summary = sorted(care_cert_agg.values(), key=lambda x: -x["evidence_count"])
    custom_summary = sorted(custom_agg.values(), key=lambda x: -x["evidence_count"])

    stats = {
        "total_meetings": len(raw_meetings),
        "cqc_count": len(cqc_agg),
        "care_cert_count": len(care_cert_agg),
        "custom_count": len(custom_agg),
        "last_meeting_date": meetings_summary[0]["date"] if meetings_summary else None,
    }

    return {
        "user": user_data,
        "stats": stats,
        "cqc_summary": cqc_summary,
        "care_cert_summary": care_cert_summary,
        "custom_summary": custom_summary,
        "meetings": meetings_summary,
    }


@router.get("/{user_id}")
async def get_portfolio(user_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"] and current_user["id"] != user_id:
        raise HTTPException(status_code=403, detail="You can only view your own portfolio")
    org_id = current_user.get("org_id", "")

    # Scoped managers may only view portfolios of staff within their scope
    if current_user["role"] == "manager" and current_user["id"] != user_id:
        scope = get_manager_scope(current_user)
        if scope["level"] != "org":
            async with database.with_org(org_id) as conn:
                scoped_ids = await get_scoped_staff_ids(conn, org_id, scope) or []
            if user_id not in scoped_ids:
                raise HTTPException(status_code=403, detail="You can only view portfolios of staff in your scope")

    data = await _build_portfolio_data(user_id, org_id)
    if data is None:
        raise HTTPException(status_code=404, detail="User not found")
    return data


@router.get("/{user_id}/export-pdf")
async def export_portfolio_pdf(user_id: str, current_user=Depends(get_current_user)):
    if current_user["role"] not in ["admin", "manager"] and current_user["id"] != user_id:
        raise HTTPException(status_code=403, detail="You can only export your own portfolio")
    org_id = current_user.get("org_id", "")

    # Scoped managers may only export portfolios of staff within their scope
    if current_user["role"] == "manager" and current_user["id"] != user_id:
        scope = get_manager_scope(current_user)
        if scope["level"] != "org":
            async with database.with_org(org_id) as conn:
                scoped_ids = await get_scoped_staff_ids(conn, org_id, scope) or []
            if user_id not in scoped_ids:
                raise HTTPException(status_code=403, detail="You can only export portfolios of staff in your scope")
    org_id = current_user.get("org_id", "")
    data = await _build_portfolio_data(user_id, org_id)
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
    from xml.sax.saxutils import escape as _xe
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from datetime import datetime as _dt

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)

    NAVY = colors.HexColor("#1E3A8A")
    TEAL = colors.HexColor("#0D9488")
    EMERALD = colors.HexColor("#059669")
    MID_GRAY = colors.HexColor("#6B7280")
    LIGHT = colors.HexColor("#F8FAFC")
    PURPLE_BG = colors.HexColor("#EDE9FE")
    BLUE_BG = colors.HexColor("#EFF6FF")
    TEAL_BG = colors.HexColor("#F0FDF4")

    title_s = ParagraphStyle("T", fontName="Helvetica-Bold", fontSize=18, textColor=NAVY, spaceAfter=2)
    body_s = ParagraphStyle("B", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#374151"), spaceAfter=2, leading=12)
    small_s = ParagraphStyle("S", fontName="Helvetica", fontSize=8, textColor=MID_GRAY, spaceAfter=1, leading=11)
    italic_s = ParagraphStyle("I", fontName="Helvetica-Oblique", fontSize=8, textColor=MID_GRAY, leading=11, spaceAfter=2)

    def e(t): return _xe(str(t or ""))

    def section_hdr(title, bg=NAVY):
        t = Table([[Paragraph(f'<font color="white"><b>{title}</b></font>',
                    ParagraphStyle("SH", fontName="Helvetica-Bold", fontSize=10, textColor=colors.white))]],
                  colWidths=[170*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]))
        return t

    story = []
    user = data["user"]
    stats = data["stats"]

    story.append(Paragraph("Supervision 2.0 — Staff Evidence Portfolio", small_s))
    story.append(Paragraph(e(user["name"]), title_s))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=4))

    meta = [
        ["Role", user["role"].title(), "Email", user["email"]],
        ["Meetings", str(stats["total_meetings"]), "Last Supervision", str(stats.get("last_meeting_date") or "—")],
    ]
    mt = Table(meta, colWidths=[28*mm, 57*mm, 28*mm, 57*mm])
    mt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), MID_GRAY),
        ("TEXTCOLOR", (2, 0), (2, -1), MID_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
    ]))
    story.append(mt)
    story.append(Spacer(1, 4*mm))

    stat_rows = [["CQC Regulations Evidenced", "Care Cert Standards", "Custom Criteria", "Total Evidence Items"]]
    total_ev = (sum(s["evidence_count"] for s in data["cqc_summary"]) +
                sum(s["evidence_count"] for s in data["care_cert_summary"]) +
                sum(s["evidence_count"] for s in data["custom_summary"]))
    stat_rows.append([str(stats["cqc_count"]), str(stats["care_cert_count"]), str(stats["custom_count"]), str(total_ev)])
    st = Table(stat_rows, colWidths=[42*mm, 42*mm, 43*mm, 43*mm])
    st.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), MID_GRAY),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, 1), 16),
        ("TEXTCOLOR", (0, 1), (0, 1), NAVY),
        ("TEXTCOLOR", (1, 1), (1, 1), EMERALD),
        ("TEXTCOLOR", (2, 1), (2, 1), TEAL),
        ("TEXTCOLOR", (3, 1), (3, 1), MID_GRAY),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
    ]))
    story.append(st)

    if data["cqc_summary"]:
        story.append(Spacer(1, 5*mm))
        story.append(section_hdr("CQC Regulatory Evidence", bg=colors.HexColor("#4C1D95")))
        story.append(Spacer(1, 2*mm))
        for s in data["cqc_summary"]:
            kq = ", ".join(s.get("key_questions", []))
            rows = [[
                Paragraph(f'<b>{e(s["regulation_ref"])}</b> — {e(s["regulation_name"])}', body_s),
                Paragraph(f'<b>{s["evidence_count"]}</b> item(s)', small_s),
            ]]
            if kq:
                rows.append([Paragraph(f'Key Questions: {e(kq)}', small_s), ""])
            rows.append([Paragraph(f'Likely: {s["likely_count"]}  |  Needs Review: {s["needs_review_count"]}', small_s), ""])
            dates = ", ".join(sorted(set(r["date"][:10] for r in s.get("meeting_refs", []))))
            if dates:
                rows.append([Paragraph(f'Meetings: {e(dates)}', small_s), ""])
            if s.get("latest_excerpt"):
                rows.append([Paragraph(f'&#34;{e(s["latest_excerpt"])}&#34;', italic_s), ""])
            t = Table(rows, colWidths=[140*mm, 30*mm])
            span_styles = [
                ("BACKGROUND", (0, 0), (-1, -1), PURPLE_BG),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
            ]
            for i in range(1, len(rows)):
                span_styles.append(("SPAN", (0, i), (1, i)))
            t.setStyle(TableStyle(span_styles))
            story.append(t)
            story.append(Spacer(1, 1.5*mm))

    if data["care_cert_summary"]:
        story.append(Spacer(1, 4*mm))
        story.append(section_hdr("Care Certificate Evidence", bg=colors.HexColor("#1E40AF")))
        story.append(Spacer(1, 2*mm))
        for s in data["care_cert_summary"]:
            rows = [[
                Paragraph(f'<b>{e(s["standard_ref"])}</b> — {e(s["standard_name"])}', body_s),
                Paragraph(f'<b>{s["evidence_count"]}</b> item(s)', small_s),
            ]]
            if s.get("outcome_ref"):
                rows.append([Paragraph(f'Outcome {e(s["outcome_ref"])}: {e(s.get("outcome_name", ""))}', small_s), ""])
            rows.append([Paragraph(f'Likely: {s["likely_count"]}  |  Needs Review: {s["needs_review_count"]}', small_s), ""])
            dates = ", ".join(sorted(set(r["date"][:10] for r in s.get("meeting_refs", []))))
            if dates:
                rows.append([Paragraph(f'Meetings: {e(dates)}', small_s), ""])
            if s.get("latest_excerpt"):
                rows.append([Paragraph(f'&#34;{e(s["latest_excerpt"])}&#34;', italic_s), ""])
            t = Table(rows, colWidths=[140*mm, 30*mm])
            span_styles = [
                ("BACKGROUND", (0, 0), (-1, -1), BLUE_BG),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
            ]
            for i in range(1, len(rows)):
                span_styles.append(("SPAN", (0, i), (1, i)))
            t.setStyle(TableStyle(span_styles))
            story.append(t)
            story.append(Spacer(1, 1.5*mm))

    if data["custom_summary"]:
        story.append(Spacer(1, 4*mm))
        story.append(section_hdr("Organisational Standards Evidence", bg=colors.HexColor("#065F46")))
        story.append(Spacer(1, 2*mm))
        for s in data["custom_summary"]:
            rows = [[
                Paragraph(f'<b>{e(s["criterion_ref"])}</b> — {e(s["criterion_name"])}', body_s),
                Paragraph(f'<b>{s["evidence_count"]}</b> item(s)', small_s),
            ]]
            if s.get("document_name"):
                rows.append([Paragraph(f'Document: {e(s["document_name"])}', small_s), ""])
            rows.append([Paragraph(f'Likely: {s["likely_count"]}  |  Needs Review: {s["needs_review_count"]}', small_s), ""])
            dates = ", ".join(sorted(set(r["date"][:10] for r in s.get("meeting_refs", []))))
            if dates:
                rows.append([Paragraph(f'Meetings: {e(dates)}', small_s), ""])
            if s.get("latest_excerpt"):
                rows.append([Paragraph(f'&#34;{e(s["latest_excerpt"])}&#34;', italic_s), ""])
            t = Table(rows, colWidths=[140*mm, 30*mm])
            span_styles = [
                ("BACKGROUND", (0, 0), (-1, -1), TEAL_BG),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
            ]
            for i in range(1, len(rows)):
                span_styles.append(("SPAN", (0, i), (1, i)))
            t.setStyle(TableStyle(span_styles))
            story.append(t)
            story.append(Spacer(1, 1.5*mm))

    if data["meetings"]:
        story.append(Spacer(1, 4*mm))
        story.append(section_hdr("Meeting History", bg=colors.HexColor("#374151")))
        story.append(Spacer(1, 2*mm))
        hdr = [["Date", "Meeting Title", "CQC", "Care Cert", "Custom", "Manager"]]
        tbl_rows = hdr + [
            [m["date"][:10] if m.get("date") else "—",
             m.get("title", ""),
             str(m["cqc_count"]),
             str(m["care_cert_count"]),
             str(m["custom_count"]),
             m.get("sign_off_manager_name", "—")]
            for m in data["meetings"]
        ]
        tbl = Table(tbl_rows, colWidths=[22*mm, 75*mm, 14*mm, 17*mm, 14*mm, 28*mm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tbl)

    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID_GRAY))
    story.append(Paragraph(
        f"Generated by 1two.one on {_dt.now().strftime('%d %b %Y %H:%M')} UTC. Confidential.",
        small_s
    ))

    doc.build(story)
    return buf.getvalue()
