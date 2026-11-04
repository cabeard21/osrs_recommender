import { useState } from "react";
import type { Draft } from "../api/contracts";
import { sameValue } from "../api/runtime";
import { applyMultiTemplate, MULTI_TEMPLATES } from "./multiDraft";

interface Applied {
  label: string;
  before: Draft;
  after: Draft;
}

export function MultiTemplates({
  draft,
  edit,
}: {
  draft: Draft;
  edit: (draft: Draft) => void;
}) {
  const [applied, setApplied] = useState<Applied | null>(null);
  // Undo is only offered until the draft is edited further.
  const canUndo = applied && sameValue(applied.after, draft);
  return (
    <div className="multi-templates">
      <span id="multi-templates-label">Quick setup</span>
      <div
        className="option-shortcuts"
        role="group"
        aria-labelledby="multi-templates-label"
      >
        {MULTI_TEMPLATES.map((template) => (
          <button
            type="button"
            key={template.label}
            onClick={() => {
              const after = applyMultiTemplate(draft, template);
              setApplied({ label: template.label, before: draft, after });
              edit(after);
            }}
          >
            {template.label}
          </button>
        ))}
      </div>
      {canUndo && (
        <p role="status" className="notice">
          Applied the {applied.label} template; the target was kept.{" "}
          <button
            type="button"
            onClick={() => {
              edit(applied.before);
              setApplied(null);
            }}
          >
            Undo template
          </button>
        </p>
      )}
    </div>
  );
}
