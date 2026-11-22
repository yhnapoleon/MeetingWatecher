import { sourcePosition, type Scenario } from "./scenario";
export type MinuteNode = Scenario["minuteEvents"][number]["node"] & {
  updatedAt: number;
};
export type CaptionEvent = {
  at: number;
  text: string;
  speaker: string;
  final: boolean;
};
export function visibleCaption<
  T extends { text: string; speaker: string; at?: number },
>(
  scenario: Scenario | null,
  caption: T | null | undefined,
  time: number,
): T | null {
  if (!caption || !scenario?.people.some((p) => p.id === caption.speaker))
    return null;
  if (
    caption.at !== undefined &&
    (caption.at > time || time - caption.at > 10000 ||
      caption.at < (sourcePosition(scenario,time)?.clip.at ?? 0))
  )
    return null;
  return caption;
}
export function minutesAt(scenario: Scenario, time: number): MinuteNode[] {
  const nodes = new Map<string, MinuteNode>();
  const start = sourcePosition(scenario, time)?.meeting.at ?? 0;
  for (const event of scenario.minuteEvents) {
    if (event.at > time) break;
    if (event.at < start) continue;
    nodes.set(event.node.id, { ...event.node, updatedAt: event.at });
  }
  return [...nodes.values()];
}
export function visibleChapters(scenario: Scenario, time: number) {
  const start = sourcePosition(scenario, time)?.meeting.at ?? 0;
  return scenario.chapters.filter(c => c.at >= start && c.at <= time);
}
export function replayCaptionAt(events: CaptionEvent[], time: number) {
  return events.filter((e) => e.at <= time).at(-1);
}
const joinWords = (words: { text: string }[]) =>
  words
    .map((w) => w.text.trim())
    .join(" ")
    .replace(/\s+([.,!?;:])/g, "$1");
export function captionAt(
  scenario: Scenario,
  time: number,
): { text: string; speaker: string; final: boolean } {
  if (scenario.captionWords) {
    const clipStart=sourcePosition(scenario,time)?.clip.at ?? 0;
    const words = scenario.captionWords.filter((w) => w.end <= time && w.start>=clipStart);
    const last = words.at(-1);
    if (!last) return { text: "", speaker: "", final: false };
    const recent = words
      .filter(
        (w) =>
          w.speaker === last.speaker &&
          w.end > Math.max(time - 8500, last.end - 8500),
      )
      .slice(-30);
    return {
      text: joinWords(recent),
      speaker: last.speaker,
      final: time - last.end > 900,
    };
  }
  const clipStart=sourcePosition(scenario,time)?.clip.at ?? 0;
  const current = scenario.segments.filter((s) => s.start <= time && s.start>=clipStart).at(-1);
  if (!current) return { text: "", speaker: "", final: false };
  // Old imported sentence-only fixtures use an explicitly documented paced preview.
  const text = current.words
    ? joinWords(current.words.filter((w) => w.end <= time))
    : current.text.slice(
        0,
        Math.floor(
          current.text.length *
            Math.min(1, (time - current.start) / (current.end - current.start)),
        ),
      );
  return { text, speaker: current.speaker, final: time >= current.end };
}
