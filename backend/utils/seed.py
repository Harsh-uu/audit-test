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


# ── CIW (Care Inspectorate Wales) — 7 inspection key questions ────────────────
# Based on RISCA 2016 and CIW's inspection framework for regulated services in Wales.
# Equivalent to CQC's 5 key questions (Safe/Effective/Caring/Responsive/Well-led).

CIW_REGULATIONS = [
    {
        "reference": "CIW 1",
        "name": "Well-being outcomes",
        "key_questions": ["Well-being"],
        "description": (
            "Are people's individual well-being outcomes achieved? "
            "Services must support people to achieve their personal outcomes and promote their physical, "
            "mental and emotional well-being, social relationships, participation in the community, and "
            "protection from abuse and neglect. Underpinned by the Social Services and Well-being (Wales) Act 2014."
        ),
        "keywords": [
            "well-being", "personal outcomes", "voice and control", "co-production",
            "social participation", "independence", "emotional health", "mental well-being",
            "SSWB Act 2014", "well-being goals", "individual outcomes",
        ],
    },
    {
        "reference": "CIW 2",
        "name": "Care and support",
        "key_questions": ["Care and Support"],
        "description": (
            "Is care and support appropriate, person-centred, safe and effective? "
            "Providers must assess individual needs, plan and deliver care that respects rights, "
            "dignity and preferences, and involves the person in all decisions about their care and support. "
            "Regulated under RISCA 2016 National Minimum Standards."
        ),
        "keywords": [
            "person-centred care", "care planning", "needs assessment", "consent", "dignity",
            "individual rights", "preferences", "cultural needs", "communication", "advocacy",
            "RISCA 2016", "statement of purpose", "active participation",
        ],
    },
    {
        "reference": "CIW 3",
        "name": "Safeguarding",
        "key_questions": ["Safeguarding"],
        "description": (
            "Are people protected from harm, abuse and neglect? "
            "Providers must have robust safeguarding policies aligned with Wales Safeguarding Procedures 2019, "
            "ensure all staff are trained, and act promptly on any concern. Includes adult and child "
            "safeguarding responsibilities under the Social Services and Well-being (Wales) Act 2014."
        ),
        "keywords": [
            "safeguarding", "abuse", "neglect", "harm", "whistleblowing",
            "Wales Safeguarding Procedures", "referral", "disclosure", "Disclosure and Barring Service",
            "DBS", "safeguarding adults", "safeguarding children", "exploitation",
            "risk of harm", "reportable", "POVA", "restrictive practice",
        ],
    },
    {
        "reference": "CIW 4",
        "name": "Health and personal care",
        "key_questions": ["Health"],
        "description": (
            "Are people's health and personal care needs assessed, planned for and met? "
            "This includes medication management, nutrition and hydration, clinical healthcare needs, "
            "personal care, pressure area care, end of life care and access to healthcare professionals. "
            "Workers must understand their responsibilities and work within their competence."
        ),
        "keywords": [
            "health needs", "medication management", "nutrition", "hydration", "personal care",
            "pressure area care", "end of life", "healthcare professionals", "GP", "district nurse",
            "medication administration", "MAR", "continence", "oral health", "dementia",
            "mental health", "sensory loss", "palliative care", "falls prevention",
        ],
    },
    {
        "reference": "CIW 5",
        "name": "Leadership and management",
        "key_questions": ["Well-led"],
        "description": (
            "Is there effective leadership, governance and a culture of continuous improvement? "
            "The Responsible Individual and Registered Manager must demonstrate competent, values-led "
            "leadership, maintain robust governance systems, and operate a culture of quality improvement "
            "and learning. This includes the Quality of Care Review required under RISCA 2016 regulations."
        ),
        "keywords": [
            "registered manager", "responsible individual", "governance", "quality improvement",
            "quality of care review", "statement of purpose", "supervision", "appraisal",
            "policies and procedures", "audit", "complaints", "notifications to CIW",
            "annual return", "learning culture", "values-led leadership", "openness",
        ],
    },
    {
        "reference": "CIW 6",
        "name": "Staffing",
        "key_questions": ["Staffing"],
        "description": (
            "Is the workforce sufficient, appropriately qualified, registered and well-supported? "
            "Providers must ensure safe staffing levels, that workers complete the All Wales Induction "
            "Framework (AWIF) within 6 months, hold relevant qualifications, are registered with Social "
            "Care Wales where required, and receive regular supervision and continuing professional development."
        ),
        "keywords": [
            "AWIF", "All Wales Induction Framework", "Social Care Wales", "SCW registration",
            "staffing levels", "qualifications", "training", "supervision", "CPD",
            "professional development", "workforce planning", "DBS", "references",
            "mandatory training", "competency", "induction",
        ],
    },
    {
        "reference": "CIW 7",
        "name": "Environment and safety",
        "key_questions": ["Environment"],
        "description": (
            "Is the environment safe, suitable, well-maintained and promoting of well-being? "
            "Premises must meet health and safety requirements, infection prevention and control standards, "
            "fire safety regulations, and provide a suitable, accessible environment that supports "
            "people's dignity and promotes their well-being."
        ),
        "keywords": [
            "health and safety", "infection prevention", "fire safety", "COSHH",
            "risk assessment", "moving and handling", "equipment maintenance", "premises",
            "accessibility", "lone working", "food safety", "hazardous substances",
            "security", "IPC", "PPE", "environmental safety",
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
    """Insert Welsh standards: CIW (7 key questions), AWIF (7 workbooks), SCW Code (6 sections)."""
    async with database.with_admin() as conn:
        welsh_count = await conn.fetchval(
            "SELECT COUNT(*) FROM standards_entries WHERE is_system=TRUE AND jurisdiction='wales'"
        )
        if welsh_count and welsh_count > 0:
            logger.info(f"Welsh standards already seeded ({welsh_count} entries) — skipping")
            return

        now = datetime.now(timezone.utc).isoformat()
        entries = []

        for reg in CIW_REGULATIONS:
            entries.append({
                "id": str(uuid.uuid4()),
                "type": "ciw",
                "reference": reg["reference"],
                "name": reg["name"],
                "description": reg["description"],
                "keywords": reg["keywords"],
                "sub_outcomes": [],
                "key_questions": reg.get("key_questions", []),
                "quality_statement": False,
                "source": "Care Inspectorate Wales (CIW) — RISCA 2016 Inspection Framework",
                "created_at": now,
            })

        for wb in AWIF_STANDARDS:
            entries.append({
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
            entries.append({
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

        await _insert_standards_entries(conn, entries, "wales")
        logger.info(
            f"Seeded {len(entries)} Welsh standards entries "
            f"({len(CIW_REGULATIONS)} CIW, {len(AWIF_STANDARDS)} AWIF, {len(SCW_CODE_STANDARDS)} SCW)"
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
    # Run one-time schema migrations (idempotent — IF NOT EXISTS guards)
    async with database.with_admin() as conn:
        await conn.execute(
            "ALTER TABLE organisations ADD COLUMN IF NOT EXISTS jurisdiction TEXT NOT NULL DEFAULT 'england'"
        )
        await conn.execute(
            "ALTER TABLE standards_entries ADD COLUMN IF NOT EXISTS jurisdiction TEXT NOT NULL DEFAULT 'england'"
        )
    await seed_standards()
    await seed_welsh_standards()
    await seed_super_admin()
    await seed_default_org()
