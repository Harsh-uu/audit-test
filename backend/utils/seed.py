from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

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
    {"reference": "CQC Reg 12 (Registration)", "name": "Statement of purpose", "key_questions": ["Well-led"], "description": "Registered persons must provide a statement of purpose covering the regulated activities they carry out.", "keywords": ["statement of purpose", "regulated activities", "registration"]},
]

CARE_CERT_STANDARDS = [
    {
        "reference": "Standard 1", "name": "Understanding your role",
        "description": "The care worker understands their role and responsibilities, the importance of working within their scope of practice, and the impact of their role on the person they support.",
        "keywords": ["role", "responsibilities", "boundaries", "scope of practice", "code of conduct", "accountability"],
        "outcomes": [
            {"ref": "1.1", "name": "Understand your own role"},
            {"ref": "1.2", "name": "Understand working relationships in health and social care"},
            {"ref": "1.3", "name": "Work in agreed ways"},
        ]
    },
    {
        "reference": "Standard 2", "name": "Your personal development",
        "description": "The care worker is committed to their personal development, including training, learning, CPD, and reflective practice. Includes supervision and appraisal.",
        "keywords": ["training", "learning", "CPD", "personal development", "reflective practice", "supervision", "appraisal", "development"],
        "outcomes": [
            {"ref": "2.1", "name": "Agree a personal development plan"},
            {"ref": "2.2", "name": "Develop your knowledge, skills and understanding"},
            {"ref": "2.3", "name": "Reflect on and evaluate your learning and development"},
        ]
    },
    {
        "reference": "Standard 3", "name": "Duty of care",
        "description": "The care worker understands their duty of care and how to balance this with an individual's rights. Includes dilemmas, complaints and incidents.",
        "keywords": ["duty of care", "dilemmas", "complaints", "incidents", "rights", "wellbeing", "safeguarding"],
        "outcomes": [
            {"ref": "3.1", "name": "Understand how duty of care contributes to safe practice"},
            {"ref": "3.2", "name": "Deal with comments and complaints"},
            {"ref": "3.3", "name": "Deal with incidents, errors and near-misses"},
            {"ref": "3.4", "name": "Deal with confrontation and difficult situations"},
        ]
    },
    {
        "reference": "Standard 4", "name": "Equality and diversity",
        "description": "The care worker works in an inclusive way that values diversity and treats people as individuals, respecting protected characteristics and challenging discrimination.",
        "keywords": ["equality", "diversity", "inclusion", "discrimination", "protected characteristics", "individual needs", "culture", "religion"],
        "outcomes": [
            {"ref": "4.1", "name": "Understand the importance of equality and inclusion"},
            {"ref": "4.2", "name": "Work in an inclusive way"},
            {"ref": "4.3", "name": "Access information, advice and support about diversity, equality and inclusion"},
        ]
    },
    {
        "reference": "Standard 5", "name": "Work in a person-centred way",
        "description": "The care worker puts the individual at the centre of care, supporting their choices, promoting their wellbeing and independence.",
        "keywords": ["person-centred", "choices", "independence", "wellbeing", "preferences", "self-determination", "outcomes"],
        "outcomes": [
            {"ref": "5.1", "name": "Understand person-centred values"},
            {"ref": "5.2", "name": "Work in a person-centred way"},
            {"ref": "5.3", "name": "Support an individual's wellbeing"},
            {"ref": "5.4", "name": "Support use of assistive technology to enhance everyday life"},
        ]
    },
    {
        "reference": "Standard 6", "name": "Communication",
        "description": "The care worker communicates effectively in verbal and non-verbal ways, adapts to individuals' communication needs, and maintains accurate records.",
        "keywords": ["communication", "listening", "non-verbal", "language needs", "records", "handover", "reporting", "documentation"],
        "outcomes": [
            {"ref": "6.1", "name": "Understand the importance of communication"},
            {"ref": "6.2", "name": "Meet the communication and language needs, wishes and preferences of individuals"},
            {"ref": "6.3", "name": "Reduce barriers to effective communication"},
            {"ref": "6.4", "name": "Use different forms of communication"},
            {"ref": "6.5", "name": "Access extra support or services to enable more effective communication"},
            {"ref": "6.6", "name": "Understand principles and practices relating to confidentiality"},
            {"ref": "6.7", "name": "Support use of information technology to enhance communication"},
        ]
    },
    {
        "reference": "Standard 7", "name": "Privacy and dignity",
        "description": "The care worker promotes and maintains the privacy, dignity and respect of each individual in their care.",
        "keywords": ["privacy", "dignity", "respect", "confidentiality", "personal information", "intimate care"],
        "outcomes": [
            {"ref": "7.1", "name": "Understand the principles that underpin privacy and dignity in care"},
            {"ref": "7.2", "name": "Maintain the privacy and dignity of individuals in their care"},
            {"ref": "7.3", "name": "Support an individual's right to make choices"},
        ]
    },
    {
        "reference": "Standard 8", "name": "Fluids and nutrition",
        "description": "The care worker supports individuals to have adequate nutrition and hydration, understands signs of malnutrition and dehydration.",
        "keywords": ["nutrition", "hydration", "fluid intake", "malnutrition", "dehydration", "diet", "eating", "drinking", "mealtime"],
        "outcomes": [
            {"ref": "8.1", "name": "Understand the principles of hydration, nutrition and food safety"},
            {"ref": "8.2", "name": "Support individuals to have access to fluids, food and nutrition"},
        ]
    },
    {
        "reference": "Standard 9", "name": "Awareness of mental health, dementia and learning disability",
        "description": "The care worker has awareness of mental health conditions, dementia and learning disability, and how these affect individuals' wellbeing and behaviour.",
        "keywords": ["mental health", "dementia", "learning disability", "behaviour", "wellbeing", "cognitive impairment", "anxiety", "depression"],
        "outcomes": [
            {"ref": "9.1", "name": "Understand the needs and experiences of people with mental health conditions"},
            {"ref": "9.2", "name": "Understand the needs and experiences of people with dementia"},
            {"ref": "9.3", "name": "Understand the needs and experiences of people with learning disabilities"},
        ]
    },
    {
        "reference": "Standard 10", "name": "Safeguarding adults",
        "description": "The care worker understands adult safeguarding, recognises signs of abuse and neglect, and knows how to report concerns.",
        "keywords": ["safeguarding", "abuse", "neglect", "reporting", "whistleblowing", "protection", "harm", "exploitation", "concerns"],
        "outcomes": [
            {"ref": "10.1", "name": "Understand the importance of safeguarding adults"},
            {"ref": "10.2", "name": "Reduce the likelihood of abuse"},
            {"ref": "10.3", "name": "Respond to suspected or disclosed abuse"},
            {"ref": "10.4", "name": "Protect people from harm and abuse – locally and nationally"},
        ]
    },
    {
        "reference": "Standard 11", "name": "Safeguarding children",
        "description": "The care worker is aware of child safeguarding responsibilities even when primarily working with adults.",
        "keywords": ["safeguarding children", "child protection", "young carers", "children"],
        "outcomes": [
            {"ref": "11.1", "name": "Understand the importance of safeguarding children"},
            {"ref": "11.2", "name": "Recognise and respond to concerns about the safeguarding of children"},
        ]
    },
    {
        "reference": "Standard 12", "name": "Basic life support",
        "description": "The care worker knows how to provide basic life support, including CPR and the use of AED, and can respond to emergency situations.",
        "keywords": ["first aid", "CPR", "resuscitation", "basic life support", "emergency", "AED", "choking"],
        "outcomes": [
            {"ref": "12.1", "name": "Understand own role in the event of a basic life support situation"},
            {"ref": "12.2", "name": "Administer basic life support (CPR)"},
        ]
    },
    {
        "reference": "Standard 13", "name": "Health and safety",
        "description": "The care worker understands health and safety legislation, risk assessment, COSHH, moving and handling, and personal protective equipment.",
        "keywords": ["health and safety", "risk assessment", "COSHH", "moving and handling", "manual handling", "PPE", "lone working", "fire safety"],
        "outcomes": [
            {"ref": "13.1", "name": "Understand own responsibilities relating to health and safety"},
            {"ref": "13.2", "name": "Understand the use of risk assessments"},
            {"ref": "13.3", "name": "Move and assist people and objects safely"},
            {"ref": "13.4", "name": "Understand how to handle hazardous substances"},
            {"ref": "13.5", "name": "Promote fire safety in the work setting"},
            {"ref": "13.6", "name": "Work safely with others"},
            {"ref": "13.7", "name": "Handle confidential information in line with agreed ways of working"},
        ]
    },
    {
        "reference": "Standard 14", "name": "Handling information",
        "description": "The care worker understands data protection, GDPR, confidentiality obligations, and maintains accurate, secure records.",
        "keywords": ["data protection", "GDPR", "confidentiality", "records management", "information governance", "sharing information"],
        "outcomes": [
            {"ref": "14.1", "name": "Understand the need for secure handling of information"},
            {"ref": "14.2", "name": "Handle information in line with agreed ways of working"},
        ]
    },
    {
        "reference": "Standard 15", "name": "Infection prevention and control",
        "description": "The care worker understands and applies infection prevention and control measures, including hand hygiene, PPE, and standard precautions.",
        "keywords": ["infection control", "PPE", "hand hygiene", "standard precautions", "cleaning", "waste disposal", "COVID", "outbreak"],
        "outcomes": [
            {"ref": "15.1", "name": "Understand own role in infection prevention and control"},
            {"ref": "15.2", "name": "Understand legislation relating to infection prevention and control"},
            {"ref": "15.3", "name": "Carry out role in team approach to infection prevention and control"},
            {"ref": "15.4", "name": "Minimise the spread of infection"},
            {"ref": "15.5", "name": "Use personal protective equipment (PPE)"},
            {"ref": "15.6", "name": "Understand principles of good personal hygiene"},
        ]
    },
    {
        "reference": "Standard 16", "name": "Awareness of learning disability and autism",
        "description": "The care worker has awareness of learning disabilities and autism, including different communication styles, behaviours and support needs.",
        "keywords": ["learning disability", "autism", "communication", "behaviour", "support needs", "neurodivergent", "sensory"],
        "outcomes": [
            {"ref": "16.1", "name": "Understand what is meant by learning disability and autism"},
            {"ref": "16.2", "name": "Understand the impact of learning disability and autism on individuals"},
            {"ref": "16.3", "name": "Understand communication and behaviour in relation to learning disability and autism"},
        ]
    },
]


