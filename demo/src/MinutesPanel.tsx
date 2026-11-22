import { useMemo, useState } from "react";
import {
  ReactFlow,
  Handle,
  Position,
  Background,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  ArrowRight,
  BookOpen,
  CheckCircle,
  Clock,
  Flag,
  ListChecks,
  TreeStructure,
  CaretDown,
  SpeakerHigh,
  Monitor,
  SlidersHorizontal,
  Lightbulb,
  Question,
  ArrowClockwise,
  LinkSimple,
} from "@phosphor-icons/react";
import { formatTime, projectAt, sourcePosition, type Scenario } from "./scenario";
import { minutesAt, visibleChapters, type MinuteNode } from "./minutes";

const labels = {
  discussing: "讨论中",
  proposed: "提议",
  confirmed: "已采纳",
  open: "待明确",
};
function TopicNode({ data }: NodeProps) {
  const n = data.item as MinuteNode;
  const Icon =
    n.id === "audio"
      ? SpeakerHigh
      : n.id === "visual"
        ? Monitor
        : n.id === "device"
          ? SlidersHorizontal
          : n.status === "open"
            ? Question
            : n.kind === "root"
              ? TreeStructure
              : Lightbulb;
  return (
    <div className={`topic-node ${n.kind} ${n.status}`}>
      <Handle type="target" position={Position.Top} />
      <div className="node-title">
        <Icon size={16} />
        <strong>{n.title}</strong>
      </div>
      <p>{n.body}</p>
      <span className="node-state">
        {n.status === "confirmed" && <CheckCircle size={11} weight="fill" />}
        {labels[n.status]}
      </span>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
const nodeTypes = { topic: TopicNode };
export function DiscussionGraph({
  items,
  onEvidence,
}: {
  items: MinuteNode[];
  onEvidence: (ids: string[]) => void;
}) {
  const root = items.filter((n) => n.kind === "root").at(-1)!;
  const visible = items.filter(
    (n) => n.id === root?.id || n.parent === root?.id,
  );
  const children = visible.filter((n) => n.id !== root?.id);
  const childWidth = children.length > 3 ? 140 : 180;
  const gap = 14;
  const nodes = useMemo(
    () =>
      visible.map((item) => {
        const i = children.findIndex((n) => n.id === item.id);
        return {
          id: item.id,
          type: "topic",
          data: { item },
          position:
            i < 0
              ? {
                  x:
                    Math.max(
                      0,
                      children.length * (childWidth + gap) - gap - 180,
                    ) / 2,
                  y: 0,
                }
              : { x: i * (childWidth + gap), y: 140 },
          style: { width: i < 0 ? 180 : childWidth },
        };
      }),
    [visible.map((n) => n.id + ":" + n.updatedAt).join("|")],
  );
  const edges = children.map((n) => ({
    id: `${root.id}-${n.id}`,
    source: root.id,
    target: n.id,
    type: "smoothstep",
    style: {
      stroke: n.status === "confirmed" ? "#a3b5ce" : "#cad2df",
      strokeWidth: 1.4,
    },
  }));
  return (
    <div className="discussion-graph">
      <ReactFlow
        key={visible.map((n) => n.id).join("-")}
        forceColorMode="light"
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: "18px" }}
        nodesDraggable={false}
        nodesConnectable={false}
        zoomOnScroll={false}
        panOnDrag={false}
        preventScrolling={false}
        zoomOnDoubleClick={false}
        minZoom={0.3}
        maxZoom={1.2}
        onNodeClick={(_, node) => {
          const item = node.data.item as MinuteNode;
          if (item.evidence.length) onEvidence(item.evidence);
        }}
        aria-label="会议讨论关系图"
      >
        <Background color="#dfe5ee" gap={18} size={1} />
      </ReactFlow>
      {!children.length && (
        <div className="graph-wait">
          <span className="listening-dot" />
          正在聆听，观点会逐步连接到议题
        </div>
      )}
    </div>
  );
}

