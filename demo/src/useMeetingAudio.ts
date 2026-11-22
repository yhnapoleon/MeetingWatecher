import { useEffect, useRef, useState } from "react";
import type { Scenario } from "./scenario";

export function useMeetingAudio(
  scenario: Scenario | null,
  files: Map<string, File> | null,
) {
  const context = useRef<AudioContext | null>(null);
  const buffers = useRef<AudioBuffer[]>([]);
  const sources = useRef<AudioBufferSourceNode[]>([]);
  const gains = useRef<GainNode[]>([]);
  const anchor = useRef({ offset: 0, clock: 0, rate: 1, playing: false });
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRateState] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [muted, setMutedState] = useState(false);
  const stopSources = () => {
    sources.current.forEach((s) => s.stop());
    sources.current = [];
  };
  const currentTime = () => {
    const a = anchor.current;
    return Math.max(
      0,
      Math.min(
        scenario?.duration ?? 0,
        a.offset +
          (a.playing
            ? ((context.current?.currentTime ?? a.clock) - a.clock) *
              1000 *
              a.rate
            : 0),
      ),
    );
  };
  const pause = () => {
    const offset = currentTime();
    stopSources();
    anchor.current = { ...anchor.current, offset, playing: false };
    setTime(offset);
    setPlaying(false);
  };
  const startAt = (offset: number) => {
    const ctx = context.current;
    if (!ctx || !scenario) return;
    stopSources();
    const clock = ctx.currentTime + 0.03;
    sources.current = buffers.current.map((buffer, index) => {
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.playbackRate.value = anchor.current.rate;
      source.connect(gains.current[index]);
      source.start(clock, offset / 1000);
      return source;
    });
    anchor.current = { ...anchor.current, offset, clock, playing: true };
    setTime(offset);
    setPlaying(true);
  };
  const play = async () => {
    if (loading || !buffers.current.length || !scenario) return;
    try {
      setError("");
      await context.current?.resume();
      startAt(currentTime() >= scenario.duration ? 0 : currentTime());
    } catch {
      setError("音频播放被浏览器阻止，请再次点击播放");
    }
  };
  const seek = (value: number) => {
    const offset = Math.max(0, Math.min(scenario?.duration ?? 0, value));
    if (anchor.current.playing && offset < (scenario?.duration ?? 0))
      startAt(offset);
    else {
      stopSources();
      anchor.current = { ...anchor.current, offset, playing: false };
      setTime(offset);
      setPlaying(false);
    }
  };
  const setRate = (value: number) => {
    const offset = currentTime();
    anchor.current = {
      ...anchor.current,
      offset,
      clock: context.current?.currentTime ?? 0,
      rate: value,
    };
    setRateState(value);
    if (anchor.current.playing) startAt(offset);
  };
  const setMuted = (value: boolean) => {
    gains.current.forEach((gain) => {
      gain.gain.value = value ? 0 : 1;
    });
    setMutedState(value);
  };

  useEffect(() => {
    if (!scenario) return;
    let cancelled = false;
    const ctx = new AudioContext();
    context.current = ctx;
    anchor.current = { offset: 0, clock: 0, rate: 1, playing: false };
    buffers.current = [];
    setTime(0);
    setPlaying(false);
    setLoading(true);
    setError("");
    setRateState(1);
    setMutedState(false);
    const load = async () => {
      const decoded = await Promise.all(
        scenario.tracks.map(async (track) => {
          let bytes: ArrayBuffer;
          if (files) {
            const file = files.get(track.src.split("/").pop()!);
            if (!file) throw new Error(`缺少音频 ${track.src}`);
            bytes = await file.arrayBuffer();
          } else {
            const response = await fetch(`/${track.src}`);
            if (!response.ok) throw new Error(`无法加载 ${track.src}`);
            bytes = await response.arrayBuffer();
          }
          const audio = await ctx.decodeAudioData(bytes);
          if (audio.duration * 1000 + 250 < scenario.duration)
            throw new Error(
              `${track.src} 声轨短于会议时长，请保留开头与结尾静音`,
            );
          return audio;
        }),
      );
      if (cancelled) return;
      buffers.current = decoded;
      gains.current = decoded.map(() => {
        const gain = ctx.createGain();
        gain.connect(ctx.destination);
        return gain;
      });
      setLoading(false);
    };
    load().catch((error) => {
      if (!cancelled) {
        setError(error.message || "音频解码失败");
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
      stopSources();
      void ctx.close();
    };
  }, [scenario, files]);

  useEffect(() => {
    if (!playing || !scenario) return;
    let frame: number;
    let lastUpdate = 0;
    const update = (stamp: number) => {
      const value = Math.max(0, currentTime());
      if (stamp - lastUpdate > 60) {
        setTime(value);
        lastUpdate = stamp;
      }
      if (value >= scenario.duration) {
        pause();
        return;
      }
      frame = requestAnimationFrame(update);
    };
    frame = requestAnimationFrame(update);
    return () => cancelAnimationFrame(frame);
  }, [playing, scenario]);

  return {
    pcm: (start: number, end: number) => {
      if (!buffers.current.length) return new Float32Array();
      const count = Math.max(0, Math.floor((end - start) * 16));
      const result = new Float32Array(count);
      for (const b of buffers.current) {
        const data = b.getChannelData(0);
        for (let i = 0; i < count; i++) {
          const index = (start / 1000 + i / 16000) * b.sampleRate;
          const lo = Math.floor(index),
            frac = index - lo;
          result[i] +=
            ((data[lo] ?? 0) * (1 - frac) + (data[lo + 1] ?? 0) * frac) /
            buffers.current.length;
        }
      }
      return result;
    },
    time,
    playing,
    rate,
    loading,
    ready: !loading && buffers.current.length > 0,
    error,
    muted,
    play,
    pause,
    seek,
    setRate,
    setMuted,
  };
}