async def seed_standards(db):
    count = await db.standards_entries.count_documents({})
    if count > 0:
        logger.info(f"Standards already seeded ({count} entries)")
        await migrate_standard_outcomes(db)
        return

    now = datetime.now(timezone.utc).isoformat()
    entries = []
    for reg in CQC_REGULATIONS:
        entries.append({**reg, "type": "cqc", "is_active": True, "created_at": now, "source": "CQC Guidance - Regulations for service providers and managers"})
    for std in CARE_CERT_STANDARDS:
        entries.append({**std, "type": "care_cert", "is_active": True, "created_at": now, "source": "Care Certificate Standards 2025 - Skills for Care"})

    await db.standards_entries.insert_many(entries)
    logger.info(f"Seeded {len(entries)} standards entries")


async def migrate_standard_outcomes(db):
    """Add outcomes to existing Care Certificate standards entries that don't have them yet."""
    outcomes_map = {std["reference"]: std["outcomes"] for std in CARE_CERT_STANDARDS}
    updated = 0
    for ref, outcomes in outcomes_map.items():
        result = await db.standards_entries.update_one(
            {"reference": ref, "type": "care_cert", "outcomes": {"$exists": False}},
            {"$set": {"outcomes": outcomes}}
        )
        if result.modified_count:
            updated += 1
    if updated:
        logger.info(f"Migrated outcomes to {updated} Care Certificate standard entries")



