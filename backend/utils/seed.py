"""
PostgreSQL seed: system standards (England + Wales), super admin, default org.
Called once on startup — all operations are idempotent.
"""
from datetime import datetime, timezone
import uuid
import logging
import os
import json

import database

logger = logging.getLogger(__name__)

# ── CQC Regulations ───────────────────────────────────────────────────────────

CQC_REGULATIONS = [
    {"reference": "Regulation 9",  "name": "Person-centred care", "key_questions": ["Effective", "Responsive"], "description": "Care and treatment must be appropriate and meet the needs and preferences of service users. Providers must involve service users in planning and decision-making.", "keywords": ["person-centred", "care plan", "individual needs", "preferences", "wishes", "involvement", "choices"]},
    {"reference": "Regulation 10", "name": "Dignity and respect", "key_questions": ["Caring", "Responsive"], "description": "Service users must be treated with dignity and respect at all times. Workers must respect the person's right to privacy and treat them as an individual.", "keywords": ["dignity", "respect", "privacy", "independence", "choices", "equal treatment", "individuality"]},
    {"reference": "Regulation 11", "name": "Need for consent", "key_questions": ["Effective", "Caring"], "description": "Care and treatment must only be provided with the consent of the relevant person. Providers must have regard to mental capacity and best interest decisions.", "keywords": ["consent", "mental capacity", "best interests", "lasting power of attorney", "advance decision", "capacity"]},
    {"reference": "Regulation 12", "name": "Safe care and treatment", "key_questions": ["Safe", "Effective"], "description": "Care and treatment must be provided in a safe way. Includes medication management, nutrition, hydration, risk assessment, and infection prevention and control.", "keywords": ["safe", "risk assessment", "medications", "nutrition", "hydration", "infection prevention", "equipment", "falls", "pressure sores"]},
    {"reference": "Regulation 13", "name": "Safeguarding service users from abuse and improper treatment", "key_questions": ["Safe"], "description": "Service users must be protected from abuse and improper treatment. Providers must have safeguarding policies and act on any concerns.", "keywords": ["safeguarding", "abuse", "neglect", "improper treatment", "restraint", "deprivation of liberty", "DoLS", "MCA", "whistleblowing"]},
    {"reference": "Regulation 14", "name": "Meeting nutritional and hydration needs", "key_questions": ["Safe", "Effective", "Caring"], "description": "Service users must have adequate nutrition and hydration. Providers must ensure food and drink meets service users' needs and preferences.", "keywords": ["nutrition", "hydration", "meals", "diet", "weight", "fluids", "food", "malnutrition", "dehydration"]},
    {"reference": "Regulation 15", "name": "Premises and equipment", "key_questions": ["Safe", "Effective"], "description": "Premises and equipment used must be clean, secure, suitable, properly used, maintained and appropriately located.", "keywords": ["premises", "equipment", "environment", "maintenance", "infection control", "cleanliness", "safety"]},
    {"reference": "Regulation 16", "name": "Receiving and acting on complaints", "key_questions": ["Responsive", "Well-led"], "description": "Service users must be able to make complaints about care received. Providers must have an accessible complaints process and act on complaints.", "keywords": ["complaints", "concerns", "feedback", "investigation", "response", "resolution", "whistleblowing"]},
    {"reference": "Regulation 17", "name": "Good governance", "key_questions": ["Well-led"], "description": "Providers must have effective governance frameworks, assess and monitor quality and safety, maintain accurate records, and seek and act on feedback.", "keywords": ["governance", "quality", "audit", "records", "risk management", "improvement", "CQC notifications", "oversight"]},
    {"reference": "Regulation 18", "name": "Staffing", "key_questions": ["Safe", "Effective", "Well-led"], "description": "Sufficient numbers of suitably qualified, competent, skilled and experienced staff must be deployed. Staff must receive appropriate support, training, professional development, supervision and appraisal.", "keywords": ["staffing", "training", "competency", "supervision", "induction", "workforce", "sickness", "agency", "qualifications", "appraisal", "development"]},
    {"reference": "Regulation 19", "name": "Fit and proper persons employed", "key_questions": ["Safe", "Well-led"], "description": "Providers must only employ persons who are of good character, have the necessary qualifications, skills and experience, are able to properly perform their duties.", "keywords": ["DBS", "references", "qualifications", "fit and proper", "employment checks", "barring", "criminal record"]},
    {"reference": "Regulation 20", "name": "Duty of candour", "key_questions": ["Well-led", "Caring"], "description": "Providers must be open and honest with service users when something goes wrong that results in harm or could result in harm.", "keywords": ["duty of candour", "openness", "transparency", "honesty", "notification of harm", "apology", "incident"]},
    {"reference": "Regulation 20A", "name": "Requirement as to display of performance assessments", "key_questions": ["Well-led"], "description": "Providers must display their CQC performance rating in a prominent place.", "keywords": ["CQC rating", "display", "performance assessment", "inspection"]},
]

CQC_QUALITY_STATEMENTS = [
    {"reference": "QS Safe 1",  "name": "Learning culture", "key_questions": ["Safe"], "quality_statement": True, "description": "We have a proactive and positive culture of safety based on openness and honesty, in which concerns about safety are investigated and reported thoroughly, and lessons are learned to continually identify and embed good practices.", "keywords": ["learning culture", "safety culture", "openness", "honesty", "lessons learned", "incident reporting", "good practice", "continuous improvement"]},
    {"reference": "QS Safe 2",  "name": "Safe systems, pathways and transitions", "key_questions": ["Safe"], "quality_statement": True, "description": "We work with people and our partners to establish and maintain safe systems of care, in which safety is managed, monitored and assured. We ensure continuity of care, including when people move between different services.", "keywords": ["safe systems", "pathways", "transitions", "continuity of care", "monitoring", "assurance", "handover", "discharge"]},
    {"reference": "QS Safe 3",  "name": "Safeguarding", "key_questions": ["Safe"], "quality_statement": True, "description": "We work with people to understand what being safe means to them as well as with our partners on the best way to achieve this. We concentrate on improving people's lives while protecting their right to live in safety, free from bullying, harassment, abuse, discrimination, avoidable harm and neglect.", "keywords": ["safeguarding", "abuse", "neglect", "harm", "bullying", "harassment", "discrimination", "concerns", "protection"]},
    {"reference": "QS Safe 4",  "name": "Involving people to manage risks", "key_questions": ["Safe"], "quality_statement": True, "description": "We work with people to understand and manage risks by thinking holistically so that care meets their needs in a way that is safe and supportive and enables them to do the things that matter to them.", "keywords": ["risk management", "risk assessment", "holistic", "involvement", "positive risk", "enabling", "safety"]},
    {"reference": "QS Safe 5",  "name": "Safe environments", "key_questions": ["Safe"], "quality_statement": True, "description": "We detect and control potential risks in the care environment. We make sure that equipment, facilities and technology support the delivery of safe care.", "keywords": ["environment", "equipment", "facilities", "technology", "risk", "health and safety", "premises"]},
    {"reference": "QS Safe 6",  "name": "Safe and effective staffing", "key_questions": ["Safe"], "quality_statement": True, "description": "We make sure there are enough qualified, skilled and experienced people, who receive effective support, supervision and development. They work together effectively to provide safe care that meets people's individual needs.", "keywords": ["staffing", "qualified", "skilled", "supervision", "support", "development", "workforce", "appraisal", "training"]},
    {"reference": "QS Safe 7",  "name": "Infection prevention and control", "key_questions": ["Safe"], "quality_statement": True, "description": "We assess and manage the risk of infection. We detect and control the risk of it spreading and share any concerns with appropriate agencies promptly.", "keywords": ["infection", "IPC", "prevention", "control", "hygiene", "PPE", "spreading", "risk"]},
    {"reference": "QS Safe 8",  "name": "Medicines optimisation", "key_questions": ["Safe"], "quality_statement": True, "description": "We make sure that medicines and treatments are safe and meet people's needs, capacities and preferences by enabling them to be involved in planning, including when changes happen.", "keywords": ["medicines", "medication", "treatment", "capacity", "preferences", "prescribing", "administration", "MAR", "medication management"]},
    {"reference": "QS Effective 1", "name": "Assessing needs", "key_questions": ["Effective"], "quality_statement": True, "description": "We maximise the effectiveness of people's care and treatment by assessing and reviewing their health, care, wellbeing and communication needs with them.", "keywords": ["assessment", "needs assessment", "health", "wellbeing", "communication needs", "review", "care planning"]},
    {"reference": "QS Effective 2", "name": "Delivering evidence-based care", "key_questions": ["Effective"], "quality_statement": True, "description": "We plan and deliver people's care and treatment with them, including what is important and matters to them. We do this in line with legislation and current evidence-based good practice and standards.", "keywords": ["evidence-based", "care planning", "legislation", "best practice", "standards", "NICE guidance", "clinical guidelines"]},
    {"reference": "QS Effective 3", "name": "How staff and teams work together", "key_questions": ["Effective"], "quality_statement": True, "description": "We work effectively across teams and services to support people. We make sure they only need to tell their story once by sharing their assessment of needs when they move between different services.", "keywords": ["teamwork", "collaboration", "information sharing", "multi-disciplinary", "handover", "integrated care", "MDT"]},
    {"reference": "QS Effective 4", "name": "Supporting people to live healthier lives", "key_questions": ["Effective"], "quality_statement": True, "description": "We support people to manage their health and wellbeing so they can maximise their independence, choice and control. We support them to live healthier lives and where possible, reduce their future needs for care and support.", "keywords": ["independence", "choice", "control", "health promotion", "wellbeing", "self-management", "prevention"]},
    {"reference": "QS Effective 5", "name": "Monitoring and improving outcomes", "key_questions": ["Effective"], "quality_statement": True, "description": "We routinely monitor people's care and treatment to continuously improve it. We ensure that outcomes are positive and consistent, and that they meet both clinical expectations and the expectations of people themselves.", "keywords": ["outcomes", "monitoring", "improvement", "quality", "audit", "review", "consistency"]},
    {"reference": "QS Effective 6", "name": "Consent to care and treatment", "key_questions": ["Effective"], "quality_statement": True, "description": "We tell people about their rights around consent and respect these when we deliver person-centred care and treatment.", "keywords": ["consent", "rights", "person-centred", "mental capacity", "best interests", "informed consent", "decision-making"]},
    {"reference": "QS Caring 1", "name": "Kindness, compassion and dignity", "key_questions": ["Caring"], "quality_statement": True, "description": "We always treat people with kindness, empathy and compassion and we respect their privacy and dignity. We treat colleagues from other organisations with kindness and respect.", "keywords": ["kindness", "compassion", "dignity", "empathy", "respect", "privacy", "emotional support"]},
    {"reference": "QS Caring 2", "name": "Treating people as individuals", "key_questions": ["Caring"], "quality_statement": True, "description": "We treat people as individuals and make sure their care, support and treatment meets their needs and preferences. We take account of their strengths, abilities, aspirations, culture and unique backgrounds and protected characteristics.", "keywords": ["individual", "person-centred", "diversity", "protected characteristics", "culture", "preferences", "strengths", "aspirations"]},
    {"reference": "QS Caring 3", "name": "Independence, choice and control", "key_questions": ["Caring"], "quality_statement": True, "description": "We promote people's independence, so they know their rights and have choice and control over their own care, treatment and wellbeing.", "keywords": ["independence", "choice", "control", "rights", "empowerment", "autonomy", "self-determination"]},
    {"reference": "QS Caring 4", "name": "Responding to people's immediate needs", "key_questions": ["Caring"], "quality_statement": True, "description": "We listen to and understand people's needs, views and wishes. We respond to these in that moment and will act to minimise any discomfort, concern or distress.", "keywords": ["listening", "immediate needs", "distress", "comfort", "responsive", "empathy", "wishes", "wellbeing"]},
    {"reference": "QS Caring 5", "name": "Workforce wellbeing and enablement", "key_questions": ["Caring"], "quality_statement": True, "description": "We care about the wellbeing of our staff, and we support and enable them to deliver person-centred care.", "keywords": ["staff wellbeing", "support", "enablement", "resilience", "occupational health", "burnout", "morale"]},
    {"reference": "QS Responsive 1", "name": "Person centred care", "key_questions": ["Responsive"], "quality_statement": True, "description": "We make sure people are at the centre of their care and treatment choices and we decide, in partnership with them, how to respond to any relevant changes in their needs.", "keywords": ["person-centred", "choices", "partnership", "co-production", "involvement", "changing needs"]},
    {"reference": "QS Responsive 2", "name": "Care provision, integration and continuity", "key_questions": ["Responsive"], "quality_statement": True, "description": "We understand the diverse health and care needs of people and our local communities, so care is joined-up, flexible and supports choice and continuity.", "keywords": ["continuity", "flexible", "joined-up", "integration", "diverse needs", "community", "coordination"]},
    {"reference": "QS Responsive 3", "name": "Providing information", "key_questions": ["Responsive"], "quality_statement": True, "description": "We provide appropriate, accurate and up-to-date information in formats that we tailor to individual needs.", "keywords": ["information", "accessible formats", "easy read", "communication", "tailored", "accurate", "up-to-date"]},
    {"reference": "QS Responsive 4", "name": "Listening to and involving people", "key_questions": ["Responsive"], "quality_statement": True, "description": "We make it easy for people to share feedback and ideas or raise complaints about their care, treatment and support. We involve them in decisions about their care and tell them what's changed as a result.", "keywords": ["feedback", "complaints", "involvement", "co-production", "listening", "acting on feedback", "participation"]},
    {"reference": "QS Responsive 5", "name": "Equity in access", "key_questions": ["Responsive"], "quality_statement": True, "description": "We make sure that everyone can access the care, support and treatment they need when they need it.", "keywords": ["equity", "access", "equality", "inclusion", "barriers", "timely", "availability"]},
    {"reference": "QS Responsive 6", "name": "Equity in experiences and outcomes", "key_questions": ["Responsive"], "quality_statement": True, "description": "We actively seek out and listen to information about people who are most likely to experience inequality in experience or outcomes. We tailor the care, support and treatment in response to this.", "keywords": ["equity", "inequality", "outcomes", "equality", "monitoring", "diversity", "protected characteristics", "health inequalities"]},
    {"reference": "QS Responsive 7", "name": "Planning for the future", "key_questions": ["Responsive"], "quality_statement": True, "description": "We support people to plan for important life changes, so they can have enough time to make informed decisions about their future, including at the end of life.", "keywords": ["future planning", "advance care planning", "end of life", "informed decisions", "life changes", "DNACPR", "preferred place of care"]},
    {"reference": "QS Well-led 1", "name": "Shared direction and culture", "key_questions": ["Well-led"], "quality_statement": True, "description": "We have a shared vision, strategy and culture. This is based on transparency, equity, equality and human rights, diversity and inclusion, engagement, and understanding challenges and the needs of people and our communities.", "keywords": ["vision", "strategy", "culture", "transparency", "equity", "equality", "human rights", "diversity", "inclusion", "values"]},
    {"reference": "QS Well-led 2", "name": "Capable, compassionate and inclusive leaders", "key_questions": ["Well-led"], "quality_statement": True, "description": "We have inclusive leaders at all levels who understand the context in which we deliver care, treatment and support and embody the culture and values of their workforce and organisation.", "keywords": ["leadership", "inclusive", "capable", "compassionate", "culture", "values", "context", "role model"]},
    {"reference": "QS Well-led 3", "name": "Freedom to speak up", "key_questions": ["Well-led"], "quality_statement": True, "description": "They have the skills, knowledge, experience and credibility to lead effectively. They do so with integrity, openness and honesty.", "keywords": ["speak up", "integrity", "openness", "honesty", "credibility", "skills", "knowledge", "whistleblowing", "psychological safety"]},
    {"reference": "QS Well-led 4", "name": "Workforce equality, diversity and inclusion", "key_questions": ["Well-led"], "quality_statement": True, "description": "We foster a positive culture where people feel that they can speak up and that their voice will be heard. We value diversity in our workforce.", "keywords": ["equality", "diversity", "inclusion", "EDI", "workforce", "culture", "belonging", "fair", "voice"]},
    {"reference": "QS Well-led 5", "name": "Governance, management and sustainability", "key_questions": ["Well-led"], "quality_statement": True, "description": "We have clear responsibilities, roles, systems of accountability and good governance. We use these to manage and deliver good quality, sustainable care. We act on the best information about risk, performance and outcomes.", "keywords": ["governance", "accountability", "roles", "responsibilities", "quality", "sustainability", "risk management", "performance", "oversight"]},
    {"reference": "QS Well-led 6", "name": "Partnerships and communities", "key_questions": ["Well-led"], "quality_statement": True, "description": "We understand our duty to collaborate and work in partnership, so our services work seamlessly for people. We share information and learning with partners and collaborate for improvement.", "keywords": ["partnership", "collaboration", "integration", "information sharing", "community", "joined-up", "learning"]},
    {"reference": "QS Well-led 7", "name": "Learning, improvement and innovation", "key_questions": ["Well-led"], "quality_statement": True, "description": "We focus on continuous learning, innovation and improvement across our organisation and the local system. We encourage creative ways of delivering equality of experience, outcome and quality of life for people.", "keywords": ["learning", "improvement", "innovation", "continuous improvement", "quality improvement", "research", "creativity"]},
    {"reference": "QS Well-led 8", "name": "Environmental sustainability", "key_questions": ["Well-led"], "quality_statement": True, "description": "We focus on sustainable development. We actively contribute to safe, effective practice and research and promote environmental sustainability.", "keywords": ["sustainability", "environment", "green", "net zero", "sustainable development", "research", "practice"]},
]

