"""Bounded source windows, durable acceptance, and one content-only split retry."""
import copy

from .inputs import digest
from .model_client import ModelResponseError
from .stage_runner import atomic_json

MAX_BYTES=6000
MAX_SEGMENTS=128
MAX_SPLIT_DEPTH=1


def plan_ranges(segments,max_bytes=MAX_BYTES,max_segments=MAX_SEGMENTS):
    if max_bytes<1 or max_segments<1:raise ValueError('Positive tracking window limits required')
    ranges=[];start=0;size=0
    for i,segment in enumerate(segments):
        amount=len(segment['text'].encode('utf8'))
        if i>start and (size+amount>max_bytes or i-start>=max_segments):
            ranges.append((start,i));start=i;size=0
        size+=amount
    if start<len(segments):ranges.append((start,len(segments)))
    return ranges


def split_at(segments,start,end):
    sizes=[len(s['text'].encode('utf8')) for s in segments[start:end]]
    total=sum(sizes);prefix=0;choices=[]
    for offset,size in enumerate(sizes[:-1],1):
        prefix+=size;choices.append((abs(total-2*prefix),abs(offset-(end-start)/2),start+offset))
    return min(choices)[2]


def track_checkpoints(pipeline,meeting,folder,trace,resume=False):
    from .extract import model_input
    segments=meeting['segments'];ranges=plan_ranges(segments)
    state=dict(version=1,input_hash=digest(model_input(meeting)),total_segments=len(segments),
        planned_ranges=ranges,completed_segments=0,accepted_ranges=[],splits=[],status='running',
        pending_segment_ids=[s['id'] for s in segments],last_ledger=None,blocked=None)
    trace['tracking']=state
    ledger=None

    def save():
        state['last_ledger']=copy.deepcopy(ledger)
        state['pending_segment_ids']=[s['id'] for s in segments[state['completed_segments']:]]
        atomic_json(folder/'tracking-state.json',state)

    def window(start,end,depth):
        nonlocal ledger
        prefix={**meeting,'segments':segments[:end]}
        payload=dict(meeting=model_input(prefix),previous=ledger,new_segment_ids=[s['id'] for s in segments[start:end]])
        state.update(status='running',blocked=dict(start=start,end=end));save()
        try:
            # run_stage persists accepted values and budgets. Replaying this
            # deterministic traversal performs no network for accepted nodes.
            value=pipeline._stage('track_context',payload,lambda x:x,folder,resume)
        except ModelResponseError as exc:
            recovery=getattr(exc,'recovery',{}) or {}
            content_failure=(recovery.get('status')=='recovery_required' and
                recovery.get('reason') in {'schema_invalid','syntax_invalid','budget_exhausted'})
            if content_failure and depth<MAX_SPLIT_DEPTH and end-start>1:
                cut=split_at(segments,start,end)
                state['splits'].append(dict(start=start,end=end,cut=cut,recovery=recovery));save()
                window(start,cut,depth+1);window(cut,end,depth+1)
                return
            state.update(status=recovery.get('status','failed'),blocked=dict(start=start,end=end,recovery=recovery))
            save();raise
        # The new value is already fully validated and atomically accepted.
        ledger=value
        state['completed_segments']=end;state['accepted_ranges'].append([start,end]);state['blocked']=None
        trace['checkpoints'].append(dict(through_segment=segments[end-1]['id'],ledger=copy.deepcopy(ledger)))
        save()

    save()
    for start,end in ranges:window(start,end,0)
    if ledger is None:ledger=dict(entities=[],links=[],threads=[])
    state.update(status='complete',blocked=None);save()
    return ledger
