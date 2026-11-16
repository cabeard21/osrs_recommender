import { canonicalObjectives, type Objective } from "../api/objectives";
const key = "gear.objectivePresets.v1";
export interface ObjectivePreset {
  name: string;
  savedAt: string;
  objectives: Objective[];
}
export function readObjectivePresets(
  storage: Storage = localStorage,
): ObjectivePreset[] {
  const value: unknown = JSON.parse(storage.getItem(key) ?? "[]");
  if (!Array.isArray(value))
    throw new Error("Saved objective presets are invalid.");
  return value.map((row) => {
    if (
      !row ||
      typeof row.name !== "string" ||
      !row.name.trim() ||
      row.name.length > 60 ||
      typeof row.savedAt !== "string"
    )
      throw new Error("A saved objective preset is invalid.");
    return {
      name: row.name,
      savedAt: row.savedAt,
      objectives: canonicalObjectives(row.objectives),
    };
  });
}
export function saveObjectivePreset(
  name: string,
  objectives: Objective[],
  storage: Storage = localStorage,
): ObjectivePreset[] {
  const label = name.trim();
  if (!label || label.length > 60)
    throw new Error("Enter a preset name of 1–60 characters.");
  const others = readObjectivePresets(storage).filter(
    (p) => p.name.toLowerCase() !== label.toLowerCase(),
  );
  if (others.length >= 20)
    throw new Error("You can keep 20 objective presets. Delete one first.");
  const next = [
    {
      name: label,
      savedAt: new Date().toISOString(),
      objectives: canonicalObjectives(objectives),
    },
    ...others,
  ];
  try {
    storage.setItem(key, JSON.stringify(next));
  } catch {
    throw new Error("This browser blocked saving objective presets.");
  }
  return next;
}
export function deleteObjectivePreset(
  name: string,
  storage: Storage = localStorage,
): ObjectivePreset[] {
  const next = readObjectivePresets(storage).filter((p) => p.name !== name);
  try {
    storage.setItem(key, JSON.stringify(next));
  } catch {
    throw new Error("This browser blocked deleting objective presets.");
  }
  return next;
}
