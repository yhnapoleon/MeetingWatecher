import copy
import hashlib
import json
from datetime import datetime, timezone


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(value):
    return hashlib.sha256(dumps(value).encode('utf-8')).hexdigest()


def instant(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError('Timestamp requires timezone')
    return dt.astimezone(timezone.utc).isoformat()


def normalize(raw, actor, roster=None):
    m = copy.deepcopy(raw)
    m['tenant'] = raw.get('tenant', 'local')
    m['source_key'] = raw.get('case_id', raw['meeting_id'])
    m['version'] = digest(raw)
    m['series'] = raw.get('series', raw['meeting_id'])
    m['started_at'] = instant(raw['started_at']) if raw.get('started_at') else None
    if raw.get('started_at') and not raw.get('meeting_date'):
        # The supplied offset defines the calendar date; UTC normalization can cross midnight.
        m['meeting_date'] = datetime.fromisoformat(raw['started_at']).date().isoformat()
    m['audience'] = raw.get('audience', [actor])
    m['writers'] = raw.get('writers', [actor])
    if actor not in m['audience']:
        raise PermissionError('Meeting source is not readable by actor')
    participant_roster = {p['person_ref']:p.get('speaker_name',p['speaker'])
                          for p in raw.get('participants', []) if p.get('person_ref')}
    m['roster'] = {**(roster or {}), **participant_roster, **raw.get('roster', {})}
    people = {p['speaker']:p for p in raw.get('participants', [])}
    seen = set()
    for s in m['segments']:
        if not isinstance(s['text'], str) or not s['id'] or s['id'] in seen:
            raise ValueError('Invalid or duplicate segment')
        seen.add(s['id'])
        p = people.get(s.get('speaker'), {})
        ref = s.get('person_ref') or raw.get('speaker_map', {}).get(s.get('speaker')) or p.get('person_ref')
        s['person_ref'] = ref
        s['speaker_name'] = s.get('speaker_name') or m['roster'].get(ref) or p.get('speaker_name') or s.get('speaker')
        if ref:
            m['roster'][ref] = s['speaker_name']
    # Only explicit synthetic/platform mappings are executable accounts.
    m['account_map'] = raw.get('account_map', {v:v for v in raw.get('speaker_map', {}).values()})
    return m
