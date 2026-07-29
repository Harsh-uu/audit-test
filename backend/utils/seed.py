from datetime import datetime, timezone
import logging
import os

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

# CQC Quality Statements (introduced in the new single assessment framework — 34 statements across 5 themes)
CQC_QUALITY_STATEMENTS = [
    # ── Safe ──────────────────────────────────────────────────────────────────
    {"reference": "QS Safe 1",  "name": "Learning culture",                     "key_questions": ["Safe"],        "quality_statement": True, "description": "We have a proactive and positive culture of safety based on openness and honesty, in which concerns about safety are investigated and reported thoroughly, and lessons are learned to continually identify and embed good practices.", "keywords": ["learning culture", "safety culture", "openness", "honesty", "lessons learned", "incident reporting", "good practice", "continuous improvement"]},
    {"reference": "QS Safe 2",  "name": "Safe systems, pathways and transitions","key_questions": ["Safe"],        "quality_statement": True, "description": "We work with people and our partners to establish and maintain safe systems of care, in which safety is managed, monitored and assured. We ensure continuity of care, including when people move between different services.", "keywords": ["safe systems", "pathways", "transitions", "continuity of care", "monitoring", "assurance", "handover", "discharge"]},
    {"reference": "QS Safe 3",  "name": "Safeguarding",                          "key_questions": ["Safe"],        "quality_statement": True, "description": "We work with people to understand what being safe means to them as well as with our partners on the best way to achieve this. We concentrate on improving people's lives while protecting their right to live in safety, free from bullying, harassment, abuse, discrimination, avoidable harm and neglect. We make sure we share concerns quickly and appropriately.", "keywords": ["safeguarding", "abuse", "neglect", "harm", "bullying", "harassment", "discrimination", "concerns", "protection"]},
    {"reference": "QS Safe 4",  "name": "Involving people to manage risks",      "key_questions": ["Safe"],        "quality_statement": True, "description": "We work with people to understand and manage risks by thinking holistically so that care meets their needs in a way that is safe and supportive and enables them to do the things that matter to them.", "keywords": ["risk management", "risk assessment", "holistic", "involvement", "positive risk", "enabling", "safety"]},
    {"reference": "QS Safe 5",  "name": "Safe environments",                     "key_questions": ["Safe"],        "quality_statement": True, "description": "We detect and control potential risks in the care environment. We make sure that equipment, facilities and technology support the delivery of safe care.", "keywords": ["environment", "equipment", "facilities", "technology", "risk", "health and safety", "premises"]},
    {"reference": "QS Safe 6",  "name": "Safe and effective staffing",           "key_questions": ["Safe"],        "quality_statement": True, "description": "We make sure there are enough qualified, skilled and experienced people, who receive effective support, supervision and development. They work together effectively to provide safe care that meets people's individual needs.", "keywords": ["staffing", "qualified", "skilled", "supervision", "support", "development", "workforce", "appraisal", "training"]},
    {"reference": "QS Safe 7",  "name": "Infection prevention and control",      "key_questions": ["Safe"],        "quality_statement": True, "description": "We assess and manage the risk of infection. We detect and control the risk of it spreading and share any concerns with appropriate agencies promptly.", "keywords": ["infection", "IPC", "prevention", "control", "hygiene", "PPE", "spreading", "risk"]},
    {"reference": "QS Safe 8",  "name": "Medicines optimisation",                "key_questions": ["Safe"],        "quality_statement": True, "description": "We make sure that medicines and treatments are safe and meet people's needs, capacities and preferences by enabling them to be involved in planning, including when changes happen.", "keywords": ["medicines", "medication", "treatment", "capacity", "preferences", "prescribing", "administration", "MAR", "medication management"]},
    # ── Effective ─────────────────────────────────────────────────────────────
    {"reference": "QS Effective 1", "name": "Assessing needs",                   "key_questions": ["Effective"],   "quality_statement": True, "description": "We maximise the effectiveness of people's care and treatment by assessing and reviewing their health, care, wellbeing and communication needs with them.", "keywords": ["assessment", "needs assessment", "health", "wellbeing", "communication needs", "review", "care planning"]},
    {"reference": "QS Effective 2", "name": "Delivering evidence-based care",    "key_questions": ["Effective"],   "quality_statement": True, "description": "We plan and deliver people's care and treatment with them, including what is important and matters to them. We do this in line with legislation and current evidence-based good practice and standards.", "keywords": ["evidence-based", "care planning", "legislation", "best practice", "standards", "NICE guidance", "clinical guidelines"]},
    {"reference": "QS Effective 3", "name": "How staff and teams work together", "key_questions": ["Effective"],   "quality_statement": True, "description": "We work effectively across teams and services to support people. We make sure they only need to tell their story once by sharing their assessment of needs when they move between different services.", "keywords": ["teamwork", "collaboration", "information sharing", "multi-disciplinary", "handover", "integrated care", "MDT"]},
    {"reference": "QS Effective 4", "name": "Supporting people to live healthier lives", "key_questions": ["Effective"], "quality_statement": True, "description": "We support people to manage their health and wellbeing so they can maximise their independence, choice and control. We support them to live healthier lives and where possible, reduce their future needs for care and support.", "keywords": ["independence", "choice", "control", "health promotion", "wellbeing", "self-management", "prevention"]},
    {"reference": "QS Effective 5", "name": "Monitoring and improving outcomes", "key_questions": ["Effective"],   "quality_statement": True, "description": "We routinely monitor people's care and treatment to continuously improve it. We ensure that outcomes are positive and consistent, and that they meet both clinical expectations and the expectations of people themselves.", "keywords": ["outcomes", "monitoring", "improvement", "quality", "audit", "review", "consistency"]},
    {"reference": "QS Effective 6", "name": "Consent to care and treatment",     "key_questions": ["Effective"],   "quality_statement": True, "description": "We tell people about their rights around consent and respect these when we deliver person-centred care and treatment.", "keywords": ["consent", "rights", "person-centred", "mental capacity", "best interests", "informed consent", "decision-making"]},
    # ── Caring ────────────────────────────────────────────────────────────────
    {"reference": "QS Caring 1", "name": "Kindness, compassion and dignity",     "key_questions": ["Caring"],      "quality_statement": True, "description": "We always treat people with kindness, empathy and compassion and we respect their privacy and dignity. We treat colleagues from other organisations with kindness and respect.", "keywords": ["kindness", "compassion", "dignity", "empathy", "respect", "privacy", "emotional support"]},
    {"reference": "QS Caring 2", "name": "Treating people as individuals",       "key_questions": ["Caring"],      "quality_statement": True, "description": "We treat people as individuals and make sure their care, support and treatment meets their needs and preferences. We take account of their strengths, abilities, aspirations, culture and unique backgrounds and protected characteristics.", "keywords": ["individual", "person-centred", "diversity", "protected characteristics", "culture", "preferences", "strengths", "aspirations"]},
    {"reference": "QS Caring 3", "name": "Independence, choice and control",     "key_questions": ["Caring"],      "quality_statement": True, "description": "We promote people's independence, so they know their rights and have choice and control over their own care, treatment and wellbeing.", "keywords": ["independence", "choice", "control", "rights", "empowerment", "autonomy", "self-determination"]},
    {"reference": "QS Caring 4", "name": "Responding to people's immediate needs","key_questions": ["Caring"],     "quality_statement": True, "description": "We listen to and understand people's needs, views and wishes. We respond to these in that moment and will act to minimise any discomfort, concern or distress.", "keywords": ["listening", "immediate needs", "distress", "comfort", "responsive", "empathy", "wishes", "wellbeing"]},
    {"reference": "QS Caring 5", "name": "Workforce wellbeing and enablement",   "key_questions": ["Caring"],      "quality_statement": True, "description": "We care about the wellbeing of our staff, and we support and enable them to deliver person-centred care.", "keywords": ["staff wellbeing", "support", "enablement", "resilience", "occupational health", "burnout", "morale"]},
    # ── Responsive ────────────────────────────────────────────────────────────
    {"reference": "QS Responsive 1", "name": "Person centred care",              "key_questions": ["Responsive"],  "quality_statement": True, "description": "We make sure people are at the centre of their care and treatment choices and we decide, in partnership with them, how to respond to any relevant changes in their needs.", "keywords": ["person-centred", "choices", "partnership", "co-production", "involvement", "changing needs"]},
    {"reference": "QS Responsive 2", "name": "Care provision, integration and continuity", "key_questions": ["Responsive"], "quality_statement": True, "description": "We understand the diverse health and care needs of people and our local communities, so care is joined-up, flexible and supports choice and continuity.", "keywords": ["continuity", "flexible", "joined-up", "integration", "diverse needs", "community", "coordination"]},
    {"reference": "QS Responsive 3", "name": "Providing information",            "key_questions": ["Responsive"],  "quality_statement": True, "description": "We provide appropriate, accurate and up-to-date information in formats that we tailor to individual needs.", "keywords": ["information", "accessible formats", "easy read", "communication", "tailored", "accurate", "up-to-date"]},
    {"reference": "QS Responsive 4", "name": "Listening to and involving people","key_questions": ["Responsive"],  "quality_statement": True, "description": "We make it easy for people to share feedback and ideas or raise complaints about their care, treatment and support. We involve them in decisions about their care and tell them what's changed as a result.", "keywords": ["feedback", "complaints", "involvement", "co-production", "listening", "acting on feedback", "participation"]},
    {"reference": "QS Responsive 5", "name": "Equity in access",                 "key_questions": ["Responsive"],  "quality_statement": True, "description": "We make sure that everyone can access the care, support and treatment they need when they need it.", "keywords": ["equity", "access", "equality", "inclusion", "barriers", "timely", "availability"]},
    {"reference": "QS Responsive 6", "name": "Equity in experiences and outcomes","key_questions": ["Responsive"], "quality_statement": True, "description": "We actively seek out and listen to information about people who are most likely to experience inequality in experience or outcomes. We tailor the care, support and treatment in response to this.", "keywords": ["equity", "inequality", "outcomes", "equality", "monitoring", "diversity", "protected characteristics", "health inequalities"]},
    {"reference": "QS Responsive 7", "name": "Planning for the future",          "key_questions": ["Responsive"],  "quality_statement": True, "description": "We support people to plan for important life changes, so they can have enough time to make informed decisions about their future, including at the end of life.", "keywords": ["future planning", "advance care planning", "end of life", "informed decisions", "life changes", "DNACPR", "preferred place of care"]},
    # ── Well-led ──────────────────────────────────────────────────────────────
    {"reference": "QS Well-led 1", "name": "Shared direction and culture",       "key_questions": ["Well-led"],    "quality_statement": True, "description": "We have a shared vision, strategy and culture. This is based on transparency, equity, equality and human rights, diversity and inclusion, engagement, and understanding challenges and the needs of people and our communities.", "keywords": ["vision", "strategy", "culture", "transparency", "equity", "equality", "human rights", "diversity", "inclusion", "values"]},
    {"reference": "QS Well-led 2", "name": "Capable, compassionate and inclusive leaders", "key_questions": ["Well-led"], "quality_statement": True, "description": "We have inclusive leaders at all levels who understand the context in which we deliver care, treatment and support and embody the culture and values of their workforce and organisation.", "keywords": ["leadership", "inclusive", "capable", "compassionate", "culture", "values", "context", "role model"]},
    {"reference": "QS Well-led 3", "name": "Freedom to speak up",                "key_questions": ["Well-led"],    "quality_statement": True, "description": "They have the skills, knowledge, experience and credibility to lead effectively. They do so with integrity, openness and honesty.", "keywords": ["speak up", "integrity", "openness", "honesty", "credibility", "skills", "knowledge", "whistleblowing", "psychological safety"]},
    {"reference": "QS Well-led 4", "name": "Workforce equality, diversity and inclusion", "key_questions": ["Well-led"], "quality_statement": True, "description": "We foster a positive culture where people feel that they can speak up and that their voice will be heard. We value diversity in our workforce.", "keywords": ["equality", "diversity", "inclusion", "EDI", "workforce", "culture", "belonging", "fair", "voice"]},
    {"reference": "QS Well-led 5", "name": "Governance, management and sustainability", "key_questions": ["Well-led"], "quality_statement": True, "description": "We have clear responsibilities, roles, systems of accountability and good governance. We use these to manage and deliver good quality, sustainable care. We act on the best information about risk, performance and outcomes.", "keywords": ["governance", "accountability", "roles", "responsibilities", "quality", "sustainability", "risk management", "performance", "oversight"]},
    {"reference": "QS Well-led 6", "name": "Partnerships and communities",       "key_questions": ["Well-led"],    "quality_statement": True, "description": "We understand our duty to collaborate and work in partnership, so our services work seamlessly for people. We share information and learning with partners and collaborate for improvement.", "keywords": ["partnership", "collaboration", "integration", "information sharing", "community", "joined-up", "learning"]},
    {"reference": "QS Well-led 7", "name": "Learning, improvement and innovation","key_questions": ["Well-led"],   "quality_statement": True, "description": "We focus on continuous learning, innovation and improvement across our organisation and the local system. We encourage creative ways of delivering equality of experience, outcome and quality of life for people.", "keywords": ["learning", "improvement", "innovation", "continuous improvement", "quality improvement", "research", "creativity"]},
    {"reference": "QS Well-led 8", "name": "Environmental sustainability",       "key_questions": ["Well-led"],    "quality_statement": True, "description": "We focus on sustainable development. We actively contribute to safe, effective practice and research and promote environmental sustainability.", "keywords": ["sustainability", "environment", "green", "net zero", "sustainable development", "research", "practice"]},
]