CARE_CERT_STANDARDS = [
    {"reference": "Standard 1",  "name": "Understand your role", "description": "The care worker understands their role and responsibilities, the importance of working within their scope of practice, and the impact of their role on the person they support.", "keywords": ["role", "responsibilities", "boundaries", "scope of practice", "code of conduct", "accountability"], "sub_outcomes": []},
    {"reference": "Standard 2",  "name": "Your personal development", "description": "The care worker is committed to their personal development, including training, learning, CPD, and reflective practice. Includes supervision and appraisal.", "keywords": ["training", "learning", "CPD", "personal development", "reflective practice", "supervision", "appraisal", "development"], "sub_outcomes": []},
    {"reference": "Standard 3",  "name": "Duty of care", "description": "The care worker understands their duty of care and how to balance this with an individual's rights. Includes dilemmas, complaints and incidents.", "keywords": ["duty of care", "duty of candour", "dilemmas", "complaints", "incidents", "rights", "wellbeing", "safeguarding"], "sub_outcomes": []},
    {"reference": "Standard 4",  "name": "Equality, diversity, inclusion and human rights", "description": "The care worker works in an inclusive way that values diversity and treats people as individuals, respecting protected characteristics and challenging discrimination.", "keywords": ["equality", "diversity", "inclusion", "human rights", "discrimination", "protected characteristics", "individual needs", "culture", "religion"], "sub_outcomes": []},
    {"reference": "Standard 5",  "name": "Work in a person-centred way", "description": "The care worker puts the individual at the centre of care, supporting their choices, promoting their wellbeing and independence.", "keywords": ["person-centred", "choices", "independence", "wellbeing", "preferences", "self-determination", "mental capacity", "consent", "dignity"], "sub_outcomes": []},
    {"reference": "Standard 6",  "name": "Communication", "description": "The care worker communicates effectively in verbal and non-verbal ways, adapts to individuals' communication needs, and maintains accurate records.", "keywords": ["communication", "listening", "non-verbal", "language needs", "records", "handover", "reporting", "documentation", "confidentiality"], "sub_outcomes": []},
    {"reference": "Standard 7",  "name": "Privacy and dignity", "description": "The care worker promotes and maintains the privacy, dignity and respect of each individual in their care, including supporting active participation and informed choice.", "keywords": ["privacy", "dignity", "respect", "confidentiality", "personal information", "intimate care", "active participation", "choices"], "sub_outcomes": []},
    {"reference": "Standard 8",  "name": "Fluids and nutrition", "description": "The care worker supports individuals to have adequate nutrition and hydration, understands signs of malnutrition and dehydration.", "keywords": ["nutrition", "hydration", "fluid intake", "malnutrition", "dehydration", "diet", "eating", "drinking", "mealtime", "food safety"], "sub_outcomes": []},
    {"reference": "Standard 9",  "name": "Awareness of mental health and dementia", "description": "The care worker has awareness of mental health conditions and dementia, including how these affect individuals' wellbeing, behaviour and the reasonable adjustments required in care delivery.", "keywords": ["mental health", "dementia", "behaviour", "wellbeing", "cognitive impairment", "anxiety", "depression", "positive attitudes", "reasonable adjustments"], "sub_outcomes": []},
    {"reference": "Standard 10", "name": "Safeguarding adults", "description": "The care worker understands adult safeguarding, recognises signs of abuse and neglect, and knows how to report concerns.", "keywords": ["safeguarding", "abuse", "neglect", "reporting", "whistleblowing", "protection", "harm", "exploitation", "concerns", "restrictive practices"], "sub_outcomes": []},
    {"reference": "Standard 11", "name": "Safeguarding children", "description": "The care worker is aware of child safeguarding responsibilities even when primarily working with adults.", "keywords": ["safeguarding children", "child protection", "young carers", "children", "abuse", "neglect"], "sub_outcomes": []},
    {"reference": "Standard 12", "name": "Basic life support", "description": "The care worker knows how to provide basic life support, including CPR, and can respond to emergency situations.", "keywords": ["first aid", "CPR", "resuscitation", "basic life support", "emergency", "AED", "choking"], "sub_outcomes": []},
    {"reference": "Standard 13", "name": "Health and safety", "description": "The care worker understands health and safety legislation, risk assessment, moving and handling, medication, fire safety, security and personal wellbeing.", "keywords": ["health and safety", "risk assessment", "COSHH", "moving and handling", "manual handling", "PPE", "lone working", "fire safety", "medication", "security"], "sub_outcomes": []},
    {"reference": "Standard 14", "name": "Handling information", "description": "The care worker understands data protection, GDPR, confidentiality obligations, and maintains accurate, secure records.", "keywords": ["data protection", "GDPR", "confidentiality", "records management", "information governance", "sharing information", "data breach"], "sub_outcomes": []},
    {"reference": "Standard 15", "name": "Infection prevention and control", "description": "The care worker understands and applies infection prevention and control measures, including hand hygiene, PPE, and standard precautions.", "keywords": ["infection control", "PPE", "hand hygiene", "standard precautions", "cleaning", "waste disposal", "decontamination", "chain of infection"], "sub_outcomes": []},
    {"reference": "Standard 16", "name": "Awareness of learning disability and autism", "description": "It is a legal requirement that all staff working in CQC-regulated services undertake training on how to interact appropriately with people with a learning disability and autistic people, at a level appropriate to their role.", "keywords": ["learning disability", "autism", "training", "CQC regulation 18", "staffing", "awareness"], "sub_outcomes": []},
]


