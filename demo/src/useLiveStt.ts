import { useEffect, useRef, useState } from "react";
import { sourcePosition, type Scenario } from "./scenario";
import { replayCaptionAt, type CaptionEvent } from "./minutes";
type Audio = {
  time: number;
  playing: boolean;
  rate: number;
  pcm: (a: number, b: number) => Float32Array;
};
export function useLiveStt(
  scenario: Scenario | null,
  audio: Audio,
  enabled: boolean,
) {
  const [status, setStatus] = useState("等待播放");
  const [caption, setCaption] = useState<CaptionEvent | null>(null);
  const [count, setCount] = useState(0);
  const [revision, setRevision] = useState(0);
  const log = useRef<CaptionEvent[]>([]);
  const sock = useRef<WebSocket | null>(null);
  const busy = useRef(false),
    lastSent = useRef(0),
    lastTime = useRef(0);
  const latest = useRef(audio);
  latest.current = audio;
  const clipStart=scenario ? sourcePosition(scenario,audio.time)?.clip.at : undefined;
  useEffect(() => {
    log.current = [];
    setCount(0);
    setCaption(null);
  }, [scenario]);
  useEffect(() => {
    if (!enabled || !audio.playing || !scenario) {
      sock.current?.close();
      sock.current = null;
      busy.current = false;
      return;
    }
    if (audio.rate !== 1) {
      setStatus("实时 STT 请使用 1× 播放");
      return;
    }
    let alive = true;
    lastSent.current = audio.time;
    lastTime.current = audio.time;
    setCaption(null);
    setStatus("连接本机识别服务…");
    const ws = new WebSocket("ws://127.0.0.1:8766/transcribe");
    sock.current = ws;
    ws.onopen = () => {
      if (alive) setStatus("正在聆听 · 本机 STT");
    };
    ws.onmessage = (message) => {
      if (!alive) return;
      busy.current = false;
      const data = JSON.parse(message.data);
      if (data.error) {
        setStatus(data.error);
        return;
      }
      if (!data.text?.trim()) return;
      const event: CaptionEvent = {
        at: Math.round(latest.current.time),
        text: data.text.trim(),
        speaker: data.speaker,
        final: data.final,
      };
      log.current = log.current.filter((e) => e.at <= event.at);
      log.current.push(event);
      setCount(log.current.length);
      setCaption(event);
      setStatus(
        `本机 STT · ${data.inferenceMs} ms · ${data.final ? "已定稿" : "识别中"}`,
      );
    };
    ws.onerror = () => {
      if (alive) setStatus("本机 STT 未连接，请启动识别服务");
    };
    ws.onclose = () => {
      if (alive) setStatus("识别服务连接已关闭");
    };
    return () => {
      alive = false;
      ws.close();
      sock.current = null;
      busy.current = false;
    };
  }, [enabled, audio.playing, audio.rate, scenario, revision, clipStart]);
  useEffect(() => {
    if (!enabled || !audio.playing || audio.rate !== 1 || !scenario) return;
    const gap = audio.time - lastTime.current;
    lastTime.current = audio.time;
    if (gap < 0 || gap > 1500) {
      setCaption(null);
      setRevision((v) => v + 1);
      return;
    }
    const ws = sock.current;
    if (
      ws?.readyState !== WebSocket.OPEN ||
      busy.current ||
      audio.time - lastSent.current < 2200
    )
      return;
    // A bounded rolling window prevents lag from sending an unbounded audio backlog.
    const start = Math.max(lastSent.current, audio.time - 4000),
      end = audio.time;
    const speaker =
      scenario.segments
        .filter((s) => s.start <= end && s.end >= start)
        .sort(
          (a, b) =>
            Math.min(b.end, end) -
            Math.max(b.start, start) -
            (Math.min(a.end, end) - Math.max(a.start, start)),
        )[0]?.speaker ?? scenario.people[0].id;
    ws.send(JSON.stringify({ start, end, speaker }));
    ws.send(audio.pcm(start, end).buffer as ArrayBuffer);
    lastSent.current = end;
    busy.current = true;
  }, [audio.time, enabled, audio.playing, audio.rate, scenario]);
  const download = () => {
    const blob = new Blob(
      [
        JSON.stringify(
          {
            version: 1,
            source: scenario?.tracks[0].src,
            engine: "faster-whisper base.en",
            mode: "live-response-events",
            events: log.current,
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = "stt-出字时间轴.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const loadRecording = async (file: File) => {
    try {
      const data = JSON.parse(await file.text());
      if (
        data.mode !== "live-response-events" ||
        data.source !== scenario?.tracks[0].src ||
        !Array.isArray(data.events)
      )
        throw Error("出字轴与当前音频不匹配");
      let previous = -1;
      for (const e of data.events) {
        if (
          !Number.isFinite(e.at) ||
          e.at < previous ||
          e.at < 0 ||
          e.at > (scenario?.duration ?? 0) ||
          typeof e.text !== "string" ||
          typeof e.final !== "boolean" ||
          !scenario?.people.some((p) => p.id === e.speaker)
        )
          throw Error("出字轴事件格式不正确");
        previous = e.at;
      }
      log.current = data.events;
      setCount(data.events.length);
      setStatus("出字轴已载入");
      return true;
    } catch (e) {
      setStatus((e as Error).message);
      return false;
    }
  };
  return {
    status,
    caption,
    count,
    download,
    loadRecording,
    recordedAt: (at: number) => replayCaptionAt(log.current, at),
  };
}