CARE_CERT_STANDARDS = [
    {
        "reference": "Standard 1", "name": "Understand your role",
        "description": "The care worker understands their role and responsibilities, the importance of working within their scope of practice, and the impact of their role on the person they support.",
        "keywords": ["role", "responsibilities", "boundaries", "scope of practice", "code of conduct", "accountability"],
        "outcomes": [
            {"ref": "1.1", "name": "Understand their own role"},
            {"ref": "1.2", "name": "Work in ways agreed with their employer"},
            {"ref": "1.3", "name": "Understand working relationships in health and social care"},
            {"ref": "1.4", "name": "Work in partnership with others"},
        ],
        "sub_outcomes": [
            {"ref": "1.1a", "desc": "Describe their main duties and responsibilities"},
            {"ref": "1.1b", "desc": "List the standards and codes of conduct and practice that relate to their role"},
            {"ref": "1.1c", "desc": "Demonstrate that they are working in accordance with the agreed ways of working with their employer"},
            {"ref": "1.1d", "desc": "Explain how their previous experiences, attitudes, values and beliefs may affect the way they work"},
            {"ref": "1.1e", "desc": "Identify the different opportunities for professional and career development in the sector"},
            {"ref": "1.2a", "desc": "Describe their employment rights and responsibilities"},
            {"ref": "1.2b", "desc": "List the aims, objectives and values of the service in which they work"},
            {"ref": "1.2c", "desc": "Explain why it is important to work in ways that are agreed with their employer"},
            {"ref": "1.2d", "desc": "Demonstrate how to access full and up-to-date details of agreed ways of working relevant to their role"},
            {"ref": "1.2e", "desc": "Explain how and when to escalate any concerns in line with organisational policy or ways of working"},
            {"ref": "1.2f", "desc": "Explain why it is important to be honest and identify where errors may have occurred and to tell the appropriate person"},
            {"ref": "1.3a", "desc": "Describe their responsibilities to the individuals they support as well as key people, advocates and others who are significant to an individual"},
            {"ref": "1.3b", "desc": "Explain how a working relationship is different from a personal relationship"},
            {"ref": "1.3c", "desc": "Describe different working relationships in health and social care settings"},
            {"ref": "1.4a", "desc": "Explain why it is important to work in teams and in partnership with others"},
            {"ref": "1.4b", "desc": "Explain why it is important to work in partnership with key people, advocates and others who are significant to individuals"},
            {"ref": "1.4c", "desc": "Demonstrate behaviours, attitudes and ways of working that can help improve partnership working"},
            {"ref": "1.4d", "desc": "Demonstrate how and when to access support and advice about partnership working and resolving conflicts"},
        ]
    },
    {
        "reference": "Standard 2", "name": "Your personal development",
        "description": "The care worker is committed to their personal development, including training, learning, CPD, and reflective practice. Includes supervision and appraisal.",
        "keywords": ["training", "learning", "CPD", "personal development", "reflective practice", "supervision", "appraisal", "development"],
        "outcomes": [
            {"ref": "2.1", "name": "Agree a personal development plan"},
            {"ref": "2.2", "name": "Develop their knowledge, skills and understanding"},
        ],
        "sub_outcomes": [
            {"ref": "2.1a", "desc": "Describe the processes for identifying own learning needs and agreeing a personal development plan, and who should be involved"},
            {"ref": "2.1b", "desc": "Explain why feedback from others is important in helping to develop and improve the way they work"},
            {"ref": "2.1c", "desc": "Contribute to and agree own personal development plan"},
            {"ref": "2.2a", "desc": "Describe the functional level of literacy, numeracy, communication, and digital skills necessary to carry out their role"},
            {"ref": "2.2b", "desc": "Explain where to find information and support on how to check and develop own current level of skills"},
            {"ref": "2.2c", "desc": "Describe how reflecting on a situation or learning activity has improved their own knowledge, skills and understanding"},
            {"ref": "2.2d", "desc": "Describe how feedback from others has developed their own knowledge, skills and understanding"},
            {"ref": "2.2e", "desc": "Demonstrate how to measure their own knowledge, performance and understanding against relevant standards"},
            {"ref": "2.2f", "desc": "List the learning opportunities available to them and how they can use them to improve their ways of working"},
            {"ref": "2.2g", "desc": "Demonstrate how to record progress in relation to their personal development"},
            {"ref": "2.2h", "desc": "Explain why continuing professional development is important"},
        ]
    },
    {
        "reference": "Standard 3", "name": "Duty of care",
        "description": "The care worker understands their duty of care and how to balance this with an individual's rights. Includes dilemmas, complaints and incidents.",
        "keywords": ["duty of care", "duty of candour", "dilemmas", "complaints", "incidents", "rights", "wellbeing", "safeguarding"],
        "outcomes": [
            {"ref": "3.1", "name": "Understand duty of care and duty of candour"},
            {"ref": "3.2", "name": "Understand the support available for addressing dilemmas about duty of care"},
            {"ref": "3.3", "name": "Deal with comments and complaints"},
            {"ref": "3.4", "name": "Deal with incidents, errors and near misses"},
            {"ref": "3.5", "name": "Deal with confrontation and difficult situations"},
        ],
        "sub_outcomes": [
            {"ref": "3.1a", "desc": "Define duty of care and duty of candour"},
            {"ref": "3.1b", "desc": "Describe how the duty of care affects their own work role"},
            {"ref": "3.2a", "desc": "Describe dilemmas that may arise between the duty of care and an individual's rights"},
            {"ref": "3.2b", "desc": "Explain what they must and must not do within their role in managing conflicts and dilemmas"},
            {"ref": "3.2c", "desc": "Explain where to get additional support and advice about how to resolve such dilemmas"},
            {"ref": "3.3a", "desc": "Demonstrate how to respond to comments and complaints in line with legislation and agreed ways of working"},
            {"ref": "3.3b", "desc": "Describe who to ask for advice and support in handling comments and complaints"},
            {"ref": "3.3c", "desc": "Explain the importance of learning from comments and complaints to improve the quality of service"},
            {"ref": "3.4a", "desc": "Describe how to recognise adverse events, incidents, errors and near misses"},
            {"ref": "3.4b", "desc": "Explain what they must and must not do in relation to adverse events, incidents, errors and near misses"},
            {"ref": "3.4c", "desc": "List the legislation and agreed ways of working in relation to reporting any adverse events, incidents, errors and near misses"},
            {"ref": "3.5a", "desc": "List the factors and difficult situations that may cause confrontation"},
            {"ref": "3.5b", "desc": "Describe how communication can be used to solve problems and reduce the likelihood or impact of confrontation"},
            {"ref": "3.5c", "desc": "Describe how to assess and reduce risks in confrontational situations"},
            {"ref": "3.5d", "desc": "Demonstrate how and when to access support and advice about resolving conflicts"},
            {"ref": "3.5e", "desc": "Explain the agreed ways of working for reporting any confrontations"},
        ]
    },
    {
        "reference": "Standard 4", "name": "Equality, diversity, inclusion and human rights",
        "description": "The care worker works in an inclusive way that values diversity and treats people as individuals, respecting protected characteristics and challenging discrimination.",
        "keywords": ["equality", "diversity", "inclusion", "human rights", "discrimination", "protected characteristics", "individual needs", "culture", "religion"],
        "outcomes": [
            {"ref": "4.1", "name": "Understand the importance of equality, diversity, inclusion and human rights"},
            {"ref": "4.2", "name": "Work in an inclusive way"},
            {"ref": "4.3", "name": "Access information, advice and support about equality, diversity, inclusion and human rights"},
        ],
        "sub_outcomes": [
            {"ref": "4.1a", "desc": "Explain what is meant by equality including protected characteristics, diversity, inclusion and human rights"},
            {"ref": "4.1b", "desc": "Explain what is meant by bias and discrimination"},
            {"ref": "4.1c", "desc": "Describe ways in which discrimination may deliberately or inadvertently occur in the work setting"},
            {"ref": "4.1d", "desc": "Explain how practices that support equality, diversity, inclusion and human rights reduce the likelihood of discrimination"},
            {"ref": "4.2a", "desc": "Identify which legislation and codes of practice relating to equality, diversity, inclusion and human rights apply to their own role"},
            {"ref": "4.2b", "desc": "Demonstrate interactions with individuals that support culturally appropriate care"},
            {"ref": "4.2c", "desc": "Describe how to recognise, challenge and report discrimination in line with employers' policies in a way that encourages positive change"},
            {"ref": "4.3a", "desc": "Identify a range of sources of information, advice and support about equality, diversity, inclusion and human rights"},
            {"ref": "4.3b", "desc": "Describe how and when to access information, advice and support about equality, diversity, inclusion and human rights"},
            {"ref": "4.3c", "desc": "Explain who to ask for advice and support about equality, diversity, inclusion and human rights"},
        ]
    },
    {
        "reference": "Standard 5", "name": "Work in a person-centred way",
        "description": "The care worker puts the individual at the centre of care, supporting their choices, promoting their wellbeing and independence.",
        "keywords": ["person-centred", "choices", "independence", "wellbeing", "preferences", "self-determination", "mental capacity", "consent", "dignity"],
        "outcomes": [
            {"ref": "5.1", "name": "Understand person-centred values"},
            {"ref": "5.2", "name": "Understand working in a person-centred way"},
            {"ref": "5.3", "name": "Understand the meaning of mental capacity in relation to how care is provided"},
            {"ref": "5.4", "name": "Demonstrate awareness of the individual's environment and address factors causing discomfort or distress"},
            {"ref": "5.5", "name": "Make others aware of actions causing discomfort or distress to individuals"},
            {"ref": "5.6", "name": "Support individuals to minimise pain, discomfort and emotional distress"},
            {"ref": "5.7", "name": "Support the individual to maintain their identity and self-esteem"},
            {"ref": "5.8", "name": "Support the individual using person-centred values"},
        ],
        "sub_outcomes": [
            {"ref": "5.1a", "desc": "Identify person-centred values and describe how to put them into practice in day-to-day work"},
            {"ref": "5.1b", "desc": "Describe why it is important to work in a way that promotes person-centred values when providing support"},
            {"ref": "5.1c", "desc": "Identify ways to promote dignity in day-to-day work"},
            {"ref": "5.1d", "desc": "Explain the importance of relationships significant to the individual when working in a person-centred way"},
            {"ref": "5.2a", "desc": "Describe the importance of finding out the history, preferences, wishes and needs of the individual"},
            {"ref": "5.2b", "desc": "Explain why the changing needs of an individual must be reflected in their care and/or support plan"},
            {"ref": "5.2c", "desc": "Explain the importance of supporting individuals to plan for their future wellbeing and fulfilment, including end-of-life care"},
            {"ref": "5.3a", "desc": "Identify relevant legislation and codes of practice relating to mental capacity"},
            {"ref": "5.3b", "desc": "Explain what is meant by the term capacity"},
            {"ref": "5.3c", "desc": "Explain why it is important to assume that someone has capacity unless there is evidence that they do not"},
            {"ref": "5.3d", "desc": "Explain what is meant by consent, and factors that influence an individual's mental capacity and ability to express consent"},
            {"ref": "5.3e", "desc": "Describe situations where an assessment of capacity might need to be undertaken including best interest decisions, advance statements and advance decisions"},
            {"ref": "5.4a", "desc": "Take appropriate steps to remove or minimise environmental factors causing discomfort or distress (lighting, noise, temperature, odours)"},
            {"ref": "5.4b", "desc": "Report any concerns about environmental factors causing discomfort or distress to the relevant person"},
            {"ref": "5.5a", "desc": "Raise concerns about distressing actions directly with the individual concerned"},
            {"ref": "5.5b", "desc": "Raise any concern about distressing actions with their supervisor or manager"},
            {"ref": "5.5c", "desc": "Raise any concerns via other channels or systems e.g. at team meetings"},
            {"ref": "5.6a", "desc": "Ensure that individuals with restricted movement or mobility are comfortable"},
            {"ref": "5.6b", "desc": "Recognise the signs that an individual is in pain, discomfort or emotional distress"},
            {"ref": "5.6c", "desc": "Take appropriate steps to remove or minimise factors causing pain, discomfort or emotional distress"},
            {"ref": "5.7a", "desc": "Explain how individual identity and self-esteem are linked to wellbeing"},
            {"ref": "5.7b", "desc": "Demonstrate that own attitudes and behaviours promote the wellbeing of the individual"},
            {"ref": "5.7c", "desc": "Support and encourage individuals' own sense of identity and self-esteem"},
            {"ref": "5.7d", "desc": "Report any concerns about the individual's wellbeing to the appropriate person"},
            {"ref": "5.8a", "desc": "Demonstrate that actions promote person-centred values including individuality, independence, privacy, partnership, choice, dignity, respect and rights"},
        ]
    },
    {
        "reference": "Standard 6", "name": "Communication",
        "description": "The care worker communicates effectively in verbal and non-verbal ways, adapts to individuals' communication needs, and maintains accurate records.",
        "keywords": ["communication", "listening", "non-verbal", "language needs", "records", "handover", "reporting", "documentation", "confidentiality"],
        "outcomes": [
            {"ref": "6.1", "name": "Understand the importance of effective communication at work"},
            {"ref": "6.2", "name": "Understand how to meet communication and language needs, wishes and preferences of individuals"},
            {"ref": "6.3", "name": "Understand how to promote effective communication"},
            {"ref": "6.4", "name": "Understand the principles and practices relating to confidentiality"},
            {"ref": "6.5", "name": "Use appropriate verbal and non-verbal communication"},
            {"ref": "6.6", "name": "Support the use of appropriate communication aids and technologies"},
        ],
        "sub_outcomes": [
            {"ref": "6.1a", "desc": "Describe the different ways that people communicate"},
            {"ref": "6.1b", "desc": "Describe how communication affects relationships at work"},
            {"ref": "6.2a", "desc": "Describe how to establish an individual's communication and language needs, wishes and preferences"},
            {"ref": "6.2b", "desc": "List a range of communication methods, aids, assistive technologies and digital communication tools that could help meet an individual's communication needs"},
            {"ref": "6.3a", "desc": "List barriers to effective communication with individuals and how they can be reduced"},
            {"ref": "6.3b", "desc": "Describe how an individual's behaviour may be a form of communication"},
            {"ref": "6.3c", "desc": "Describe how to check whether they have been understood"},
            {"ref": "6.3d", "desc": "Describe where to find information and support or services to help the individual communicate more effectively"},
            {"ref": "6.4a", "desc": "Describe what confidentiality means in relation to their role"},
            {"ref": "6.4b", "desc": "List any legislation and agreed ways of working to maintain confidentiality in day-to-day communication"},
            {"ref": "6.4c", "desc": "Describe situations where information normally considered confidential might need to be passed on"},
            {"ref": "6.4d", "desc": "Describe who they should ask for advice and support about confidentiality"},
            {"ref": "6.5a", "desc": "Demonstrate the use of appropriate verbal and non-verbal communication (tone, volume, position, eye contact, body language, touch, writing, signing, communication aids)"},
            {"ref": "6.5b", "desc": "Describe why it is important to observe and be receptive to an individual's reactions when communicating with them"},
            {"ref": "6.6a", "desc": "Ensure communication aids, assistive technologies and digital communication tools are available, clean and working properly"},
            {"ref": "6.6b", "desc": "Report any concerns about the communication aid, technology or digital communication tool to the appropriate person"},
        ]
    },
    {
        "reference": "Standard 7", "name": "Privacy and dignity",
        "description": "The care worker promotes and maintains the privacy, dignity and respect of each individual in their care, including supporting active participation and informed choice.",
        "keywords": ["privacy", "dignity", "respect", "confidentiality", "personal information", "intimate care", "active participation", "choices"],
        "outcomes": [
            {"ref": "7.1", "name": "Understand the principles that underpin privacy and dignity in care"},
            {"ref": "7.2", "name": "Maintain the privacy and dignity of the individual(s) in their care"},
            {"ref": "7.3", "name": "Support an individual's right to make choices"},
            {"ref": "7.4", "name": "Support individuals in making choices about their care"},
            {"ref": "7.5", "name": "Understand how to support active participation"},
            {"ref": "7.6", "name": "Support the individual in active participation in their own care"},
        ],
        "sub_outcomes": [
            {"ref": "7.1a", "desc": "Describe what is meant by privacy and dignity"},
            {"ref": "7.1b", "desc": "List situations where an individual's privacy and dignity could be compromised"},
            {"ref": "7.1c", "desc": "Describe different ways to maintain privacy and dignity of individuals in care and support"},
            {"ref": "7.2a", "desc": "Demonstrate that their actions maintain the privacy of the individual"},
            {"ref": "7.2b", "desc": "Demonstrate that privacy and dignity is maintained at all times when providing personal care in line with the person's individual needs and preferences"},
            {"ref": "7.2c", "desc": "Explain why it is important not to disclose anything about the individual that they may wish to be kept private, unless it is appropriate to do so"},
            {"ref": "7.2d", "desc": "Report any concerns about privacy and dignity to the relevant person"},
            {"ref": "7.3a", "desc": "Describe ways of helping individuals to make informed choices"},
            {"ref": "7.3b", "desc": "Explain how risk assessment processes can be used to support the right of individuals to make their own decisions"},
            {"ref": "7.3c", "desc": "Explain why personal views must not influence an individual's own choices or decisions"},
            {"ref": "7.3d", "desc": "Describe why there may be times when they need to support an individual to question or challenge decisions made about them by others"},
            {"ref": "7.4a", "desc": "Demonstrate how to support individuals to make informed choices"},
            {"ref": "7.4b", "desc": "Ensure risk assessment processes are used to support the right of individuals to make their own decisions"},
            {"ref": "7.4c", "desc": "Ensure their own personal views do not influence an individual's own choices or decisions"},
            {"ref": "7.4d", "desc": "Describe how to report any concerns about decision-making to the relevant person"},
            {"ref": "7.5a", "desc": "Describe the importance of how valuing people contributes to active participation"},
            {"ref": "7.5b", "desc": "Explain how to enable individuals to make informed choices about their lives"},
            {"ref": "7.5c", "desc": "List other ways they can support active participation"},
            {"ref": "7.5d", "desc": "Describe the importance of enabling individuals to be as independent as possible and to maintain their own network of relationships and community connections"},
            {"ref": "7.6a", "desc": "Demonstrate that they can support the active participation of individuals in their care"},
            {"ref": "7.6b", "desc": "Reflect on how their own personal views could restrict the individual's ability to actively participate in their care"},
            {"ref": "7.6c", "desc": "Report any concerns about active participation to the relevant person"},
        ]
    },
    {
        "reference": "Standard 8", "name": "Fluids and nutrition",
        "description": "The care worker supports individuals to have adequate nutrition and hydration, understands signs of malnutrition and dehydration.",
        "keywords": ["nutrition", "hydration", "fluid intake", "malnutrition", "dehydration", "diet", "eating", "drinking", "mealtime", "food safety"],
        "outcomes": [
            {"ref": "8.1", "name": "Understand the principles of hydration, nutrition and food safety"},
            {"ref": "8.2", "name": "Support individuals to have access to fluids in accordance with their plan of care"},
            {"ref": "8.3", "name": "Support individuals to have access to food and nutrition in accordance with their plan of care"},
        ],
        "sub_outcomes": [
            {"ref": "8.1a", "desc": "Describe the importance of food safety, including hygiene, in the preparation and handling of food"},
            {"ref": "8.1b", "desc": "Explain the importance of good nutrition and hydration in maintaining health and wellbeing"},
            {"ref": "8.1c", "desc": "List signs and symptoms of poor nutrition and hydration"},
            {"ref": "8.1d", "desc": "Explain how to promote adequate nutrition and hydration"},
            {"ref": "8.1e", "desc": "Explain how to identify and report changes or risks relating to nutrition and hydration needs"},
            {"ref": "8.2a", "desc": "Ensure that fluids are within reach of those that have restrictions on their liberty, movement or mobility"},
            {"ref": "8.2b", "desc": "Ensure that fluids are refreshed on a regular basis"},
            {"ref": "8.2c", "desc": "Ensure that fluids are offered and individuals are supported and encouraged to drink in accordance with their plan of care"},
            {"ref": "8.2d", "desc": "Know how to report any concerns about fluid intake to the relevant person"},
            {"ref": "8.3a", "desc": "Ensure any nutritional products are within reach of those that have restrictions on their liberty, movement or mobility"},
            {"ref": "8.3b", "desc": "Ensure food is provided at the appropriate temperature in accordance with the plan of care and the individual is able to eat it"},
            {"ref": "8.3c", "desc": "Ensure that appropriate utensils are available to enable the individual to meet their nutritional needs as independently as possible"},
            {"ref": "8.3d", "desc": "Support and encourage individuals to eat in accordance with their plan of care"},
            {"ref": "8.3e", "desc": "Know how to report concerns about nutrition to the relevant person"},
        ]
    },
    {
        "reference": "Standard 9", "name": "Awareness of mental health and dementia",
        "description": "The care worker has awareness of mental health conditions and dementia, including how these affect individuals' wellbeing, behaviour and the reasonable adjustments required in care delivery.",
        "keywords": ["mental health", "dementia", "behaviour", "wellbeing", "cognitive impairment", "anxiety", "depression", "positive attitudes", "reasonable adjustments"],
        "outcomes": [
            {"ref": "9.1", "name": "Understand the needs and experiences of people with mental health conditions or dementia"},
            {"ref": "9.2", "name": "Understand the importance of promoting positive health and wellbeing for individuals with mental health conditions or dementia"},
            {"ref": "9.3", "name": "Understand the reasonable adjustments necessary in care delivery for individuals with mental health conditions or dementia"},
            {"ref": "9.4", "name": "Understand the importance of early detection of mental health conditions or dementia"},
            {"ref": "9.5", "name": "Understand legal frameworks, policy and guidelines relating to mental health conditions or dementia"},
        ],
        "sub_outcomes": [
            {"ref": "9.1a", "desc": "Describe what is meant by the terms mental health and mental wellbeing"},
            {"ref": "9.1b", "desc": "List common types of mental health conditions"},
            {"ref": "9.1c", "desc": "Explain what is meant by the term dementia"},
            {"ref": "9.1d", "desc": "Explain how these conditions may influence a person's needs in relation to the care that they may require"},
            {"ref": "9.1e", "desc": "Explain why it is important to understand that the causes and support needs are different for people with mental health conditions or dementia"},
            {"ref": "9.2a", "desc": "Explain how positive attitudes towards those with mental health conditions or dementia will improve the care and support they receive"},
            {"ref": "9.2b", "desc": "Describe the social model of disability and how it underpins positive attitudes and involving people in their own care"},
            {"ref": "9.3a", "desc": "Identify reasonable adjustments which can be made in health and care services accessed by individuals with mental health conditions or dementia"},
            {"ref": "9.3b", "desc": "Describe how to report concerns associated with any unmet needs which may arise from mental health conditions or dementia"},
            {"ref": "9.4a", "desc": "Describe how to recognise early indicators of mental health deterioration"},
            {"ref": "9.4b", "desc": "List early signs and symptoms of dementia"},
            {"ref": "9.4c", "desc": "Explain why early detection of mental health needs or dementia is important"},
            {"ref": "9.4d", "desc": "Give examples of how adjustments to care and support might need to be made when a mental health condition or dementia is identified or there is a decline in condition"},
            {"ref": "9.4e", "desc": "Explain ways to engage with and signpost individuals with mental health conditions or dementia and their families and carers to other services"},
            {"ref": "9.5a", "desc": "List the main requirements of legislation and policies designed to promote the human rights, inclusion and equal life chances of individuals with mental health conditions or dementia"},
            {"ref": "9.5b", "desc": "Explain how legislation and policies may affect the day-to-day experiences of individuals with mental health needs or dementia and their families"},
        ]
    },
    {
        "reference": "Standard 10", "name": "Safeguarding adults",
        "description": "The care worker understands adult safeguarding, recognises signs of abuse and neglect, and knows how to report concerns.",
        "keywords": ["safeguarding", "abuse", "neglect", "reporting", "whistleblowing", "protection", "harm", "exploitation", "concerns", "restrictive practices"],
        "outcomes": [
            {"ref": "10.1", "name": "Principles of adult safeguarding"},
            {"ref": "10.2", "name": "Reduce the likelihood of abuse"},
            {"ref": "10.3", "name": "Respond to suspected or disclosed abuse"},
            {"ref": "10.4", "name": "Protect people from harm and abuse – locally and nationally"},
        ],
        "sub_outcomes": [
            {"ref": "10.1a", "desc": "Explain the term adult safeguarding"},
            {"ref": "10.1b", "desc": "Give the legal definition of an adult at risk"},
            {"ref": "10.1c", "desc": "Explain their own role and responsibilities in safeguarding individuals"},
            {"ref": "10.1d", "desc": "List the main types of abuse"},
            {"ref": "10.1e", "desc": "Describe what constitutes harm"},
            {"ref": "10.1f", "desc": "Describe what constitutes restrictive practices"},
            {"ref": "10.1g", "desc": "List the possible indicators of abuse"},
            {"ref": "10.1h", "desc": "Describe the nature and scope of harm to and abuse of adults at risk"},
            {"ref": "10.1i", "desc": "List a range of factors which have featured in adult abuse and neglect"},
            {"ref": "10.1j", "desc": "Describe the range of potential risks with using technology and how to support individuals to be safe without being risk averse"},
            {"ref": "10.1k", "desc": "Demonstrate the importance of ensuring individuals are treated with dignity and respect when providing health and care services"},
            {"ref": "10.1l", "desc": "Describe where to get information and advice about their role and responsibilities in preventing and protecting individuals from harm and abuse"},
            {"ref": "10.2a", "desc": "Explain why an individual may be at risk from harm or abuse"},
            {"ref": "10.2b", "desc": "Describe how care environments can promote or undermine people's dignity and rights"},
            {"ref": "10.2c", "desc": "Explain the importance of individualised and person-centred care in reducing abuse"},
            {"ref": "10.2d", "desc": "Explain how to apply the basic principles of helping people to keep themselves safe"},
            {"ref": "10.2e", "desc": "Explain the local arrangements for the implementation of multi-agency adult safeguarding policies and procedures"},
            {"ref": "10.2f", "desc": "List ways in which the likelihood of abuse may be reduced"},
            {"ref": "10.3a", "desc": "Explain what to do if abuse of an adult is suspected, including how to raise concerns in accordance with ways of working"},
            {"ref": "10.4a", "desc": "List relevant legislation, local and national policies and procedures which relate to adult safeguarding"},
            {"ref": "10.4b", "desc": "Explain the importance of sharing information with the relevant agencies"},
            {"ref": "10.4c", "desc": "Describe the actions to take if they experience barriers in alerting or referring to relevant agencies"},
        ]
    },
    {
        "reference": "Standard 11", "name": "Safeguarding children",
        "description": "The care worker is aware of child safeguarding responsibilities even when primarily working with adults.",
        "keywords": ["safeguarding children", "child protection", "young carers", "children", "abuse", "neglect"],
        "outcomes": [
            {"ref": "11.1", "name": "Safeguard children"},
        ],
        "sub_outcomes": [
            {"ref": "11.1a", "desc": "Understand own role and responsibilities in relation to the safeguarding of children and young people"},
            {"ref": "11.1b", "desc": "Explain what to do if they suspect a child or young person (met in any circumstances) is being abused or neglected"},
            {"ref": "11.1c", "desc": "Know how to access current safeguarding children training appropriate to their workplace and role"},
        ]
    },
    {
        "reference": "Standard 12", "name": "Basic life support",
        "description": "The care worker knows how to provide basic life support, including CPR, and can respond to emergency situations.",
        "keywords": ["first aid", "CPR", "resuscitation", "basic life support", "emergency", "AED", "choking"],
        "outcomes": [
            {"ref": "12.1", "name": "Provide basic life support"},
        ],
        "sub_outcomes": [
            {"ref": "12.1a", "desc": "Understand when to call for emergency assistance and how to keep the individual safe until help arrives"},
            {"ref": "12.1b", "desc": "Complete practical basic life support training meeting UK Resuscitation Council guidelines appropriate to their workplace"},
            {"ref": "12.1c", "desc": "Demonstrate safe and effective CPR technique following UK Resuscitation Council guidelines for the population they work with"},
        ]
    },
    {
        "reference": "Standard 13", "name": "Health and safety",
        "description": "The care worker understands health and safety legislation, risk assessment, moving and handling, medication, fire safety, security and personal wellbeing.",
        "keywords": ["health and safety", "risk assessment", "COSHH", "moving and handling", "manual handling", "PPE", "lone working", "fire safety", "medication", "security"],
        "outcomes": [
            {"ref": "13.1", "name": "Understand own responsibilities and others' responsibilities relating to health and safety"},
            {"ref": "13.2", "name": "Understand risk assessment"},
            {"ref": "13.3", "name": "Move and assist safely"},
            {"ref": "13.4", "name": "Understand procedures for responding to accidents and sudden illness"},
            {"ref": "13.5", "name": "Understand medication and healthcare tasks"},
            {"ref": "13.6", "name": "Handle hazardous substances"},
            {"ref": "13.7", "name": "Promote fire safety"},
            {"ref": "13.8", "name": "Work securely"},
            {"ref": "13.9", "name": "Manage mental health and personal wellbeing"},
        ],
        "sub_outcomes": [
            {"ref": "13.1a", "desc": "Identify legislation relating to general health and safety in a health or social care work setting"},
            {"ref": "13.1b", "desc": "Describe the main points of the health and safety policies and procedures agreed with the employer"},
            {"ref": "13.1c", "desc": "Outline the main health and safety responsibilities of self, the employer or manager, and others in the work setting"},
            {"ref": "13.1d", "desc": "List tasks relating to health and safety that should not be carried out without special training"},
            {"ref": "13.1e", "desc": "Explain how to access additional support and information relating to health and safety"},
            {"ref": "13.2a", "desc": "Explain why it is important to assess health and safety risks posed by particular work settings, situations or activities"},
            {"ref": "13.2b", "desc": "Describe how and when to report health and safety risks that they have identified"},
            {"ref": "13.3a", "desc": "Identify key pieces of legislation that relate to moving and assisting"},
            {"ref": "13.3b", "desc": "List tasks relating to moving and assisting that they are not allowed to carry out until they are competent"},
            {"ref": "13.3c", "desc": "Demonstrate how to move and assist people and objects safely, maintaining dignity, in line with legislation and agreed ways of working"},
            {"ref": "13.4a", "desc": "List the different types of accidents and sudden illness that may occur in the course of their work"},
            {"ref": "13.4b", "desc": "Describe the procedures to be followed if an accident or sudden illness should occur"},
            {"ref": "13.4c", "desc": "List the emergency first aid actions they are and are not allowed to carry out"},
            {"ref": "13.5a", "desc": "Describe the agreed ways of working in relation to medication"},
            {"ref": "13.5b", "desc": "Describe the agreed ways of working in relation to healthcare tasks"},
            {"ref": "13.5c", "desc": "List the tasks relating to medication and healthcare procedures they are not allowed to carry out until competent"},
            {"ref": "13.6a", "desc": "Describe the hazardous substances in their workplace"},
            {"ref": "13.6b", "desc": "Demonstrate safe practices for storing, using and disposing of hazardous substances"},
            {"ref": "13.7a", "desc": "Explain how to prevent fires from starting or spreading"},
            {"ref": "13.7b", "desc": "Describe what to do in the event of a fire"},
            {"ref": "13.8a", "desc": "Describe the measures designed to protect their own security at work and the security of those they support"},
            {"ref": "13.8b", "desc": "Explain the agreed ways of working for checking the identity of anyone requesting access to premises or information"},
            {"ref": "13.9a", "desc": "Describe common factors that can affect the mental health and wellbeing of themselves and others"},
            {"ref": "13.9b", "desc": "Identify circumstances that tend to trigger these factors in themselves and others"},
            {"ref": "13.9c", "desc": "Explain how to access and use resources available to support own and others' mental health and wellbeing"},
        ]
    },
    {
        "reference": "Standard 14", "name": "Handling information",
        "description": "The care worker understands data protection, GDPR, confidentiality obligations, and maintains accurate, secure records.",
        "keywords": ["data protection", "GDPR", "confidentiality", "records management", "information governance", "sharing information", "data breach"],
        "outcomes": [
            {"ref": "14.1", "name": "Handle information"},
        ],
        "sub_outcomes": [
            {"ref": "14.1a", "desc": "Describe the agreed ways of working and legislation regarding accessing, recording, storing and sharing of information"},
            {"ref": "14.1b", "desc": "Explain why it is important to have secure systems for accessing, recording, storing and sharing information"},
            {"ref": "14.1c", "desc": "Demonstrate how to keep records that are up to date, complete, accurate and legible"},
            {"ref": "14.1d", "desc": "Explain how, and to whom, to report if agreed ways of working have not been followed or there has been a data breach or risk to data security"},
        ]
    },
    {
        "reference": "Standard 15", "name": "Infection prevention and control",
        "description": "The care worker understands and applies infection prevention and control measures, including hand hygiene, PPE, and standard precautions.",
        "keywords": ["infection control", "PPE", "hand hygiene", "standard precautions", "cleaning", "waste disposal", "decontamination", "chain of infection"],
        "outcomes": [
            {"ref": "15.1", "name": "Prevent the spread of infection"},
        ],
        "sub_outcomes": [
            {"ref": "15.1a", "desc": "Describe the causes of infection and the six links in the chain of infection"},
            {"ref": "15.1b", "desc": "Identify the standard infection prevention and control precautions which must be followed to protect you and others in the workplace"},
            {"ref": "15.1c", "desc": "Explain your role in preventing infection in the area you work"},
            {"ref": "15.1d", "desc": "Demonstrate effective hand hygiene using appropriate products"},
            {"ref": "15.1e", "desc": "Explain how your own health, hygiene, vaccination status and exposure to infection at work might pose a risk to the individuals you support"},
            {"ref": "15.1f", "desc": "Identify common types of personal protective equipment (PPE) and describe how and when to use them"},
            {"ref": "15.1g", "desc": "Demonstrate effective use of PPE including putting on and taking off (donning and doffing) safely"},
            {"ref": "15.1h", "desc": "Describe the appropriate methods for cleaning and/or decontamination of the care environment and equipment"},
            {"ref": "15.1i", "desc": "Identify the process for safe handling of blood and bodily fluids spills"},
            {"ref": "15.1j", "desc": "Identify the principles of safe handling and disposal of infected or soiled linen, equipment and clinical waste"},
        ]
    },
    {
        "reference": "Standard 16", "name": "Awareness of learning disability and autism",
        "description": "It is a legal requirement that all staff working in CQC-regulated services undertake training on how to interact appropriately with people with a learning disability and autistic people, at a level appropriate to their role (CQC Regulation 18: Staffing).",
        "keywords": ["learning disability", "autism", "training", "CQC regulation 18", "staffing", "awareness"],
        "outcomes": [
            {"ref": "16.1", "name": "Demonstrate awareness of learning disability and autism"},
        ],
        "sub_outcomes": [
            {"ref": "16.1a", "desc": "Complete training on how to interact appropriately with people with a learning disability and autistic people, at a level appropriate to their role, as required by CQC Regulation 18: Staffing"},
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
    for qs in CQC_QUALITY_STATEMENTS:
        entries.append({**qs, "type": "cqc", "is_active": True, "created_at": now, "source": "CQC Single Assessment Framework - Quality Statements"})
    for std in CARE_CERT_STANDARDS:
        entries.append({**std, "type": "care_cert", "is_active": True, "created_at": now, "source": "Care Certificate Standards 2025 - Skills for Care"})

    await db.standards_entries.insert_many(entries)
    logger.info(f"Seeded {len(entries)} standards entries")


async def migrate_standard_outcomes(db):
    """Add outcomes and sub_outcomes to existing Care Certificate standards entries."""
    updated = 0
    for std in CARE_CERT_STANDARDS:
        ref = std["reference"]
        update_fields = {}
        existing = await db.standards_entries.find_one({"reference": ref, "type": "care_cert"})
        if existing is None:
            continue
        if not existing.get("outcomes"):
            update_fields["outcomes"] = std["outcomes"]
        # Always overwrite sub_outcomes so corrections in seed.py are applied
        if existing.get("sub_outcomes") != std["sub_outcomes"]:
            update_fields["sub_outcomes"] = std["sub_outcomes"]
        if existing.get("name") != std["name"]:
            update_fields["name"] = std["name"]
        if existing.get("description") != std["description"]:
            update_fields["description"] = std["description"]
        if update_fields:
            await db.standards_entries.update_one(
                {"reference": ref, "type": "care_cert"},
                {"$set": update_fields}
            )
            updated += 1
    if updated:
        logger.info(f"Migrated outcomes/sub_outcomes to {updated} Care Certificate standard entries")


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


async def migrate_standards_entries_system_flag(db):
    """Mark existing seeded standards_entries (no org_id) as is_system=True.

    This prevents them being treated as org-specific custom entries and ensures
    all orgs can still read them after the org-scoping fix was applied.
    """
    result = await db.standards_entries.update_many(
        {"org_id": {"$exists": False}},
        {"$set": {"is_system": True}}
    )
    if result.modified_count:
        logger.info(f"Marked {result.modified_count} legacy standards_entries as is_system=True")


async def seed_super_admin(db):
    """Create the single super admin account from environment variables."""
    from routers.auth import hash_password
    email = os.environ.get("SUPER_ADMIN_EMAIL", "superadmin@1two.one")
    password = os.environ.get("SUPER_ADMIN_PASSWORD", "SuperAdmin123!")
    existing = await db.users.find_one({"email": email})
    if existing is None:
        await db.users.insert_one({
            "email": email,
            "password_hash": hash_password(password),
            "name": "Super Admin",
            "role": "super_admin",
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Super admin seeded: {email}")
    elif existing.get("role") != "super_admin":
        await db.users.update_one({"email": email}, {"$set": {"role": "super_admin"}})
        logger.info(f"Updated {email} to super_admin role")


async def seed_default_org(db):
    """Create 'Test Company' org if not exists and migrate all unscoped data into it."""
    org = await db.organisations.find_one({"slug": "test-company"})
    if not org:
        now = datetime.now(timezone.utc).isoformat()
        result = await db.organisations.insert_one({
            "name": "Test Company",
            "slug": "test-company",
            "status": "active",
            "created_at": now,
        })
        org_id = str(result.inserted_id)
        logger.info(f"Default org 'Test Company' created: {org_id}")
    else:
        org_id = str(org["_id"])

    # Migrate unscoped users (exclude super_admin)
    r1 = await db.users.update_many(
        {"org_id": {"$exists": False}, "role": {"$ne": "super_admin"}},
        {"$set": {"org_id": org_id}}
    )
    # Migrate unscoped meetings
    r2 = await db.meetings.update_many(
        {"org_id": {"$exists": False}},
        {"$set": {"org_id": org_id}}
    )
    # Migrate org_settings
    r3 = await db.org_settings.update_many(
        {"org_id": {"$exists": False}},
        {"$set": {"org_id": org_id}}
    )
    # Migrate teams
    r4 = await db.teams.update_many(
        {"org_id": {"$exists": False}},
        {"$set": {"org_id": org_id}}
    )
    migrated = r1.modified_count + r2.modified_count + r3.modified_count + r4.modified_count
    if migrated:
        logger.info(
            f"Migrated to 'Test Company' org: {r1.modified_count} users, "
            f"{r2.modified_count} meetings, {r3.modified_count} settings, {r4.modified_count} teams"
        )
    return org_id


async def seed_quality_statements_migration(db):
    """Insert the 34 CQC Quality Statements into the standards collection if not already present.
    Safe to run on existing databases — only inserts missing entries."""
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for qs in CQC_QUALITY_STATEMENTS:
        exists = await db.standards.find_one({"reference": qs["reference"], "type": "cqc"})
        if not exists:
            await db.standards.insert_one({
                **qs,
                "type": "cqc",
                "is_active": True,
                "created_at": now,
                "source": "CQC Single Assessment Framework - Quality Statements",
            })
            inserted += 1
    if inserted:
        logger.info(f"Seeded {inserted} CQC Quality Statements into standards collection")
