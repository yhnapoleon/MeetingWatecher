import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { CrossMeetingPanel } from '../src/CrossMeetingPanel';
import { validateScenario, projectAt, sourcePosition } from "../src/scenario";
import {
  minutesAt,
  captionAt,
  replayCaptionAt,
  visibleCaption,
  visibleChapters,
} from "../src/minutes";
const raw = () =>
  JSON.parse(
    readFileSync(
      new URL("../public/scenario-real.json", import.meta.url),
      "utf8",
    ),
  );
test('meeting outline and graph reveal only reached topics, including a blank second meeting', () => {
  const s = validateScenario(JSON.parse(readFileSync(new URL('../public/scenario-cross.json', import.meta.url), 'utf8')));
  assert.equal(visibleChapters(s, 0).length, 1);
  assert.equal(visibleChapters(s, 50000).length, 2);
  assert.equal(visibleChapters(s, 390000).length, 0);
  assert.equal(minutesAt(s, 390000).length, 0);
  assert.equal(minutesAt(s, 424000).length, 3);
  assert.equal(visibleChapters(s, 424000).length, 1);
  assert.equal(minutesAt(s, 390000).length, 0);
});
test("graph nodes are born once, updated in place, and rewind removes future revisions", () => {
  const s = validateScenario(raw());
  assert.equal(
    minutesAt(s, 192000).some((n) => n.id === "grouping"),
    false,
  );
  assert.equal(
    minutesAt(s, 194000).find((n) => n.id === "grouping")?.status,
    "proposed",
  );
  assert.equal(
    minutesAt(s, 271000).find((n) => n.id === "grouping")?.status,
    "confirmed",
  );
  assert.equal(
    minutesAt(s, 271000).filter((n) => n.id === "grouping").length,
    1,
  );
  assert.equal(
    minutesAt(s, 194000).find((n) => n.id === "grouping")?.status,
    "proposed",
  );
});
test("caption cannot reveal future words and handles interleaved speakers", () => {
  const s = validateScenario(raw());
  s.captionWords = [
    { start: 100, end: 400, text: "Hello", speaker: "A" },
    { start: 500, end: 700, text: "there", speaker: "A" },
    { start: 600, end: 850, text: "Yes", speaker: "B" },
  ];
  assert.equal(captionAt(s, 399).text, "");
  assert.equal(captionAt(s, 450).text, "Hello");
  assert.equal(captionAt(s, 750).text, "Hello there");
  assert.equal(captionAt(s, 900).speaker, "B");
  assert.equal(captionAt(s, 450).text, "Hello");
});
test("real recognition snapshots preserve revisions and exact receipt times", () => {
  const events = [
    { at: 1000, text: "a cat", speaker: "A", final: false },
    { at: 1300, text: "a cap", speaker: "A", final: true },
  ];
  assert.equal(replayCaptionAt(events, 999)?.text, undefined);
  assert.equal(replayCaptionAt(events, 1200)?.text, "a cat");
  assert.equal(replayCaptionAt(events, 1400)?.text, "a cap");
  assert.equal(replayCaptionAt(events, 1200)?.text, "a cat");
});
test("invalid graph references and caption timestamps reject at import", () => {
  const r = raw();
  r.minuteEvents[1].node.evidence = ["missing"];
  assert.throws(() => validateScenario(r));
  const t = raw();
  t.captionWords = [{ start: 500, end: 400, text: "bad", speaker: "A" }];
  assert.throws(() => validateScenario(t));
});
test("paused seek and scene switch never expose future or foreign live captions", () => {
  const s = validateScenario(raw());
  const c = { at: 3000, text: "future content", speaker: "A", final: false };
  assert.equal(visibleCaption(s, c, 2000), null);
  assert.equal(visibleCaption(s, c, 3200)?.text, "future content");
  assert.equal(visibleCaption(s, c, 14000), null);
  assert.equal(visibleCaption(s, { ...c, speaker: "missing" }, 3200), null);
});

const pair = () => validateScenario(JSON.parse(readFileSync(new URL('../public/scenario-cross.json', import.meta.url), 'utf8')));
test('next meeting inherits actual prior state, reaffirms without inventing a version, and replaces power once', () => {
  const s=pair();
  const before=projectAt(s,390000), recap=projectAt(s,424000), end=projectAt(s,s.duration);
  assert.equal(before.tasks.length,4);
  assert.equal(recap.decisions.length,4);
  const power=recap.decisions.find(d=>d.id==='power')!;
  assert.equal(power.versions.length,1);
  assert.equal(power.reaffirmations.length,1);
  assert.notDeepEqual(power.evidence,power.versions[0].evidence);
  const revised=end.decisions.find(d=>d.id==='power')!;
  assert.deepEqual(revised.versions.map(v=>v.value),['常规电池','动能辅助＋电池后备']);
  assert.equal(projectAt(s,390000).decisions.find(d=>d.id==='power')!.reaffirmations.length,0);
  assert.equal(end.tasks.length,4);
  assert.equal(end.tasks.filter(t=>t.status==='进行中').length,3);
  assert.equal(end.tasks.filter(t=>t.status==='已完成').length,0);
});
test('source mapping exposes original meeting times at boundaries and subtitles do not bleed across edits', () => {
  const s=pair();
  assert.equal(sourcePosition(s,390000)?.meeting.id,'ES2002c');
  assert.equal(sourcePosition(s,390000)?.sourceTime,15000);
  assert.equal(sourcePosition(s,460000)?.sourceTime,186000);
  assert.equal(sourcePosition(s,s.duration)?.sourceTime,1993000);
  s.captionWords=[{start:389000,end:389900,text:'old meeting',speaker:'A'}, {start:390100,end:390500,text:'new meeting',speaker:'B'}];
  assert.equal(captionAt(s,390000).text,'');
  assert.equal(captionAt(s,390600).text,'new meeting');
  assert.equal(visibleCaption(s,{at:389900,text:'stale live',speaker:'A'},390100),null);
  delete s.captionWords;
  assert.equal(captionAt(s,390000).text,'');
  assert.equal(captionAt(s,460000).text,'');
});
test('import rejects broken meeting ranges and unmapped source excerpts', () => {
  const s=pair();
  s.clips[1].meetingId='missing';
  assert.throws(()=>validateScenario(s));
  const t=pair(); t.meetings[0].end+=1000;
  assert.throws(()=>validateScenario(t));
  const one=pair(); one.meetings=[{id:'one',title:'单场来源',at:0,end:one.duration}];
  one.clips.forEach(c=>c.meetingId='one');
  assert.equal(sourcePosition(validateScenario(one),390000)?.meeting.id,'one');
  const three=pair(); three.meetings.push({...three.meetings[1],id:'third'});
  assert.throws(()=>validateScenario(three));
});
test('a decision first introduced in meeting two is displayed as new, without a fabricated prior', () => {
  const s=pair();
  s.events=s.events.filter(e=>!(e.at<390000 && e.kind==='decision' && e.decision.id==='power'));
  validateScenario(s);
  const html=renderToStaticMarkup(createElement(CrossMeetingPanel,{scenario:s,time:424000,onEvidence:()=>{},onSeek:()=>{}}));
  assert.match(html,/本场新增/);
  assert.match(html,/前场未形成/);
});
