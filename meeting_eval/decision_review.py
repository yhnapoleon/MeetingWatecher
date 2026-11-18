"""Ground decision topics in dialogue before publishing them."""
from pathlib import Path

from .stage_runner import run_stage

PROMPTS = Path(__file__).resolve().parents[1] / 'prompts'


def text_field(row, key):
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Missing decision review text: ' + key)
    return value.strip()


def numbers(value, allowed, *, empty=False):
    if (not isinstance(value, list) or (not empty and not value)
            or any(type(n) is not int or n not in allowed for n in value)):
        raise ValueError('Invalid decision review evidence or target')
    return list(dict.fromkeys(value))


class DecisionReview:
    def __init__(self, client, folder, settings):
        self.client = client
        self.folder = folder
        self.settings = settings
        self.prompts = {stage: (PROMPTS / (stage + '-v1.txt')).read_text(encoding='utf8')
                        for stage in ('decision_verify', 'decision_scan', 'decision_merge', 'decision_reconcile',
                                      'decision_close', 'decision_history')}

    def call(self, stage, payload, check):
        settings = self.settings
        if stage in ('decision_reconcile','decision_merge','decision_close') and self.client.model.startswith('deepseek'):
            settings = dict(settings, thinking='enabled', reasoning_effort='high', max_tokens=16384)
        prompt = self.prompts[stage]
        if stage == 'decision_reconcile' and payload.get('history'):
            prompt += '\n' + self.prompts['decision_history']
        return run_stage(self.client, prompt, payload, stage, check, self.folder,
                         settings, require_case_id=False)

    def scan(self, transcript):
        topics = []
        for start in range(0, len(transcript), 160):
            window = transcript[max(0, start-6):start+160]
            allowed = {row[0] for row in window}

            def check(raw):
                if not isinstance(raw, dict) or not isinstance(raw.get('topics'), list):
                    raise ValueError('Expected decision topics')
                if any(not isinstance(row, dict) for row in raw['topics']):
                    raise ValueError('Expected topic objects')
                return [dict(topic=text_field(row, 'topic'), refs=numbers(row.get('refs'), allowed))
                        for row in raw['topics']]

            topics.extend(self.call('decision_scan', {'turns': window}, check))
        return topics

    def verify(self, transcript, topics, history):
        findings = self.findings(transcript, topics, history)
        return [dict(attribute=r['attribute'],statement=r['statement'],supersedes=r['supersedes'],
                     refs=sorted(set(r['refs']+r['adopted']+r['later'])))
                for r in findings if r['state']=='effective']

    def findings(self, transcript, topics, history):
        if not topics:
            return []
        allowed = {row[0] for row in transcript}
        history_ids = {item['id']:item['attribute'] for item in history}
        targets = {str(i):topic for i, topic in enumerate(topics, 1)}

        def check(raw):
            if not isinstance(raw, dict) or set(raw) != set(targets):
                raise ValueError('Decision review must address every topic')
            claims = []
            for key in targets:
                findings = raw[key]
                if isinstance(findings,dict):
                    findings = [findings]
                if not isinstance(findings, list):
                    raise ValueError('Expected findings array')
                for row in findings:
                    if not isinstance(row, dict):
                        raise ValueError('Invalid finding')
                    state = row.get('state')
                    if state not in ('effective','open','reopened','withdrawn','superseded','unsupported'):
                        raise ValueError('Invalid issue state')
                    refs = numbers(row.get('refs'), allowed)
                    adopted = numbers(row.get('adopted'), allowed, empty=state!='effective')
                    later = numbers(row.get('later'), allowed, empty=state not in ('reopened','withdrawn','superseded'))
                    if later and max(later) < min(refs):
                        raise ValueError('Later evidence precedes issue')
                    reason = text_field(row, 'reason')
                    attribute = text_field(row, 'attribute') if state=='effective' else targets[key]['topic']
                    prior = row.get('supersedes')
                    if prior is not None and (not isinstance(prior,str) or history_ids.get(prior)!=attribute):
                        raise ValueError('Invalid decision replacement')
                    claims.append(dict(topic=int(key),state=state,attribute=attribute,
                                       statement=text_field(row,'statement') if state=='effective' else row.get('statement',''),
                                       supersedes=prior,refs=refs,adopted=adopted,later=later,reason=reason))
            return claims

        return self.call('decision_verify', dict(turns=transcript, topics=targets, history=history,
                         result_format='issue_history_v1'), check)

    def merge(self, claims, drafts=()):
        if len(claims)<2:
            return claims

        def check(raw):
            groups = raw.get('groups') if isinstance(raw,dict) else None
            if not isinstance(groups,list):
                raise ValueError('Expected merge groups')
            used = set()
            output = []
            for group in groups:
                ids = numbers(group, range(1,len(claims)+1))
                if len(ids)!=len(group) or used.intersection(ids):
                    raise ValueError('Decision assigned to multiple groups')
                used.update(ids)
                representative = claims[ids[0]-1]
                if any(claims[i-1].get(field) != representative.get(field)
                       for i in ids for field in ('supersedes','reaffirms')):
                    raise ValueError('Cannot merge separate history replacements')
                evidence = sorted({n for i in ids for n in claims[i-1]['refs']})
                output.append({**representative, 'refs':evidence})
            if len(used)!=len(claims):
                raise ValueError('Merge must account for every claim')
            replacements = raw.get('complete_lists',{})
            if not isinstance(replacements,dict):
                raise ValueError('Expected complete_lists object')
            for key,index in replacements.items():
                if key not in {str(g[0]) for g in groups if len(g)>1}:
                    raise ValueError('List replacement requires a merged group')
                draft = drafts[numbers([index],range(1,len(drafts)+1))[0]-1]
                target = output[next(i for i,g in enumerate(groups) if str(g[0])==key)]
                if target['supersedes']!=draft['supersedes'] or target.get('reaffirms'):
                    raise ValueError('History mismatch in list')
                target.update(statement=draft['statement'],attribute=draft['topic'])
            return output

        return self.call('decision_merge', {'claims':{str(i):c for i,c in enumerate(claims,1)},
                         'draft_lists':{str(i):c for i,c in enumerate(drafts,1)}}, check)

    def closing_status(self, transcript, claims, findings):
        def nearby(refs):
            positions = {p for n in refs for p in range(n-3,n+5)}
            return [t for t in transcript if t[0] in positions]
        cases = {}
        for i,claim in enumerate(claims):
            # Keep an explicit temporal check when the final claim relies on earlier evidence.
            later = {n for f in findings if f['topic']==claim['topic'] for n in f['later']
                     if n>claim['anchor']}
            if later:
                cases[str(i)] = dict(statement=claim['statement'],early=nearby(claim['refs']),later=nearby(later))
        if not cases:
            return claims
        def check(raw):
            states = raw.get('states') if isinstance(raw,dict) else None
            if not isinstance(states,dict) or set(states)!=set(cases) or any(
                    s not in ('stands','open','changed') for s in states.values()):
                raise ValueError('Closing verdict required for every case')
            return states
        statuses = self.call('decision_close',{'cases':cases},check)
        return [c for i,c in enumerate(claims) if statuses.get(str(i),'stands')=='stands']

    def reconcile(self, transcript, topics, draft, independent, history):
        if not topics:
            return []
        turns = {i:text for i, _, text in transcript}
        prior = {r['id']:r['attribute'] for r in history}
        reopened = {}
        for finding in independent:
            if finding['state'] in ('open','reopened','withdrawn','superseded') and finding['later']:
                key = finding['topic']
                reopened[key] = max(reopened.get(key,0),max(finding['later']))
        def check(raw):
            if not isinstance(raw, dict) or not isinstance(raw.get('decisions'), list):
                raise ValueError('Expected decisions array')
            result = []
            for row in raw['decisions']:
                if not isinstance(row, dict) or row.get('basis') not in ('communicated_rule','newly_adopted'):
                    raise ValueError('Invalid decision basis')
                numbers([row.get('topic')], range(1,len(topics)+1))
                refs = numbers(row.get('refs'), turns)
                anchor = numbers([row.get('anchor')], refs)[0]
                if anchor <= reopened.get(row['topic'],0):
                    raise ValueError('Topic reopened later. Omit it unless adopted after turn '+str(reopened[row['topic']]))
                if text_field(row,'quote') not in turns[anchor]:
                    raise ValueError('Anchor quote must be an exact substring of its cited turn')
                attr = text_field(row,'attribute')
                old = row.get('supersedes')
                if old is not None and (not isinstance(old,str) or prior.get(old)!=attr):
                    raise ValueError('Invalid decision replacement')
                same = row.get('reaffirms')
                if same is not None and (old is not None or not isinstance(same,str) or prior.get(same)!=attr):
                    raise ValueError('Invalid decision reaffirmation')
                result.append(dict(attribute=attr, statement=text_field(row,'statement'),
                                   refs=refs, supersedes=old,topic=row['topic'],anchor=anchor,
                                   **({'reaffirms':same} if same else {})))
            return result
        return self.call('decision_reconcile',dict(turns=transcript,
            topics={str(i):t for i,t in enumerate(topics,1)},draft=draft,
            independent=independent,history=history,result_format='claim_with_issue_and_anchor'),check)

    def review(self, meeting, proposals, history):
        transcript, topics = review_input(meeting, proposals)
        independent = self.findings(transcript, topics, history)
        draft = [{**t,'statement':p['statement'],'supersedes':p['supersedes']}
                 for t,p in zip(topics,proposals)]
        topics += self.scan(transcript)
        confirmed = self.reconcile(transcript, topics, draft, independent, history)
        claims = self.merge(self.closing_status(transcript, confirmed, independent),draft)
        return project_claims(meeting, claims)


def review_input(meeting, proposals):
    segments = meeting['segments']
    index = {s['id']:i for i,s in enumerate(segments,1)}
    transcript = [[i,s.get('speaker_name') or s.get('speaker'),s['text']]
                  for i,s in enumerate(segments,1)]
    topics = [dict(topic=row['attribute'],refs=[index[e] for e in row['evidence_ids']])
              for row in proposals]
    return transcript, topics


def project_claims(meeting, claims):
    return [dict(attribute=c['attribute'], statement=c['statement'], supersedes=c['supersedes'],
                 evidence_ids=[meeting['segments'][i-1]['id'] for i in c['refs']],
                 **({'reaffirms':c['reaffirms']} if c.get('reaffirms') else {})) for c in claims]