async def _insert_standards_entries(conn, entries: list, jurisdiction: str):
    """Shared helper: bulk-insert standards entries with given jurisdiction."""
    for e in entries:
        await conn.execute(
            """INSERT INTO standards_entries
               (id, org_id, type, reference, name, description, keywords, sub_outcomes,
                key_questions, quality_statement, source, is_active, is_system, jurisdiction, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb,$10,$11,$12,$13,$14,$15)
               ON CONFLICT (id) DO NOTHING""",
            e["id"], None, e["type"], e["reference"], e["name"], e["description"],
            json.dumps(e["keywords"]), json.dumps(e["sub_outcomes"]),
            json.dumps(e["key_questions"]), e.get("quality_statement", False), e["source"],
            e.get("is_active", True), True, jurisdiction, e["created_at"],
        )


async def seed_standards():
    """Insert CQC regulations, quality statements, and Care Certificate standards (idempotent, jurisdiction=england)."""
    async with database.with_admin() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM standards_entries WHERE is_system=TRUE AND jurisdiction='england'"
        )
        if count and count > 0:
            # One-time fix: check if JSONB fields were double-encoded (sub_outcomes stored as string)
            sample = await conn.fetchrow(
                "SELECT sub_outcomes FROM standards_entries WHERE is_system=TRUE AND jurisdiction='england' LIMIT 1"
            )
            if sample and isinstance(sample["sub_outcomes"], str):
                logger.info("Detected double-encoded JSONB in standards — repairing…")
                rows = await conn.fetch(
                    "SELECT id, keywords, sub_outcomes, key_questions FROM standards_entries WHERE is_system=TRUE AND jurisdiction='england'"
                )
                for row in rows:
                    kw = json.loads(row["keywords"]) if isinstance(row["keywords"], str) else (row["keywords"] or [])
                    so = json.loads(row["sub_outcomes"]) if isinstance(row["sub_outcomes"], str) else (row["sub_outcomes"] or [])
                    kq = json.loads(row["key_questions"]) if isinstance(row["key_questions"], str) else (row["key_questions"] or [])
                    await conn.execute(
                        "UPDATE standards_entries SET keywords=$1, sub_outcomes=$2, key_questions=$3 WHERE id=$4",
                        kw, so, kq, row["id"],
                    )
                logger.info("JSONB repair complete for standards_entries")
            else:
                logger.info(f"England standards already seeded ({count} entries) — skipping")
            return

        now = datetime.now(timezone.utc).isoformat()
        entries = []
        for reg in CQC_REGULATIONS:
            entries.append({
                "id": str(uuid.uuid4()),
                "type": "cqc",
                "reference": reg["reference"],
                "name": reg["name"],
                "description": reg["description"],
                "keywords": reg["keywords"],
                "sub_outcomes": [],
                "key_questions": reg.get("key_questions", []),
                "quality_statement": False,
                "source": "CQC Guidance - Regulations for service providers and managers",
                "created_at": now,
            })
        for qs in CQC_QUALITY_STATEMENTS:
            entries.append({
                "id": str(uuid.uuid4()),
                "type": "cqc",
                "reference": qs["reference"],
                "name": qs["name"],
                "description": qs["description"],
                "keywords": qs["keywords"],
                "sub_outcomes": [],
                "key_questions": qs.get("key_questions", []),
                "quality_statement": True,
                "source": "CQC Single Assessment Framework - Quality Statements",
                "created_at": now,
            })
        for std in CARE_CERT_STANDARDS:
            entries.append({
                "id": str(uuid.uuid4()),
                "type": "care_cert",
                "reference": std["reference"],
                "name": std["name"],
                "description": std["description"],
                "keywords": std["keywords"],
                "sub_outcomes": std.get("sub_outcomes", []),
                "key_questions": [],
                "quality_statement": False,
                "source": "Care Certificate Standards 2025 - Skills for Care",
                "created_at": now,
            })

        await _insert_standards_entries(conn, entries, "england")
        logger.info(f"Seeded {len(entries)} England standards entries")


# ── CIW (Care Inspectorate Wales) — RSI(SPRI)(W)R 2017 Numbered Regulations ──
# The Regulated Services (Service Providers and Responsible Individuals) (Wales)
# Regulations 2017 (as amended).  These are the actual regulations CIW inspects
# against — equivalent to CQC's numbered regulations.  Grouped by 5 CIW
# inspection themes (key_questions field).
#
# Themes: "Quality of Care and Support" | "Safeguarding" | "Staffing" |
#         "Leadership and Management" | "Environment"
#
# Premises/environment regulations (Reg 43-55) excluded per design decision —
# they do not generate supervision evidence.

