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
    {"reference": "Standard 1",  "name": "Understand your role", "description": "The care worker understands their role and responsibilities, the importance of working within their scope of practice, and the impact of their role on the person they support.", "keywords": ["role", "responsibilities", "boundaries", "scope of practice", "code of conduct", "accountability"], "sub_outcomes": [
        {"ref": "1.1a", "desc": "Describe the duties and responsibilities of own work role"},
        {"ref": "1.1b", "desc": "Identify standards that influence the way the role is carried out"},
        {"ref": "1.2a", "desc": "Explain why it is important to work in ways agreed with the employer"},
        {"ref": "1.3a", "desc": "Describe the importance of working in partnership with others"}
    ]},
    {"reference": "Standard 2",  "name": "Your personal development", "description": "The care worker is committed to their personal development, including training, learning, CPD, and reflective practice. Includes supervision and appraisal.", "keywords": ["training", "learning", "CPD", "personal development", "reflective practice", "supervision", "appraisal", "development"], "sub_outcomes": [
        {"ref": "2.1a", "desc": "Describe the processes for identifying own learning and development needs"},
        {"ref": "2.1b", "desc": "Identify sources of support available for own learning and development"},
        {"ref": "2.2a", "desc": "Explain the importance of reflective practice in continuously improving the quality of service"},
        {"ref": "2.3a", "desc": "Describe why it is important to keep up to date with the latest thinking and changes in the area you work in"}
    ]},
    {"reference": "Standard 3",  "name": "Duty of care", "description": "The care worker understands their duty of care and how to balance this with an individual's rights. Includes dilemmas, complaints and incidents.", "keywords": ["duty of care", "duty of candour", "dilemmas", "complaints", "incidents", "rights", "wellbeing", "safeguarding"], "sub_outcomes": [
        {"ref": "3.1a", "desc": "Define duty of care"},
        {"ref": "3.2a", "desc": "Describe dilemmas that may arise between the duty of care and an individual's rights"},
        {"ref": "3.3a", "desc": "Identify how to respond to complaints and concerns"},
        {"ref": "3.3b", "desc": "Describe how comments and complaints are used to improve the quality of service"}
    ]},
    {"reference": "Standard 4",  "name": "Equality, diversity, inclusion and human rights", "description": "The care worker works in an inclusive way that values diversity and treats people as individuals, respecting protected characteristics and challenging discrimination.", "keywords": ["equality", "diversity", "inclusion", "human rights", "discrimination", "protected characteristics", "individual needs", "culture", "religion"], "sub_outcomes": [
        {"ref": "4.1a", "desc": "Define what is meant by diversity, equality and inclusion"},
        {"ref": "4.2a", "desc": "Describe ways in which discrimination may deliberately or inadvertently occur in the work setting"},
        {"ref": "4.3a", "desc": "Explain the importance of inclusive practice"},
        {"ref": "4.3b", "desc": "Describe how to challenge discrimination in a way that promotes change"}
    ]},
    {"reference": "Standard 5",  "name": "Work in a person-centred way", "description": "The care worker puts the individual at the centre of care, supporting their choices, promoting their wellbeing and independence.", "keywords": ["person-centred", "choices", "independence", "wellbeing", "preferences", "self-determination", "mental capacity", "consent", "dignity"], "sub_outcomes": [
        {"ref": "5.1a", "desc": "Describe the key principles of person-centred care"},
        {"ref": "5.2a", "desc": "Explain the importance of working in a way that promotes the individual's wellbeing"},
        {"ref": "5.3a", "desc": "Describe ways of reducing the risk of harm when carrying out activities with individuals"},
        {"ref": "5.4a", "desc": "Describe the importance of an individual's right to make choices and decisions"}
    ]},
    {"reference": "Standard 6",  "name": "Communication", "description": "The care worker communicates effectively in verbal and non-verbal ways, adapts to individuals' communication needs, and maintains accurate records.", "keywords": ["communication", "listening", "non-verbal", "language needs", "records", "handover", "reporting", "documentation", "confidentiality"], "sub_outcomes": [
        {"ref": "6.1a", "desc": "Identify different forms of communication and how these may affect relationships"},
        {"ref": "6.2a", "desc": "Describe the factors that may affect communication with an individual"},
        {"ref": "6.3a", "desc": "Describe ways of adapting communication in response to an individual's reactions, needs and preferences"},
        {"ref": "6.4a", "desc": "Explain why it is important to have accurate and up-to-date records and reports"}
    ]},
    {"reference": "Standard 7",  "name": "Privacy and dignity", "description": "The care worker promotes and maintains the privacy, dignity and respect of each individual in their care, including supporting active participation and informed choice.", "keywords": ["privacy", "dignity", "respect", "confidentiality", "personal information", "intimate care", "active participation", "choices"], "sub_outcomes": [
        {"ref": "7.1a", "desc": "Describe what is meant by privacy and dignity"},
        {"ref": "7.2a", "desc": "Explain the importance of maintaining the dignity and privacy of individuals"},
        {"ref": "7.3a", "desc": "Describe how to maintain the privacy, dignity and respect of individuals during day-to-day activities"},
        {"ref": "7.4a", "desc": "Describe ways to support active participation in activities"}
    ]},
    {"reference": "Standard 8",  "name": "Fluids and nutrition", "description": "The care worker supports individuals to have adequate nutrition and hydration, understands signs of malnutrition and dehydration.", "keywords": ["nutrition", "hydration", "fluid intake", "malnutrition", "dehydration", "diet", "eating", "drinking", "mealtime", "food safety"], "sub_outcomes": [
        {"ref": "8.1a", "desc": "Understand the importance of food safety including storage, handling and preparation of food"},
        {"ref": "8.2a", "desc": "Describe signs of poor nutrition and hydration and the impact on health and wellbeing"},
        {"ref": "8.3a", "desc": "Describe ways to support individuals to have adequate nutrition and hydration"},
        {"ref": "8.4a", "desc": "Identify nutritional needs and preferences including religious, cultural and personal choices"}
    ]},
    {"reference": "Standard 9",  "name": "Awareness of mental health and dementia", "description": "The care worker has awareness of mental health conditions and dementia, including how these affect individuals' wellbeing, behaviour and the reasonable adjustments required in care delivery.", "keywords": ["mental health", "dementia", "behaviour", "wellbeing", "cognitive impairment", "anxiety", "depression", "positive attitudes", "reasonable adjustments"], "sub_outcomes": [
        {"ref": "9.1a", "desc": "Describe the main forms of mental ill health and their prevalence"},
        {"ref": "9.2a", "desc": "Describe the key aspects of dementia including how it may affect the individual"},
        {"ref": "9.3a", "desc": "Describe what is meant by learning disability and how it may affect an individual"},
        {"ref": "9.4a", "desc": "Describe how the way an individual communicates may be affected by mental health, dementia or learning disability"}
    ]},
    {"reference": "Standard 10", "name": "Safeguarding adults", "description": "The care worker understands adult safeguarding, recognises signs of abuse and neglect, and knows how to report concerns.", "keywords": ["safeguarding", "abuse", "neglect", "reporting", "whistleblowing", "protection", "harm", "exploitation", "concerns", "restrictive practices"], "sub_outcomes": [
        {"ref": "10.1a", "desc": "Define the term 'safeguarding'"},
        {"ref": "10.2a", "desc": "Describe the types of abuse and neglect and the signs and symptoms associated with them"},
        {"ref": "10.3a", "desc": "Describe what to do if abuse of an adult is suspected"},
        {"ref": "10.4a", "desc": "Describe the importance of ensuring individuals are treated with dignity and respect"}
    ]},
    {"reference": "Standard 11", "name": "Safeguarding children", "description": "The care worker is aware of child safeguarding responsibilities even when primarily working with adults.", "keywords": ["safeguarding children", "child protection", "young carers", "children", "abuse", "neglect"], "sub_outcomes": [
        {"ref": "11.1a", "desc": "Describe the main duties and responsibilities in relation to safeguarding children"},
        {"ref": "11.2a", "desc": "Identify signs of abuse and what to do if abuse is suspected"}
    ]},
    {"reference": "Standard 12", "name": "Basic life support", "description": "The care worker knows how to provide basic life support, including CPR, and can respond to emergency situations.", "keywords": ["first aid", "CPR", "resuscitation", "basic life support", "emergency", "AED", "choking"], "sub_outcomes": [
        {"ref": "12.1a", "desc": "Describe when it would be appropriate to administer basic life support"},
        {"ref": "12.2a", "desc": "Demonstrate the ability to perform CPR using appropriate equipment"},
        {"ref": "12.3a", "desc": "Describe how to reduce the risk of infection when administering first aid"}
    ]},
    {"reference": "Standard 13", "name": "Health and safety", "description": "The care worker understands health and safety legislation, risk assessment, moving and handling, medication, fire safety, security and personal wellbeing.", "keywords": ["health and safety", "risk assessment", "COSHH", "moving and handling", "manual handling", "PPE", "lone working", "fire safety", "medication", "security"], "sub_outcomes": [
        {"ref": "13.1a", "desc": "Identify the health and safety legislation relevant to their role"},
        {"ref": "13.2a", "desc": "Describe what is meant by a risk assessment and why they are carried out"},
        {"ref": "13.3a", "desc": "Describe how to reduce the risk of accidents in the work setting"},
        {"ref": "13.4a", "desc": "Describe what to do if an accident or incident occurs"},
        {"ref": "13.5a", "desc": "Describe how to use PPE correctly to reduce risk of infection"}
    ]},
    {"reference": "Standard 14", "name": "Handling information", "description": "The care worker understands data protection, GDPR, confidentiality obligations, and maintains accurate, secure records.", "keywords": ["data protection", "GDPR", "confidentiality", "records management", "information governance", "sharing information", "data breach"], "sub_outcomes": [
        {"ref": "14.1a", "desc": "Identify the legislation and agreed ways of working in relation to recording, storing and sharing information"},
        {"ref": "14.2a", "desc": "Describe how to maintain confidentiality in day-to-day communication"},
        {"ref": "14.3a", "desc": "Describe the potential consequences of a breach of confidentiality"}
    ]},
    {"reference": "Standard 15", "name": "Infection prevention and control", "description": "The care worker understands and applies infection prevention and control measures, including hand hygiene, PPE, and standard precautions.", "keywords": ["infection control", "PPE", "hand hygiene", "standard precautions", "cleaning", "waste disposal", "decontamination", "chain of infection"], "sub_outcomes": [
        {"ref": "15.1a", "desc": "Describe the routes by which infection can enter the body"},
        {"ref": "15.2a", "desc": "Demonstrate how to carry out hand washing technique"},
        {"ref": "15.3a", "desc": "Describe the correct procedures for using and disposing of PPE"},
        {"ref": "15.4a", "desc": "Describe how to reduce the risk of spreading infection"}
    ]},
    {"reference": "Standard 16", "name": "Awareness of learning disability and autism", "description": "It is a legal requirement that all staff working in CQC-regulated services undertake training on how to interact appropriately with people with a learning disability and autistic people, at a level appropriate to their role.", "keywords": ["learning disability", "autism", "training", "CQC regulation 18", "staffing", "awareness"], "sub_outcomes": [
        {"ref": "16.1a", "desc": "Describe what is meant by learning disability"},
        {"ref": "16.2a", "desc": "Describe what is meant by autism"},
        {"ref": "16.3a", "desc": "Describe how to communicate and interact appropriately with people who have a learning disability or who are autistic"}
    ]},
]


async def _insert_standards_entries(conn, entries: list, jurisdiction: str):
    """Shared helper: bulk-insert standards entries with given jurisdiction."""
    for e in entries:
        await conn.execute(
            """INSERT INTO standards_entries
               (id, org_id, type, reference, name, description, keywords, sub_outcomes,
                key_questions, quality_statement, source, is_active, is_system, jurisdiction, service_type, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb,$10,$11,$12,$13,$14,$15,$16)
               ON CONFLICT (id) DO NOTHING""",
            e["id"], None, e["type"], e["reference"], e["name"], e["description"],
            e["keywords"], e["sub_outcomes"],
            e["key_questions"], e.get("quality_statement", False), e["source"],
            e.get("is_active", True), True, jurisdiction, e.get("service_type"), e["created_at"],
        )


async def seed_standards():
    """Insert CQC regulations, quality statements, and Care Certificate standards (idempotent, jurisdiction=england).

    Checks each type independently so a partial previous seed (e.g. care_cert seeded but
    CQC missing) is repaired automatically on the next startup without duplicating existing rows.
    """
    async with database.with_admin() as conn:
        cqc_count = await conn.fetchval(
            "SELECT COUNT(*) FROM standards_entries WHERE type='cqc' AND is_system=TRUE"
        )
        care_cert_count = await conn.fetchval(
            "SELECT COUNT(*) FROM standards_entries WHERE type='care_cert' AND is_system=TRUE"
        )

        if cqc_count and cqc_count > 0:
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

        if care_cert_count and care_cert_count > 0:
            # One-time fix: backfill sub_outcomes for care_cert standards that have an empty list
            cc_empty = await conn.fetchval(
                "SELECT COUNT(*) FROM standards_entries WHERE type='care_cert' AND is_system=TRUE AND sub_outcomes='[]'::jsonb"
            )
            if cc_empty and cc_empty > 0:
                logger.info("Backfilling sub_outcomes for %d Care Certificate standards…", cc_empty)
                sub_map = {s["reference"]: s["sub_outcomes"] for s in CARE_CERT_STANDARDS}
                for ref, sub_outcomes in sub_map.items():
                    await conn.execute(
                        "UPDATE standards_entries SET sub_outcomes=$1 WHERE type='care_cert' AND reference=$2 AND is_system=TRUE",
                        sub_outcomes, ref,
                    )
                logger.info("Care Certificate sub_outcomes backfill complete")

        # If both types are present, nothing more to do
        if (cqc_count and cqc_count > 0) and (care_cert_count and care_cert_count > 0):
            logger.info(f"England standards already seeded (cqc={cqc_count}, care_cert={care_cert_count}) — skipping")
            return

        # Insert whichever types are missing
        now = datetime.now(timezone.utc).isoformat()
        entries = []

        if not cqc_count or cqc_count == 0:
            logger.info("CQC standards missing — seeding now…")
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

        if not care_cert_count or care_cert_count == 0:
            logger.info("Care Certificate standards missing — seeding now…")
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

        if entries:
            await _insert_standards_entries(conn, entries, "england")
            logger.info(f"Seeded {len(entries)} England standards entries (cqc={cqc_count or 0}, care_cert={care_cert_count or 0} were present before)")
            # Re-warm the in-process cache so AI analysis picks up the new rows
            # in the same process run without requiring another restart.
            from utils.standards_cache import rewarm
            await rewarm(conn)


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
# Granular section-level entries (67 total, one per section across all 7 workbooks).
# Adults use workbooks 1, 3, 5, 6, 7. Children's services use workbooks 2, 4, 5, 6, 7.
# Both MUST be seeded as providers may work with adults AND children.
# description = practice learning outcomes (what the worker CAN DO — "You are able to...")
# sub_outcomes = knowledge statements (what the worker KNOWS — manager-verified)

