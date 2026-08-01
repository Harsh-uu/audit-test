"""
PostgreSQL seed: system standards, super admin, default org.
Called once on startup — all operations are idempotent.
"""
from datetime import datetime, timezone
import uuid
import logging
import os

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


async def seed_standards():
    """Insert CQC regulations, quality statements, and Care Certificate standards (idempotent)."""
    import json as _json

    async with database.with_admin() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM standards_entries WHERE is_system = TRUE")
        if count and count > 0:
            # One-time fix: check if JSONB fields were double-encoded (sub_outcomes stored as string)
            sample = await conn.fetchrow(
                "SELECT sub_outcomes FROM standards_entries WHERE is_system = TRUE LIMIT 1"
            )
            if sample and isinstance(sample["sub_outcomes"], str):
                logger.info("Detected double-encoded JSONB in standards — repairing…")
                rows = await conn.fetch(
                    "SELECT id, keywords, sub_outcomes, key_questions FROM standards_entries WHERE is_system = TRUE"
                )
                for row in rows:
                    kw = _json.loads(row["keywords"]) if isinstance(row["keywords"], str) else (row["keywords"] or [])
                    so = _json.loads(row["sub_outcomes"]) if isinstance(row["sub_outcomes"], str) else (row["sub_outcomes"] or [])
                    kq = _json.loads(row["key_questions"]) if isinstance(row["key_questions"], str) else (row["key_questions"] or [])
                    await conn.execute(
                        "UPDATE standards_entries SET keywords=$1, sub_outcomes=$2, key_questions=$3 WHERE id=$4",
                        kw, so, kq, row["id"],
                    )
                logger.info("JSONB repair complete for standards_entries")
            else:
                logger.info(f"Standards already seeded ({count} entries) — skipping")
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
                "is_active": True,
                "is_system": True,
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
                "is_active": True,
                "is_system": True,
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
                "is_active": True,
                "is_system": True,
                "created_at": now,
            })

        import json
        for e in entries:
            await conn.execute(
                """INSERT INTO standards_entries
                   (id, org_id, type, reference, name, description, keywords, sub_outcomes,
                    key_questions, quality_statement, source, is_active, is_system, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb,$10,$11,$12,$13,$14)
                   ON CONFLICT (id) DO NOTHING""",
                e["id"], None, e["type"], e["reference"], e["name"], e["description"],
                json.dumps(e["keywords"]), json.dumps(e["sub_outcomes"]),
                json.dumps(e["key_questions"]), e["quality_statement"], e["source"],
                e["is_active"], e["is_system"], e["created_at"],
            )
        logger.info(f"Seeded {len(entries)} standards entries")


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
    await seed_standards()
    await seed_super_admin()
    await seed_default_org()