CIW_REGULATIONS = [
    # ── Theme 1: Quality of Care and Support ─────────────────────────────────
    {
        "reference": "Reg 6",
        "name": "Requirements in relation to the provision of the service",
        "key_questions": ["Quality of Care and Support", "Leadership and Management"],
        "description": (
            "The service provider must ensure the service is provided with sufficient care, competence and skill. "
            "Requires clear arrangements for oversight and governance; a rights-based, person-centred culture; "
            "systems for assessment, care planning and review; safe staffing; and quality/audit systems."
        ),
        "keywords": [
            "care provision", "competence", "skill", "governance", "culture", "rights-based",
            "person-centred", "assessment", "care planning", "monitoring", "review",
            "safe staffing", "quality systems", "audit", "statement of purpose",
        ],
    },
    {
        "reference": "Reg 14",
        "name": "Suitability of the service",
        "key_questions": ["Quality of Care and Support"],
        "description": (
            "The service provider must not agree to provide care unless the service is suitable to meet "
            "the individual's care and support needs and personal outcomes. Must involve the individual, "
            "placing authority and representative. Must consider existing care plans, health assessments, "
            "views, wishes, risks, and any reasonable adjustments."
        ),
        "keywords": [
            "suitability", "needs assessment", "personal outcomes", "admission policy",
            "care and support plan", "individual views", "wishes and feelings", "risk",
            "reasonable adjustments", "mental capacity", "commencement policy",
        ],
    },
    {
        "reference": "Reg 15",
        "name": "Personal plan",
        "key_questions": ["Quality of Care and Support"],
        "description": (
            "The service provider must prepare a personal plan before care commences (or within 24 hours "
            "in an emergency). The plan must set out how care needs will be met daily, how personal outcomes "
            "will be supported, how risks will be mitigated, and how independence and positive risk-taking "
            "will be supported. Must be co-produced with the individual."
        ),
        "keywords": [
            "personal plan", "care planning", "personal outcomes", "risk management",
            "positive risk-taking", "independence", "co-production", "daily care needs",
            "individual preferences", "wishes", "aspirations", "reviewing plans",
        ],
    },
    {
        "reference": "Reg 21",
        "name": "Standards of care and support – overarching requirements",
        "key_questions": ["Quality of Care and Support"],
        "description": (
            "Care and support must protect, promote and maintain the safety and well-being of individuals, "
            "and must be delivered in accordance with the personal plan. Must maintain good professional "
            "relationships and encourage dignity, respect and responsiveness. Covers physical, mental, "
            "emotional, cultural, religious and social needs."
        ),
        "keywords": [
            "standards of care", "safety", "well-being", "personal plan compliance",
            "dignity", "respect", "professional relationships", "person-centred",
            "physical well-being", "mental well-being", "emotional well-being",
            "cultural needs", "religious needs", "social care standards",
        ],
    },
    {
        "reference": "Reg 22",
        "name": "Continuity of care",
        "key_questions": ["Quality of Care and Support"],
        "description": (
            "The service provider must ensure individuals receive reasonable continuity of care. "
            "Staffing arrangements must provide consistency; individuals must know their staff; "
            "changes must be communicated; replacement staff must be familiar with individuals."
        ),
        "keywords": [
            "continuity of care", "consistency", "staffing continuity", "staff changes",
            "familiar staff", "replacement staff", "reliability", "service continuity",
        ],
    },
    {
        "reference": "Reg 23",
        "name": "Information",
        "key_questions": ["Quality of Care and Support"],
        "description": (
            "Individuals must have the information they need to make or participate in assessments, plans "
            "and day-to-day decisions. Information must be in the appropriate language, format and style "
            "having regard to the individual's understanding, communication needs and, for children, age."
        ),
        "keywords": [
            "information provision", "accessible information", "informed decisions",
            "language needs", "communication format", "advocacy", "self-advocacy",
            "understanding", "participation", "easy read",
        ],
    },
    {
        "reference": "Reg 24",
        "name": "Language and communication",
        "key_questions": ["Quality of Care and Support"],
        "description": (
            "The service provider must take reasonable steps to meet individuals' language needs and "
            "provide access to aids/equipment to facilitate communication. Includes Welsh language, "
            "alternative communication methods (Makaton, BSL, PECS, TEACCH) and ensuring "
            "active offering of Welsh language services."
        ),
        "keywords": [
            "Welsh language", "language needs", "communication aids", "Makaton",
            "British Sign Language", "BSL", "PECS", "TEACCH", "alternative communication",
            "bilingual", "language of choice", "communication impairment",
        ],
    },
    {
        "reference": "Reg 25",
        "name": "Respect and sensitivity",
        "key_questions": ["Quality of Care and Support"],
        "description": (
            "Individuals must be treated with respect and sensitivity. This includes respecting privacy "
            "and dignity, confidentiality, autonomy and independence, and having regard to protected "
            "characteristics under the Equality Act 2010."
        ),
        "keywords": [
            "respect", "dignity", "privacy", "confidentiality", "autonomy", "independence",
            "equality", "protected characteristics", "sensitivity", "person-centred",
            "courteous", "valued", "intimate care",
        ],
    },
    # ── Theme 2: Safeguarding ────────────────────────────────────────────────
    {
        "reference": "Reg 26",
        "name": "Safeguarding – overarching requirement",
        "key_questions": ["Safeguarding"],
        "description": (
            "The service provider must ensure individuals are safe and protected from abuse, neglect and "
            "improper treatment. Staff must receive safeguarding training at induction and regularly. "
            "Service providers must work with other agencies, maintain safeguarding referral records, "
            "and ensure governance oversight of safeguarding at board level."
        ),
        "keywords": [
            "safeguarding", "abuse", "neglect", "improper treatment", "safeguarding training",
            "induction", "referral", "multi-agency", "whistleblowing", "governance",
            "Wales Safeguarding Procedures", "disclosure", "raising concerns",
        ],
    },
    {
        "reference": "Reg 27",
        "name": "Safeguarding policies and procedures",
        "key_questions": ["Safeguarding"],
        "description": (
            "Service providers must have and effectively operate safeguarding policies and procedures "
            "for prevention of and response to abuse, neglect and improper treatment. On any allegation: "
            "act immediately, refer to other agencies, keep records. For children's services: must also "
            "have anti-bullying policy and missing child procedures."
        ),
        "keywords": [
            "safeguarding policy", "safeguarding procedures", "prevention of abuse",
            "responding to allegations", "referral", "immediate action", "records",
            "local authority", "multi-agency safeguarding", "Wales Safeguarding Procedures",
            "bullying", "missing child",
        ],
    },
    {
        "reference": "Reg 28",
        "name": "Supporting individuals to manage their money",
        "key_questions": ["Safeguarding"],
        "description": (
            "Service providers must have a policy to support individuals to manage their money and "
            "protect them from financial abuse. Where money is held, it must be in the individual's "
            "named account with clear demarcation. Staff must not act as an individual's financial agent "
            "without lawful authority."
        ),
        "keywords": [
            "financial abuse", "money management", "individual finances", "financial support",
            "bank accounts", "financial records", "financial policy", "budgeting",
            "financial transactions", "receipts", "agent", "valuables",
        ],
    },
    {
        "reference": "Reg 29",
        "name": "The appropriate use of control and restraint",
        "key_questions": ["Safeguarding"],
        "description": (
            "Control or restraint may only be used to prevent risk of harm and must be proportionate. "
            "Must only be carried out by trained staff. Service providers must have a policy and must "
            "record any incident within 24 hours. Reviews must inform the quality of care review."
        ),
        "keywords": [
            "restraint", "control", "restrictive practice", "proportionate", "risk of harm",
            "trained staff", "positive behaviour support", "mental capacity",
            "deprivation of liberty safeguards", "DOLS", "recording incidents",
        ],
    },
    {
        "reference": "Reg 31",
        "name": "Deprivation of liberty",
        "key_questions": ["Safeguarding"],
        "description": (
            "Individuals must not be deprived of their liberty for care purposes without lawful authority. "
            "Service providers and staff must act in accordance with the Mental Capacity Act 2005 and "
            "Deprivation of Liberty Safeguards. Staff must receive training at appropriate intervals."
        ),
        "keywords": [
            "deprivation of liberty", "lawful authority", "Mental Capacity Act", "MCA 2005",
            "Deprivation of Liberty Safeguards", "DoLS", "best interests", "mental capacity",
            "consent", "authorisation", "liberty protection safeguards",
        ],
    },
    # ── Theme 3: Staffing ────────────────────────────────────────────────────
    {
        "reference": "Reg 34",
        "name": "Staffing – overarching requirements",
        "key_questions": ["Staffing"],
        "description": (
            "The service provider must ensure that at all times a sufficient number of suitably qualified, "
            "trained, skilled, competent and experienced staff are deployed. Must consider the statement of "
            "purpose, individual needs, personal outcomes and all other regulatory requirements. "
            "The staffing determination must be demonstrable and measurable."
        ),
        "keywords": [
            "staffing levels", "skill mix", "qualified staff", "competence", "deployment",
            "staffing determination", "care needs", "personal outcomes", "temporary staff",
            "agency staff", "nursing staff", "staff cover", "staffing policy",
        ],
    },
    {
        "reference": "Reg 35",
        "name": "Fitness of staff",
        "key_questions": ["Staffing"],
        "description": (
            "Service providers must not employ or allow anyone to work at the service unless they are fit "
            "to do so: suitable character, required qualifications/skills/experience, health, and satisfactory "
            "DBS checks. Care workers and managers must be registered with Social Care Wales. "
            "DBS checks must be renewed at least every 3 years."
        ),
        "keywords": [
            "fitness of staff", "DBS", "Disclosure and Barring Service", "Social Care Wales",
            "SCW registration", "character check", "qualifications", "skills", "experience",
            "references", "employment checks", "health assessment", "recruitment vetting",
        ],
    },
    {
        "reference": "Reg 36",
        "name": "Supporting and developing staff",
        "key_questions": ["Staffing"],
        "description": (
            "Service providers must have a staff support and development policy. All staff must receive: "
            "role-appropriate induction (AWIF within defined timescale), regular supervision (at least "
            "quarterly), annual appraisal, core training, and specialist training as appropriate. "
            "Staff must be supported to maintain professional registration with Social Care Wales."
        ),
        "keywords": [
            "induction", "AWIF", "All Wales Induction Framework", "supervision", "quarterly supervision",
            "appraisal", "annual appraisal", "training", "core training", "specialist training",
            "CPD", "professional development", "Social Care Wales registration", "staff development policy",
            "training needs analysis", "delegation",
        ],
    },
    {
        "reference": "Reg 37",
        "name": "Compliance with employer's code of practice",
        "key_questions": ["Staffing"],
        "description": (
            "The service provider must adhere to Social Care Wales's code of practice on the standards "
            "of conduct and practice expected of persons employing or seeking to employ social care workers "
            "(the Employer's Code of Practice)."
        ),
        "keywords": [
            "employer's code of practice", "Social Care Wales", "SCW", "conduct standards",
            "employment standards", "code of practice", "workforce standards",
        ],
    },
    {
        "reference": "Reg 38",
        "name": "Information for staff",
        "key_questions": ["Staffing"],
        "description": (
            "All staff and volunteers must be provided with information about the service and how it is "
            "provided. Must include codes of professional practice, policies, confidentiality, "
            "safeguarding arrangements, lone working, and disciplinary procedures. Regular staff "
            "meetings (minimum 6 per year) must take place and be recorded."
        ),
        "keywords": [
            "staff information", "code of practice", "policies and procedures", "induction",
            "confidentiality", "data protection", "safeguarding awareness", "lone working",
            "staff meetings", "job description", "accountability",
        ],
    },
    {
        "reference": "Reg 39",
        "name": "Disciplinary procedures",
        "key_questions": ["Staffing"],
        "description": (
            "Service providers must have and operate a disciplinary procedure. Must include provision "
            "for suspension, and failure to report abuse is grounds for disciplinary action. "
            "Where an employee leaves before completion of disciplinary proceedings, providers must "
            "consider referral to DBS, Social Care Wales or police."
        ),
        "keywords": [
            "disciplinary procedure", "suspension", "misconduct", "reporting abuse",
            "DBS referral", "Social Care Wales referral", "police referral", "performance",
            "conduct", "grievance", "employment law",
        ],
    },
    # ── Theme 4: Leadership, Management and Governance ───────────────────────
    {
        "reference": "Reg 59",
        "name": "Records",
        "key_questions": ["Leadership and Management"],
        "description": (
            "Service providers must keep and maintain all records specified in Schedule 2 of the Regulations. "
            "Records must be accurate, up to date and kept securely. Adults' records retained for 3 years; "
            "children's for 15 years. Individuals must be able to access their own records. "
            "Electronic records must be password protected."
        ),
        "keywords": [
            "records management", "record keeping", "accuracy", "secure storage", "retention",
            "data protection", "GDPR", "individual access", "electronic records",
            "Schedule 2", "personal records", "staff records", "confidentiality",
        ],
    },
    {
        "reference": "Reg 64",
        "name": "Complaints policy and procedure",
        "key_questions": ["Leadership and Management"],
        "description": (
            "Service providers must have an accessible complaints policy and effective arrangements for "
            "identifying, investigating and responding to complaints. Must include advocacy information "
            "(Llais/Citizen Voice Body), timescales, and written responses to complainants. "
            "Complaints must be analysed to identify areas for improvement."
        ),
        "keywords": [
            "complaints", "complaints policy", "complaints procedure", "investigation",
            "response timescales", "Llais", "Citizen Voice Body", "advocacy",
            "complainant rights", "complaints analysis", "trends", "service improvement",
            "Public Services Ombudsman", "whistleblowing",
        ],
    },
    {
        "reference": "Reg 65",
        "name": "Whistleblowing",
        "key_questions": ["Leadership and Management"],
        "description": (
            "Service providers must have a whistleblowing policy and effective arrangements to enable "
            "staff to raise concerns about matters affecting individual health, safety or well-being. "
            "Concerns must be investigated, appropriate action taken, and a record kept. "
            "Staff must not suffer victimisation for raising concerns."
        ),
        "keywords": [
            "whistleblowing", "raising concerns", "staff concerns", "whistleblowing policy",
            "confidentiality", "investigation", "no victimisation", "safeguarding concerns",
            "duty of candour", "speak up", "transparency",
        ],
    },
    {
        "reference": "Reg 80",
        "name": "Quality of care review",
        "key_questions": ["Leadership and Management"],
        "description": (
            "The responsible individual must establish and maintain a system for monitoring, reviewing "
            "and improving quality of care — at least every 6 months. The review must analyse engagement "
            "outcomes, incidents, safeguarding, whistleblowing, complaints and records audits. "
            "A report with assessment and recommendations must be prepared for the service provider."
        ),
        "keywords": [
            "quality of care review", "responsible individual", "monitoring", "quality improvement",
            "six-monthly review", "incident analysis", "safeguarding analysis", "complaints review",
            "records audit", "quality assurance", "governance report", "CIW inspection",
        ],
    },
]


# ── AWIF (All Wales Induction Framework) ─────────────────────────────────────
# 7 workbooks. Each workbook is one standard entry with sub_outcomes for each section.
# Adults use workbooks 1, 3, 5, 6, 7. Children's services use workbooks 2, 4, 5, 6, 7.
# Both MUST be seeded as providers may work with adults AND children.