export function MinutesPanel({
  scenario,
  time,
  onEvidence,
  onSeek,
  graphOnly = false,
  archived = false,
  caption,
  captionLabel = 'STT 词轴回放',
}: {
  scenario: Scenario;
  time: number;
  onEvidence: (ids: string[]) => void;
  onSeek: (at: number) => void;
  graphOnly?: boolean;
  archived?: boolean;
  caption?: { text: string; speaker: string } | null;
  captionLabel?: string;
}) {
  const [contextOpen, setContextOpen] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const nodes = minutesAt(scenario, time);
  const state = projectAt(scenario, time);
  const chapters = visibleChapters(scenario, time);
  const chapter = chapters.at(-1);
  const meeting=sourcePosition(scenario,time)?.meeting;
  const baseline = meeting?.at ? projectAt(scenario, meeting.at - 1) : null;
  const captionPerson = scenario.people.find(p => p.id === caption?.speaker);
  const latest = nodes
    .filter((n) => n.evidence.length)
    .sort((a, b) => b.updatedAt - a.updatedAt)[0];
  const finished = archived || time >= scenario.duration;
  return (
    <div className="minutes-document">
      {!graphOnly && !archived && baseline && <details className="inherited-memory"><summary><BookOpen size={15} /> 上场已确认 <b>{baseline.decisions.length} 项决定 · {baseline.tasks.length} 项任务</b><span>展开查看</span></summary><p>继承自已归档会议；下方本场讨论图随发言生成。</p>{baseline.decisions.map(d => <div key={d.id}><strong>{d.title}</strong><span>{d.value}</span></div>)}</details>}
      {!graphOnly && !archived && <section className="live-transcription"><header><span className="listening-dot" /><strong>实时转写</strong><small>{captionLabel}</small><span>{captionPerson?.name ?? '等待发言'}</span></header><p>{caption?.text || '正在聆听，文字将随发言逐词出现…'}</p></section>}
      {!graphOnly && scenario.context && (!meeting || meeting.at===0) && (
        <section
          className={`previous-meeting ${contextOpen ? "expanded" : ""}`}
        >
          <button
            className="context-toggle"
            onClick={() => setContextOpen(!contextOpen)}
            aria-expanded={contextOpen}
          >
            <BookOpen size={17} />
            <span>
              <strong>会前承接</strong>
              <small>{scenario.context.title}</small>
            </span>
            <CaretDown size={15} />
          </button>
          <div className="context-facts">
            {scenario.context.facts.map((f) => (
              <span key={f}>{f}</span>
            ))}
          </div>
          {contextOpen && (
            <div className="context-detail">
              <p>{scenario.context.summary}</p>
              <p>{scenario.context.open}</p>
              <small>{scenario.context.source}</small>
            </div>
          )}
        </section>
      )}
      {!graphOnly && (
        <div className="minutes-shortcuts">
          <button
            onClick={() =>
              document
                .getElementById("decisions-section")
                ?.scrollIntoView({ behavior: "smooth", block: "start" })
            }
          >
            <Flag size={13} />
            决策 <b>{state.decisions.length}</b>
          </button>
          <button
            onClick={() =>
              document
                .getElementById("tasks-section")
                ?.scrollIntoView({ behavior: "smooth", block: "start" })
            }
          >
            <ListChecks size={14} />
            行动 <b>{state.tasks.length}</b>
          </button>
          <span>内容随会议持续整理</span>
        </div>
      )}
      <section className="current-discussion">
        <div className="document-section-title">
          <span className="listening-dot" />
          <span>{finished ? "会议回顾" : "当前讨论"}</span>
          {chapter && <button onClick={() => onSeek(chapter.at)}>
            {formatTime(chapter.at - (meeting?.at ?? 0))} <ArrowRight size={12} />
          </button>}
        </div>
        <h2>{chapter?.title ?? '等待讨论展开'}</h2>
        <p key={latest?.updatedAt}>
          {latest ? latest.body : "正在聆听，观点和议题将在讨论中逐步整理。"}
        </p>
        <div className="topic-breadcrumbs">
          {chapters.map((c, i) => (
            <button
              key={c.at}
              title={c.title}
              onClick={() => onSeek(c.at)}
              className={c === chapter ? "current" : c.at < time ? "done" : ""}
            >
              <span>{i + 1}</span>
              {c === chapter ? c.title : ""}
            </button>
          ))}
        </div>
      </section>
      <section className="minutes-section graph-section">
        <div className="document-heading">
          <h3>
            <TreeStructure size={19} />
            讨论全览
          </h3>
          <span>
            {meeting && meeting.at>0 ? '跨会承接图' : nodes.some((n) => n.id === "grouping")
              ? "功能分类图"
              : "方案收敛图"}
          </span>
        </div>
        <DiscussionGraph items={nodes} onEvidence={onEvidence} />
        <div className="graph-caption">
          <span>点击节点，回到讨论依据</span>
          <span>
            <i className="legend-dot" />
            已采纳
            <i className="legend-dot proposed" />
            提议 / 待明确
          </span>
        </div>
      </section>
      {!graphOnly && (
        <>
          <section
            id="decisions-section"
            className="minutes-section decisions-document"
          >
            <div className="document-heading">
              <h3>
                <Flag size={18} />
                决策纪要 <em>{state.decisions.length}</em>
              </h3>
              <span>随讨论更新</span>
            </div>
            {!state.decisions.length && (
              <p className="document-empty">
                听取方案与理由，明确共识后记录决定。
              </p>
            )}
            {state.decisions.map((d) => (
              <article className="decision-entry" key={d.id}>
                <span className="decision-marker">
                  <CheckCircle size={17} weight="fill" />
                </span>
                <div className="decision-copy">
                  <button
                    className="decision-title"
                    onClick={() => setExpanded(expanded === d.id ? null : d.id)}
                  >
                    <strong>{d.title}</strong>
                    <span
                      className={
                        d.versions.length > 1
                          ? "revision-badge"
                          : "adopted-badge"
                      }
                    >
                      {d.versions.length > 1 ? "已修订" : d.reaffirmations.length ? '已重申' : baseline?.decisions.some(p => p.id === d.id) ? '沿用上场' : "已采纳"}
                    </span>
                    <CaretDown size={13} />
                  </button>
                  <p className="decision-value" key={d.value}>
                    {d.value}
                    {d.unit && ` ${d.unit}`}
                  </p>
                  {expanded === d.id && (
                    <div className="decision-details">
                      <p>{d.detail}</p>
                      {d.versions.length > 1 && (
                        <div className="version-diff">
                          <del>{d.versions[0].value}</del>
                          <ArrowRight size={13} />
                          <span>{d.value}</span>
                        </div>
                      )}
                      <button onClick={() => onEvidence(d.evidence)}>
                        <LinkSimple size={13} />
                        查看原话 · {formatTime(d.versions.at(-1)!.at)}
                      </button>
                      {!!d.reaffirmations.length && <p>已跨会重申 {d.reaffirmations.length} 次，保留同一版本。</p>}
                    </div>
                  )}
                </div>
                <button
                  className="source-timestamp"
                  onClick={() => onEvidence(d.evidence)}
                >
                  {formatTime(d.versions.at(-1)!.at)}
                </button>
              </article>
            ))}
          </section>
          <section
            id="tasks-section"
            className="minutes-section action-document"
          >
            <div className="document-heading">
              <h3>
                <ListChecks size={19} />
                行动事项 <em>{state.tasks.length}</em>
              </h3>
              <span>负责人 · 交付时间</span>
            </div>
            {!state.tasks.length && (
              <p className="document-empty">
                明确交付内容与负责人后，分工将出现在这里。
              </p>
            )}
            {state.tasks.map((t) => {
              const p = scenario.people.find((p) => p.id === t.owner)!;
              return (
                <article className="action-entry" key={t.id}>
                  <span className="task-checkbox" />
                  <div>
                    <strong>{t.title}</strong>
                    <p>{t.detail}</p>
                    <div className="action-meta">
                      <span className="person-tag">
                        <i style={{ background: p.color }}>{p.initial}</i>
                        {p.name}
                      </span>
                      <span>
                        <Clock size={12} />
                        {t.due}
                      </span>
                      <span>{t.status==='进行中'?'已汇报 · 进行中':t.status}</span>
                    </div>
                  </div>
                  <button
                    title="查看任务依据"
                    onClick={() => onEvidence(t.evidence)}
                  >
                    <LinkSimple size={15} />
                  </button>
                </article>
              );
            })}
          </section>
          {state.changes.length > 0 && (
            <div className="document-update" key={state.changes.at(-1)!.at}>
              <ArrowClockwise size={14} />
              <span>{state.changes.at(-1)!.label}</span>
              <time>{formatTime(state.changes.at(-1)!.at)}</time>
            </div>
          )}
          {finished && (
            <div className="meeting-complete">
              <CheckCircle size={20} />
              <div>
                <strong>会议纪要已整理</strong>
                <p>
                  {state.decisions.length} 项决定 · {state.tasks.length} 项行动
                  · 原话均可追溯
                </p>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
