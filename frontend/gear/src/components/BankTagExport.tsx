import { useState } from "react";
import type { Equipment } from "../api/contracts";
import { mobileBankTag } from "../api/bankTags";
import { Dialog } from "./Dialog";

export function BankTagExport({
  equipment,
  name,
}: {
  equipment: Equipment;
  name: string;
}) {
  const code = mobileBankTag(equipment);
  return <ExportSession key={`${name}:${code}`} code={code} name={name} />;
}

function ExportSession({ code, name }: { code: string | null; name: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        disabled={!code}
        onClick={() => {
          setOpen(true);
        }}
      >
        Export mobile bank tag
      </button>
      {!code && (
        <p>Bank tag export requires nonempty equipment with valid item IDs.</p>
      )}
      {open && code && (
        <ExportDialog code={code} name={name} onClose={() => setOpen(false)} />
      )}
    </div>
  );
}

function ExportDialog({
  code,
  name,
  onClose,
}: {
  code: string;
  name: string;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<"copied" | "error" | null>(null);
  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setStatus("copied");
    } catch {
      setStatus("error");
    }
  }
  return (
    <Dialog title="Export mobile bank tag" onClose={onClose}>
      <p>
        {name} · {code.split(",")[1]} equipped items
      </p>
      <p>
        In OSRS mobile, open the Bank Tags menu, choose Import, and paste this
        code. Name the tag in-game. Items follow the equipment layout, including
        gaps for empty slots.
      </p>
      <label>
        Bank tag code
        <textarea readOnly rows={4} value={code} spellCheck={false} />
      </label>
      <button onClick={() => void copy()}>Copy code</button>
      {status === "copied" && <p role="status">Bank tag code copied.</p>}
      {status === "error" && (
        <p role="alert">Could not copy. Select and copy the code above.</p>
      )}
    </Dialog>
  );
}
