import copy
import unittest

from test_task_events import sample


def ledger_fixture():
    meeting, event = sample()
    quote = {'segment_id':'s1','quote':'剪辑视频'}
    ledger = {'entities':[{'entity_id':'N1','label':'视频','mentions':[{'segment_id':'s1','quote':'视频'}]}],
              'links':[], 'threads':[{'thread_id':'T1','entity_ids':['N1'],'updates':[
                  {'after_segment':'s1','kind':'work','description':'剪辑视频','evidence':[quote]}]}]}
    record = dict(record_id='R1',thread_ids=['T1'],kind='work',content_basis='explicit',
                  description='剪辑视频',evidence=[quote],missing_fields=[],question=None,issuer_ref='alice')
    event['record_id']='R1'
    return meeting,event,ledger,record


class ContextStateTests(unittest.TestCase):
    def test_update_boundary_derived_from_latest_cited_evidence(self):
        from meeting_eval.context_state import canonical_ledger
        m,e,ledger,r=ledger_fixture()
        m['segments'].append(dict(id='s2',speaker='A',person_ref='alice',text='先不做。'))
        ledger['threads'][0]['updates'][0].update(after_segment='s1',kind='withdrawn',
            evidence=[dict(segment_id='s1',quote='剪辑视频'),dict(segment_id='s2',quote='先不做')])
        result=canonical_ledger(ledger,m,None)
        self.assertEqual(result['threads'][0]['updates'][0]['after_segment'],'s2')

    def test_unknown_and_future_mentions_rejected_without_guessing(self):
        from meeting_eval.context_state import canonical_ledger
        m,e,ledger,r=ledger_fixture()
        bad=copy.deepcopy(ledger);bad['entities'][0]['mentions'][0]['segment_id']='future'
        with self.assertRaises(ValueError):canonical_ledger(bad,m,None)
        bad=copy.deepcopy(ledger);bad['threads'][0]['entity_ids']=['unknown']
        with self.assertRaises(ValueError):canonical_ledger(bad,m,None)

    def test_history_preserved_and_later_correction_appended(self):
        from meeting_eval.context_state import canonical_ledger
        m,e,ledger,r=ledger_fixture()
        old=canonical_ledger(ledger,m,None)
        m['segments'].append(dict(id='s2',speaker='A',person_ref='alice',text='视频先不做。'))
        new=copy.deepcopy(old)
        new['threads'][0]['updates'].append(dict(after_segment='s2',kind='withdrawn',description='视频先不做',
                                                evidence=[dict(segment_id='s2',quote='视频先不做')]))
        state=canonical_ledger(new,m,old)
        self.assertEqual(state['threads'][0]['updates'][-1]['kind'],'withdrawn')
        new['threads'][0]['updates'][0]['description']='检查文稿'
        with self.assertRaisesRegex(ValueError,'history'):canonical_ledger(new,m,old)

    def test_related_entities_do_not_merge_threads(self):
        from meeting_eval.context_state import canonical_ledger
        m,e,ledger,r=ledger_fixture()
        ledger['entities'].append(dict(entity_id='N2',label='方案',mentions=[dict(segment_id='s1',quote='方案')]))
        ledger['links']=[dict(source='N1',target='N2',relation='related',evidence=[dict(segment_id='s1',quote='视频。我们可以细化方案')])]
        ledger['threads'].append(dict(thread_id='T2',entity_ids=['N2'],updates=[dict(after_segment='s1',kind='work',description='细化方案',evidence=[dict(segment_id='s1',quote='细化方案')])]))
        state=canonical_ledger(ledger,m,None)
        self.assertEqual(len(state['threads']),2)
        self.assertEqual(state['links'][0]['relation'],'related')

    def test_inferred_need_cannot_execute_even_with_accepted_event(self):
        from meeting_eval.context_state import reduce_context
        m,e,ledger,r=ledger_fixture()
        r.update(kind='implicit_need',content_basis='inferred',missing_fields=['work'],question='是否要研究视频使用问题？')
        r['check']=dict(verdict='supported',reason='作为推测保留',evidence=e['work']['evidence'])
        output=reduce_context([e],[],[r],m,{'tasks':[]})
        self.assertEqual(output['items'],[])
        self.assertEqual(output['updates'],[])
        self.assertEqual(output['review_records'][0]['category'],'implicit_need')

    def test_supported_missing_scope_still_requires_confirmation(self):
        from meeting_eval.context_state import reduce_context
        m,e,ledger,r=ledger_fixture()
        r.update(missing_fields=['scope'],question='请确认视频要剪辑哪些部分？')
        r['check']=dict(verdict='supported',reason='确实缺少范围',evidence=e['work']['evidence'])
        output=reduce_context([e],[],[r],m,{'tasks':[]})
        self.assertEqual(output['items'],[])
        self.assertEqual(output['review_records'][0]['missing_fields'],['scope'])

    def test_explicit_time_question_not_lost_but_absent_deadline_is_optional(self):
        from meeting_eval.context_state import reduce_context
        m,e,ledger,r=ledger_fixture()
        r['check']=dict(verdict='supported',reason='没有期限也可以执行',evidence=e['work']['evidence'])
        self.assertEqual(reduce_context([e],[],[r],m,{'tasks':[]})['items'][0]['operation'],'create')
        r.update(missing_fields=['time'],question='两个期限以哪个为准？')
        result=reduce_context([e],[],[r],m,{'tasks':[]})
        self.assertEqual(result['items'][0]['operation'],'candidate')
        self.assertIsNone(result['items'][0]['due_date'])
        self.assertEqual(result['review_records'][0]['question'],'两个期限以哪个为准？')

    def test_missing_event_with_existing_history_cannot_default_to_new(self):
        from meeting_eval.context_state import reduce_context
        m,e,ledger,r=ledger_fixture()
        r.update(kind='implicit_need',content_basis='inferred',missing_fields=['work'],question='要做什么？')
        r['check']=dict(verdict='supported',reason='待确认',evidence=e['work']['evidence'])
        output=reduce_context([],[],[r],m,{'tasks':[{'guid':'T-old'}]})
        self.assertFalse(output['review_records'][0]['can_add_task'])

    def test_checker_only_omission_has_stable_actionable_review_id(self):
        from meeting_eval.context_state import reduce_context
        m,e,ledger,r=ledger_fixture()
        first=reduce_context([],e['work']['evidence'],[],m,{'tasks':[]})
        second=reduce_context([],e['work']['evidence'],[],m,{'tasks':[]})
        self.assertEqual(len(first['review_records']),1)
        self.assertEqual(first['review_records'][0]['record_id'],second['review_records'][0]['record_id'])
        self.assertEqual(first['review_records'][0]['description_status'],'unverified_hypothesis')
        self.assertTrue(first['review_records'][0]['can_add_task'])

    def test_contextual_assignment_retained_and_rejected_title_not_presented_as_fact(self):
        from meeting_eval.context_state import reduce_context
        m,e,ledger,r=ledger_fixture()
        r['content_basis']='contextual';e['commitment']['kind']='assigned'
        r['check']=dict(verdict='supported',reason='连续分工',evidence=e['work']['evidence'])
        output=reduce_context([e],[],[r],m,{'tasks':[]})
        self.assertEqual(output['items'][0]['operation'],'candidate')
        self.assertEqual(output['review_records'][0]['category'],'ambiguous')
        e['checks']['time']['verdict']='contradicted'
        r['check']['verdict']='insufficient'
        output=reduce_context([e],[],[r],m,{'tasks':[]})
        self.assertEqual(output['items'],[])
        self.assertEqual(output['review_records'][0]['description_status'],'unverified_hypothesis')

    def test_team_commitment_only_asks_for_personal_owner(self):
        from meeting_eval.context_state import reduce_context
        m,e,ledger,r=ledger_fixture()
        e['owner'].update(kind='group',ref=None,label='我们')
        r['check']=dict(verdict='supported',reason='团队已明确承诺',evidence=e['work']['evidence'])
        result=reduce_context([e],[],[r],m,{'tasks':[]})
        self.assertEqual(result['review_records'][0]['missing_fields'],['owner'])
        self.assertEqual(result['review_records'][0]['question'],'这项已明确的工作由哪位具体负责人执行？')

    def test_entity_only_and_withdrawn_never_create_or_raise_questions(self):
        from meeting_eval.context_state import reduce_context
        m,e,ledger,r=ledger_fixture()
        r['check']=dict(verdict='supported',reason='原话支持',evidence=e['work']['evidence'])
        for kind in ('entity_only','withdrawn'):
            r['kind']=kind
            result=reduce_context([],[],[r],m,{'tasks':[]})
            self.assertEqual(result['items'],[])
            self.assertEqual(result['review_records'],[])

    def test_record_coverage_and_provenance_required(self):
        from meeting_eval.context_state import canonical_records,canonical_ledger
        m,e,ledger,r=ledger_fixture();ledger=canonical_ledger(ledger,m,None)
        with self.assertRaises(ValueError):canonical_records([],ledger,[e],m)
        bad=copy.deepcopy(r);bad['thread_ids']=['unknown']
        with self.assertRaises(ValueError):canonical_records([bad],ledger,[e],m)
        records=canonical_records([r],ledger,[e],m)
        self.assertEqual(records[0]['evidence'][0]['start'],2)


if __name__=='__main__':unittest.main()