AWIF_STANDARDS = [
    {
        "reference": "AWIF 1",
        "name": "Principles and values of health and social care (adults)",
        "description": (
            "Covers the legislative and value base underpinning health and social care work with adults in Wales. "
            "Includes the Social Services and Well-being (Wales) Act 2014, the Code of Professional Practice, "
            "rights-based approaches, person-centred care, equality and diversity, positive risk taking, "
            "communication, Welsh language and culture, restrictive practices, and reflection."
        ),
        "keywords": [
            "SSWB Act 2014", "voice and control", "well-being", "co-production", "person-centred",
            "rights-based", "Code of Professional Practice", "Social Care Wales", "equality", "diversity",
            "inclusion", "positive risk taking", "professional boundaries", "communication",
            "Welsh language", "restrictive practices", "reflection", "principles", "values",
        ],
        "sub_outcomes": [
            {"ref": "1.1", "desc": "Legislation, national policies and codes of conduct and practice that underpin health and social care"},
            {"ref": "1.2", "desc": "Rights-based approaches and how they relate to health and social care"},
            {"ref": "1.3", "desc": "Person-centred approaches and how to apply them in practice"},
            {"ref": "1.4", "desc": "Equality, diversity and inclusion — recognising and responding to discrimination"},
            {"ref": "1.5", "desc": "Positive risk taking — supporting individuals to take calculated risks safely"},
            {"ref": "1.6", "desc": "Positive relationships and maintaining professional boundaries"},
            {"ref": "1.7", "desc": "Communication — verbal, non-verbal and written; adapting to individual needs"},
            {"ref": "1.8", "desc": "Welsh language and culture — recognising and meeting linguistic and cultural needs"},
            {"ref": "1.9", "desc": "Positive approaches to reduce restrictive practices in social care"},
            {"ref": "1.10", "desc": "Change and transitions in health and social care — supporting individuals through life events"},
            {"ref": "1.11", "desc": "Reflection — how own values, beliefs and experiences influence practice"},
        ],
    },
    {
        "reference": "AWIF 2",
        "name": "Principles and values of health and social care (children and young people)",
        "description": (
            "Covers the legislative and value base underpinning health and social care work with children and "
            "young people in Wales. Includes the UN Convention on the Rights of the Child, child-centred "
            "approaches, equality and diversity, positive risk taking, professional relationships, "
            "communication, Welsh language, restrictive practices, and reflection. "
            "Must be completed by all workers who may work with children, even if primarily with adults."
        ),
        "keywords": [
            "children's rights", "UN CRC", "child-centred", "young people", "SSWB Act 2014",
            "Code of Professional Practice", "equality", "diversity", "positive risk", "safeguarding",
            "communication", "Welsh language", "professional boundaries", "reflection", "trauma-informed",
            "residential child care", "foster care", "children's services", "transitions",
        ],
        "sub_outcomes": [
            {"ref": "2.1", "desc": "Legislation, national policies and codes of conduct for working with children and young people"},
            {"ref": "2.2", "desc": "Rights-based approaches for children and young people"},
            {"ref": "2.3", "desc": "Child-centred approaches and how to apply them in practice"},
            {"ref": "2.4", "desc": "Equality, diversity and inclusion when working with children and young people"},
            {"ref": "2.5", "desc": "Positive risk taking — balancing safety with children's rights to experience and learn"},
            {"ref": "2.6", "desc": "Positive relationships and professional boundaries with children and young people"},
            {"ref": "2.7", "desc": "Communication with children and young people, including developmentally appropriate approaches"},
            {"ref": "2.8", "desc": "Welsh language and culture — supporting identity and cultural heritage"},
            {"ref": "2.9", "desc": "Positive approaches to reduce restrictive practices when working with children"},
            {"ref": "2.10", "desc": "Change and transitions — supporting children and young people through significant life events"},
            {"ref": "2.11", "desc": "Reflection — examining own values and their impact on practice with children"},
        ],
    },
    {
        "reference": "AWIF 3",
        "name": "Health and well-being (adults)",
        "description": (
            "Covers knowledge and skills for supporting the health and well-being of adults in social care settings. "
            "Includes understanding well-being, supporting personal care, pressure area care, oral and foot care, "
            "medication administration, nutrition and hydration, falls prevention, end of life care, "
            "assistive technology, sensory loss, dementia, mental health, and substance misuse."
        ),
        "keywords": [
            "well-being", "personal care", "continence", "pressure area care", "oral health", "foot care",
            "medication", "MAR", "nutrition", "hydration", "falls prevention", "end of life",
            "palliative care", "assistive technology", "sensory loss", "dementia", "mental health",
            "substance misuse", "health needs", "clinical care",
        ],
        "sub_outcomes": [
            {"ref": "3.1", "desc": "What well-being means in the context of health and social care for adults"},
            {"ref": "3.2", "desc": "Factors that impact upon the health and well-being of individuals"},
            {"ref": "3.3", "desc": "How to support individuals with their personal care and continence management"},
            {"ref": "3.4", "desc": "Good practice in relation to pressure area care — prevention and management"},
            {"ref": "3.5", "desc": "How to support good oral health care and mouth care for individuals"},
            {"ref": "3.6", "desc": "Supporting foot care — recognising problems and accessing specialist services"},
            {"ref": "3.7", "desc": "Roles and responsibilities related to the administration of medication in social care"},
            {"ref": "3.8", "desc": "The importance of nutrition and hydration and how to support individuals' needs"},
            {"ref": "3.9", "desc": "How to support falls prevention — risk factors and interventions"},
            {"ref": "3.10", "desc": "Factors that affect end of life care and how to support individuals and families"},
            {"ref": "3.11", "desc": "How assistive technology can be used to support the health and well-being of individuals"},
            {"ref": "3.12", "desc": "How sensory loss can impact on health and well-being and how to support individuals"},
            {"ref": "3.13", "desc": "How living with dementia can impact on the health and well-being of individuals"},
            {"ref": "3.14", "desc": "How mental ill-health can impact upon the health and well-being of individuals"},
            {"ref": "3.15", "desc": "How substance misuse can impact upon the health and well-being of individuals"},
        ],
    },
    {
        "reference": "AWIF 4",
        "name": "Health and well-being (children and young people)",
        "description": (
            "Covers knowledge and skills for supporting the health and well-being of children and young people "
            "in social care settings. Includes understanding children's well-being, developmental factors, "
            "positive environments, play, speech and language development, additional support needs, "
            "advice and guidance, medication administration, personal care, and nutrition and hydration. "
            "Must be completed by all workers who may work with children, even if primarily with adults."
        ),
        "keywords": [
            "children's well-being", "development", "positive environment", "play", "learning",
            "speech and language", "additional support needs", "SEND", "personal care", "nutrition",
            "hydration", "medication", "assessment", "child development", "holistic needs",
            "transitions", "attachment", "trauma", "resilience",
        ],
        "sub_outcomes": [
            {"ref": "4.1", "desc": "What well-being means in the context of health and social care for children and young people"},
            {"ref": "4.2", "desc": "Factors that affect the health, well-being and development of children and young people"},
            {"ref": "4.3", "desc": "Environments that support the health, well-being and development of children and young people"},
            {"ref": "4.4", "desc": "Supporting the use of play for the health, well-being and development of children"},
            {"ref": "4.5", "desc": "Speech, language and communication development — importance and how to support it"},
            {"ref": "4.6", "desc": "Additional support needs — understanding and responding to individual requirements"},
            {"ref": "4.7", "desc": "How to offer advice, guidance and support to children, young people and their families"},
            {"ref": "4.8", "desc": "Administration of medication — roles, responsibilities and safe practice for children"},
            {"ref": "4.9", "desc": "Supporting children and young people with their personal care needs"},
            {"ref": "4.10", "desc": "The importance of nutrition and hydration for the health and well-being of children"},
        ],
    },
    {
        "reference": "AWIF 5",
        "name": "Professional practice as a health and social care worker",
        "description": (
            "Covers the professional responsibilities, accountabilities and conduct of health and social care "
            "workers in Wales. Includes understanding roles and responsibilities, partnership and team working, "
            "information handling and GDPR, personal conduct and professional registration, and "
            "continuing professional development (CPD) and the Code of Professional Practice."
        ),
        "keywords": [
            "professional responsibility", "accountability", "scope of practice", "partnership working",
            "team working", "multi-disciplinary", "information handling", "GDPR", "data protection",
            "confidentiality", "records", "personal conduct", "Code of Professional Practice",
            "Social Care Wales registration", "SCW", "CPD", "continuing professional development",
            "reflective practice", "supervision", "appraisal",
        ],
        "sub_outcomes": [
            {"ref": "5.1", "desc": "Role, responsibilities and accountabilities of the health and social care worker"},
            {"ref": "5.2", "desc": "How to develop and maintain effective partnership working with others"},
            {"ref": "5.3", "desc": "How effective team working supports good practice in health and social care"},
            {"ref": "5.4", "desc": "How to handle information — GDPR, confidentiality and record-keeping"},
            {"ref": "5.5", "desc": "The importance of personal conduct and upholding the social care profession"},
            {"ref": "5.6", "desc": "How continuing professional development contributes to professional practice"},
        ],
    },
    {
        "reference": "AWIF 6",
        "name": "Safeguarding individuals",
        "description": (
            "Covers the knowledge and skills needed to safeguard adults and children in social care settings. "
            "Includes understanding the legislative framework (Social Services and Well-being (Wales) Act 2014, "
            "Wales Safeguarding Procedures 2019), working in ways that protect individuals, recognising factors "
            "that contribute to harm and abuse, and how to respond, record and report concerns."
        ),
        "keywords": [
            "safeguarding", "abuse", "neglect", "harm", "exploitation", "Wales Safeguarding Procedures",
            "SSWB Act 2014", "disclosure", "allegation", "concern", "reporting", "recording",
            "whistle-blowing", "DBS", "Barring List", "categories of abuse", "indicators",
            "information sharing", "multi-agency", "adult protection", "child protection",
        ],
        "sub_outcomes": [
            {"ref": "6.1", "desc": "The purpose of legislation, national policies and codes in relation to safeguarding individuals"},
            {"ref": "6.2", "desc": "How to work in ways that safeguard individuals from harm, abuse and neglect"},
            {"ref": "6.3", "desc": "Factors, situations and actions that could lead to or contribute to harm, abuse or neglect"},
            {"ref": "6.4", "desc": "How to respond, record and report concerns, disclosures or allegations related to safeguarding"},
        ],
    },
    {
        "reference": "AWIF 7",
        "name": "Health and safety in health and social care",
        "description": (
            "Covers health and safety legislation, responsibilities and practical skills for health and social "
            "care workers in Wales. Includes workplace health and safety legislation, risk assessment, fire safety, "
            "moving and handling, emergency first aid, infection prevention and control, food safety, "
            "hazardous substances (COSHH), security and managing stress."
        ),
        "keywords": [
            "Health and Safety at Work Act", "risk assessment", "fire safety", "moving and handling",
            "manual handling", "first aid", "infection prevention", "IPC", "PPE", "food safety",
            "COSHH", "hazardous substances", "security", "lone working", "stress management",
            "HSE", "personal protective equipment", "hand hygiene", "emergency procedures",
        ],
        "sub_outcomes": [
            {"ref": "7.1", "desc": "Health and safety in the workplace — legislation, responsibilities and rights"},
            {"ref": "7.2", "desc": "Risk assessments for health and safety — how to carry out and act on them"},
            {"ref": "7.3", "desc": "Fire safety — prevention, detection, evacuation and responsibilities"},
            {"ref": "7.4", "desc": "Moving and handling and moving and positioning — safe techniques and legislation"},
            {"ref": "7.5", "desc": "Emergency first aid — basic life support, responding to accidents and incidents"},
            {"ref": "7.6", "desc": "Infection prevention and control — standard precautions, PPE, hand hygiene"},
            {"ref": "7.7", "desc": "Food safety — safe handling, storage, preparation and legal requirements"},
            {"ref": "7.8", "desc": "Hazardous substances (COSHH) — identification, safe use and storage"},
            {"ref": "7.9", "desc": "Security in the work setting — including lone working arrangements"},
            {"ref": "7.10", "desc": "Managing stress — recognising signs and accessing support for well-being"},
        ],
    },
]


# ── SCW (Social Care Wales) Code of Professional Practice ─────────────────────
# Worker's Code — 6 sections applicable to all social care workers in Wales.
# Section 7 (for managers who lead staff) is included within section 6.

