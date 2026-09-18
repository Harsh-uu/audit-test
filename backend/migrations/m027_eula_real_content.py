"""Swaps the placeholder EULA (m026) for the finalised legal text the user
supplied. Updates the existing version=1 row IN PLACE (does not bump to a
new version) — the placeholder was never a real acceptance by anyone (all
existing accounts were auto-backfilled by m026, not a genuine "I Agree"
click), so there is no reason to re-gate those already-backfilled demo
accounts. Any new user created from now on will simply see this final text
on their first login.
"""

VERSION = "027_eula_real_content"

CONTENT = """END USER LICENSE AGREEMENT (EULA)
& TERMS OF SERVICE

Effective Date: August 2026
Provider: Itwo.one Ltd ("Licensor", "We", "Us", "Our")
Customer: The legal entity or organisation purchasing a subscription
("Customer", "Licensee", "You")

1. GRANT OF LICENSE & SUBSCRIPTION MODEL

1.1 Branch-Based Subscription
Subject to the terms of this Agreement and payment of applicable fees,
Licensor grants Customer a non-exclusive, non-transferable, revocable license
to access and use the Itwo.one ambient supervision platform ("Software").

1.2 Organisational Licensing
This Agreement is executed at the organisation level. Subscriptions are
licensed on a per-branch, per-setting, or per-location basis as specified in
Customer's Order Form or account dashboard. Use is restricted to authorised
employees and managers operating within registered locations.

1.3 Authorised Users
Customer remains fully responsible for all activity occurring under its user
accounts, branch settings, and administrative credentials.

2. AUDIO RECORDING, STATUTORY NOTICES & CONSENT OBLIGATIONS

2.1 Mandatory Notice Display
The Software displays an explicit pre-recording notice prior to session capture
stating: "This meeting is being recorded in line with our recording policy and
requirement to gather evidence of compliance."

2.2 Prohibition of Covert Recordings
Covert or secret recordings are strictly prohibited. Customer explicitly agrees
and warrants that ambient audio capture will only take place with the full
knowledge of all meeting participants. Because the Itwo.one workflow requires
dual electronic sign-off from both the supervisor and supervisee/attendee,
unacknowledged or covert recordings cannot be validated or processed into
final compliance records.

2.3 Statutory Data Protection Responsibility
Customer acts as the Data Controller under UK GDPR for all audio captured
during supervisions and care assessments. Customer warrants that it maintains
appropriate organisational recording policies, privacy notices, and statutory
legal bases (or explicit consents where required) before initiating any recording
session via Itwo.one.

3. PROHIBITED USES & INTELLECTUAL PROPERTY HARDENING

3.1 Reverse-Engineering & Prompt Protection
Customer shall not, and shall not permit any third party to:
• Reverse engineer, decompile, disassemble, or attempt to derive the
underlying source code, database schemas, Row-Level Security (RLS)
policies, or system architecture of the Software.
• Extract, capture, "jailbreak", or reverse-engineer the AI system prompts,
system instructions (_PROMPT_INJECTION_GUARD), or regulatory
reasoning schemas utilised by Itwo.one.
• Use the Software outside the scope of adult social care, education
(including schools and colleges), staff supervision, care assessment, and
regulatory compliance logging.
• Bypass, disable, or tamper with security controls, rate-limiting
parameters, or multi-tenant database isolation boundaries.

4. PROPRIETARY RIGHTS & DATA OWNERSHIP

4.1 Customer Data Ownership
As between Licensor and Customer, Customer retains 100% ownership of all
raw audio inputs, sanitised text transcripts, generated CQC/regulatory
evidence cards, action logs, and exportable supervision reports ("Customer
Content").

4.2 Licensor Intellectual Property
Licensor retains exclusive ownership of all right, title, and interest in and to the
Software, brand assets, proprietary algorithms, database architecture, prompt
templates, and software interfaces.

4.3 No AI Model Training
Licensor guarantees that Customer Content, transcripts, and personal health
data will never be used to train, retrain, or improve public or commercial AI
foundation models.

5. SERVICE LEVELS, MAINTENANCE & WARRANTIES

5.1 Service Provision ("As-Is")
Unless Customer has negotiated and executed a bespoke Service Level
Agreement (SLA) Order Form with Licensor, the Software is provided on an
"AS-IS" and "AS-AVAILABLE" basis.

5.2 Standard Support
Standard subscriptions include best-effort technical email support during
normal UK business hours (09:00-17:00 BST/GMT, Monday-Friday, excluding
public holidays).

5.3 Enterprise SLAs
Custom uptime guarantees, priority response windows, and dedicated account
management are available under separate enterprise addenda.

6. DATA RETENTION, TERMINATION & CANCELLATION EXPORTS

6.1 Automated Transient Audio Purge & Draft Retention
• Raw audio files uploaded to Itwo.one are held in transient encrypted
storage solely for transcription and dual sign-off validation.
• Raw audio files are automatically and permanently hard-deleted upon
dual electronic sign-off by the supervisor and supervisee, or strictly
within 30 days of initial upload, whichever occurs first.
• The expiration or deletion of raw audio files after 30 days shall not affect
or delete pending draft transcripts, action logs, or unconfirmed
compliance evidence cards. If a supervision session remains in draft
status past 30 days, the sanitised text transcript remains accessible to
authorised users to complete dual sign-off, while the underlying raw
audio is unrecoverably purged.

6.2 Offboarding & Data Export Obligation
Upon subscription cancellation, non-renewal, or termination of this Agreement,
all data exports and report downloads must be completed by Customer PRIOR
to the effective cancellation date.

6.3 Post-Cancellation Hard Erasure
Immediately following the effective date of subscription cancellation or
non-payment termination, Customer's tenant database container, user
accounts, and stored supervision records will be queued for permanent,
unrecoverable hard deletion from UK-based cloud infrastructure (London /
europe-west2). Licensor assumes no liability for Customer Content that was
not exported prior to cancellation.

7. LIMITATION OF LIABILITY

7.1 Cap on Liability
To the maximum extent permitted by English law, Licensor's total aggregate
liability arising out of or related to this Agreement shall be strictly limited to the
total subscription fees paid by Customer to Licensor for the branch/setting in
question during the 12 months immediately preceding the event giving rise to
liability.

7.2 Regulatory Compliance
Itwo.one is an administrative support tool designed to map supervision
evidence against regulatory frameworks (CQC, CIW, Care Inspectorate, RQIA,
Ofsted). Customer remains solely responsible for ensuring its operational care
delivery and educational provision comply with statutory standards.

8. INDEMNIFICATION & GENERAL LEGAL PROVISIONS

8.1 Customer Indemnification
Customer agrees to defend, indemnify, and hold harmless Licensor, its officers,
directors, and employees from and against any third-party claims, liabilities,
damages, losses, or regulatory fines (including ICO penalties) arising out of or
related to:
• Customer's breach of Section 2 (Audio Recording, Statutory Notices &
Consent Obligations), including any claim stemming from alleged covert,
unacknowledged, or unlawful audio capture.
• Customer's processing of Special Category Data without a valid lawful
basis under UK GDPR.

8.2 Force Majeure
Neither party shall be liable for any failure or delay in performance under this
Agreement (except for payment obligations) resulting from causes beyond its
reasonable control, including but not limited to acts of God, widespread
internet or telecommunication outages, major cloud infrastructure failures,
cyber-attacks, or changes in statutory law.

8.3 Severability
If any provision of this Agreement is found by a court of competent jurisdiction
to be invalid, illegal, or unenforceable, that provision shall be limited or
eliminated to the minimum extent necessary, and the remaining provisions of
this Agreement shall remain in full force and effect.

8.4 Entire Agreement
This Agreement (together with any applicable Order Form, Schedule, or DPA)
constitutes the entire agreement between Customer and Licensor regarding the
Software and supersedes all prior oral or written agreements, understandings,
or representations.

8.5 Governing Law & Jurisdiction
This Agreement and any non-contractual obligations arising out of or in
connection with it shall be governed by and construed in accordance with the
laws of England and Wales. The courts of England and Wales shall have
exclusive jurisdiction to settle any dispute or claim.

9. SCHEDULE 1: DATA PROCESSING AGREEMENT (UK GDPR ARTICLE 28)

9.1 Controller & Processor Roles
The parties acknowledge that for the purposes of the UK Data Protection
Legislation (including the UK GDPR and Data Protection Act 2018), the
Customer is the Data Controller and Licensor is the Data Processor in respect
of any Personal Data and Special Category Data processed via the Software
("Customer Personal Data").

9.2 Scope & Instructions
Licensor shall process Customer Personal Data solely on documented
instructions from the Customer (including as set out in this Agreement) and
exclusively for the purpose of providing ambient supervision transcription,
compliance evidence mapping, and platform administration.

9.3 Data Security & Confidentiality
Licensor shall implement appropriate technical and organisational measures to
ensure a level of security appropriate to the risk—including encryption in transit
(TLS 1.3) and at rest (AES-256), multi-tenant isolation (Row-Level Security),
and zero-retention policies for AI model training. Licensor shall ensure that
persons authorised to process Customer Personal Data have committed
themselves to confidentiality.

9.4 Sub-processors
Customer grants general authorisation to Licensor to engage third-party
sub-processors (including cloud infrastructure providers, API-based
transcription engines, and LLM inference providers) for the performance of the
Service. Licensor shall maintain an up-to-date list of sub-processors and
impose data protection obligations no less protective than those set out in this
Section.

9.5 Data Subject Rights & Incident Notification
Licensor shall assist Customer by appropriate technical measures to enable
Customer to respond to requests from Data Subjects. Licensor shall notify
Customer without undue delay (and in any event within 48 hours) upon
becoming aware of a confirmed Personal Data Breach affecting Customer
Personal Data.

9.6 Data Return & Erasure
Upon termination of this Agreement, Licensor shall hard-delete all Customer
Personal Data in accordance with Section 6.3, unless retention is required by
applicable English law.

10. FEES, BILLING & SUBSCRIPTION TERMS

10.1 Automated Monthly Processing
All subscription fees are billed strictly on a monthly recurring basis in advance,
as specified at supervision2.co.uk/#pricing or within your account dashboard.
Payment must be processed automatically via Stripe using a valid credit card,
debit card, or Direct Debit mandate.

10.2 Strict Access Conditional on Payment
Access to and continuous use of the Software is strictly conditional upon
receipt of cleared subscription fees. If a monthly payment fails or cannot be
processed by Stripe on the renewal date:
• Platform access will be suspended immediately.
• Your account will enter a 14-day grace period for billing retries.
• Continued non-payment following the 14-day grace period will result in
immediate account termination and permanent hard erasure in
accordance with Section 6.3.

10.3 Price Changes
We reserve the right to modify subscription pricing. Existing customers will
receive a minimum of 30 days' advance written notice via email before any
monthly price adjustments take effect.

10.4 Taxes & Non-Refundability
All listed fees are exclusive of Value Added Tax (VAT) and applicable statutory
taxes, which shall be calculated and added at checkout via Stripe. All monthly
subscription payments are non-refundable."""


async def up(conn):
    await conn.execute("UPDATE eula_versions SET content = $1 WHERE version = 1", CONTENT)