async def migrate_cqc_key_questions(db):
    """Add key_questions to existing CQC regulation entries that don't have them yet."""
    kq_map = {reg["reference"]: reg["key_questions"] for reg in CQC_REGULATIONS}
    updated = 0
    for ref, kq in kq_map.items():
        result = await db.standards_entries.update_one(
            {"reference": ref, "type": "cqc", "key_questions": {"$exists": False}},
            {"$set": {"key_questions": kq}}
        )
        if result.modified_count:
            updated += 1
    if updated:
        logger.info(f"Migrated key_questions to {updated} CQC regulation entries")


async def migrate_analyses_key_questions(db):
    """Back-fill key_questions onto cqc_mappings in existing analysis documents."""
    kq_map = {reg["reference"]: reg["key_questions"] for reg in CQC_REGULATIONS}
    updated = 0
    async for analysis in db.analyses.find({}):
        mappings = analysis.get("cqc_mappings", [])
        changed = False
        for m in mappings:
            if not m.get("key_questions") and m.get("regulation_ref") in kq_map:
                m["key_questions"] = kq_map[m["regulation_ref"]]
                changed = True
        if changed:
            await db.analyses.update_one(
                {"_id": analysis["_id"]},
                {"$set": {"cqc_mappings": mappings}}
            )
            updated += 1
    if updated:
        logger.info(f"Back-filled key_questions on {updated} existing analysis documents")