SCW_CODE_STANDARDS = [
    {
        "reference": "SCW 1",
        "name": "Respect the views and wishes, and promote the rights and interests of individuals and carers",
        "description": (
            "Social care workers must respect and uphold the rights, values, beliefs, views and wishes of "
            "individuals and carers. This includes working in person-centred ways, supporting decision-making, "
            "working with dignity and respect, and ensuring actions promote equality, diversity and inclusion."
        ),
        "keywords": [
            "respect", "rights", "wishes", "person-centred", "dignity", "autonomy",
            "decision-making", "equality", "diversity", "inclusion", "cultural needs",
            "beliefs", "values", "preferences", "language", "privacy",
        ],
        "sub_outcomes": [
            {"ref": "1.1", "desc": "Working with individuals in person-centred ways as the basis for social care"},
            {"ref": "1.2", "desc": "Respecting and promoting the rights, values, beliefs, views and wishes of individuals"},
            {"ref": "1.3", "desc": "Supporting individuals to maximise their decision-making and control over their lives"},
            {"ref": "1.4", "desc": "Working with respect for dignity, privacy, preferences, culture, language and rights"},
            {"ref": "1.5", "desc": "Ensuring actions promote equality, diversity and inclusion"},
        ],
    },
    {
        "reference": "SCW 2",
        "name": "Strive to establish and maintain the trust and confidence of individuals and carers",
        "description": (
            "Social care workers must be honest, trustworthy and reliable. This includes communicating openly "
            "and accurately, respecting confidentiality, being dependable, honouring commitments, declaring "
            "conflicts of interest, and adhering to policies on gifts and money."
        ),
        "keywords": [
            "trust", "confidence", "honesty", "transparency", "confidentiality",
            "communication", "reliability", "conflicts of interest", "openness",
            "accurate information", "data protection", "professional relationship",
        ],
        "sub_outcomes": [
            {"ref": "2.1", "desc": "Being honest and trustworthy in all interactions"},
            {"ref": "2.2", "desc": "Communicating in an open, accurate and straightforward way"},
            {"ref": "2.3", "desc": "Supporting individuals to communicate their views using their preferred method and language"},
            {"ref": "2.4", "desc": "Respecting confidential information and explaining confidentiality policies"},
            {"ref": "2.5", "desc": "Being reliable and dependable — honouring commitments and arrangements"},
            {"ref": "2.6", "desc": "Declaring conflicts of interest and not letting them influence professional judgement"},
            {"ref": "2.7", "desc": "Adhering to policies about accepting gifts or money from individuals or families"},
        ],
    },
    {
        "reference": "SCW 3",
        "name": "Promote the well-being, voice and control of individuals and carers while supporting them to stay safe",
        "description": (
            "Social care workers must work in ways that maximise well-being, active participation and balance "
            "rights with safety. This includes working in partnership, sharing information appropriately, "
            "supporting individuals to express concerns or make complaints, and challenging unsafe practice."
        ),
        "keywords": [
            "well-being", "voice", "control", "active participation", "safety", "partnership",
            "information sharing", "complaints", "whistleblowing", "safeguarding", "unsafe practice",
            "empowerment", "self-determination", "advocacy", "challenging practice",
        ],
        "sub_outcomes": [
            {"ref": "3.1", "desc": "Working in ways that maximise well-being, active participation and balance rights"},
            {"ref": "3.2", "desc": "Working in partnership to promote the well-being, voice and control of individuals"},
            {"ref": "3.3", "desc": "Working with individuals and carers to keep themselves safe"},
            {"ref": "3.4", "desc": "Using power responsibly and sensitively in work with individuals"},
            {"ref": "3.5", "desc": "Supporting individuals to express concerns or make complaints"},
            {"ref": "3.6", "desc": "Using agreed systems and procedures to share information appropriately"},
            {"ref": "3.7", "desc": "Challenging and reporting dangerous, abusive or discriminatory behaviour"},
            {"ref": "3.8", "desc": "Raising concerns about unsafe or substandard practice by colleagues"},
            {"ref": "3.9", "desc": "Reporting resource or operational difficulties that affect safe delivery of care"},
        ],
    },
    {
        "reference": "SCW 4",
        "name": "Respect the rights of individuals while seeking to ensure their behaviour does not harm themselves or others",
        "description": (
            "Social care workers must balance individual rights with safety. This includes following risk "
            "assessment procedures, taking necessary steps to minimise risk of harm, and ensuring relevant "
            "colleagues are informed about risk assessment outcomes."
        ),
        "keywords": [
            "risk assessment", "rights and risks", "positive risk taking", "harm minimisation",
            "capacity", "best interests", "safety planning", "behaviour", "protection",
            "balancing rights", "proportionate response", "information sharing",
        ],
        "sub_outcomes": [
            {"ref": "4.1", "desc": "Working with individuals to balance rights, responsibilities and risks"},
            {"ref": "4.2", "desc": "Following risk assessment policies to assess whether behaviour presents risk of harm"},
            {"ref": "4.3", "desc": "Taking steps to minimise the risks of individuals' behaviour causing harm"},
            {"ref": "4.4", "desc": "Ensuring relevant colleagues and agencies are informed about risk assessment outcomes"},
        ],
    },
    {
        "reference": "SCW 5",
        "name": "Act with integrity and uphold public trust and confidence in the social care profession",
        "description": (
            "Social care workers must not directly or indirectly abuse, neglect or exploit individuals. "
            "Must not form inappropriate relationships or abuse trust. Must not discriminate, put people "
            "at unnecessary risk, or behave in ways that undermine confidence in the profession — in or "
            "outside work, including online."
        ),
        "keywords": [
            "integrity", "public trust", "professional conduct", "professional boundaries",
            "exploitation", "abuse of trust", "discrimination", "social media", "fitness to practise",
            "registration", "Social Care Wales", "professional standards", "conduct",
        ],
        "sub_outcomes": [
            {"ref": "5.1", "desc": "Not directly or indirectly abusing, neglecting or harming individuals or colleagues"},
            {"ref": "5.2", "desc": "Not exploiting individuals, carers or colleagues in any way"},
            {"ref": "5.3", "desc": "Not abusing trust or access to personal information, property or home"},
            {"ref": "5.4", "desc": "Not forming inappropriate personal relationships with individuals or families"},
            {"ref": "5.5", "desc": "Not discriminating unlawfully or unjustifiably against individuals or colleagues"},
            {"ref": "5.6", "desc": "Not condoning unlawful discrimination by others"},
            {"ref": "5.7", "desc": "Not putting yourself or others at unnecessary risk"},
            {"ref": "5.8", "desc": "Not behaving in a way that calls into question suitability to work in social care"},
        ],
    },
    {
        "reference": "SCW 6",
        "name": "Be accountable for the quality of your work and take responsibility for maintaining and developing knowledge and skills",
        "description": (
            "Social care workers must meet relevant standards of practice, maintain accurate records, be "
            "open when things go wrong, seek help when uncertain, work openly with colleagues, and "
            "understand their responsibility for delegated work. Workers who manage or lead staff must "
            "also embed the Code in their team's work (Section 7)."
        ),
        "keywords": [
            "accountability", "quality of work", "records management", "documentation",
            "openness", "duty of candour", "CPD", "professional development", "supervision",
            "appraisal", "delegated work", "responsibility", "competence",
            "training", "learning", "reflection", "leadership accountability",
        ],
        "sub_outcomes": [
            {"ref": "6.1", "desc": "Meeting relevant standards of practice and working lawfully, safely and effectively"},
            {"ref": "6.2", "desc": "Maintaining clear and accurate records in accordance with legal and work setting requirements"},
            {"ref": "6.3", "desc": "Being open and honest when things go wrong, including notifying employer or authority"},
            {"ref": "6.4", "desc": "Informing employer about personal difficulties that might affect job competence"},
            {"ref": "6.5", "desc": "Seeking assistance when not adequately prepared or unsure how to proceed"},
            {"ref": "6.6", "desc": "Working openly and co-operatively with colleagues, treating them with respect"},
            {"ref": "6.7", "desc": "Understanding responsibility for work delegated to other workers"},
            {"ref": "7.1", "desc": "Embedding the Code of Professional Practice in the work of staff (managers/leaders)"},
        ],
    },
]


async def seed_welsh_standards():
    """Seed Welsh standards: CIW (RSI(SPRI)(W)R 2017 regulations), AWIF (7 workbooks), SCW Worker's Code.

    Migration-aware:
    - If old 7-question CIW entries exist → replace with real numbered regulations.
    - AWIF and SCW entries are only seeded once (idempotent).
    """
    async with database.with_admin() as conn:
        # ── CIW: detect old structure (7 entries) and migrate ────────────────
        ciw_count = await conn.fetchval(
            "SELECT COUNT(*) FROM standards_entries WHERE type='ciw' AND jurisdiction='wales' AND is_system=TRUE"
        )
        if ciw_count == 7:
            logger.info(
                "Migrating CIW standards: replacing old 7-question structure "
                "with RSI(SPRI)(W)R 2017 numbered regulations…"
            )
            await conn.execute(
                "DELETE FROM standards_entries WHERE type='ciw' AND jurisdiction='wales' AND is_system=TRUE"
            )
            ciw_count = 0

        ciw_entries = []
        if ciw_count == 0:
            now = datetime.now(timezone.utc).isoformat()
            for reg in CIW_REGULATIONS:
                ciw_entries.append({
                    "id": str(uuid.uuid4()),
                    "type": "ciw",
                    "reference": reg["reference"],
                    "name": reg["name"],
                    "description": reg["description"],
                    "keywords": reg["keywords"],
                    "sub_outcomes": [],
                    "key_questions": reg.get("key_questions", []),
                    "quality_statement": False,
                    "source": (
                        "The Regulated Services (Service Providers and Responsible Individuals) "
                        "(Wales) Regulations 2017 (as amended)"
                    ),
                    "created_at": now,
                })
            await _insert_standards_entries(conn, ciw_entries, "wales")
            logger.info(f"Seeded {len(ciw_entries)} CIW regulation entries")
        else:
            logger.info(f"CIW standards already current ({ciw_count} entries) — skipping")

        # ── AWIF + SCW: seed once ────────────────────────────────────────────
        awif_scw_count = await conn.fetchval(
            "SELECT COUNT(*) FROM standards_entries "
            "WHERE type IN ('awif','scw') AND jurisdiction='wales' AND is_system=TRUE"
        )
        if awif_scw_count > 0:
            logger.info(f"AWIF/SCW standards already seeded ({awif_scw_count} entries) — skipping")
            return

        now = datetime.now(timezone.utc).isoformat()
        awif_scw_entries = []

        for wb in AWIF_STANDARDS:
            awif_scw_entries.append({
                "id": str(uuid.uuid4()),
                "type": "awif",
                "reference": wb["reference"],
                "name": wb["name"],
                "description": wb["description"],
                "keywords": wb["keywords"],
                "sub_outcomes": wb["sub_outcomes"],
                "key_questions": [],
                "quality_statement": False,
                "source": "All Wales Induction Framework for Health and Social Care (AWIF) — Social Care Wales",
                "created_at": now,
            })

        for std in SCW_CODE_STANDARDS:
            awif_scw_entries.append({
                "id": str(uuid.uuid4()),
                "type": "scw",
                "reference": std["reference"],
                "name": std["name"],
                "description": std["description"],
                "keywords": std["keywords"],
                "sub_outcomes": std["sub_outcomes"],
                "key_questions": [],
                "quality_statement": False,
                "source": "Social Care Wales — Code of Professional Practice for Social Care (Worker's Code)",
                "created_at": now,
            })

        await _insert_standards_entries(conn, awif_scw_entries, "wales")
        logger.info(
            f"Seeded {len(awif_scw_entries)} AWIF/SCW entries "
            f"({len(AWIF_STANDARDS)} AWIF, {len(SCW_CODE_STANDARDS)} SCW)"
        )



# ── CI (Care Inspectorate Scotland) — Quality Framework Indicators ────────────
# 6 key questions with 17 quality indicators (plus KQ6 overall capacity).
# Equivalent to CQC's 5 key questions + quality statements.
# Source: Care Inspectorate Quality Framework for Care Homes for Adults and
# Older People (covers all registered adult social care services).
# Graded on 1–6 scale during inspection.

