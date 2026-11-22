import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { validateScenario, projectAt } from "../src/scenario";

const fixture = () =>
  JSON.parse(
    readFileSync(new URL("../public/scenario.json", import.meta.url), "utf8"),
  );

test("imported transcript is ordered before speaker and caption projection", () => {
  const raw = fixture();
  raw.segments.reverse();
  const scenario = validateScenario(raw);
  assert.equal(
    scenario.segments.filter((s) => s.end <= 58000).at(-1)?.id,
    "s03",
  );
  assert.equal(scenario.segments[0].id, "s01");
});

test("automatic confirmation follows media time and rewinds without residual tasks", () => {
  const scenario = validateScenario(fixture());
  const interaction = scenario.interactions[0];
  assert.equal(
    projectAt(scenario, interaction.showAt - 1).interaction,
    undefined,
  );
  assert.equal(
    projectAt(scenario, interaction.selectAt - 1).interaction?.phase,
    "waiting",
  );
  assert.equal(
    projectAt(scenario, interaction.selectAt).interaction?.phase,
    "selected",
  );
  assert.ok(
    projectAt(scenario, interaction.completeAt).tasks.some(
      (t) => t.id === interaction.task.id,
    ),
  );
  assert.ok(
    !projectAt(scenario, interaction.showAt).tasks.some(
      (t) => t.id === interaction.task.id,
    ),
  );
});

test("seek to end equals final sequential projection with one effective decision and two tasks", () => {
  const scenario = validateScenario(fixture());
  const final = projectAt(scenario, scenario.duration);
  let sequential;
  for (let time = 0; time <= scenario.duration; time += 1000)
    sequential = projectAt(scenario, time);
  sequential = projectAt(scenario, scenario.duration);
  assert.deepEqual(sequential, final);
  assert.equal(final.tasks.length, 2);
  assert.equal(final.decisions.length, 1);
  assert.equal(final.decisions[0].value, "89");
  assert.equal(final.decisions[0].versions.length, 2);
  assert.equal(final.decisions[0].reaffirmations.length, 1);
  assert.equal(final.tasks.find((t) => t.id === "roster")?.due, "本周四");
});

test("rejects missing speaker, out of range timestamps and early evidence", () => {
  const unknown = fixture();
  unknown.segments[0].speaker = "missing";
  assert.throws(() => validateScenario(unknown), /说话人/);
  const late = fixture();
  late.segments[0].end = late.duration + 10;
  assert.throws(() => validateScenario(late), /时间/);
  const early = fixture();
  early.events[0].at = 0;
  assert.throws(() => validateScenario(early), /证据/);
});

test("mixed audio has one playback source and retains separate speaker annotations", () => {
  const raw = fixture();
  raw.audioMode = "mixed";
  raw.tracks = [{ speaker: "*", src: "audio/mixed.mp3" }];
  const scenario = validateScenario(raw);
  assert.equal(scenario.tracks.length, 1);
  assert.equal(new Set(scenario.segments.map((s) => s.speaker)).size, 4);
  raw.tracks.push({ speaker: "*", src: "audio/duplicate.mp3" });
  assert.throws(() => validateScenario(raw), /混音/);
});