AWIF_STANDARDS = [
    # ── Workbook 1: Principles and Values (Adults) ─────────────────────────────
    {
        "reference": "AWIF 1.1",
        "name": "Legislation, national policies and codes of conduct (adults)",
        "description": (
            "Worker is able to: relate the principles and values of the Social Services and Well-being (Wales) "
            "Act 2014 to their practice; uphold the Code of Conduct and Code of Professional Practice for Social Care in their work."
        ),
        "keywords": [
            "SSWB Act 2014", "Social Services and Well-being", "Code of Professional Practice",
            "Code of Conduct", "Social Care Wales", "legislation", "national policy",
            "professional standards", "values", "principles",
        ],
        "sub_outcomes": [
            {"ref": "1.1a", "desc": "Knows the principles and values of the Social Services and Well-being (Wales) Act 2014"},
            {"ref": "1.1b", "desc": "Knows why these principles are important for health and social care and how they underpin practice"},
            {"ref": "1.1c", "desc": "Knows what the Codes of Conduct and Professional Practice are, who they apply to and how to use them"},
            {"ref": "1.1d", "desc": "Understands how the Codes underpin the principles and values of health and social care"},
        ],
    },
    {
        "reference": "AWIF 1.2",
        "name": "Rights-based approaches in health and social care (adults)",
        "description": (
            "Worker is able to: embed a rights-based approach in their practice with adults."
        ),
        "keywords": [
            "rights-based", "human rights", "SSWB Act", "advocacy", "individual rights",
            "legal rights", "voice and control", "empowerment", "complaints",
        ],
        "sub_outcomes": [
            {"ref": "1.2a", "desc": "Knows the meaning of a rights-based approach"},
            {"ref": "1.2b", "desc": "Knows how legislation and national policies underpin a rights-based approach"},
            {"ref": "1.2c", "desc": "Understands what advocacy is and how it supports a rights-based approach"},
            {"ref": "1.2d", "desc": "Knows how to support individuals and families to make a complaint or express a concern"},
        ],
    },
    {
        "reference": "AWIF 1.3",
        "name": "Person-centred approaches (adults)",
        "description": (
            "Worker is able to: recognise the importance of knowing an individual's preferences and background "
            "and reflect this in practice; embed person-centred approaches; support active participation and inclusion."
        ),
        "keywords": [
            "person-centred", "co-production", "voice choice control", "individual preferences",
            "dignity", "respect", "consent", "active participation", "personal plan",
            "well-being", "inclusion", "meaningful activities",
        ],
        "sub_outcomes": [
            {"ref": "1.3a", "desc": "Knows what 'person-centred approaches' means and why these are important"},
            {"ref": "1.3b", "desc": "Understands co-production and 'voice, choice and control'"},
            {"ref": "1.3c", "desc": "Knows the importance of understanding an individual's preferences, background, history and what matters to them"},
            {"ref": "1.3d", "desc": "Knows ways of working to establish individual preferences and desired outcomes"},
            {"ref": "1.3e", "desc": "Knows what 'dignity and respect' means and why this is central to the role"},
            {"ref": "1.3f", "desc": "Understands consent when providing care and why it is important"},
            {"ref": "1.3g", "desc": "Knows what 'active participation' means and why supporting meaningful activities matters"},
            {"ref": "1.3h", "desc": "Knows the purpose of personal plans"},
        ],
    },
    {
        "reference": "AWIF 1.4",
        "name": "Equality, diversity and inclusion (adults)",
        "description": (
            "Worker is able to: respect and promote equality, diversity and inclusion in their practice with adults."
        ),
        "keywords": [
            "equality", "diversity", "inclusion", "discrimination", "protected characteristics",
            "Equality Act 2010", "cultural awareness", "religious beliefs", "challenging discrimination",
        ],
        "sub_outcomes": [
            {"ref": "1.4a", "desc": "Knows what equality, diversity, inclusion and discrimination mean"},
            {"ref": "1.4b", "desc": "Knows what 'protected characteristics' are"},
            {"ref": "1.4c", "desc": "Knows how person-centred approaches promote equality, diversity and inclusion"},
            {"ref": "1.4d", "desc": "Knows how to value cultural, religious and linguistic backgrounds of individuals"},
            {"ref": "1.4e", "desc": "Knows how to challenge discrimination and practice that does not support equality"},
        ],
    },
    {
        "reference": "AWIF 1.5",
        "name": "Positive risk taking (adults)",
        "description": (
            "Worker is able to: follow workplace policies and procedures for risk assessments to support "
            "individuals to take positive risks that promote their well-being and autonomy."
        ),
        "keywords": [
            "positive risk taking", "risk assessment", "risk management", "autonomy",
            "best interest", "rights to take risks", "balancing risks", "calculated risk",
        ],
        "sub_outcomes": [
            {"ref": "1.5a", "desc": "Knows what 'positive risk taking' means and its importance for well-being"},
            {"ref": "1.5b", "desc": "Knows individuals' rights to make choices and take risks"},
            {"ref": "1.5c", "desc": "Understands how balancing rights, risks and responsibilities contributes to person-centred approaches"},
            {"ref": "1.5d", "desc": "Knows what to consider when supporting individuals to take positive risks"},
            {"ref": "1.5e", "desc": "Knows what 'best interest decisions' means"},
        ],
    },
    {
        "reference": "AWIF 1.6",
        "name": "Positive relationships and professional boundaries (adults)",
        "description": (
            "Worker demonstrates relationship-centred working that supports individuals' sense of security, "
            "belonging and purpose, while maintaining clear professional boundaries."
        ),
        "keywords": [
            "professional boundaries", "therapeutic relationship", "relationship-centred",
            "trust", "rapport", "appropriate relationships", "unacceptable practices",
        ],
        "sub_outcomes": [
            {"ref": "1.6a", "desc": "Knows what 'relationship-centred working' means"},
            {"ref": "1.6b", "desc": "Understands the importance of positive relationships with individuals, families and carers"},
            {"ref": "1.6c", "desc": "Knows the meaning of 'professional boundaries' and how to balance these with relationship-centred working"},
            {"ref": "1.6d", "desc": "Knows unacceptable practices in relationships with individuals, families and carers"},
        ],
    },
    {
        "reference": "AWIF 1.7",
        "name": "Communication (adults)",
        "description": (
            "Worker is able to: identify and use a range of communication methods to meet the needs and "
            "preferences of the individuals they support."
        ),
        "keywords": [
            "communication", "verbal communication", "non-verbal", "written communication",
            "barriers to communication", "augmentative communication", "language needs",
            "active listening", "communication preferences",
        ],
        "sub_outcomes": [
            {"ref": "1.7a", "desc": "Knows what 'effective communication' means and why it is important for well-being"},
            {"ref": "1.7b", "desc": "Knows key features of effective communication and the skills needed"},
            {"ref": "1.7c", "desc": "Knows how to find out an individual's communication and language needs"},
            {"ref": "1.7d", "desc": "Knows barriers to effective communication and ways to address them"},
        ],
    },
    {
        "reference": "AWIF 1.8",
        "name": "Welsh language and culture (adults)",
        "description": (
            "Worker is able to: implement the principles of Mwy na geiriau / More than just words in their work, "
            "actively offering Welsh language provision to individuals."
        ),
        "keywords": [
            "Welsh language", "Cymraeg", "Welsh culture", "More than just words", "Mwy na geiriau",
            "Active Offer", "Welsh Language Standards", "linguistic needs", "bilingual",
        ],
        "sub_outcomes": [
            {"ref": "1.8a", "desc": "Knows the importance of recognising and supporting Welsh language and culture"},
            {"ref": "1.8b", "desc": "Knows legislation and national strategies for Welsh language"},
            {"ref": "1.8c", "desc": "Knows the principles of Mwy na geiriau / More than just words"},
            {"ref": "1.8d", "desc": "Understands the meaning of the Active Offer"},
        ],
    },
    {
        "reference": "AWIF 1.9",
        "name": "Positive approaches to reduce restrictive practices (adults)",
        "description": (
            "Worker is able to: embed the use of positive approaches in their practice; follow workplace "
            "policies and procedures for behaviour support; work to reduce restrictive practices."
        ),
        "keywords": [
            "restrictive practices", "positive behaviour support", "PBS", "restraint",
            "de-escalation", "least restrictive", "Deprivation of Liberty", "DoLS",
            "proactive approaches", "reactive strategies",
        ],
        "sub_outcomes": [
            {"ref": "1.9a", "desc": "Knows the meaning of 'positive approaches' and 'restrictive practices'"},
            {"ref": "1.9b", "desc": "Knows underlying causes that may impact upon the behaviour of individuals"},
            {"ref": "1.9c", "desc": "Knows how positive approaches can be used to reduce restrictive practices"},
        ],
    },
    {
        "reference": "AWIF 1.10",
        "name": "Change and transitions in health and social care (adults)",
        "description": (
            "Worker supports adults through significant life changes and transitions in a positive and "
            "person-centred way, recognising the impact these have on well-being."
        ),
        "keywords": [
            "transitions", "life changes", "change management", "moving home", "bereavement",
            "hospital discharge", "significant life events", "adaptation", "support through change",
        ],
        "sub_outcomes": [
            {"ref": "1.10a", "desc": "Knows types of change that may occur in an individual's life as a result of significant life events or transitions"},
            {"ref": "1.10b", "desc": "Knows factors that make these changes either positive or negative"},
        ],
    },
    {
        "reference": "AWIF 1.11",
        "name": "Reflection in health and social care practice (adults)",
        "description": (
            "Worker reflects on how their own values, beliefs and experiences influence their practice, "
            "recognising the impact of their attitude and behaviour on individuals."
        ),
        "keywords": [
            "reflection", "reflective practice", "self-awareness", "personal values", "bias",
            "professional development", "impact on practice", "Code of Professional Practice",
        ],
        "sub_outcomes": [
            {"ref": "1.11a", "desc": "Understands the impact of own attitude and behaviour on individuals and carers"},
        ],
    },

    # ── Workbook 2: Principles and Values (Children and Young People) ──────────
    {
        "reference": "AWIF 2.1",
        "name": "Legislation, national policies and codes of conduct (children and young people)",
        "description": (
            "Worker is able to: relate the principles and values of the SSWB Act 2014 and Children Act 1989 "
            "to their practice with children and young people; uphold the codes of conduct and professional practice."
        ),
        "keywords": [
            "Children Act 1989", "SSWB Act 2014", "Code of Professional Practice", "UN CRC",
            "children's rights", "legislation", "young people", "codes of conduct",
        ],
        "sub_outcomes": [
            {"ref": "2.1a", "desc": "Knows the principles and values of the SSWB Act 2014 and the Children Act 1989"},
            {"ref": "2.1b", "desc": "Knows the Codes of Conduct and Professional Practice and how they apply"},
            {"ref": "2.1c", "desc": "Understands how the Codes underpin the principles of health and social care for children"},
        ],
    },
    {
        "reference": "AWIF 2.2",
        "name": "Rights-based approaches for children and young people",
        "description": (
            "Worker is able to: embed a rights-based approach in their work with children and young people."
        ),
        "keywords": [
            "children's rights", "UN Convention on the Rights of the Child", "UNCRC", "advocacy",
            "rights-based", "voice of the child", "child participation", "complaints",
        ],
        "sub_outcomes": [
            {"ref": "2.2a", "desc": "Knows the meaning of a rights-based approach for children and young people"},
            {"ref": "2.2b", "desc": "Knows how legislation underpins rights-based approaches for children"},
            {"ref": "2.2c", "desc": "Understands advocacy and how it supports children's rights"},
            {"ref": "2.2d", "desc": "Knows how to support children, families and carers to make a complaint or concern"},
        ],
    },
    {
        "reference": "AWIF 2.3",
        "name": "Child-centred approaches",
        "description": (
            "Worker is able to: embed child-centred approaches in their practice; support children and young "
            "people to engage in activities that reflect their preferences; ensure the best interests of the child are paramount."
        ),
        "keywords": [
            "child-centred", "best interests of the child", "voice of the child", "co-production",
            "active participation", "children's preferences", "consent", "parental responsibility",
            "personal plan", "child development",
        ],
        "sub_outcomes": [
            {"ref": "2.3a", "desc": "Knows what 'child-centred approaches' means and why these are important"},
            {"ref": "2.3b", "desc": "Understands co-production and voice, choice and control for children"},
            {"ref": "2.3c", "desc": "Knows the importance of understanding a child's preferences, background and what matters to them"},
            {"ref": "2.3d", "desc": "Knows what dignity, respect and consent mean in the context of working with children"},
            {"ref": "2.3e", "desc": "Knows what 'parental responsibility' means"},
            {"ref": "2.3f", "desc": "Knows the purpose of personal plans for children and young people"},
        ],
    },
    {
        "reference": "AWIF 2.4",
        "name": "Equality, diversity and inclusion (children and young people)",
        "description": (
            "Worker is able to: respect and promote equality, diversity and inclusion when working with "
            "children and young people."
        ),
        "keywords": [
            "equality", "diversity", "inclusion", "discrimination", "children", "cultural background",
            "religious beliefs", "linguistic heritage", "challenging discrimination",
        ],
        "sub_outcomes": [
            {"ref": "2.4a", "desc": "Knows what equality, diversity, inclusion and discrimination mean in children's services"},
            {"ref": "2.4b", "desc": "Knows how child-centred approaches promote equality, diversity and inclusion"},
            {"ref": "2.4c", "desc": "Knows how to value cultural, religious and linguistic backgrounds of children"},
            {"ref": "2.4d", "desc": "Knows how to challenge discrimination in practice with children"},
        ],
    },
    {
        "reference": "AWIF 2.5",
        "name": "Positive risk taking (children and young people)",
        "description": (
            "Worker is able to: follow workplace risk assessment policies to support children and young people "
            "to take positive risks; balance a child's need to experience and learn with their duty to keep them safe."
        ),
        "keywords": [
            "positive risk taking", "children's risk", "child development", "balancing safety",
            "risk assessment", "experiential learning", "risk benefit analysis",
        ],
        "sub_outcomes": [
            {"ref": "2.5a", "desc": "Knows what positive risk taking means for children and its importance for well-being"},
            {"ref": "2.5b", "desc": "Knows children's rights to make choices and take risks"},
            {"ref": "2.5c", "desc": "Knows how balancing rights, risks and responsibilities contributes to child-centred approaches"},
            {"ref": "2.5d", "desc": "Knows what to consider when supporting children to take positive risks, including stage of development"},
        ],
    },
    {
        "reference": "AWIF 2.6",
        "name": "Positive relationships and professional boundaries (children and young people)",
        "description": (
            "Worker demonstrates relationship-centred working with children and young people, maintaining "
            "clear professional boundaries while building trust and positive connections."
        ),
        "keywords": [
            "professional boundaries", "therapeutic relationship", "children", "young people",
            "trust", "appropriate relationships", "relationship-centred working",
        ],
        "sub_outcomes": [
            {"ref": "2.6a", "desc": "Knows what relationship-centred working means with children and young people"},
            {"ref": "2.6b", "desc": "Understands the importance of positive relationships with children, families and carers"},
            {"ref": "2.6c", "desc": "Knows how to balance professional boundaries with relationship-centred working"},
            {"ref": "2.6d", "desc": "Knows unacceptable practices in relationships with children, young people and families"},
        ],
    },
    {
        "reference": "AWIF 2.7",
        "name": "Communication with children and young people",
        "description": (
            "Worker is able to: identify and use a range of communication methods to meet the needs and "
            "preferences of the children and young people they support, including developmentally appropriate approaches."
        ),
        "keywords": [
            "communication", "children's communication", "developmentally appropriate", "play-based",
            "non-verbal", "language development", "AAC", "listening skills",
        ],
        "sub_outcomes": [
            {"ref": "2.7a", "desc": "Knows what effective communication means in children's services and why it is important"},
            {"ref": "2.7b", "desc": "Knows how a child's stage of development impacts their communication skills"},
            {"ref": "2.7c", "desc": "Knows how to find out a child's communication needs, wishes and preferences"},
            {"ref": "2.7d", "desc": "Knows barriers to communication with children and how to address them"},
        ],
    },
    {
        "reference": "AWIF 2.8",
        "name": "Welsh language and culture (children and young people)",
        "description": (
            "Worker is able to: implement the principles of Mwy na geiriau / More than just words when "
            "working with children and young people, supporting Welsh language identity and cultural heritage."
        ),
        "keywords": [
            "Welsh language", "Cymraeg", "cultural identity", "Welsh culture", "Active Offer",
            "More than just words", "Mwy na geiriau", "bilingual", "children's identity",
        ],
        "sub_outcomes": [
            {"ref": "2.8a", "desc": "Knows the importance of recognising and supporting Welsh language and culture for children"},
            {"ref": "2.8b", "desc": "Knows Welsh language legislation and national strategies"},
            {"ref": "2.8c", "desc": "Knows the principles of Mwy na geiriau / More than just words and the Active Offer"},
        ],
    },
    {
        "reference": "AWIF 2.9",
        "name": "Positive approaches to reduce restrictive practices (children and young people)",
        "description": (
            "Worker is able to: embed positive approaches in their work with children; follow workplace "
            "policies for behaviour support; actively work to reduce restrictive practices."
        ),
        "keywords": [
            "restrictive practices", "positive behaviour support", "PBS", "de-escalation",
            "children's behaviour", "proactive approaches", "least restrictive option",
        ],
        "sub_outcomes": [
            {"ref": "2.9a", "desc": "Knows the meaning of 'positive approaches' and 'restrictive practices' in children's services"},
            {"ref": "2.9b", "desc": "Knows underlying causes that may impact on the behaviour of children and young people"},
            {"ref": "2.9c", "desc": "Knows how positive approaches can be used to reduce restrictive practices and promote positive behaviour"},
        ],
    },
    {
        "reference": "AWIF 2.10",
        "name": "Change and transitions (children and young people)",
        "description": (
            "Worker supports children and young people through significant life changes and transitions, "
            "including preparing young people for adult life."
        ),
        "keywords": [
            "transitions", "life changes", "children's transitions", "care leavers",
            "moving placements", "significant life events", "preparing for adulthood",
        ],
        "sub_outcomes": [
            {"ref": "2.10a", "desc": "Knows types of change in a child's life as a result of significant life events or transitions"},
            {"ref": "2.10b", "desc": "Knows factors that make transitions positive or negative for children"},
            {"ref": "2.10c", "desc": "Knows how to support young people to develop skills, confidence and knowledge for adult life"},
        ],
    },
    {
        "reference": "AWIF 2.11",
        "name": "Reflection in practice (children and young people)",
        "description": (
            "Worker is able to: reflect on how their attitude and behaviour impacts on the children "
            "and young people they support."
        ),
        "keywords": [
            "reflection", "self-awareness", "impact on children", "personal values",
            "bias", "professional development", "reflexive practice",
        ],
        "sub_outcomes": [
            {"ref": "2.11a", "desc": "Understands the impact of own attitude and behaviour on children and young people"},
        ],
    },

    # ── Workbook 3: Health and Well-being (Adults) ─────────────────────────────
    {
        "reference": "AWIF 3.1",
        "name": "Well-being of adults",
        "description": (
            "Worker is able to: work in ways that recognise the importance of families, friends and community "
            "networks and support these relationships; recognise what matters to each individual."
        ),
        "keywords": [
            "well-being", "holistic well-being", "community networks", "social connections",
            "what matters to individuals", "strengths-based", "SSWB Act well-being outcomes",
        ],
        "sub_outcomes": [
            {"ref": "3.1a", "desc": "Knows what 'well-being' means in the context of health and social care for adults"},
            {"ref": "3.1b", "desc": "Knows factors that affect the well-being of individuals and carers"},
            {"ref": "3.1c", "desc": "Understands the importance of families, friends and community networks on well-being"},
            {"ref": "3.1d", "desc": "Knows ways of working that support well-being"},
        ],
    },
    {
        "reference": "AWIF 3.2",
        "name": "Factors that impact upon health and well-being (adults)",
        "description": (
            "Worker is able to: know where to access further information or support; take account of factors "
            "impacting the health and well-being of individuals they work with; support health promotion."
        ),
        "keywords": [
            "health factors", "well-being determinants", "disability models", "mental health",
            "physical health", "social model of disability", "health promotion", "attachment",
            "self-identity", "health checks", "safeguarding links", "Mental Capacity Act",
        ],
        "sub_outcomes": [
            {"ref": "3.2a", "desc": "Knows human development and factors that can affect it"},
            {"ref": "3.2b", "desc": "Knows the range of factors that may affect health, well-being and development"},
            {"ref": "3.2c", "desc": "Knows the difference between the medical and social models of disability"},
            {"ref": "3.2d", "desc": "Knows what good physical and mental health means and how they are interdependent"},
            {"ref": "3.2e", "desc": "Knows the importance of self-identity, self-worth and sense of security on well-being"},
            {"ref": "3.2f", "desc": "Knows the types of changes in an individual that would give cause for concern"},
            {"ref": "3.2g", "desc": "Understands links between health and well-being and safeguarding"},
        ],
    },
    {
        "reference": "AWIF 3.3",
        "name": "Supporting personal care and continence management (adults)",
        "description": (
            "Worker is able to: follow individuals' personal plans when assisting with personal care and/or "
            "continence management; follow infection prevention and control procedures; record appropriately."
        ),
        "keywords": [
            "personal care", "continence", "continence management", "infection prevention",
            "dignity in care", "privacy", "personal hygiene", "intimate care",
        ],
        "sub_outcomes": [
            {"ref": "3.3a", "desc": "Knows what 'personal care' means and how to establish individual preferences"},
            {"ref": "3.3b", "desc": "Knows how to protect the privacy and dignity of individuals during personal care"},
            {"ref": "3.3c", "desc": "Knows factors that may contribute to difficulties with continence"},
            {"ref": "3.3d", "desc": "Knows aids, equipment and professionals that can support continence management"},
        ],
    },
    {
        "reference": "AWIF 3.4",
        "name": "Pressure area care (adults)",
        "description": (
            "Worker is able to: follow individuals' personal plans and risk assessments for pressure area care; "
            "follow infection prevention procedures; report and record any changes in skin condition."
        ),
        "keywords": [
            "pressure area care", "pressure ulcers", "skin integrity", "pressure damage",
            "tissue viability", "repositioning", "pressure relief", "Waterlow", "wound care",
        ],
        "sub_outcomes": [
            {"ref": "3.4a", "desc": "Knows what pressure area care, pressure damage and pressure ulcers mean"},
            {"ref": "3.4b", "desc": "Knows factors that cause skin breakdown and pressure damage"},
            {"ref": "3.4c", "desc": "Knows stages of pressure ulcer development and common affected body parts"},
            {"ref": "3.4d", "desc": "Knows interventions that can reduce the risk of pressure damage"},
        ],
    },
    {
        "reference": "AWIF 3.5",
        "name": "Oral health care and mouth care (adults)",
        "description": (
            "Worker is able to: follow individuals' personal plans when assisting with mouth care; "
            "follow infection prevention procedures; record and report any changes in oral condition."
        ),
        "keywords": [
            "oral health", "mouth care", "dental health", "dentures", "oral hygiene",
            "nutrition links", "specialist referral", "older adults", "oral health policy",
        ],
        "sub_outcomes": [
            {"ref": "3.5a", "desc": "Knows what oral health care and mouth care means and why it is important"},
            {"ref": "3.5b", "desc": "Knows national policy and practice guidance on oral health care"},
            {"ref": "3.5c", "desc": "Knows common oral and dental problems in older people and individuals needing care"},
            {"ref": "3.5d", "desc": "Knows the impact of poor oral health on health, well-being and self-esteem"},
        ],
    },
    {
        "reference": "AWIF 3.6",
        "name": "Foot care (adults)",
        "description": (
            "Worker is able to: follow individuals' personal plans when assisting with foot care; "
            "monitor, record and report on the condition of individuals' feet."
        ),
        "keywords": [
            "foot care", "podiatry", "chiropody", "foot conditions", "toenails",
            "diabetes foot care", "mobility", "specialist referral",
        ],
        "sub_outcomes": [
            {"ref": "3.6a", "desc": "Knows why foot care is needed and common conditions causing foot problems"},
            {"ref": "3.6b", "desc": "Knows signs of foot and toenail abnormalities and their impact on well-being"},
            {"ref": "3.6c", "desc": "Knows the range of professionals who may help with foot care"},
        ],
    },
    {
        "reference": "AWIF 3.7",
        "name": "Administration of medication (adults)",
        "description": (
            "Worker is aware of what they can and cannot do in relation to medication administration "
            "at their stage of training; follows workplace policies and procedures for medication."
        ),
        "keywords": [
            "medication", "administration of medication", "MAR chart", "medication errors",
            "prescribing", "dispensing", "medication safety", "over-the-counter medication",
            "safeguarding medication", "controlled drugs",
        ],
        "sub_outcomes": [
            {"ref": "3.7a", "desc": "Knows legislation and national guidance related to medication administration"},
            {"ref": "3.7b", "desc": "Knows the roles and responsibilities of those involved in prescribing, dispensing and supporting medication use"},
            {"ref": "3.7c", "desc": "Knows links between misadministration of medication and safeguarding"},
        ],
    },
    {
        "reference": "AWIF 3.8",
        "name": "Nutrition and hydration (adults)",
        "description": (
            "Worker is able to: take account of specific nutrition and hydration requirements for individuals "
            "they support; follow workplace policies for monitoring and recording nutrition and hydration."
        ),
        "keywords": [
            "nutrition", "hydration", "balanced diet", "malnutrition", "dehydration",
            "food intake", "MUST tool", "nutritional assessment", "dietary requirements",
        ],
        "sub_outcomes": [
            {"ref": "3.8a", "desc": "Knows what nutrition and hydration means and the principles of a balanced diet"},
            {"ref": "3.8b", "desc": "Knows national initiatives that support nutrition and hydration"},
            {"ref": "3.8c", "desc": "Knows the importance of a balanced diet for health and well-being"},
            {"ref": "3.8d", "desc": "Knows factors that can affect nutrition and hydration"},
        ],
    },
    {
        "reference": "AWIF 3.9",
        "name": "Falls prevention (adults)",
        "description": (
            "Worker is able to: minimise the factors that can contribute to falls; follow workplace policies "
            "for recording and reporting concerns about fall risk factors."
        ),
        "keywords": [
            "falls prevention", "falls risk", "fall assessment", "mobility", "balance",
            "moving safely", "environmental hazards", "older adults", "post-fall review",
        ],
        "sub_outcomes": [
            {"ref": "3.9a", "desc": "Knows factors that can contribute to falls"},
            {"ref": "3.9b", "desc": "Knows how falls can be prevented and how to report concerns"},
        ],
    },
    {
        "reference": "AWIF 3.10",
        "name": "End of life care (adults)",
        "description": (
            "Worker is able to: follow workplace policies and procedures when supporting individuals "
            "with end of life care."
        ),
        "keywords": [
            "end of life", "palliative care", "dying", "bereavement", "advance care planning",
            "advance directives", "DNACPR", "grief", "culture and death", "spiritual care",
        ],
        "sub_outcomes": [
            {"ref": "3.10a", "desc": "Knows how death, dying, grief and mourning may impact on individuals and key people"},
            {"ref": "3.10b", "desc": "Knows how culture, religion and personal beliefs impact approach to death and dying"},
            {"ref": "3.10c", "desc": "Knows what advance care planning and advance directives are and why they are important"},
            {"ref": "3.10d", "desc": "Knows the range of support available for individuals with end of life care"},
        ],
    },
    {
        "reference": "AWIF 3.11",
        "name": "Assistive technology (adults)",
        "description": (
            "Worker is able to: follow workplace policies and procedures for the use of assistive technology "
            "to support individuals' independence and well-being."
        ),
        "keywords": [
            "assistive technology", "electronic assistive technology", "technology-enabled care",
            "telecare", "smart home", "independence", "accessibility", "digital aids",
        ],
        "sub_outcomes": [
            {"ref": "3.11a", "desc": "Knows what assistive technology means and the range of technological aids available"},
            {"ref": "3.11b", "desc": "Knows how technological aids support active participation and independence"},
        ],
    },
    {
        "reference": "AWIF 3.12",
        "name": "Sensory loss (adults)",
        "description": (
            "Worker is able to: take account of sensory loss support requirements when working with individuals."
        ),
        "keywords": [
            "sensory loss", "sight loss", "hearing loss", "deafblindness", "visual impairment",
            "hearing aids", "glasses", "communication adaptations", "sensory impairment",
        ],
        "sub_outcomes": [
            {"ref": "3.12a", "desc": "Knows what sensory loss means, its causes and conditions"},
            {"ref": "3.12b", "desc": "Knows indicators and signs of sensory loss"},
            {"ref": "3.12c", "desc": "Knows factors that impact individuals with sensory loss"},
            {"ref": "3.12d", "desc": "Knows what to consider when communicating with individuals with sight, hearing or deafblind loss"},
        ],
    },
    {
        "reference": "AWIF 3.13",
        "name": "Dementia (adults)",
        "description": (
            "Worker is able to: support individuals to live well with dementia using person-centred approaches."
        ),
        "keywords": [
            "dementia", "Alzheimer's", "living well with dementia", "dementia-friendly",
            "cognitive impairment", "memory loss", "dementia care", "person-centred dementia",
        ],
        "sub_outcomes": [
            {"ref": "3.13a", "desc": "Knows what dementia is, its indicators and signs"},
            {"ref": "3.13b", "desc": "Knows how dementia can affect individuals and their experience of the world"},
            {"ref": "3.13c", "desc": "Knows what 'living well with dementia' means and how person-centred approaches support this"},
            {"ref": "3.13d", "desc": "Knows what to consider when communicating with someone living with dementia"},
            {"ref": "3.13e", "desc": "Knows the impact of dementia on family carers and how to support them"},
        ],
    },
    {
        "reference": "AWIF 3.14",
        "name": "Mental health (adults)",
        "description": (
            "Worker is able to: support individuals to live well with mental ill-health in a person-centred way."
        ),
        "keywords": [
            "mental health", "mental ill-health", "mental health conditions", "recovery",
            "well-being", "stigma", "mental health support", "mental health services",
        ],
        "sub_outcomes": [
            {"ref": "3.14a", "desc": "Knows what mental ill-health means and factors that can contribute to it"},
            {"ref": "3.14b", "desc": "Knows indicators and signs of mental illness"},
            {"ref": "3.14c", "desc": "Knows the potential impact of mental ill-health on health and well-being"},
            {"ref": "3.14d", "desc": "Knows ways individuals can be supported to live well with mental ill-health"},
        ],
    },
    {
        "reference": "AWIF 3.15",
        "name": "Substance misuse (adults)",
        "description": (
            "Worker recognises the impact of substance misuse on the health and well-being of individuals "
            "they support and knows what support is available."
        ),
        "keywords": [
            "substance misuse", "alcohol", "drugs", "addiction", "harm reduction",
            "dependency", "substance use", "recovery services",
        ],
        "sub_outcomes": [
            {"ref": "3.15a", "desc": "Knows what substance misuse means and its indicators and signs"},
            {"ref": "3.15b", "desc": "Knows the potential impact of substance misuse on health and well-being"},
            {"ref": "3.15c", "desc": "Knows the range of support available to individuals who misuse substances"},
        ],
    },

    # ── Workbook 4: Health and Well-being (Children and Young People) ──────────
    {
        "reference": "AWIF 4.1",
        "name": "Well-being of children and young people",
        "description": (
            "Worker is able to: recognise the importance of a child's family and significant others and "
            "support and develop these relationships in the best interest of the child."
        ),
        "keywords": [
            "children's well-being", "family importance", "significant others", "protective factors",
            "children's welfare", "SSWB Act well-being outcomes",
        ],
        "sub_outcomes": [
            {"ref": "4.1a", "desc": "Knows what well-being means for children and young people"},
            {"ref": "4.1b", "desc": "Knows factors that affect the well-being of children and young people"},
            {"ref": "4.1c", "desc": "Understands the importance of family and significant others in a child's well-being"},
        ],
    },
    {
        "reference": "AWIF 4.2",
        "name": "Factors affecting health, well-being and development of children and young people",
        "description": (
            "Worker is able to: recognise the impact of experiences and life events on children's lives; "
            "promote self-identity and self-esteem; support active participation and developmental progress appropriate to age and needs."
        ),
        "keywords": [
            "child development", "developmental factors", "attachment", "resilience", "self-esteem",
            "self-identity", "adverse childhood experiences", "ACEs", "trauma-informed",
            "early intervention", "holistic development",
        ],
        "sub_outcomes": [
            {"ref": "4.2a", "desc": "Knows child development stages and factors that can affect development"},
            {"ref": "4.2b", "desc": "Knows the range of factors affecting health, well-being and development of children"},
            {"ref": "4.2c", "desc": "Understands the meaning of 'attachment' and its importance in child development"},
            {"ref": "4.2d", "desc": "Knows the meaning of 'resilience' and why it matters for children"},
            {"ref": "4.2e", "desc": "Knows what children need to stay healthy physically, mentally and emotionally"},
            {"ref": "4.2f", "desc": "Knows how to use every-day routines and activities to support children's health and well-being"},
        ],
    },
    {
        "reference": "AWIF 4.3",
        "name": "Positive environments for children and young people",
        "description": (
            "Worker is able to: support a positive, safe, caring, nurturing and responsive environment "
            "that meets the health, well-being, development and individual needs of children and young people."
        ),
        "keywords": [
            "positive environment", "nurturing environment", "safe environment", "learning environment",
            "inclusive environment", "routines", "stimulating", "child-friendly spaces",
        ],
        "sub_outcomes": [
            {"ref": "4.3a", "desc": "Knows the features of a positive environment for children and how it supports holistic development"},
            {"ref": "4.3b", "desc": "Knows how the environment supports inclusion of all children"},
            {"ref": "4.3c", "desc": "Understands the importance of consistent routines for children's health and well-being"},
        ],
    },
    {
        "reference": "AWIF 4.4",
        "name": "Play (children and young people)",
        "description": (
            "Worker is able to: provide a range of opportunities for different types of play; "
            "adapt the environment and activities to support participation; meet individual needs and preferences."
        ),
        "keywords": [
            "play", "play-based learning", "types of play", "imaginative play", "physical play",
            "creative play", "exploratory play", "risk in play", "play opportunities",
        ],
        "sub_outcomes": [
            {"ref": "4.4a", "desc": "Knows the importance of play for children's health, well-being and development"},
            {"ref": "4.4b", "desc": "Knows different types of play and their benefits"},
            {"ref": "4.4c", "desc": "Knows how to support holistic development through play"},
            {"ref": "4.4d", "desc": "Understands why risk is important in play and how to support acceptable levels"},
        ],
    },
    {
        "reference": "AWIF 4.5",
        "name": "Speech, language and communication (children and young people)",
        "description": (
            "Worker is able to: take account of the speech and language communication needs of children "
            "in their practice."
        ),
        "keywords": [
            "speech and language", "communication development", "language delay", "SLT",
            "SLCN", "AAC", "early language", "play and communication", "multi-agency",
        ],
        "sub_outcomes": [
            {"ref": "4.5a", "desc": "Knows the importance of speech, language and communication for children's development"},
            {"ref": "4.5b", "desc": "Knows the importance of early intervention for speech and language delays"},
            {"ref": "4.5c", "desc": "Knows how play and activities support communication development"},
        ],
    },
    {
        "reference": "AWIF 4.6",
        "name": "Additional support needs (children and young people)",
        "description": (
            "Worker understands the types of additional support needs children may have and the principles "
            "of inclusion; adapts the environment and activities to enable all children to take part."
        ),
        "keywords": [
            "additional support needs", "ASN", "SEND", "inclusion", "special educational needs",
            "disability", "adapting activities", "inclusive practice", "reasonable adjustments",
        ],
        "sub_outcomes": [
            {"ref": "4.6a", "desc": "Knows the types of additional support needs that children may have"},
            {"ref": "4.6b", "desc": "Knows the principles of inclusion for children with additional support needs"},
            {"ref": "4.6c", "desc": "Knows how to adapt the environment and activities to enable all children to participate"},
        ],
    },
    {
        "reference": "AWIF 4.7",
        "name": "Advice, guidance and support for children and young people",
        "description": (
            "Worker knows key areas of health and well-being for children and the range of agencies "
            "providing information and advice."
        ),
        "keywords": [
            "health information", "children's services", "advice and guidance", "signposting",
            "multi-agency", "family support", "early help",
        ],
        "sub_outcomes": [
            {"ref": "4.7a", "desc": "Knows areas of health and well-being for children and young people and the range of agencies providing advice"},
        ],
    },
    {
        "reference": "AWIF 4.8",
        "name": "Administration of medication (children and young people)",
        "description": (
            "Worker is aware of what they can and cannot do in relation to medication administration for "
            "children; follows workplace policies for medication."
        ),
        "keywords": [
            "medication", "children's medication", "MAR chart", "medication administration",
            "prescribing", "dispensing", "safeguarding medication", "medication errors",
        ],
        "sub_outcomes": [
            {"ref": "4.8a", "desc": "Knows legislation and national guidance related to medication administration for children"},
            {"ref": "4.8b", "desc": "Knows the roles and responsibilities for prescribing, dispensing and supporting medication"},
            {"ref": "4.8c", "desc": "Knows links between misadministration of medication and safeguarding"},
        ],
    },
    {
        "reference": "AWIF 4.9",
        "name": "Personal care (children and young people)",
        "description": (
            "Worker is able to: support personal care routines that meet individual needs; treat children "
            "with dignity and respect; follow infection prevention and control policies."
        ),
        "keywords": [
            "personal care", "intimate care", "dignity", "children's personal care",
            "safe practice", "cultural considerations", "infection control",
        ],
        "sub_outcomes": [
            {"ref": "4.9a", "desc": "Knows the importance of supporting personal care routines for children and young people"},
            {"ref": "4.9b", "desc": "Knows how to treat children with dignity and respect during personal care, considering cultural background"},
            {"ref": "4.9c", "desc": "Knows how to support personal care in a way that protects both the child and the worker"},
        ],
    },
    {
        "reference": "AWIF 4.10",
        "name": "Nutrition and hydration (children and young people)",
        "description": (
            "Worker is able to: take account of specific nutrition and hydration requirements for the "
            "children and young people they support; provide support for a balanced diet and good hydration."
        ),
        "keywords": [
            "nutrition", "hydration", "children's diet", "balanced diet", "healthy eating",
            "food allergies", "dietary requirements", "growth", "development and nutrition",
        ],
        "sub_outcomes": [
            {"ref": "4.10a", "desc": "Knows what nutrition and hydration means for children and principles of a balanced diet"},
            {"ref": "4.10b", "desc": "Knows national initiatives that support nutrition and hydration for children"},
            {"ref": "4.10c", "desc": "Knows the importance of a balanced diet for children's growth, health and development"},
            {"ref": "4.10d", "desc": "Knows factors that can affect nutrition and hydration for children"},
        ],
    },

    # ── Workbook 5: Professional Practice ──────────────────────────────────────
    {
        "reference": "AWIF 5.1",
        "name": "Role and responsibilities of the health and social care worker",
        "description": (
            "Worker is able to: embed the ethos and structure of their organisation; take account of job "
            "description limits; seek support when needed; report unsafe practices; follow workplace policies; "
            "maintain duty of candour."
        ),
        "keywords": [
            "professional responsibility", "scope of practice", "accountability", "duty of care",
            "duty of candour", "confidentiality", "policies and procedures", "reporting unsafe practice",
            "job description", "professional boundaries",
        ],
        "sub_outcomes": [
            {"ref": "5.1a", "desc": "Knows professional responsibilities and accountabilities within relevant legislative frameworks"},
            {"ref": "5.1b", "desc": "Knows the purpose of job descriptions and the importance of working within role limits"},
            {"ref": "5.1c", "desc": "Knows how and when to seek support in situations beyond role, responsibilities or expertise"},
            {"ref": "5.1d", "desc": "Knows why it is important to report unsafe practices and how this should be done"},
            {"ref": "5.1e", "desc": "Knows what 'duty of care' means and conflicts that may arise with individual rights"},
            {"ref": "5.1f", "desc": "Knows what 'duty of candour' is and why being open and honest matters when things go wrong"},
            {"ref": "5.1g", "desc": "Knows what 'confidentiality' means and when confidential information must be shared"},
        ],
    },
    {
        "reference": "AWIF 5.2",
        "name": "Partnership working in health and social care",
        "description": (
            "Worker is able to: recognise the range and roles of other workers and agencies; apply "
            "partnership working and co-production principles; apply confidentiality in all communications; "
            "develop good professional relationships while maintaining boundaries."
        ),
        "keywords": [
            "partnership working", "multi-disciplinary team", "MDT", "co-production", "collaboration",
            "multi-agency", "professional relationships", "inter-agency working",
        ],
        "sub_outcomes": [
            {"ref": "5.2a", "desc": "Knows how to develop and maintain effective partnership working"},
            {"ref": "5.2b", "desc": "Knows the principles of working in partnership and co-production"},
            {"ref": "5.2c", "desc": "Knows the range and roles of other workers and professionals in health and social care"},
            {"ref": "5.2d", "desc": "Knows the importance of multi-agency working"},
        ],
    },
    {
        "reference": "AWIF 5.3",
        "name": "Team working in health and social care",
        "description": (
            "Worker is able to: contribute to the work of their team; fulfil their role and responsibilities; "
            "support effective communication with team members; reflect on team performance."
        ),
        "keywords": [
            "team working", "teamwork", "team contribution", "handover", "communication within teams",
            "team roles", "supervision within teams", "shared goals",
        ],
        "sub_outcomes": [
            {"ref": "5.3a", "desc": "Knows types of team working and how teams may differ in structure and purpose"},
            {"ref": "5.3b", "desc": "Knows the principles that underpin effective team working"},
            {"ref": "5.3c", "desc": "Knows how effective team working contributes to the well-being of individuals"},
        ],
    },
    {
        "reference": "AWIF 5.4",
        "name": "Handling information, records and confidentiality",
        "description": (
            "Worker is able to: follow workplace policies for handling information including storing, recording, "
            "confidentiality and sharing; record written information accurately, clearly and in a timely manner."
        ),
        "keywords": [
            "information handling", "record keeping", "GDPR", "data protection", "UK GDPR",
            "confidentiality", "information sharing", "secure systems", "accurate recording",
            "care records", "fact opinion judgement",
        ],
        "sub_outcomes": [
            {"ref": "5.4a", "desc": "Knows what 'handling information' means and the legislation relating to it"},
            {"ref": "5.4b", "desc": "Knows what secure systems for recording and storing information are and why they matter"},
            {"ref": "5.4c", "desc": "Knows how to record written information with accuracy, clarity, relevance and appropriate detail"},
            {"ref": "5.4d", "desc": "Knows the difference between fact, opinion and judgement in recording"},
            {"ref": "5.4e", "desc": "Understands the importance of sharing recorded information with individuals appropriately"},
        ],
    },
    {
        "reference": "AWIF 5.5",
        "name": "Personal conduct of health and social care workers",
        "description": (
            "Worker is able to: uphold the profession of health and social care workers and role model "
            "best practice in their work, including outside work and on social media."
        ),
        "keywords": [
            "personal conduct", "professional conduct", "role modelling", "social media",
            "professional image", "Code of Professional Practice", "inappropriate relationships",
            "power dynamics", "professional reputation",
        ],
        "sub_outcomes": [
            {"ref": "5.5a", "desc": "Knows what positive role modelling means in health and social care"},
            {"ref": "5.5b", "desc": "Knows why conduct outside work and on social media can affect suitability for the role"},
            {"ref": "5.5c", "desc": "Knows why it is important not to form inappropriate relationships with individuals or families"},
            {"ref": "5.5d", "desc": "Understands the power dynamics in working with individuals and how not to abuse this power"},
        ],
    },
    {
        "reference": "AWIF 5.6",
        "name": "Continuing professional development (CPD)",
        "description": (
            "Worker is able to: meet workplace CPD requirements; identify own learning needs and develop "
            "a personal development plan; prepare for and contribute to supervision and appraisal; "
            "reflect on practice to support professional development."
        ),
        "keywords": [
            "CPD", "continuing professional development", "supervision", "appraisal",
            "reflective practice", "personal development plan", "PDP", "learning needs",
            "professional registration", "Social Care Wales registration", "training",
        ],
        "sub_outcomes": [
            {"ref": "5.6a", "desc": "Knows what continuing professional development (CPD) means"},
            {"ref": "5.6b", "desc": "Knows legislative requirements and codes relating to CPD"},
            {"ref": "5.6c", "desc": "Knows how to evaluate own knowledge and practice against relevant standards"},
            {"ref": "5.6d", "desc": "Knows the range of learning opportunities and how to access information on best practice"},
            {"ref": "5.6e", "desc": "Knows the principles of reflective practice and why it is important"},
            {"ref": "5.6f", "desc": "Knows the purpose of supervision and appraisal and the role and responsibilities for these"},
            {"ref": "5.6g", "desc": "Knows how effective supervision and reflective practice impact on the well-being of individuals"},
        ],
    },

    # ── Workbook 6: Safeguarding Individuals ───────────────────────────────────
    {
        "reference": "AWIF 6.1",
        "name": "Legislation, policies and codes for safeguarding",
        "description": (
            "Worker is able to: follow their local and workplace policies and procedures for safeguarding individuals."
        ),
        "keywords": [
            "safeguarding legislation", "Wales Safeguarding Procedures", "SSWB Act safeguarding",
            "Section 47", "categories of abuse", "safeguarding policy", "reporting safeguarding",
            "recording safeguarding", "adult safeguarding", "child protection",
        ],
        "sub_outcomes": [
            {"ref": "6.1a", "desc": "Knows what safeguarding means"},
            {"ref": "6.1b", "desc": "Knows the main categories of abuse and neglect"},
            {"ref": "6.1c", "desc": "Knows common signs and symptoms associated with harm, abuse and neglect"},
            {"ref": "6.1d", "desc": "Knows legislation, national policies and codes relating to safeguarding both adults and children"},
            {"ref": "6.1e", "desc": "Knows how legislative frameworks support rights to be protected from harm"},
            {"ref": "6.1f", "desc": "Knows how to record and report safeguarding concerns"},
        ],
    },
    {
        "reference": "AWIF 6.2",
        "name": "Working in ways that safeguard individuals from harm, abuse and neglect",
        "description": (
            "Worker is able to: promote and support the safeguarding of individuals through their day-to-day practice."
        ),
        "keywords": [
            "safeguarding practice", "safeguarding culture", "trust and rapport", "reporting concerns",
            "person-centred safeguarding", "safe working", "online safety", "social media risks",
            "whistle-blowing", "zero tolerance",
        ],
        "sub_outcomes": [
            {"ref": "6.2a", "desc": "Knows the role and responsibilities of health and social care workers in safeguarding"},
            {"ref": "6.2b", "desc": "Knows the role of advocacy in relation to safeguarding"},
            {"ref": "6.2c", "desc": "Understands the importance of establishing relationships that support trust and rapport"},
            {"ref": "6.2d", "desc": "Knows how to promote an environment where individuals can express fears and concerns safely"},
            {"ref": "6.2e", "desc": "Knows how to make individuals aware of risks associated with social media, internet and phones"},
        ],
    },
    {
        "reference": "AWIF 6.3",
        "name": "Factors that contribute to harm, abuse or neglect",
        "description": (
            "Worker is able to: promote safe practice and minimise risks to individuals of harm, abuse or neglect."
        ),
        "keywords": [
            "abuse risk factors", "safeguarding risk", "vulnerability", "perpetrator behaviour",
            "grooming", "exploitation", "disclosure barriers", "serious case review", "learning lessons",
        ],
        "sub_outcomes": [
            {"ref": "6.3a", "desc": "Knows why some individuals could be more at risk from harm, abuse or neglect"},
            {"ref": "6.3b", "desc": "Knows why abuse may not be disclosed by adults, children, families or workers"},
            {"ref": "6.3c", "desc": "Knows actions, behaviours or situations that increase the risk of harm or abuse"},
            {"ref": "6.3d", "desc": "Knows features of perpetrator behaviour and grooming"},
            {"ref": "6.3e", "desc": "Knows learning from reviews and reports into serious failures to protect individuals"},
        ],
    },
    {
        "reference": "AWIF 6.4",
        "name": "Responding to, recording and reporting safeguarding concerns",
        "description": (
            "Worker is able to: access personal support when dealing with safeguarding issues; "
            "follow workplace policies for recording and reporting concerns accurately and in a timely manner."
        ),
        "keywords": [
            "safeguarding response", "reporting safeguarding", "recording concerns", "whistleblowing",
            "duty to report", "information sharing safeguarding", "safeguarding boundaries",
            "allegations", "disclosure",
        ],
        "sub_outcomes": [
            {"ref": "6.4a", "desc": "Knows how to respond to suspected, disclosed or alleged harm, abuse or neglect"},
            {"ref": "6.4b", "desc": "Knows actions to take if harm, abuse or neglect is suspected or disclosed"},
            {"ref": "6.4c", "desc": "Knows actions to avoid if harm is suspected to protect any future investigation"},
            {"ref": "6.4d", "desc": "Knows boundaries of confidentiality in relation to safeguarding"},
            {"ref": "6.4e", "desc": "Knows what whistleblowing means and why it is important to report concerns"},
            {"ref": "6.4f", "desc": "Knows potential barriers to reporting or raising concerns"},
            {"ref": "6.4g", "desc": "Knows how to record safeguarding information with accuracy, clarity and appropriate detail"},
        ],
    },

    # ── Workbook 7: Health and Safety ──────────────────────────────────────────
    {
        "reference": "AWIF 7.1",
        "name": "Health and safety in the workplace",
        "description": (
            "Worker is able to: meet their responsibilities in line with health and safety legislation; "
            "adhere to workplace policies and procedures for health and safety; follow processes for "
            "recording and reporting health and safety concerns or incidents."
        ),
        "keywords": [
            "Health and Safety at Work Act 1974", "HSWA", "health and safety legislation",
            "employer responsibilities", "worker responsibilities", "unsafe practices",
            "health and safety reporting",
        ],
        "sub_outcomes": [
            {"ref": "7.1a", "desc": "Knows key relevant health and safety legislation and what this means in practice"},
            {"ref": "7.1b", "desc": "Knows the responsibilities of employers, workers and others for health and safety"},
            {"ref": "7.1c", "desc": "Knows the importance of raising concerns about unsafe practices or working conditions"},
        ],
    },
    {
        "reference": "AWIF 7.2",
        "name": "Risk assessments for health and safety",
        "description": (
            "Worker is able to: comply with health and safety risk assessments for their workplace "
            "and follow procedures for reporting concerns or incidents."
        ),
        "keywords": [
            "risk assessment", "health and safety risk", "hazard identification", "risk control",
            "incident reporting", "RIDDOR", "near miss", "risk management",
        ],
        "sub_outcomes": [
            {"ref": "7.2a", "desc": "Knows what risk assessment means in relation to health and safety"},
            {"ref": "7.2b", "desc": "Knows the types of accidents, incidents, emergencies and hazards that may occur"},
            {"ref": "7.2c", "desc": "Knows responsibilities for carrying out, recording and following risk assessments"},
            {"ref": "7.2d", "desc": "Knows the difference between formal risk assessments and routine risk checks"},
        ],
    },
    {
        "reference": "AWIF 7.3",
        "name": "Fire safety",
        "description": (
            "Worker is able to: adhere to the fire procedures of their work setting, including evacuation procedures."
        ),
        "keywords": [
            "fire safety", "fire evacuation", "fire prevention", "fire legislation",
            "fire risk assessment", "evacuation plan", "fire exits", "fire extinguisher",
            "muster point", "Regulatory Reform (Fire Safety) Order",
        ],
        "sub_outcomes": [
            {"ref": "7.3a", "desc": "Knows key legislation relating to fire safety"},
            {"ref": "7.3b", "desc": "Knows the responsibilities of employers and workers for fire safety"},
            {"ref": "7.3c", "desc": "Knows practices that prevent fires from starting and spreading"},
            {"ref": "7.3d", "desc": "Knows the importance of knowing and following fire evacuation procedures"},
            {"ref": "7.3e", "desc": "Knows the importance of maintaining clear exit routes at all times"},
        ],
    },
    {
        "reference": "AWIF 7.4",
        "name": "Moving and handling / moving and positioning",
        "description": (
            "Worker is able to: undertake safe moving and positioning and/or moving and handling "
            "in accordance with their training and the context of their role."
        ),
        "keywords": [
            "moving and handling", "manual handling", "moving and positioning", "LOLER",
            "MHOR", "hoisting", "transfer technique", "safe handling", "ergonomics",
        ],
        "sub_outcomes": [
            {"ref": "7.4a", "desc": "Knows the meaning of 'moving and handling' and 'moving and positioning'"},
            {"ref": "7.4b", "desc": "Knows key legislation relating to moving and handling"},
            {"ref": "7.4c", "desc": "Knows the principles and techniques of moving and handling"},
            {"ref": "7.4d", "desc": "Knows the implications of poor practice in moving and handling"},
        ],
    },
    {
        "reference": "AWIF 7.5",
        "name": "Emergency first aid",
        "description": (
            "Worker has attended emergency first aid training suitable to their role and knows when it "
            "is appropriate to apply emergency first aid and when to seek medical help."
        ),
        "keywords": [
            "first aid", "emergency first aid", "basic life support", "BLS", "CPR",
            "AED", "choking", "medical emergency", "first aid at work",
        ],
        "sub_outcomes": [
            {"ref": "7.5a", "desc": "Has attended emergency first aid training appropriate to their role"},
            {"ref": "7.5b", "desc": "Knows when it is appropriate to apply emergency first aid and when medical help is needed"},
        ],
    },
    {
        "reference": "AWIF 7.6",
        "name": "Infection prevention and control",
        "description": (
            "Worker is able to: follow good hygiene practice; implement workplace infection prevention "
            "and control policies; follow correct hand washing technique."
        ),
        "keywords": [
            "infection prevention", "IPC", "infection control", "PPE", "personal protective equipment",
            "hand hygiene", "hand washing", "standard precautions", "MRSA", "C.diff",
            "isolation precautions", "environmental cleaning",
        ],
        "sub_outcomes": [
            {"ref": "7.6a", "desc": "Knows the difference between bacteria, viruses, fungi and parasites and how infections spread"},
            {"ref": "7.6b", "desc": "Knows factors that make infections more likely to occur"},
            {"ref": "7.6c", "desc": "Knows key legislation and standards related to infection prevention and control"},
            {"ref": "7.6d", "desc": "Knows the role and responsibilities of employers and workers for IPC"},
            {"ref": "7.6e", "desc": "Knows how to maintain a clean environment and good personal hygiene to prevent infection"},
            {"ref": "7.6f", "desc": "Knows hand washing technique and the use of PPE to prevent infection spread"},
        ],
    },
    {
        "reference": "AWIF 7.7",
        "name": "Food safety",
        "description": (
            "Worker is able to: follow workplace policies and procedures in relation to food safety."
        ),
        "keywords": [
            "food safety", "food hygiene", "food handling", "food storage", "food preparation",
            "food poisoning", "temperature control", "HACCP", "Food Standards Agency",
        ],
        "sub_outcomes": [
            {"ref": "7.7a", "desc": "Knows key legislation for food safety"},
            {"ref": "7.7b", "desc": "Knows the role and responsibilities of employers and workers for food safety"},
            {"ref": "7.7c", "desc": "Knows food safety hazards during preparation, serving, clearing and storing"},
            {"ref": "7.7d", "desc": "Knows safe storage, disposal and preparation of food and drink"},
        ],
    },
    {
        "reference": "AWIF 7.8",
        "name": "Hazardous substances (COSHH)",
        "description": (
            "Worker is able to: follow workplace policies and procedures for the storage, use and "
            "disposal of hazardous substances."
        ),
        "keywords": [
            "COSHH", "hazardous substances", "Control of Substances Hazardous to Health",
            "chemical safety", "cleaning products", "spillage", "SDS", "safe disposal",
        ],
        "sub_outcomes": [
            {"ref": "7.8a", "desc": "Knows what hazardous substances and COSHH mean"},
            {"ref": "7.8b", "desc": "Knows the types of hazardous substances that may be found in the workplace"},
            {"ref": "7.8c", "desc": "Knows safe practice for storing, using, dealing with spillages and disposing of hazardous substances"},
        ],
    },
    {
        "reference": "AWIF 7.9",
        "name": "Security in the work setting",
        "description": (
            "Worker is able to: adhere to arrangements that ensure safety of self, individuals and others "
            "in the work setting; follow policies for lone working, advising of whereabouts and access."
        ),
        "keywords": [
            "workplace security", "lone working", "access control", "visitor management",
            "personal safety", "security procedures", "door security", "identity checks",
        ],
        "sub_outcomes": [
            {"ref": "7.9a", "desc": "Knows potential risks to security in the work setting"},
            {"ref": "7.9b", "desc": "Knows safe practice to ensure security including lone working arrangements"},
        ],
    },
    {
        "reference": "AWIF 7.10",
        "name": "Managing stress in health and social care",
        "description": (
            "Worker is able to: use supervision to discuss their well-being with their line manager; "
            "recognise signs of stress and access support."
        ),
        "keywords": [
            "stress management", "worker well-being", "burnout", "compassion fatigue",
            "supervision and well-being", "resilience", "stress indicators", "support resources",
        ],
        "sub_outcomes": [
            {"ref": "7.10a", "desc": "Knows the common signs and indicators of stress"},
            {"ref": "7.10b", "desc": "Knows the circumstances that can trigger stress in health and social care"},
            {"ref": "7.10c", "desc": "Knows ways to manage stress and the importance of recognising stress and taking action"},
            {"ref": "7.10d", "desc": "Knows where to access additional support if experiencing stress"},
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
    """Seed Welsh standards: CIW (RSI(SPRI)(W)R 2017 regulations), AWIF (67 section-level entries), SCW Worker's Code.

    Migration-aware:
    - If old 7-question CIW entries exist → replace with real numbered regulations.
    - If old 7 AWIF workbook-level entries exist → replace with 67 granular section entries.
    - JSONB double-encoding is repaired on every startup.
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

        # ── AWIF + SCW: seed once (migrate from 7 workbook-level to 67 section-level) ────
        awif_count = await conn.fetchval(
            "SELECT COUNT(*) FROM standards_entries "
            "WHERE type='awif' AND jurisdiction='wales' AND is_system=TRUE"
        )
        scw_count = await conn.fetchval(
            "SELECT COUNT(*) FROM standards_entries "
            "WHERE type='scw' AND jurisdiction='wales' AND is_system=TRUE"
        )
        # Old format: 7 AWIF workbook entries. New format: 67 section entries.
        # Delete and re-seed if we have the old coarse-grained entries.
        if awif_count > 0 and awif_count < 50:
            logger.info(f"AWIF: found {awif_count} legacy workbook-level entries — migrating to granular section entries")
            await conn.execute(
                "DELETE FROM standards_entries WHERE type='awif' AND jurisdiction='wales' AND is_system=TRUE"
            )
            awif_count = 0
        if awif_count >= 50 and scw_count > 0:
            # Repair double-encoded JSONB if needed (happens when TEXT column stores json.dumps'd string)
            sample = await conn.fetchrow(
                "SELECT sub_outcomes FROM standards_entries WHERE type='awif' AND jurisdiction='wales' AND is_system=TRUE LIMIT 1"
            )
            if sample and isinstance(sample["sub_outcomes"], str):
                logger.info("AWIF Wales: detected double-encoded JSONB — repairing…")
                rows = await conn.fetch(
                    "SELECT id, keywords, sub_outcomes, key_questions FROM standards_entries WHERE type='awif' AND jurisdiction='wales' AND is_system=TRUE"
                )
                for row in rows:
                    kw = json.loads(row["keywords"]) if isinstance(row["keywords"], str) else (row["keywords"] or [])
                    so = json.loads(row["sub_outcomes"]) if isinstance(row["sub_outcomes"], str) else (row["sub_outcomes"] or [])
                    if isinstance(so, str):  # triple-encoded: decode once more
                        so = json.loads(so)
                    kq = json.loads(row["key_questions"]) if isinstance(row["key_questions"], str) else (row["key_questions"] or [])
                    await conn.execute(
                        "UPDATE standards_entries SET keywords=$1, sub_outcomes=$2, key_questions=$3 WHERE id=$4",
                        kw, so, kq, row["id"],
                    )
                logger.info("AWIF Wales JSONB repair complete")
            logger.info(f"AWIF/SCW standards already seeded ({awif_count} AWIF + {scw_count} SCW entries) — skipping")
            return

        now = datetime.now(timezone.utc).isoformat()
        awif_scw_entries = []

        if awif_count == 0:
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
            if scw_count == 0:
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



# ── Northern Ireland — RQIA Domiciliary Minimum Standards (DHSSPS 2021) ────────

NI_DOM_STANDARDS = [
    # Theme: Quality Care
    {
        "reference": "Dom Std 1",
        "name": "Service users' involvement",
        "key_questions": ["Quality Care"],
        "description": (
            "The views of service users and their carers/representatives shape the quality of services "
            "provided by the agency. Agencies must actively seek feedback, involve service users in "
            "assessments and reviews, and act on their views to improve care delivery."
        ),
        "keywords": [
            "service user involvement", "feedback", "views", "carers", "representatives",
            "participation", "person-centred", "involvement in reviews", "satisfaction survey",
            "individual needs", "quality improvement",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 2",
        "name": "Information for service users",
        "key_questions": ["Quality Care"],
        "description": (
            "Prospective service users are provided with information about the services provided by "
            "the agency before care commences. Information must be clear, accessible and in "
            "appropriate formats. Service users must understand their rights, the complaints procedure "
            "and how to access RQIA."
        ),
        "keywords": [
            "information provision", "accessible information", "prospective service users",
            "service guide", "rights", "complaints procedure", "RQIA contact", "formats",
            "language needs", "statement of purpose",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 3",
        "name": "Referral arrangements",
        "key_questions": ["Quality Care"],
        "description": (
            "Referral arrangements ensure the service user's identified needs can be met by the agency. "
            "The agency must carry out an assessment of needs before agreeing to provide care, "
            "and must not accept a referral if needs cannot be safely met."
        ),
        "keywords": [
            "referral", "needs assessment", "suitability", "care needs", "risk assessment",
            "pre-admission assessment", "eligibility", "care and support needs", "commissioning",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 4",
        "name": "Agreement between service user and agency",
        "key_questions": ["Quality Care"],
        "description": (
            "Each service user has a written individual service agreement before care commences. "
            "The agreement must cover the services to be provided, fees, notice periods, and "
            "the complaints procedure. Service users must be supported to understand and consent to "
            "the agreement."
        ),
        "keywords": [
            "service agreement", "written agreement", "consent", "fees", "notice period",
            "services provided", "contract", "terms and conditions", "person-centred",
            "individual agreement",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 5",
        "name": "Recording and reporting",
        "key_questions": ["Quality Care"],
        "description": (
            "All activities undertaken in relation to the service user's care plan are recorded and "
            "relevant information communicated to appropriate people. Records must be accurate, "
            "up-to-date, and securely maintained. Significant incidents, changes in condition, "
            "and near misses must be reported promptly."
        ),
        "keywords": [
            "recording", "reporting", "care records", "documentation", "accurate records",
            "incident reporting", "near misses", "significant events", "communication",
            "information sharing", "data protection", "GDPR", "confidentiality",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 6",
        "name": "Contributing to service user reviews",
        "key_questions": ["Quality Care"],
        "description": (
            "The agency contributes to the review of the service user's care plan. Reviews must "
            "happen at agreed intervals or when needs change. The agency must involve the service "
            "user, carers and other professionals, and update care plans to reflect changing needs."
        ),
        "keywords": [
            "care plan review", "review process", "changing needs", "multidisciplinary",
            "involvement", "regular review", "care planning", "outcomes", "personal outcomes",
            "risk review",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 7",
        "name": "Management of medicines",
        "key_questions": ["Quality Care"],
        "description": (
            "The agency has arrangements to ensure that care workers manage medicines safely and "
            "securely. This includes written policies, trained staff, secure storage, accurate "
            "recording (MAR charts), and clear protocols for self-administration, assistance, "
            "and safe disposal. Medicine errors must be reported and investigated."
        ),
        "keywords": [
            "medicines management", "medication", "MAR chart", "controlled drugs",
            "safe storage", "administration", "medicine errors", "self-administration",
            "trained staff", "medication policy", "disposal", "prescriptions",
        ],
        "service_type": "domiciliary",
    },
    # Theme: Management of the Domiciliary Care Agency
    {
        "reference": "Dom Std 8",
        "name": "Management and control of operations",
        "key_questions": ["Management of the Agency"],
        "description": (
            "Management systems and arrangements are in place that support and promote the delivery "
            "of quality care services. The registered person and manager must ensure the agency is "
            "conducted with sufficient care, competence and skill. Clear governance, oversight "
            "systems, and quality assurance must be demonstrable."
        ),
        "keywords": [
            "management systems", "governance", "quality assurance", "oversight", "competence",
            "registered person", "registered manager", "operational control", "quality review",
            "service improvement", "audit", "accountability",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 9",
        "name": "Policies and procedures",
        "key_questions": ["Management of the Agency"],
        "description": (
            "There are comprehensive, up-to-date policies and procedures in place that direct the "
            "quality of care and services. All policies must be reviewed at least every three years, "
            "and staff must have access to and be familiar with relevant policies including "
            "safeguarding, medicines, and complaints."
        ),
        "keywords": [
            "policies and procedures", "policy review", "safeguarding policy", "medicines policy",
            "complaints policy", "health and safety policy", "lone working policy",
            "staff access", "knowledge of policies", "review cycle",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 10",
        "name": "Management of records",
        "key_questions": ["Management of the Agency"],
        "description": (
            "Clear, documented systems are in place for the management of records in accordance with "
            "legislative requirements. Records must be accurate, legible, stored securely and "
            "retained for required periods. Service users and their representatives must be able to "
            "access their own records. Electronic records must be password-protected."
        ),
        "keywords": [
            "records management", "record keeping", "accuracy", "legibility", "secure storage",
            "data retention", "data protection", "GDPR", "access to records",
            "electronic records", "password protection", "confidentiality",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 11",
        "name": "Recruitment of staff",
        "key_questions": ["Management of the Agency"],
        "description": (
            "Staff are recruited and employed in accordance with relevant statutory employment "
            "legislation. This includes AccessNI criminal record checks, satisfactory references, "
            "verification of qualifications, NISCC registration checks, and health assessments. "
            "Agencies must not employ persons who are unsuitable to work with vulnerable adults."
        ),
        "keywords": [
            "recruitment", "AccessNI", "criminal record check", "DBS", "references",
            "qualifications", "NISCC registration", "employment checks", "fitness to work",
            "vetting", "safer recruitment", "employment legislation",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 12",
        "name": "Staff training and development",
        "key_questions": ["Management of the Agency"],
        "description": (
            "Staff are trained for their roles and responsibilities. All care workers must complete "
            "the NISCC Induction Programme within agreed timescales. Mandatory training must include "
            "safeguarding, manual handling, medicines management, infection control and fire safety. "
            "A training needs analysis must be conducted and training records maintained."
        ),
        "keywords": [
            "training", "NISCC induction", "induction programme", "mandatory training",
            "safeguarding training", "manual handling", "medicines training", "infection control",
            "training records", "training needs analysis", "CPD", "professional development",
            "skills development", "competency",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 13",
        "name": "Staff supervision and appraisal",
        "key_questions": ["Management of the Agency"],
        "description": (
            "Staff are supervised and their performance appraised to promote the delivery of quality "
            "care and services. Supervision must be regular, documented and support staff development. "
            "Annual appraisals must identify training needs and personal development goals. "
            "Supervision records must be maintained securely."
        ),
        "keywords": [
            "supervision", "appraisal", "performance management", "staff development",
            "regular supervision", "documented supervision", "supervision records",
            "annual appraisal", "training needs", "personal development", "reflective practice",
            "line management",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 14",
        "name": "Protection of vulnerable adults and safeguarding children",
        "key_questions": ["Management of the Agency"],
        "description": (
            "Service users are protected from abuse. Agencies must have a safeguarding policy, "
            "a designated safeguarding lead, and ensure all staff receive safeguarding training. "
            "All allegations and concerns must be reported immediately to the designated person and "
            "the appropriate Trust. Agencies must follow Northern Ireland adult safeguarding procedures "
            "and work collaboratively with statutory agencies."
        ),
        "keywords": [
            "safeguarding", "abuse", "neglect", "vulnerable adults", "safeguarding lead",
            "safeguarding policy", "reporting concerns", "allegations", "HSC Trust",
            "adult safeguarding procedures", "NIAPSA", "safeguarding training", "whistleblowing",
            "financial abuse", "exploitation", "restraint",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 15",
        "name": "Complaints",
        "key_questions": ["Management of the Agency"],
        "description": (
            "All complaints are taken seriously and dealt with promptly and effectively. "
            "The agency must have a clear complaints procedure accessible to service users and carers. "
            "Complaints must be investigated, and the complainant informed of the outcome and any "
            "action taken within 28 days. Complaints must be analysed to identify service improvements."
        ),
        "keywords": [
            "complaints", "complaints procedure", "investigation", "resolution",
            "28-day response", "complainant rights", "complaints analysis", "service improvement",
            "RQIA complaints", "advocate", "NIPSO",
        ],
        "service_type": "domiciliary",
    },
    {
        "reference": "Dom Std 16",
        "name": "Safe and healthy working practices",
        "key_questions": ["Management of the Agency"],
        "description": (
            "The agency has systems that ensure safe and healthy working practices for staff and "
            "service users. This includes risk assessments for care workers visiting service users' "
            "homes, lone working policies, manual handling procedures, infection prevention and "
            "control, and appropriate PPE provision. Staff wellbeing must be actively promoted."
        ),
        "keywords": [
            "health and safety", "risk assessment", "lone working", "manual handling",
            "infection prevention", "infection control", "PPE", "personal protective equipment",
            "staff wellbeing", "COSHH", "home environment risk", "first aid",
        ],
        "service_type": "domiciliary",
    },
]


# ── Northern Ireland — RQIA Residential Care Home Regulations 2005 ──────────────

NI_RES_REGULATIONS = [
    {
        "reference": "Reg 3",
        "name": "Statement of purpose",
        "key_questions": ["Conduct of the Home"],
        "description": (
            "The registered person must compile a written statement of purpose detailing the home's "
            "aims and objectives, the facilities and services provided, the philosophy of care, "
            "resident numbers and needs, admission criteria, and complaints procedure. "
            "A copy must be supplied to RQIA and made available to residents and their representatives."
        ),
        "keywords": [
            "statement of purpose", "aims and objectives", "philosophy of care", "RQIA",
            "facilities", "services", "admission criteria", "care home information",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 10",
        "name": "Registered person: general requirements",
        "key_questions": ["Management"],
        "description": (
            "The registered provider and manager must conduct the home with sufficient care, "
            "competence and skill, having regard to the size of the home, its statement of purpose, "
            "and the needs of residents. Both must undertake appropriate training to fulfil their roles."
        ),
        "keywords": [
            "registered person", "registered manager", "registered provider", "competence",
            "care and skill", "management training", "accountable person",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 12",
        "name": "Requirements to ensure quality of care and other service provision",
        "key_questions": ["Conduct of the Home"],
        "description": (
            "Care and services must meet individual needs, reflect best practice and use appropriate "
            "aids and equipment. Food and drink must be adequate, nutritious, varied and suitable "
            "for residents' specific dietary, cultural, and clinical needs. Equipment must be "
            "suitable, maintained, and used correctly."
        ),
        "keywords": [
            "quality of care", "individual needs", "best practice", "food and drink",
            "nutrition", "hydration", "equipment", "aids", "dietary needs",
            "cultural needs", "special diets",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 13",
        "name": "Health and welfare of residents",
        "key_questions": ["Conduct of the Home"],
        "description": (
            "The home must promote residents' health and welfare, enabling them to make decisions "
            "about their own care. Residents' wishes and feelings must be ascertained and taken into "
            "account. Medicine management must be safe and well-documented. The home must respect "
            "residents' privacy, dignity, and diversity, and staff must maintain professional relationships."
        ),
        "keywords": [
            "health and welfare", "informed decisions", "wishes and feelings", "dignity",
            "privacy", "medicines management", "medication records", "infection prevention",
            "diversity", "respect", "professional relationships", "person-centred care",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 14",
        "name": "Further requirements as to health and welfare",
        "key_questions": ["Conduct of the Home"],
        "description": (
            "Residents must have arrangements to register with a GP and receive necessary professional "
            "services. The home must be free from hazards, with safe systems for moving and handling. "
            "Measures to prevent harm and abuse are mandatory. Restraint may only be used in "
            "exceptional circumstances and must be recorded. Training in first aid is required."
        ),
        "keywords": [
            "GP registration", "professional services", "hazard-free environment", "risk management",
            "moving and handling", "manual handling", "safeguarding", "abuse prevention",
            "restraint", "first aid training", "falls prevention",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 15",
        "name": "Assessment of residents",
        "key_questions": ["Conduct of the Home"],
        "description": (
            "Before admitting a resident, their needs must be assessed by a qualified person. "
            "The registered person must confirm in writing that the home is suitable for the "
            "resident's needs. Assessments must consider physical, mental, cultural and social "
            "needs. Assessments must be reviewed at least annually or when needs change."
        ),
        "keywords": [
            "needs assessment", "pre-admission assessment", "suitability", "holistic assessment",
            "physical needs", "mental needs", "cultural needs", "social needs", "annual review",
            "assessment review", "qualified assessor",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 16",
        "name": "Residents' care plan",
        "key_questions": ["Conduct of the Home"],
        "description": (
            "A written care plan must be prepared in consultation with the resident or their "
            "representative, outlining how their needs will be met. The care plan must be available "
            "to the resident, kept under regular review, and revised to reflect changing needs. "
            "Residents must be notified of any revisions."
        ),
        "keywords": [
            "care plan", "person-centred care plan", "care planning", "consultation",
            "resident involvement", "care plan review", "changing needs", "individual outcomes",
            "representative", "care plan update",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 17",
        "name": "Review of quality of care and other service provision",
        "key_questions": ["Management"],
        "description": (
            "Systems must be maintained for reviewing the quality of care and services at least "
            "annually. A report of the review must be supplied to RQIA and made available to "
            "residents. The review must include consultation with residents and their representatives "
            "and analyse incidents, complaints, and areas for improvement."
        ),
        "keywords": [
            "quality review", "annual review", "quality assurance", "RQIA report", "resident feedback",
            "incident analysis", "complaints analysis", "quality improvement", "governance",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 19",
        "name": "Records",
        "key_questions": ["Management"],
        "description": (
            "Comprehensive records must be maintained for each resident and for the home overall, "
            "as specified in Schedules 3 and 4 of the Regulations. Records must be up-to-date, "
            "available to authorised persons, and retained for at least 6 years. Service users must "
            "be informed about how to access their personal records."
        ),
        "keywords": [
            "record keeping", "resident records", "care records", "incident records",
            "staff records", "duty rosters", "training records", "complaint records",
            "6-year retention", "data protection", "GDPR", "access to records",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 20",
        "name": "Staffing",
        "key_questions": ["Conduct of the Home"],
        "description": (
            "The home must have suitably qualified, competent and experienced staff in appropriate "
            "numbers at all times. Staff must receive appraisal and training, be supported to maintain "
            "professional registration (NISCC), and enabled to gain further qualifications. "
            "Adequate supervision must be provided and job descriptions given to all staff."
        ),
        "keywords": [
            "staffing levels", "qualified staff", "competent staff", "staff appraisal",
            "training", "NISCC registration", "professional registration", "qualifications",
            "supervision", "job description", "staffing policy", "care workers",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 21",
        "name": "Fitness of workers",
        "key_questions": ["Conduct of the Home"],
        "description": (
            "Persons employed must be fit to work in the home, with satisfactory background "
            "information including AccessNI criminal record checks, authentic references, "
            "and verification of qualifications and experience. This applies both to directly "
            "employed staff and those employed by third parties working at the home."
        ),
        "keywords": [
            "fitness to work", "AccessNI", "criminal record check", "references", "qualifications",
            "employment vetting", "safer recruitment", "integrity", "character check",
            "third party staff", "agency staff",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 23",
        "name": "Staff views as to conduct of the home",
        "key_questions": ["Management"],
        "description": (
            "Arrangements must be made to enable staff to inform the registered person, RQIA, and "
            "local HSC Trust, in confidence, of their views on matters affecting the care, safety "
            "or welfare of residents. This underpins a culture of openness, transparency and "
            "psychological safety."
        ),
        "keywords": [
            "staff views", "whistleblowing", "raising concerns", "confidential reporting",
            "RQIA", "HSC Trust", "psychological safety", "transparency", "openness",
            "duty of candour", "freedom to speak up",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 24",
        "name": "Complaints",
        "key_questions": ["Management"],
        "description": (
            "A complaints procedure must be established appropriate to residents' needs. "
            "Complaints must be fully investigated, and the complainant informed of the process, "
            "outcome, and any action taken within 28 days. A written copy of the procedure "
            "must be given to residents, including RQIA contact details."
        ),
        "keywords": [
            "complaints procedure", "investigation", "28-day response", "complainant",
            "outcome", "RQIA complaints", "resident rights", "summary of complaints",
            "complaints analysis",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 25",
        "name": "Guidance for social care workers, nurses and health care professionals",
        "key_questions": ["Conduct of the Home"],
        "description": (
            "Relevant Codes of Practice — including the NISCC Code of Practice for Social Care "
            "Workers — must be made available to staff. Staff must be supported to meet the "
            "standards set out in the Codes, and appropriate action must be taken when standards "
            "are not met, including referral to NISCC where required."
        ),
        "keywords": [
            "NISCC code of practice", "code of practice", "professional standards",
            "NMC code", "NISCC referral", "fitness to practise", "professional conduct",
            "standards of practice",
        ],
        "service_type": "residential",
    },
    {
        "reference": "Reg 30",
        "name": "Notification of death, illness and other events",
        "key_questions": ["Management"],
        "description": (
            "The registered person must notify RQIA without delay of resident deaths (including "
            "circumstances), outbreaks of serious infectious disease, serious injuries, "
            "events adversely affecting care, theft, burglary, accidents, or allegations of "
            "misconduct. Oral notifications must be confirmed in writing within 3 working days."
        ),
        "keywords": [
            "notification", "RQIA notification", "death", "serious incident", "serious injury",
            "infectious disease", "outbreak", "misconduct allegation", "reporting requirements",
            "incident reporting", "3 working days",
        ],
        "service_type": "residential",
    },
]


# ── Northern Ireland — NISCC Code of Practice for Social Care Workers ──────────
# Both domiciliary and residential — service_type=None means shared/applicable to all NI.

NISCC_CODE_STANDARDS = [
    # Standards of Conduct (6 standards)
    {
        "reference": "NISCC Conduct 1",
        "name": "Protect the rights and promote the interests of service users",
        "description": (
            "Social care workers must treat each person as an individual, treat them with respect "
            "and compassion, empower service users and carers to communicate their views, support "
            "their right to control their lives and make informed choices, gain appropriate consent, "
            "and respect and maintain the dignity and privacy of service users."
        ),
        "keywords": [
            "rights", "interests", "dignity", "respect", "compassion", "consent",
            "informed choices", "privacy", "individual needs", "equality", "diversity",
            "protected characteristics", "person-centred", "empowerment",
        ],
        "sub_outcomes": [
            {"ref": "C1.1", "desc": "Treat each person as an individual"},
            {"ref": "C1.2", "desc": "Treat people with consideration, respect and compassion"},
            {"ref": "C1.3", "desc": "Empower service users and carers to communicate their views, needs and preferences"},
            {"ref": "C1.4", "desc": "Support service users' right to control their lives and make informed choices"},
            {"ref": "C1.5", "desc": "Gain consent appropriately before providing care or services"},
            {"ref": "C1.6", "desc": "Respect and maintain the dignity and privacy of service users"},
            {"ref": "C1.7", "desc": "Treat service users and carers fairly and promote equal opportunities"},
        ],
        "service_type": None,
    },
    {
        "reference": "NISCC Conduct 2",
        "name": "Establish and maintain the trust and confidence of service users",
        "description": (
            "Workers must be honest and trustworthy, communicate openly and accurately, "
            "respect confidential information and data protection obligations, be reliable and "
            "dependable, honour work commitments, declare conflicts of interest, and refuse "
            "inappropriate gifts, loans or financial transactions."
        ),
        "keywords": [
            "trust", "honesty", "trustworthy", "confidentiality", "data protection",
            "reliability", "conflicts of interest", "gifts policy", "financial boundaries",
            "communication", "transparent", "straightforward",
        ],
        "sub_outcomes": [
            {"ref": "C2.1", "desc": "Be honest and trustworthy"},
            {"ref": "C2.2", "desc": "Communicate in an appropriate, open, accurate and straightforward way"},
            {"ref": "C2.3", "desc": "Respect confidential information and explain confidentiality policies"},
            {"ref": "C2.4", "desc": "Hold, use and store records in line with procedures and data protection"},
            {"ref": "C2.5", "desc": "Be reliable and dependable, honour work commitments"},
            {"ref": "C2.6", "desc": "Declare conflicts of interest and adhere to policies on accepting gifts"},
        ],
        "service_type": None,
    },
    {
        "reference": "NISCC Conduct 3",
        "name": "Promote autonomy of service users while safeguarding from harm",
        "description": (
            "Workers must promote service users' independence, use processes to manage dangerous or "
            "abusive behaviour, follow procedures to keep themselves and others safe, report "
            "resource difficulties, inform employers of unsafe practice without delay, comply with "
            "health and safety policies, and use power responsibly."
        ),
        "keywords": [
            "autonomy", "independence", "safeguarding", "dangerous behaviour", "risk management",
            "lone working", "health and safety", "unsafe practice", "power and control",
            "duty of care", "reporting concerns",
        ],
        "sub_outcomes": [
            {"ref": "C3.1", "desc": "Promote service users' independence and empower them to exercise their rights"},
            {"ref": "C3.2", "desc": "Use processes to assess, respond to and manage dangerous, abusive or exploitative behaviour"},
            {"ref": "C3.3", "desc": "Report resource or operational difficulties that hinder safe care delivery"},
            {"ref": "C3.4", "desc": "Inform employer or authority of unsafe practice by colleagues without delay"},
        ],
        "service_type": None,
    },
    {
        "reference": "NISCC Conduct 4",
        "name": "Respect service users' rights while protecting them from harm",
        "description": (
            "Workers must recognise service users' right to take positive risks and help manage "
            "them. They must follow risk assessment policies to assess harm risks, take steps to "
            "minimise risks, and inform relevant colleagues and agencies of risk assessment outcomes."
        ),
        "keywords": [
            "positive risk", "risk assessment", "right to take risks", "harm minimisation",
            "risk management plan", "informed risk", "risk enablement", "safety",
        ],
        "sub_outcomes": [
            {"ref": "C4.1", "desc": "Recognise service users' right to take positive risks and help manage them"},
            {"ref": "C4.2", "desc": "Follow risk assessment policies to assess harm risks"},
            {"ref": "C4.3", "desc": "Take steps to minimise risks of harm and inform relevant colleagues of outcomes"},
        ],
        "service_type": None,
    },
    {
        "reference": "NISCC Conduct 5",
        "name": "Uphold public trust and confidence in social care services",
        "description": (
            "Workers must not abuse, neglect or harm service users, carers or colleagues; "
            "not exploit service users or abuse trust; not form inappropriate personal relationships; "
            "not discriminate unlawfully; not put themselves or others at unnecessary risk; "
            "not behave in a way that questions their suitability; and use social media appropriately."
        ),
        "keywords": [
            "public trust", "abuse", "neglect", "exploitation", "professional boundaries",
            "personal relationships", "discrimination", "social media", "professional conduct",
            "suitability", "professional behaviour",
        ],
        "sub_outcomes": [
            {"ref": "C5.1", "desc": "Not abuse, neglect or harm service users, carers or colleagues"},
            {"ref": "C5.2", "desc": "Not exploit service users, carers or colleagues"},
            {"ref": "C5.3", "desc": "Not form inappropriate personal relationships with service users"},
            {"ref": "C5.4", "desc": "Not discriminate unlawfully or unjustifiably"},
            {"ref": "C5.5", "desc": "Not use social media/electronic communication contravening professional boundaries or standards"},
        ],
        "service_type": None,
    },
    {
        "reference": "NISCC Conduct 6",
        "name": "Be accountable for the quality of your work",
        "description": (
            "Workers must meet relevant standards of practice, work lawfully, safely and effectively, "
            "take personal accountability for their actions, maintain clear and accurate records, "
            "inform employers of personal difficulties, co-operate with investigations, work "
            "collaboratively with colleagues, and commit to ongoing training and professional development."
        ),
        "keywords": [
            "accountability", "quality of work", "accurate records", "professional development",
            "training", "CPD", "openness", "duty of candour", "co-operation", "fitness to practise",
            "NISCC registration", "supervision", "appraisal", "reflective practice",
        ],
        "sub_outcomes": [
            {"ref": "C6.1", "desc": "Meet relevant standards of practice and work lawfully, safely and effectively"},
            {"ref": "C6.2", "desc": "Take personal and collective responsibility for quality improvement and safety"},
            {"ref": "C6.3", "desc": "Maintain clear and accurate records"},
            {"ref": "C6.4", "desc": "Be open and honest if things go wrong — duty of candour"},
            {"ref": "C6.5", "desc": "Co-operate with investigations and work openly with colleagues"},
            {"ref": "C6.6", "desc": "Undertake relevant training and learning to improve knowledge and skills"},
        ],
        "service_type": None,
    },
    # Standards of Practice (6 standards)
    {
        "reference": "NISCC Practice 1",
        "name": "Understand main duties and responsibilities of your role",
        "description": (
            "Workers must know the aims, objectives and values of their service, access and adhere "
            "to policies and procedures, know their responsibilities to service users (including "
            "duty of care), prioritise and manage their work effectively, work in partnership, "
            "and keep accurate records. Includes reporting of adverse events and responding to complaints."
        ),
        "keywords": [
            "duties", "responsibilities", "role understanding", "policies", "procedures",
            "duty of care", "work management", "prioritisation", "partnership", "records",
            "adverse events", "incident reporting", "complaints response", "job description",
        ],
        "sub_outcomes": [
            {"ref": "P1.1", "desc": "Know the aims, objectives and values of the service in which you work"},
            {"ref": "P1.2", "desc": "Access and adhere to policies, procedures and agreed ways of working"},
            {"ref": "P1.3", "desc": "Know your main responsibilities to those service users and carers you support including duty of care"},
            {"ref": "P1.4", "desc": "Prioritise and manage your work effectively"},
            {"ref": "P1.5", "desc": "Keep records that are up to date, complete, accurate and legible"},
            {"ref": "P1.6", "desc": "Report adverse events, incidents, errors and near misses"},
            {"ref": "P1.7", "desc": "Respond appropriately to comments and complaints"},
        ],
        "service_type": None,
    },
    {
        "reference": "NISCC Practice 2",
        "name": "Be able to communicate effectively",
        "description": (
            "Workers must develop effective relationships with service users and carers, establish "
            "communication needs and preferences, use appropriate communication methods, "
            "recognise and address barriers to communication, work effectively in teams, "
            "and share information with other staff and agencies appropriately."
        ),
        "keywords": [
            "communication", "effective communication", "communication needs", "language needs",
            "barriers to communication", "non-verbal communication", "teamwork",
            "information sharing", "confidentiality", "relationship building", "listening",
        ],
        "sub_outcomes": [
            {"ref": "P2.1", "desc": "Develop effective relationships with service users and carers"},
            {"ref": "P2.2", "desc": "Establish service user communication and language needs, wishes and preferences"},
            {"ref": "P2.3", "desc": "Use a range of communication methods and styles to meet individual needs"},
            {"ref": "P2.4", "desc": "Recognise and address barriers to effective communication"},
            {"ref": "P2.5", "desc": "Work effectively as part of a team, sharing relevant information"},
            {"ref": "P2.6", "desc": "Share information with other staff and agencies in a timely manner, adhering to confidentiality"},
        ],
        "service_type": None,
    },
    {
        "reference": "NISCC Practice 3",
        "name": "Deliver person-centred care and support which is safe and effective",
        "description": (
            "Workers must promote person-centred values, deliver care in line with assessed needs "
            "and preferences, undertake risk assessments in partnership, contribute to planning and "
            "review, support service users' daily living, promote independence, enable informed "
            "choices and support social network development."
        ),
        "keywords": [
            "person-centred care", "care delivery", "assessed needs", "risk assessment",
            "care planning", "independence", "daily living", "informed choices", "goal setting",
            "care plan review", "skills development", "social inclusion", "wellbeing",
        ],
        "sub_outcomes": [
            {"ref": "P3.1", "desc": "Promote and apply person-centred values in day to day work"},
            {"ref": "P3.2", "desc": "Deliver care in line with assessed needs and service user preferences"},
            {"ref": "P3.3", "desc": "Understand risk assessments appropriate to your role, in partnership"},
            {"ref": "P3.4", "desc": "Contribute to care and support plans, risk management plans and their review"},
            {"ref": "P3.5", "desc": "Support service users to retain, regain and develop skills for daily living"},
            {"ref": "P3.6", "desc": "Enable service users and carers to make informed choices and participate in decision-making"},
        ],
        "service_type": None,
    },
    {
        "reference": "NISCC Practice 4",
        "name": "Support the safeguarding of individuals",
        "description": (
            "Workers must know the main types of abuse and factors making individuals vulnerable, "
            "know Northern Ireland regional safeguarding policies and procedures, know their own "
            "role in safeguarding, recognise signs and symptoms of harm or abuse, take appropriate "
            "actions, and report suspected or actual harm to the designated person."
        ),
        "keywords": [
            "safeguarding", "types of abuse", "vulnerability", "NIAPSA", "safeguarding procedures",
            "regional safeguarding", "signs of abuse", "harm", "designated safeguarding lead",
            "reporting abuse", "safeguarding training", "recognition of abuse",
        ],
        "sub_outcomes": [
            {"ref": "P4.1", "desc": "Know the main types of abuse and factors making a service user or carer vulnerable to harm or abuse"},
            {"ref": "P4.2", "desc": "Know the regional policies and procedures relating to safeguarding in Northern Ireland"},
            {"ref": "P4.3", "desc": "Know your own role and responsibilities in relation to safeguarding"},
            {"ref": "P4.4", "desc": "Recognise the signs and symptoms of harm or abuse when present"},
            {"ref": "P4.5", "desc": "Take appropriate actions to safeguard a service user if harm is suspected or disclosed"},
            {"ref": "P4.6", "desc": "Report suspected or actual harm or abuse to the designated person in accordance with employer safeguarding policies"},
        ],
        "service_type": None,
    },
    {
        "reference": "NISCC Practice 5",
        "name": "Maintain health and safety at work",
        "description": (
            "Workers must apply the organisation's health and safety policies and procedures, "
            "apply procedures for medication and health care tasks, apply moving and handling "
            "procedures, know what they can and cannot do regarding health and safety, and "
            "recognise and minimise risks to their personal safety and wellbeing."
        ),
        "keywords": [
            "health and safety", "medication procedures", "moving and handling", "manual handling",
            "lone working", "personal safety", "risk minimisation", "infection control",
            "PPE", "COSHH", "fire safety", "safe working practices",
        ],
        "sub_outcomes": [
            {"ref": "P5.1", "desc": "Apply the organisation's policies and procedures in relation to health and safety"},
            {"ref": "P5.2", "desc": "Apply the organisation's policies and procedures for medication and health care tasks"},
            {"ref": "P5.3", "desc": "Apply the organisation's policies and procedures in relation to moving and handling"},
            {"ref": "P5.4", "desc": "Know what you can and cannot do relating to general health and safety commensurate with your role"},
            {"ref": "P5.5", "desc": "Recognise the risks to your personal safety and wellbeing and take steps to minimise these"},
        ],
        "service_type": None,
    },
    {
        "reference": "NISCC Practice 6",
        "name": "Develop yourself as a social care worker",
        "description": (
            "Workers must be aware of relevant standards, evaluate their own knowledge and "
            "performance against standards, reflect on practice to continuously improve, "
            "use sources of support including supervision and appraisal, seek and use feedback, "
            "and record progress in relation to personal development."
        ),
        "keywords": [
            "professional development", "self-evaluation", "reflection", "reflective practice",
            "supervision", "appraisal", "feedback", "CPD", "personal development",
            "NISCC registration", "standards awareness", "improvement", "learning",
        ],
        "sub_outcomes": [
            {"ref": "P6.1", "desc": "Be aware of the relevant standards that relate to your work role"},
            {"ref": "P6.2", "desc": "Evaluate your knowledge, performance and understanding against relevant standards"},
            {"ref": "P6.3", "desc": "Reflect on your practice to continuously improve the quality of service provided"},
            {"ref": "P6.4", "desc": "Use sources of support for your personal development, including supervision, appraisals and training"},
            {"ref": "P6.5", "desc": "Seek and use feedback, including that from service users and carers"},
            {"ref": "P6.6", "desc": "Record progress in relation to your personal development"},
        ],
        "service_type": None,
    },
]


# ── Northern Ireland — NISCC Induction Programme (NI Care Certificate equivalent) ──

NISCC_INDUCTION_MODULES = [
    {
        "reference": "NI Induction 1",
        "name": "Understand the main duties and responsibilities of your own role",
        "description": (
            "The worker understands their role within the organisation, its aims and values, "
            "and how to access relevant policies and procedures. Covers duty of care, "
            "managing and prioritising work, partnership working, literacy and communication skills, "
            "record keeping, reporting adverse events, and responding to complaints."
        ),
        "keywords": [
            "role understanding", "duties", "responsibilities", "policies and procedures",
            "duty of care", "aims and values", "prioritisation", "partnership working",
            "record keeping", "incident reporting", "near misses", "complaints response",
        ],
        "sub_outcomes": [
            {"ref": "NI1.1", "desc": "Knowing the aims, objectives and values of the service in which you work"},
            {"ref": "NI1.2", "desc": "Accessing full and up to date details of policies, procedures and agreed ways of working"},
            {"ref": "NI1.3", "desc": "Knowing your main responsibilities to those service users and carers you support including duty of care"},
            {"ref": "NI1.4", "desc": "Prioritising and managing your work effectively"},
            {"ref": "NI1.5", "desc": "Working in partnership with key people, advocates and others significant to service users"},
            {"ref": "NI1.6", "desc": "Possessing the required literacy, numeracy and communication skills necessary to carry out your role"},
            {"ref": "NI1.7", "desc": "Keeping records that are up to date, complete, accurate and legible"},
            {"ref": "NI1.8", "desc": "Reporting adverse events, incidents, errors and near misses affecting the quality of care"},
            {"ref": "NI1.9", "desc": "Responding appropriately to comments and complaints in accordance with your organisation's complaints procedure"},
        ],
        "service_type": None,
    },
    {
        "reference": "NI Induction 2",
        "name": "Be able to communicate effectively",
        "description": (
            "The worker develops effective communication skills for working with service users, "
            "carers and colleagues. Covers building relationships, establishing communication "
            "needs and preferences, using different communication methods, overcoming barriers, "
            "and sharing information appropriately within confidentiality frameworks."
        ),
        "keywords": [
            "communication", "effective communication", "communication needs", "language preferences",
            "communication methods", "barriers to communication", "team communication",
            "information sharing", "confidentiality", "relationship building",
        ],
        "sub_outcomes": [
            {"ref": "NI2.1", "desc": "Developing effective relationships with service users and carers"},
            {"ref": "NI2.2", "desc": "Establishing the service user's communication and language needs, wishes and preferences"},
            {"ref": "NI2.3", "desc": "Using the range of communication methods and styles to meet the service user's needs"},
            {"ref": "NI2.4", "desc": "Recognising and addressing barriers to effective communication"},
            {"ref": "NI2.5", "desc": "Working effectively as part of a team, sharing relevant information"},
            {"ref": "NI2.6", "desc": "Sharing information with other health and social care staff and agencies in a timely manner, adhering to confidentiality"},
        ],
        "service_type": None,
    },
    {
        "reference": "NI Induction 3",
        "name": "Deliver person-centred care and support which is safe and effective",
        "description": (
            "The worker delivers care that centres on the individual, promotes independence, "
            "and is grounded in assessed needs and preferences. Covers person-centred values, "
            "risk assessment in partnership, care planning and review, supporting daily living, "
            "enabling informed choices, and social network development."
        ),
        "keywords": [
            "person-centred care", "care delivery", "assessed needs", "risk assessment",
            "care planning", "independence", "daily living", "informed choices",
            "care plan review", "skills development", "social inclusion", "goals",
        ],
        "sub_outcomes": [
            {"ref": "NI3.1", "desc": "Promoting and applying person-centred values in day to day work"},
            {"ref": "NI3.2", "desc": "Delivering care in line with assessed needs and service user and carer preferences"},
            {"ref": "NI3.3", "desc": "Understanding risk assessments appropriate to your role, in partnership with service users"},
            {"ref": "NI3.4", "desc": "Contributing to the risk assessment process by identifying and reporting risks"},
            {"ref": "NI3.5", "desc": "Contributing to the planning process with service users and carers"},
            {"ref": "NI3.6", "desc": "Working in partnership with service users to enable them to achieve their goals and be independent"},
            {"ref": "NI3.7", "desc": "Developing care and support plans and/or risk management plans where appropriate"},
            {"ref": "NI3.8", "desc": "Contributing to the implementation of care or support plans and risk management plans"},
            {"ref": "NI3.9", "desc": "Participating in the review of care or support plans and/or risk management plans"},
            {"ref": "NI3.10", "desc": "Supporting service users with their daily living"},
            {"ref": "NI3.11", "desc": "Supporting service users to retain, regain and develop skills to manage their daily living"},
            {"ref": "NI3.12", "desc": "Contributing to the physical and emotional well-being of service users and carers"},
            {"ref": "NI3.13", "desc": "Enabling service users and carers to make informed choices and participate in decision-making"},
            {"ref": "NI3.14", "desc": "Supporting service users to develop and maintain social networks and relationships"},
        ],
        "service_type": None,
    },
    {
        "reference": "NI Induction 4",
        "name": "Support the safeguarding of individuals",
        "description": (
            "The worker understands adult safeguarding in a Northern Ireland context, recognises "
            "abuse and vulnerability, knows NI regional safeguarding procedures, understands "
            "their specific role and responsibilities, and can take appropriate action when "
            "harm is suspected or disclosed."
        ),
        "keywords": [
            "safeguarding", "types of abuse", "vulnerability factors", "NIAPSA",
            "NI safeguarding procedures", "designated safeguarding lead", "recognition of abuse",
            "disclosure", "reporting", "safeguarding training", "adult at risk",
        ],
        "sub_outcomes": [
            {"ref": "NI4.1", "desc": "Knowing the main types of abuse and the factors that may make a service user or carer vulnerable"},
            {"ref": "NI4.2", "desc": "Knowing the regional policies and procedures relating to safeguarding in Northern Ireland"},
            {"ref": "NI4.3", "desc": "Knowing your own role and responsibilities in relation to safeguarding"},
            {"ref": "NI4.4", "desc": "Recognising the signs and symptoms of harm or abuse when present"},
            {"ref": "NI4.5", "desc": "Taking appropriate actions to safeguard a service user or carer if harm is suspected or disclosed"},
            {"ref": "NI4.6", "desc": "Reporting suspected or actual harm or abuse to the designated person in accordance with employer safeguarding policies"},
        ],
        "service_type": None,
    },
    {
        "reference": "NI Induction 5",
        "name": "Maintain health and safety at work",
        "description": (
            "The worker applies health and safety policies and procedures in their work setting. "
            "Covers organisational H&S policies, medication and healthcare task procedures, "
            "moving and handling, personal safety, and the boundaries of what they can safely "
            "do within their role and training."
        ),
        "keywords": [
            "health and safety", "medication procedures", "moving and handling", "manual handling",
            "lone working", "personal safety", "infection control", "PPE", "fire safety",
            "COSHH", "safe systems", "risk minimisation", "home environment",
        ],
        "sub_outcomes": [
            {"ref": "NI5.1", "desc": "Applying the organisation's policies and procedures in relation to health and safety"},
            {"ref": "NI5.2", "desc": "Applying the organisation's policies and procedures for medication and health care tasks"},
            {"ref": "NI5.3", "desc": "Applying the organisation's policies and procedures in relation to moving and handling"},
            {"ref": "NI5.4", "desc": "Knowing what you can and cannot do relating to general health and safety"},
            {"ref": "NI5.5", "desc": "Recognising the risks to your personal safety and wellbeing and taking steps to minimise them"},
        ],
        "service_type": None,
    },
    {
        "reference": "NI Induction 6",
        "name": "Develop yourself as a social care worker",
        "description": (
            "The worker commits to ongoing professional development. Covers awareness of "
            "NISCC standards, self-evaluation against those standards, reflective practice, "
            "using supervision and appraisal as development tools, seeking feedback from "
            "service users and colleagues, and recording personal development progress."
        ),
        "keywords": [
            "professional development", "NISCC standards", "self-evaluation", "reflection",
            "reflective practice", "supervision", "appraisal", "feedback", "CPD",
            "personal development plan", "improvement", "knowledge and skills",
        ],
        "sub_outcomes": [
            {"ref": "NI6.1", "desc": "Being aware of the relevant standards that relate to your work role"},
            {"ref": "NI6.2", "desc": "Evaluating your knowledge, performance and understanding against relevant standards"},
            {"ref": "NI6.3", "desc": "Reflecting on your practice to continuously improve the quality of service provided"},
            {"ref": "NI6.4", "desc": "Using sources of support for your personal development, including supervision, appraisals and training"},
            {"ref": "NI6.5", "desc": "Seeking and using feedback, including that from service users and carers"},
            {"ref": "NI6.6", "desc": "Recording progress in relation to your personal development"},
        ],
        "service_type": None,
    },
    {
        "reference": "NI Induction 7",
        "name": "Understand how the NISCC Standards of Conduct underpin all that you do",
        "description": (
            "The worker understands how the six NISCC Standards of Conduct provide the ethical "
            "foundation for all their practice. Covers protecting service user rights and interests, "
            "establishing trust, promoting autonomy while safeguarding, respecting rights while "
            "preventing harm, upholding public trust, and professional accountability."
        ),
        "keywords": [
            "NISCC standards", "standards of conduct", "ethical practice", "values",
            "rights and interests", "trust and confidence", "autonomy", "public trust",
            "accountability", "professional conduct", "code of practice",
        ],
        "sub_outcomes": [
            {"ref": "NI7.1", "desc": "Protect the rights and promote the interests and wellbeing of service users and carers"},
            {"ref": "NI7.2", "desc": "Strive to establish and maintain the trust and confidence of service users and carers"},
            {"ref": "NI7.3", "desc": "Promote the autonomy of service users while safeguarding them as far as possible from danger or harm"},
            {"ref": "NI7.4", "desc": "Respect the rights of service users while seeking to ensure their behaviour does not harm themselves or others"},
            {"ref": "NI7.5", "desc": "Uphold public trust and confidence in social care services"},
            {"ref": "NI7.6", "desc": "Be accountable for the quality of your work and take responsibility for improving your knowledge and skills"},
        ],
        "service_type": None,
    },
]


async def seed_northern_ireland_standards():
    """Seed Northern Ireland standards: RQIA Dom (16), RQIA Res (15), NISCC Code (12), NISCC Induction (7)."""
    async with database.with_admin() as conn:
        ni_count = await conn.fetchval(
            "SELECT COUNT(*) FROM standards_entries WHERE is_system=TRUE AND jurisdiction='northern_ireland'"
        )
        if ni_count and ni_count > 0:
            logger.info(f"Northern Ireland standards already seeded ({ni_count} entries) — skipping")
            return

        now = datetime.now(timezone.utc).isoformat()
        entries = []

        for std in NI_DOM_STANDARDS:
            entries.append({
                "id": str(uuid.uuid4()),
                "type": "rqia_dom",
                "reference": std["reference"],
                "name": std["name"],
                "description": std["description"],
                "keywords": std["keywords"],
                "sub_outcomes": [],
                "key_questions": std.get("key_questions", []),
                "quality_statement": False,
                "source": "RQIA — Domiciliary Care Agencies Minimum Standards (DHSSPS, August 2021)",
                "service_type": "domiciliary",
                "created_at": now,
            })

        for reg in NI_RES_REGULATIONS:
            entries.append({
                "id": str(uuid.uuid4()),
                "type": "rqia_res",
                "reference": reg["reference"],
                "name": reg["name"],
                "description": reg["description"],
                "keywords": reg["keywords"],
                "sub_outcomes": [],
                "key_questions": reg.get("key_questions", []),
                "quality_statement": False,
                "source": "RQIA — The Residential Care Homes Regulations (Northern Ireland) 2005",
                "service_type": "residential",
                "created_at": now,
            })

        for std in NISCC_CODE_STANDARDS:
            entries.append({
                "id": str(uuid.uuid4()),
                "type": "niscc_code",
                "reference": std["reference"],
                "name": std["name"],
                "description": std["description"],
                "keywords": std["keywords"],
                "sub_outcomes": std.get("sub_outcomes", []),
                "key_questions": [],
                "quality_statement": False,
                "source": "NISCC — Standards of Conduct and Practice for Social Care Workers (Northern Ireland Social Care Council)",
                "service_type": None,
                "created_at": now,
            })

        for mod in NISCC_INDUCTION_MODULES:
            entries.append({
                "id": str(uuid.uuid4()),
                "type": "niscc_induction",
                "reference": mod["reference"],
                "name": mod["name"],
                "description": mod["description"],
                "keywords": mod["keywords"],
                "sub_outcomes": mod.get("sub_outcomes", []),
                "key_questions": [],
                "quality_statement": False,
                "source": "NISCC — Induction Programme for Social Care Workers (Northern Ireland Social Care Council)",
                "service_type": None,
                "created_at": now,
            })

        await _insert_standards_entries(conn, entries, "northern_ireland")
        logger.info(
            f"Seeded {len(entries)} Northern Ireland standards entries "
            f"({len(NI_DOM_STANDARDS)} RQIA Dom, {len(NI_RES_REGULATIONS)} RQIA Res, "
            f"{len(NISCC_CODE_STANDARDS)} NISCC Code, {len(NISCC_INDUCTION_MODULES)} NISCC Induction)"
        )


_KNOWN_WEAK_PASSWORDS = {
    "SuperAdmin123!", "admin", "password", "admin123", "changeme",
    "password123", "letmein", "welcome1", "supervisor", "supervisor1",
}

async def seed_super_admin():
    """Create the super admin account (idempotent).
    SEC-001: Refuses to create a new super-admin with a known-weak password.
    Never aborts the whole app on this — a bootstrapping/config issue must not
    take down the entire backend (crash-looping here blocks ALL logins, not
    just super-admin). If the account already exists, emits a CRITICAL log
    but does not abort (avoids breaking a running production deployment on
    every restart).
    """
    from routers.auth import hash_password
    email = os.environ.get("SUPER_ADMIN_EMAIL", "superadmin@1two.one")
    password = os.environ.get("SUPER_ADMIN_PASSWORD", "SuperAdmin123!")

    is_weak = password in _KNOWN_WEAK_PASSWORDS or len(password) < 12

    async with database.with_admin() as conn:
        existing = await conn.fetchrow("SELECT id, role FROM users WHERE email = $1", email)
        if existing is None:
            # Refuse to seed a super-admin with a known-weak password, but do NOT
            # crash the process — that would take the entire app offline for every
            # user, not just block super-admin creation. Log critically and skip;
            # a real super-admin can be seeded later once a strong password is set.
            if is_weak:
                logger.critical(
                    "SUPER_ADMIN_PASSWORD is a known-weak or default value — "
                    "skipping super-admin seeding. Set a strong password "
                    "(>=12 chars, mixed case, numbers, symbols) in the "
                    "SUPER_ADMIN_PASSWORD environment variable and restart to "
                    "create the super-admin account."
                )
                return
            await conn.execute(
                """INSERT INTO users (id, email, password_hash, name, role, is_active, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                str(uuid.uuid4()), email, hash_password(password),
                "Super Admin", "super_admin", True,
                datetime.now(timezone.utc).isoformat(),
            )
            logger.info(f"Super admin seeded: {email}")
        else:
            # Account already exists — the env var is only used for initial creation,
            # so its value is irrelevant to the live password (which is the DB hash
            # set by the user). No warning needed.
            if existing["role"] != "super_admin":
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
        # Northern Ireland: service_type distinguishes residential vs domiciliary
        await conn.execute(
            "ALTER TABLE organisations ADD COLUMN IF NOT EXISTS service_type TEXT"
        )
        await conn.execute(
            "ALTER TABLE standards_entries ADD COLUMN IF NOT EXISTS service_type TEXT"
        )
    await seed_standards()
    await seed_welsh_standards()
    await seed_scotland_standards()
    await seed_northern_ireland_standards()
    await seed_super_admin()
    await seed_default_org()