CI_QUALITY_INDICATORS = [
    # ── KQ1: How well do we support people's wellbeing? ──────────────────────
    {
        "reference": "CI 1.1",
        "name": "People experience compassion, dignity and respect",
        "key_questions": ["How well do we support people's wellbeing?"],
        "description": (
            "Inspectors evaluate whether people are treated with genuine compassion, dignity and respect. "
            "Staff demonstrate person-centred values in their interactions; people are not subject to "
            "discrimination; their human rights, privacy, individuality and cultural identity are upheld. "
            "Underpinned by Health and Social Care Standards themes 1 and 2."
        ),
        "keywords": [
            "dignity", "respect", "compassion", "equality", "inclusion", "discrimination",
            "human rights", "person-centred", "privacy", "individuality", "cultural identity",
            "diversity", "protected characteristics", "intimate care", "autonomy",
        ],
    },
    {
        "reference": "CI 1.2",
        "name": "People get the most out of life",
        "key_questions": ["How well do we support people's wellbeing?"],
        "description": (
            "People are supported to pursue meaningful activities, maintain relationships and fulfil "
            "personal goals and aspirations. Independence is promoted; people participate in social, "
            "creative and recreational activities; their interests and preferences are actively supported."
        ),
        "keywords": [
            "quality of life", "independence", "meaningful activities", "social participation",
            "community involvement", "interests", "aspirations", "goals", "relationships",
            "positive risk", "enabling", "choice",
        ],
    },
    {
        "reference": "CI 1.3",
        "name": "People's health and wellbeing benefits from their care and support",
        "key_questions": ["How well do we support people's wellbeing?"],
        "description": (
            "Physical, mental and emotional health needs are assessed, planned for and consistently met. "
            "Medication management is safe and effective; nutrition and hydration needs are addressed; "
            "pressure area care, personal care and clinical needs are met; access to healthcare "
            "professionals is supported. Includes end of life care."
        ),
        "keywords": [
            "health needs", "medication management", "MAR", "nutrition", "hydration",
            "pressure area care", "personal care", "clinical care", "healthcare professionals",
            "mental health", "dementia", "end of life", "palliative care",
            "continence", "falls prevention", "monitoring",
        ],
    },
    {
        "reference": "CI 1.4",
        "name": "People experience meaningful contact that meets their outcomes, needs and wishes",
        "key_questions": ["How well do we support people's wellbeing?"],
        "description": (
            "People have consistent, trusting relationships with staff; communication is adapted to "
            "individual needs and preferences; contact is meaningful and contributes to well-being. "
            "People's views, wishes and feelings are listened to and acted upon."
        ),
        "keywords": [
            "communication", "relationships", "staff continuity", "person-centred",
            "needs and wishes", "listening", "advocacy", "preferred communication",
            "meaningful contact", "responsive", "trust",
        ],
    },
    {
        "reference": "CI 1.5",
        "name": "People's health and wellbeing benefits from safe infection prevention and control practices",
        "key_questions": ["How well do we support people's wellbeing?"],
        "description": (
            "Infection prevention and control (IPC) procedures are followed consistently; staff use "
            "appropriate PPE; hand hygiene standards are maintained; environments are clean and "
            "well-maintained; outbreak management procedures are in place and effective."
        ),
        "keywords": [
            "IPC", "infection prevention", "infection control", "hand hygiene", "PPE",
            "personal protective equipment", "cleanliness", "outbreak management",
            "NIPCM", "decontamination", "environmental cleanliness",
        ],
    },
    # ── KQ2: How good is our leadership? ─────────────────────────────────────
    {
        "reference": "CI 2.1",
        "name": "Vision and values positively inform practice",
        "key_questions": ["How good is our leadership?"],
        "description": (
            "The service has a clear, values-led vision which is understood and lived by all staff. "
            "Leadership promotes a positive, rights-based culture; the statement of aims and objectives "
            "reflects the Health and Social Care Standards; practice is informed by the service's values."
        ),
        "keywords": [
            "vision", "values", "culture", "leadership", "person-centred", "rights-based",
            "statement of aims", "culture of care", "continuous improvement", "positive culture",
        ],
    },
    {
        "reference": "CI 2.2",
        "name": "Quality assurance and improvement is led well",
        "key_questions": ["How good is our leadership?"],
        "description": (
            "Robust quality assurance systems are in place and actively used; improvements are "
            "evidence-based and clearly driven by outcomes for people; complaints, incidents and "
            "near-misses are analysed to drive learning; governance arrangements are transparent "
            "and effective. The service can demonstrate continuous improvement."
        ),
        "keywords": [
            "quality assurance", "governance", "audit", "monitoring", "continuous improvement",
            "complaints analysis", "incident analysis", "learning culture", "self-evaluation",
            "quality framework", "key performance indicators", "improvement planning",
        ],
    },
    {
        "reference": "CI 2.3",
        "name": "Leaders collaborate to support people",
        "key_questions": ["How good is our leadership?"],
        "description": (
            "Leadership works effectively with external agencies, commissioners, health professionals, "
            "social work, families and other partners to support people's individual outcomes. "
            "Partnership and integration arrangements are well-managed."
        ),
        "keywords": [
            "partnership", "multi-agency", "collaboration", "external agencies", "commissioners",
            "integrated care", "social work", "health professionals", "community links",
            "referral pathways",
        ],
    },
    {
        "reference": "CI 2.4",
        "name": "Staff are led well",
        "key_questions": ["How good is our leadership?"],
        "description": (
            "Staff receive regular, meaningful supervision and annual appraisal; communication is "
            "open and transparent; staff wellbeing is actively supported; leadership is visible, "
            "accessible and responsive. Staff feel valued, supported and confident to raise concerns."
        ),
        "keywords": [
            "supervision", "appraisal", "staff wellbeing", "open communication", "visible leadership",
            "team meetings", "whistleblowing", "speaking up", "staff support", "team culture",
            "staff engagement", "recognition",
        ],
    },
    # ── KQ3: How good is our staff team? ─────────────────────────────────────
    {
        "reference": "CI 3.1",
        "name": "Staff have been recruited well",
        "key_questions": ["How good is our staff team?"],
        "description": (
            "Safer recruitment practices are followed; PVG (Protection of Vulnerable Groups) Scheme "
            "checks are in place for all relevant staff; thorough references are obtained; "
            "SSSC registration requirements are met before staff begin working; "
            "fitness to practise is assessed and maintained."
        ),
        "keywords": [
            "safer recruitment", "PVG", "Protection of Vulnerable Groups", "SSSC registration",
            "references", "induction", "fitness to practise", "employment checks",
            "pre-employment screening", "Disclosure Scotland",
        ],
    },
    {
        "reference": "CI 3.2",
        "name": "Staff have the right knowledge, competence and development to care for and support people",
        "key_questions": ["How good is our staff team?"],
        "description": (
            "Staff complete the National Induction Framework (NIF) and meet SSSC registration "
            "requirements including mandatory qualifications. Ongoing CPD is actively supported; "
            "training needs are systematically identified and met; staff can demonstrate competence "
            "and reflect on practice. Specialist training is provided as needed."
        ),
        "keywords": [
            "NIF", "National Induction Framework", "SSSC registration", "SVQ", "qualifications",
            "CPD", "continuing professional development", "competency", "training",
            "mandatory training", "specialist training", "reflection", "learning", "supervision",
        ],
    },
    {
        "reference": "CI 3.3",
        "name": "Staffing arrangements are right and staff work well together",
        "key_questions": ["How good is our staff team?"],
        "description": (
            "Staffing levels and skill mix are appropriate and safe at all times; staff work "
            "cohesively as a team; effective handovers ensure continuity of care; deployment "
            "decisions are driven by people's needs; temporary/agency staff are appropriately "
            "inducted and supervised."
        ),
        "keywords": [
            "staffing levels", "skill mix", "teamwork", "continuity of care", "handover",
            "shift patterns", "safe staffing", "deployment", "agency staff", "bank staff",
            "lone working", "team cohesion",
        ],
    },
    # ── KQ4: How good is our setting? ────────────────────────────────────────
    {
        "reference": "CI 4.1",
        "name": "People experience high quality facilities",
        "key_questions": ["How good is our setting?"],
        "description": (
            "The physical environment is safe, well-maintained, clean and suited to the needs "
            "of the people who use the service. Equipment is appropriate, well-maintained and "
            "available. Health and safety requirements are met; fire safety, COSHH and "
            "risk assessments are in place."
        ),
        "keywords": [
            "facilities", "environment", "cleanliness", "maintenance", "equipment", "health and safety",
            "fire safety", "COSHH", "risk assessment", "premises", "accessibility",
        ],
    },
    {
        "reference": "CI 4.2",
        "name": "The setting promotes people's independence",
        "key_questions": ["How good is our setting?"],
        "description": (
            "The environment is designed and managed to actively promote independence; assistive "
            "technology is used where appropriate; people can move freely and safely around the "
            "spaces available to them; the layout supports dignity and privacy."
        ),
        "keywords": [
            "independence", "assistive technology", "accessibility", "mobility", "layout",
            "privacy", "dignity", "enabling environment", "technology enabled care",
        ],
    },
    {
        "reference": "CI 4.3",
        "name": "People can be connected to and involved in the wider community",
        "key_questions": ["How good is our setting?"],
        "description": (
            "The service actively supports people to maintain community connections, access local "
            "amenities and sustain relationships outside the service. Social isolation is proactively "
            "addressed; people are supported to be active citizens in their local community."
        ),
        "keywords": [
            "community connections", "social isolation", "community involvement", "outings",
            "volunteers", "family contact", "citizenship", "community activities",
        ],
    },
    # ── KQ5: How well is our care and support planned? ────────────────────────
    {
        "reference": "CI 5.1",
        "name": "Assessment and personal planning reflects people's outcomes and wishes",
        "key_questions": ["How well is our care and support planned?"],
        "description": (
            "Individual assessments are thorough, person-centred and co-produced; personal plans "
            "are detailed, current and clearly reflect each person's outcomes, needs, wishes and "
            "choices; plans are reviewed regularly and when needs change; the person is central to "
            "all planning decisions."
        ),
        "keywords": [
            "personal plan", "care planning", "assessment", "personal outcomes", "co-production",
            "person-centred", "individual needs", "wishes", "review", "risk assessment",
            "positive risk", "informed decisions",
        ],
    },
    {
        "reference": "CI 5.2",
        "name": "Carers, friends and family members are encouraged to be involved",
        "key_questions": ["How well is our care and support planned?"],
        "description": (
            "Carers, family members and people important to the individual are actively included "
            "in assessment, care planning and reviews; their expertise about the person is valued; "
            "their own support needs as carers are recognised and addressed."
        ),
        "keywords": [
            "carers", "family involvement", "carer support", "carer assessment", "partnership",
            "relatives", "significant others", "inclusive planning", "carer rights",
        ],
    },
    # ── KQ6: Overall capacity for improvement ────────────────────────────────
    {
        "reference": "CI 6",
        "name": "Overall capacity for improvement",
        "key_questions": ["What is our overall capacity for improvement?"],
        "description": (
            "A global judgement based on evidence and evaluations from all other key questions. "
            "Assesses whether the organisation has the leadership, culture, resources and systems "
            "to sustain and improve quality over time. Takes account of contextual factors "
            "such as staffing changes, restructuring plans or significant funding changes."
        ),
        "keywords": [
            "capacity for improvement", "sustainability", "leadership capability", "change management",
            "resources", "culture of improvement", "self-evaluation", "track record",
            "forward planning", "resilience", "organisational health",
        ],
    },
]


# ── SSSC Code of Practice for Social Service Workers (Worker's Code 2024) ─────
# 6 sections — equivalent to the SCW Worker's Code (Wales) and Care Certificate.
# Source: Scottish Social Services Council, Codes of Practice 2024.

