"""One-time data fixes: legacy naming + double-encoded JSONB array columns."""

VERSION = "007_data_cleanup"


async def up(conn):
    await conn.execute(
        "UPDATE meeting_types SET name = 'Supervision' WHERE name = 'Monthly Supervision'"
    )
    # Fix meetings where attendees/shared_with were stored as a JSON object
    # instead of an array (legacy data bug). Also un-stringify double-encoded
    # JSON strings (jsonb_typeof = 'string').
    await conn.execute("""
        UPDATE meetings
        SET attendees = CASE
            WHEN jsonb_typeof(attendees) = 'string' THEN (attendees #>> '{}')::jsonb
            WHEN attendees = '{}'::jsonb THEN '[]'::jsonb
            ELSE jsonb_build_array(attendees)
        END
        WHERE jsonb_typeof(attendees) IN ('object', 'string')
    """)
    await conn.execute("""
        UPDATE meetings
        SET shared_with = CASE
            WHEN jsonb_typeof(shared_with) = 'string' THEN (shared_with #>> '{}')::jsonb
            WHEN shared_with = '{}'::jsonb THEN '[]'::jsonb
            ELSE jsonb_build_array(shared_with)
        END
        WHERE shared_with IS NOT NULL
          AND jsonb_typeof(shared_with) IN ('object', 'string')
    """)
    # Fix other JSONB array columns that may also be double-encoded
    for col in ("pii_redactions", "recording_events", "paused_periods"):
        await conn.execute(f"""
            UPDATE meetings
            SET {col} = (({col}) #>> '{{}}')::jsonb
            WHERE jsonb_typeof({col}) = 'string'
        """)
    await conn.execute("""
        UPDATE meetings
        SET sign_off_record = (sign_off_record #>> '{}')::jsonb
        WHERE sign_off_record IS NOT NULL AND jsonb_typeof(sign_off_record) = 'string'
    """)
    await conn.execute("""
        UPDATE transcripts
        SET speaker_colors = (speaker_colors #>> '{}')::jsonb
        WHERE jsonb_typeof(speaker_colors) = 'string'
    """)
    await conn.execute("""
        UPDATE standards_entries
        SET
            keywords      = CASE WHEN jsonb_typeof(keywords)      = 'string' THEN (keywords      #>> '{}')::jsonb ELSE keywords      END,
            sub_outcomes  = CASE WHEN jsonb_typeof(sub_outcomes)  = 'string' THEN (sub_outcomes  #>> '{}')::jsonb ELSE sub_outcomes  END,
            key_questions = CASE WHEN jsonb_typeof(key_questions) = 'string' THEN (key_questions #>> '{}')::jsonb ELSE key_questions END
        WHERE jsonb_typeof(keywords)='string' OR jsonb_typeof(sub_outcomes)='string' OR jsonb_typeof(key_questions)='string'
    """)
    # Fix analyses JSONB columns (all may be double-encoded strings)
    await conn.execute("""
        UPDATE analyses
        SET
            cqc_mappings       = CASE WHEN jsonb_typeof(cqc_mappings)       = 'string' THEN (cqc_mappings       #>> '{}')::jsonb ELSE cqc_mappings       END,
            care_cert_mappings = CASE WHEN jsonb_typeof(care_cert_mappings) = 'string' THEN (care_cert_mappings #>> '{}')::jsonb ELSE care_cert_mappings END,
            custom_mappings    = CASE WHEN jsonb_typeof(custom_mappings)    = 'string' THEN (custom_mappings    #>> '{}')::jsonb ELSE custom_mappings    END,
            actions            = CASE WHEN jsonb_typeof(actions)            = 'string' THEN (actions            #>> '{}')::jsonb ELSE actions            END,
            risks              = CASE WHEN jsonb_typeof(risks)              = 'string' THEN (risks              #>> '{}')::jsonb ELSE risks              END,
            learning_needs     = CASE WHEN jsonb_typeof(learning_needs)     = 'string' THEN (learning_needs     #>> '{}')::jsonb ELSE learning_needs     END,
            achievements       = CASE WHEN jsonb_typeof(achievements)       = 'string' THEN (achievements       #>> '{}')::jsonb ELSE achievements       END
        WHERE
            jsonb_typeof(cqc_mappings)       = 'string'
         OR jsonb_typeof(care_cert_mappings) = 'string'
         OR jsonb_typeof(custom_mappings)    = 'string'
         OR jsonb_typeof(actions)            = 'string'
         OR jsonb_typeof(risks)              = 'string'
         OR jsonb_typeof(learning_needs)     = 'string'
         OR jsonb_typeof(achievements)       = 'string'
    """)
