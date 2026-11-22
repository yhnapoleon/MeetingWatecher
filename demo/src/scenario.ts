import { z } from "zod";

const id = z.string().min(1);
const time = z.number().finite().nonnegative();
const evidence = z.array(id).min(1);
const taskSchema = z.object({
  id,
  title: id,
  owner: id,
  due: id,
  status: z.enum(["待开始", "进行中", "已完成"]),
  detail: z.string(),
  evidence,
});
const decisionSchema = z.object({
  id,
  title: id,
  value: id,
  unit: z.string(),
  detail: z.string(),
  evidence,
});
const eventBase = { id, at: time, label: id };
const wordSchema = z.object({ start: time, end: time, text: id });
const minuteNode = z.object({
  id,
  kind: z.enum(["root", "category", "point"]),
  title: id,
  body: z.string(),
  status: z.enum(["discussing", "proposed", "confirmed", "open"]),
  parent: z.string().nullable().optional(),
  evidence: z.array(id),
});
const schema = z.object({
  version: z.literal(1),
  title: id,
  subtitle: z.string(),
  duration: time.positive(),
  provenance: id,
  video: z
    .string()
    .regex(/^video\/[a-zA-Z0-9._-]+\.mp4$/)
    .optional(),
  sourceUrl: z.string().url().optional(),
  captionSource: z.string().optional(),
  captionWords: z.array(wordSchema.extend({ speaker: id })).optional(),
  meetings: z.array(z.object({ id, title: id, at: time, end: time })).max(2).default([]),
  clips: z.array(z.object({ meetingId: id, at: time, end: time, sourceStart: time, label: id })).default([]),
  context: z
    .object({
      title: id,
      source: id,
      summary: id,
      facts: z.array(id),
      open: id,
    })
    .optional(),
  minuteEvents: z.array(z.object({ at: time, node: minuteNode })).default([]),
  people: z
    .array(
      z.object({
        id,
        name: id,
        role: id,
        initial: id,
        color: z.string().regex(/^#[0-9a-fA-F]{6}$/),
      }),
    )
    .min(1)
    .max(12),
  tracks: z.array(z.object({ speaker: id, src: id })).min(1),
  audioMode: z.enum(["individual", "mixed"]).default("individual"),
  segments: z
    .array(
      z.object({
        id,
        speaker: id,
        start: time,
        end: time,
        text: id,
        words: z.array(wordSchema).optional(),
      }),
    )
    .min(1),
  events: z.array(
    z.discriminatedUnion("kind", [
      z.object({ ...eventBase, kind: z.literal("task"), task: taskSchema }),
      z.object({
        ...eventBase,
        kind: z.literal("decision"),
        decision: decisionSchema,
      }),
    ]),
  ),
  interactions: z.array(
    z.object({
      id,
      showAt: time,
      selectAt: time,
      completeAt: time,
      title: id,
      quote: id,
      task: taskSchema,
    }),
  ),
  chapters: z.array(z.object({ at: time, title: id })).min(1),
});
export type Scenario = z.infer<typeof schema>;
export type Person = Scenario["people"][number];
export type Task = z.infer<typeof taskSchema>;
export type Decision = z.infer<typeof decisionSchema>;
export type Change = {
  at: number;
  label: string;
  detail: string;
  evidence: string[];
  kind: "task" | "decision" | "confirmation";
};
export type DecisionView = Decision & {
  versions: { at: number; value: string; evidence: string[] }[];
  reaffirmations: { at: number; value: string; evidence: string[] }[];
};

export function validateScenario(raw: unknown): Scenario {
  const result = schema.safeParse(raw);
  if (!result.success)
    throw new Error(
      `场景格式不正确，请核对 ${result.error.issues[0].path.join(".")} 字段`,
    );
  const data = result.data;
  if (data.meetings.length || data.clips.length) {
    for (const ranges of [data.meetings, data.clips]) {
      if (!ranges.length || ranges[0].at !== 0 || ranges.at(-1)!.end !== data.duration ||
          ranges.some((r,i)=>r.end<=r.at || (i>0 && r.at!==ranges[i-1].end)))
        throw new Error('会议与节选时间须连续覆盖整个演示');
    }
    if (new Set(data.meetings.map(m=>m.id)).size!==data.meetings.length)
      throw new Error('会议 ID 重复');
    for (const c of data.clips) {
      const m=data.meetings.find(m=>m.id===c.meetingId);
      if (!m || c.at<m.at || c.end>m.end) throw new Error('节选未映射到对应会议');
    }
  }
  const unique = (values: string[]) => new Set(values).size === values.length;
  if (
    !unique(data.people.map((p) => p.id)) ||
    !unique(data.segments.map((s) => s.id)) ||
    !unique([
      ...data.events.map((e) => e.id),
      ...data.interactions.map((i) => i.id),
    ])
  )
    throw new Error("标注中的 ID 重复");
  const people = new Set(data.people.map((p) => p.id));
  const segments = new Map(data.segments.map((s) => [s.id, s]));
  for (const s of data.segments) {
    if (!people.has(s.speaker)) throw new Error("发言的说话人映射缺失");
    if (s.end <= s.start || s.end > data.duration)
      throw new Error("发言时间超出会议范围");
  }
  for (const track of data.tracks) {
    if (data.audioMode === "individual" && !people.has(track.speaker))
      throw new Error("声轨的说话人映射缺失");
    if (!/^audio\/[^/\\\u0000-\u001f]+\.(mp3|wav|m4a|ogg)$/i.test(track.src))
      throw new Error("音频路径须为 audio/文件名.mp3、wav、m4a 或 ogg");
  }
  if (
    data.audioMode === "individual" &&
    (!unique(data.tracks.map((t) => t.speaker)) ||
      data.people.some((p) => !data.tracks.some((t) => t.speaker === p.id)))
  )
    throw new Error("每位参会人需要一个声轨入口");
  if (
    data.audioMode === "mixed" &&
    (data.tracks.length !== 1 || data.tracks[0].speaker !== "*")
  )
    throw new Error("混音模式只接受一个 speaker 为 * 的音频入口");
  const checkEvidence = (ids: string[], at: number) => {
    if (
      at > data.duration ||
      ids.some((id) => !segments.has(id) || segments.get(id)!.end > at)
    )
      throw new Error("事项时间或证据不正确，所需发言必须先结束");
  };
  for (const event of data.events) {
    const value = event.kind === "task" ? event.task : event.decision;
    checkEvidence(value.evidence, event.at);
    if (event.kind === "task" && !people.has(event.task.owner))
      throw new Error("任务负责人映射缺失");
  }
  const graphIds = new Set<string>();
  data.minuteEvents.sort((a, b) => a.at - b.at);
  for (const event of data.minuteEvents) {
    checkEvidence(event.node.evidence, event.at);
    if (event.node.parent && !graphIds.has(event.node.parent))
      throw new Error("图节点的父级尚未创建");
    graphIds.add(event.node.id);
  }
  for (const word of data.captionWords ?? []) {
    if (
      !people.has(word.speaker) ||
      word.end < word.start ||
      word.end > data.duration
    )
      throw new Error("字幕词轴超出范围或说话人缺失");
  }
  data.captionWords?.sort((a, b) => a.end - b.end || a.start - b.start);
  for (const s of data.segments) {
    for (const w of s.words ?? [])
      if (w.start < s.start || w.end > s.end || w.end < w.start)
        throw new Error("发言内的词轴不正确");
  }
  const interactions = [...data.interactions].sort(
    (a, b) => a.showAt - b.showAt,
  );
  for (let index = 0; index < interactions.length; index++) {
    const i = interactions[index];
    if (
      !(i.showAt < i.selectAt && i.selectAt < i.completeAt) ||
      i.completeAt + 2000 > data.duration
    )
      throw new Error("自动交互时间顺序不正确");
    if (index && interactions[index - 1].completeAt + 2000 > i.showAt)
      throw new Error("自动交互浮层时间重叠");
    checkEvidence(i.task.evidence, i.showAt);
    if (!people.has(i.task.owner)) throw new Error("确认卡负责人映射缺失");
  }
  if (
    data.chapters[0].at !== 0 ||
    data.chapters.some(
      (c, index) =>
        c.at > data.duration ||
        (index > 0 && c.at <= data.chapters[index - 1].at),
    )
  )
    throw new Error("章节时间须从 0 开始并递增");
  data.segments.sort((a, b) => a.start - b.start || a.end - b.end);
  return data;
}

export function projectAt(scenario: Scenario, time: number) {
  const tasks = new Map<string, Task>();
  const decisions = new Map<string, DecisionView>();
  const changes: Change[] = [];
  const automatic = scenario.interactions.map((i) => ({
    id: i.id,
    at: i.completeAt,
    kind: "task" as const,
    task: i.task,
    label: "澄清后创建任务",
    confirmed: true,
  }));
  const events = [...scenario.events, ...automatic].sort((a, b) => a.at - b.at);
  for (const event of events) {
    if (event.at > time) break;
    if (event.kind === "task") {
      const old = tasks.get(event.task.id);
      const detail = old
        ? old.status !== event.task.status
          ? `${old.status} → ${event.task.status} · ${event.task.detail}`
          : old.due !== event.task.due ? `${old.due} → ${event.task.due}` : event.task.detail
        : event.task.title;
      tasks.set(event.task.id, event.task);
      changes.push({
        at: event.at,
        label: event.label,
        detail,
        evidence: event.task.evidence,
        kind: "confirmed" in event ? "confirmation" : "task",
      });
    } else {
      const old = decisions.get(event.decision.id);
      const reaffirmed = !!old && old.value === event.decision.value && old.unit === event.decision.unit;
      const observation = {
        at: event.at,
        value: event.decision.value,
        evidence: event.decision.evidence,
      };
      const versions = reaffirmed ? old.versions : [
        ...(old?.versions ?? []),
        observation,
      ];
      const reaffirmations = [...(old?.reaffirmations ?? []), ...(reaffirmed ? [observation] : [])];
      decisions.set(event.decision.id, { ...event.decision, versions, reaffirmations });
      changes.push({
        at: event.at,
        label: event.label,
        detail:
          old && old.value !== event.decision.value
            ? `${old.value} → ${event.decision.value} ${event.decision.unit}`
            : `${event.decision.value} ${event.decision.unit}`,
        evidence: event.decision.evidence,
        kind: "decision",
      });
    }
  }
  const item = scenario.interactions.find(
    (i) => time >= i.showAt && time < i.completeAt + 2000,
  );
  const phase =
    item &&
    (time >= item.completeAt
      ? "complete"
      : time >= item.selectAt
        ? "selected"
        : "waiting");
  return {
    tasks: [...tasks.values()],
    decisions: [...decisions.values()],
    changes,
    interaction: item
      ? {
          ...item,
          phase,
          remaining: Math.max(0, Math.ceil((item.selectAt - time) / 1000)),
        }
      : undefined,
  };
}

export function sourcePosition(scenario: Scenario, time: number) {
  const clip=scenario.clips.find(c=>c.at<=time && time<c.end) ??
    (time===scenario.duration ? scenario.clips.at(-1) : undefined);
  if (!clip) return null;
  return { clip, meeting:scenario.meetings.find(m=>m.id===clip.meetingId)!,
    sourceTime:clip.sourceStart+time-clip.at };
}

export function formatTime(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000);
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}