SSSC_CODE_STANDARDS = [
    {
        "reference": "SSSC 1",
        "name": "Protect and promote the rights and interests of individuals and carers",
        "description": (
            "Social service workers must work with kindness, compassion and respect; treat each "
            "individual as unique; respect and promote people's rights, views, wishes and choices; "
            "promote control and informed decision-making; use preferred communication methods; "
            "maintain dignity and privacy; and promote diversity and respect all identities, "
            "values and cultures."
        ),
        "keywords": [
            "rights", "interests", "compassion", "respect", "kindness", "dignity", "privacy",
            "choices", "individuality", "diversity", "identities", "values", "cultures",
            "preferred communication", "informed decisions",
        ],
        "sub_outcomes": [
            {"ref": "1.1", "desc": "Work with kindness, compassion and respect and treat each individual as unique"},
            {"ref": "1.2", "desc": "Respect and promote the rights and, where appropriate, the views, wishes and choices of individuals and carers"},
            {"ref": "1.3", "desc": "Promote the rights of individuals to have control over their lives and make informed choices about their care or support"},
            {"ref": "1.4", "desc": "Work with individuals and carers to communicate using their preferred method and language"},
            {"ref": "1.5", "desc": "Respect and maintain the dignity and privacy of individuals"},
            {"ref": "1.6", "desc": "Promote diversity and respect all identities, values and cultures"},
        ],
    },
    {
        "reference": "SSSC 2",
        "name": "Build and maintain the trust and confidence of individuals and carers",
        "description": (
            "Social service workers must be truthful, open, honest and trustworthy; communicate "
            "respectfully and accurately; maintain confidentiality; be reliable and dependable; "
            "declare conflicts of interest; follow policies on gifts and money; and maintain "
            "professional boundaries that respect dignity, wellbeing and safety."
        ),
        "keywords": [
            "trust", "honesty", "openness", "transparency", "confidentiality", "reliability",
            "professional boundaries", "conflicts of interest", "dependability",
            "communication", "gifts policy",
        ],
        "sub_outcomes": [
            {"ref": "2.1", "desc": "Be truthful, open, honest and trustworthy"},
            {"ref": "2.2", "desc": "Communicate in a respectful, open, accurate and straightforward way"},
            {"ref": "2.3", "desc": "Respect confidential information and clearly explain policies about confidentiality to individuals and carers"},
            {"ref": "2.4", "desc": "Be reliable and dependable"},
            {"ref": "2.5", "desc": "Honour work commitments, agreements and arrangements and explain why when not possible"},
            {"ref": "2.6", "desc": "Declare issues that might create conflicts of interest and ensure they do not influence judgement or practice"},
            {"ref": "2.7", "desc": "Follow policies and procedures about exchanging gifts and money with individuals and carers"},
            {"ref": "2.8", "desc": "Form open, positive relationships and maintain professional boundaries with individuals, colleagues or carers"},
        ],
    },
    {
        "reference": "SSSC 3",
        "name": "Promote the wellbeing and independence of individuals and carers while protecting them from harm",
        "description": (
            "Social service workers must report and challenge dangerous, abusive or discriminatory "
            "behaviour; follow safety procedures; tell employers about resource or operational matters "
            "affecting safe care delivery; report impaired fitness to practise of colleagues; "
            "be open when practice causes harm; cooperate with investigations; work with "
            "individuals to address concerns and complaints; and use power responsibly."
        ),
        "keywords": [
            "wellbeing", "independence", "harm prevention", "safeguarding", "reporting",
            "whistleblowing", "speaking up", "duty of candour", "safety procedures",
            "complaints", "feedback", "power", "abuse reporting",
        ],
        "sub_outcomes": [
            {"ref": "3.1", "desc": "Report allegations of harm, challenge and report any dangerous, abusive or discriminatory behaviour"},
            {"ref": "3.2", "desc": "Follow practices, procedures and policies designed to keep workers and other people safe at work"},
            {"ref": "3.3", "desc": "Tell employer or relevant authority about any resourcing or operational matter that might affect care or support"},
            {"ref": "3.4", "desc": "Tell employer or relevant authority when a colleague's fitness to practise may be impaired"},
            {"ref": "3.5", "desc": "Be open and honest with employer, individuals and carers when practice has or may have caused harm or loss"},
            {"ref": "3.6", "desc": "Cooperate with any investigations by employer, SSSC or relevant authority into fitness to practise"},
            {"ref": "3.7", "desc": "Work with individuals and carers to give and receive feedback, raise concerns and complaints, and act upon them"},
            {"ref": "3.8", "desc": "Recognise and use responsibly the power and authority held when working with individuals, carers and colleagues"},
        ],
    },
    {
        "reference": "SSSC 4",
        "name": "Recognise that individuals have the right to take risks and work with them to understand and manage those risks",
        "description": (
            "Social service workers must support informed choices about potential and actual risks; "
            "follow risk assessment policies; take steps to reduce identified risks; and ensure "
            "relevant colleagues and agencies are informed about risk assessment findings."
        ),
        "keywords": [
            "risk", "positive risk taking", "informed choice", "risk assessment",
            "risk management", "autonomy", "safety", "harm reduction",
        ],
        "sub_outcomes": [
            {"ref": "4.1", "desc": "Work with individuals to make informed choices about potential and actual risks to themselves or others"},
            {"ref": "4.2", "desc": "Follow risk assessment policies and procedures to assess whether behaviour presents a risk of harm"},
            {"ref": "4.3", "desc": "Take necessary steps to reduce the risks of individuals harming themselves or others"},
            {"ref": "4.4", "desc": "Make sure that individuals, relevant colleagues and agencies are informed about the findings and implications of risk assessments"},
        ],
    },
    {
        "reference": "SSSC 5",
        "name": "Be accountable for the quality of work and take responsibility for maintaining and improving knowledge and skills",
        "description": (
            "Social service workers must meet relevant standards of practice; maintain accurate "
            "records; tell employers about personal circumstances affecting job competence; seek "
            "support when uncertain; engage in supervision to reflect on practice and development; "
            "maintain CPL (Continuous Professional Learning) to improve knowledge and skills; "
            "work openly with colleagues; understand responsibility for delegated work; "
            "and work in a trauma-informed way."
        ),
        "keywords": [
            "accountability", "quality of work", "records management", "documentation",
            "professional development", "CPL", "continuous professional learning",
            "supervision", "reflection", "delegated work", "competence",
            "trauma-informed practice", "partnership working", "fitness to practise",
        ],
        "sub_outcomes": [
            {"ref": "5.1", "desc": "Meet relevant standards of practice and work in a lawful, safe and effective way"},
            {"ref": "5.2", "desc": "Maintain clear, accurate and up-to-date records in line with policies and procedures"},
            {"ref": "5.3", "desc": "Tell employer about personal circumstances or experiences that may affect ability to do job competently and safely"},
            {"ref": "5.4", "desc": "Ask for support if not adequately prepared or unsure how to proceed"},
            {"ref": "5.5", "desc": "Prepare for and engage in supervision to reflect on development, learning needs, wellbeing and practice"},
            {"ref": "5.6", "desc": "Maintain continuous professional learning (CPL) to improve knowledge and skills and contribute to others' development"},
            {"ref": "5.7", "desc": "Cooperate and work inclusively and openly with colleagues and treat them with respect"},
            {"ref": "5.8", "desc": "Work in a way that is informed by an understanding of the impact that trauma may have on individuals, carers and colleagues"},
            {"ref": "5.9", "desc": "Be responsible for the work delegated to others"},
            {"ref": "5.10", "desc": "Respect the roles and expertise of colleagues from other professions and work in partnership with them"},
            {"ref": "5.11", "desc": "Recognise and respect the roles, expertise and experience of carers, families and relevant others"},
            {"ref": "5.12", "desc": "Invite and listen to feedback from individuals, carers and others and use this to improve practice"},
        ],
    },
    {
        "reference": "SSSC 6",
        "name": "Uphold public trust and confidence",
        "description": (
            "Social service workers must not abuse, harm, neglect or exploit individuals, carers "
            "or colleagues; must not abuse trust or misuse personal information; must not form "
            "unprofessional relationships; must not discriminate or condone discrimination; "
            "must not put people at unnecessary risk; and must not behave in a way that brings "
            "into question suitability to work in social services — in or outside work."
        ),
        "keywords": [
            "public trust", "professional conduct", "integrity", "exploitation", "abuse of trust",
            "confidentiality", "professional relationships", "discrimination", "fitness to practise",
            "SSSC registration", "conduct outside work", "social media",
        ],
        "sub_outcomes": [
            {"ref": "6.1", "desc": "Must not abuse, harm, neglect or exploit individuals, carers or colleagues"},
            {"ref": "6.2", "desc": "Must not abuse the trust of individuals, carers or colleagues, or misuse information about them"},
            {"ref": "6.3", "desc": "Must not form unprofessional or harmful relationships with individuals or carers"},
            {"ref": "6.4", "desc": "Must not discriminate against individuals, carers or colleagues"},
            {"ref": "6.5", "desc": "Must not condone any discrimination by individuals, carers or colleagues"},
            {"ref": "6.6", "desc": "Must not put self or other people at unnecessary risk"},
            {"ref": "6.7", "desc": "Must not behave, while in or outside work, in a way that would bring suitability to work in social services into question"},
        ],
    },
]


async def seed_scotland_standards():
    """Seed Scottish standards: CI Quality Indicators (18) and SSSC Worker's Code (6 sections)."""
    async with database.with_admin() as conn:
        scotland_count = await conn.fetchval(
            "SELECT COUNT(*) FROM standards_entries WHERE is_system=TRUE AND jurisdiction='scotland'"
        )
        if scotland_count and scotland_count > 0:
            logger.info(f"Scotland standards already seeded ({scotland_count} entries) — skipping")
            return

        now = datetime.now(timezone.utc).isoformat()
        entries = []

        for qi in CI_QUALITY_INDICATORS:
            entries.append({
                "id": str(uuid.uuid4()),
                "type": "ci",
                "reference": qi["reference"],
                "name": qi["name"],
                "description": qi["description"],
                "keywords": qi["keywords"],
                "sub_outcomes": [],
                "key_questions": qi.get("key_questions", []),
                "quality_statement": False,
                "source": (
                    "Care Inspectorate Scotland — Quality Framework for Care Homes for Adults "
                    "and Older People (applicable across registered adult social care services)"
                ),
                "created_at": now,
            })

        for std in SSSC_CODE_STANDARDS:
            entries.append({
                "id": str(uuid.uuid4()),
                "type": "sssc",
                "reference": std["reference"],
                "name": std["name"],
                "description": std["description"],
                "keywords": std["keywords"],
                "sub_outcomes": std["sub_outcomes"],
                "key_questions": [],
                "quality_statement": False,
                "source": "Scottish Social Services Council — Code of Practice for Social Service Workers (2024)",
                "created_at": now,
            })

        await _insert_standards_entries(conn, entries, "scotland")
        logger.info(
            f"Seeded {len(entries)} Scotland standards entries "
            f"({len(CI_QUALITY_INDICATORS)} CI quality indicators, {len(SSSC_CODE_STANDARDS)} SSSC Code sections)"
        )



async def seed_super_admin():
    """Create the super admin account (idempotent)."""
    from routers.auth import hash_password
    email = os.environ.get("SUPER_ADMIN_EMAIL", "superadmin@1two.one")
    password = os.environ.get("SUPER_ADMIN_PASSWORD", "SuperAdmin123!")

    async with database.with_admin() as conn:
        existing = await conn.fetchrow("SELECT id, role FROM users WHERE email = $1", email)
        if existing is None:
            await conn.execute(
                """INSERT INTO users (id, email, password_hash, name, role, is_active, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                str(uuid.uuid4()), email, hash_password(password),
                "Super Admin", "super_admin", True,
                datetime.now(timezone.utc).isoformat(),
            )
            logger.info(f"Super admin seeded: {email}")
        elif existing["role"] != "super_admin":
            await conn.execute("UPDATE users SET role = 'super_admin' WHERE email = $1", email)
            logger.info(f"Updated {email} to super_admin role")


async def seed_default_org():
    """Create 'Test Company' org if not exists (idempotent)."""
    async with database.with_admin() as conn:
        org = await conn.fetchrow("SELECT id FROM organisations WHERE slug = 'test-company'")
        if org is None:
            now = datetime.now(timezone.utc).isoformat()
            org_id = str(uuid.uuid4())
            await conn.execute(
                """INSERT INTO organisations (id, name, slug, status, branding, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6)""",
                org_id, "Test Company", "test-company", "active", "{}", now,
            )
            logger.info(f"Default org 'Test Company' created: {org_id}")
            return org_id
        return org["id"]


async def seed_all():
    """Run all seed functions on startup."""
    # One-time schema migrations
    async with database.with_admin() as conn:
        await conn.execute(
            "ALTER TABLE organisations ADD COLUMN IF NOT EXISTS jurisdiction TEXT NOT NULL DEFAULT 'england'"
        )
        await conn.execute(
            "ALTER TABLE standards_entries ADD COLUMN IF NOT EXISTS jurisdiction TEXT NOT NULL DEFAULT 'england'"
        )
    await seed_standards()
    await seed_welsh_standards()
    await seed_scotland_standards()
    await seed_super_admin()
    await seed_default_org()
