import { useEffect, useRef, type ReactNode } from "react";

const SIDE_PANEL_QUERY = "(min-width: 1280px)";

export function Dialog({
  title,
  onClose,
  children,
  contextual = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  contextual?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const previousFocus = useRef(document.activeElement as HTMLElement);
  const latestClose = useRef(onClose);
  useEffect(() => {
    latestClose.current = onClose;
  });
  useEffect(() => {
    const dialog = ref.current;
    const sidePanel = contextual ? window.matchMedia(SIDE_PANEL_QUERY) : null;
    const present = () => {
      if (dialog?.open) dialog.close();
      if (sidePanel?.matches) dialog?.show();
      else dialog?.showModal();
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (
        event.key === "Escape" &&
        !event.defaultPrevented &&
        sidePanel?.matches
      )
        latestClose.current();
    };
    present();
    sidePanel?.addEventListener?.("change", present);
    if (contextual) document.addEventListener("keydown", closeOnEscape);
    return () => {
      sidePanel?.removeEventListener?.("change", present);
      document.removeEventListener("keydown", closeOnEscape);
      dialog?.close();
      previousFocus.current?.focus();
    };
  }, [contextual]);
  return (
    <dialog
      className={contextual ? "inspector-dialog" : undefined}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        }
      }}
      ref={ref}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target !== e.currentTarget) return;
        const bounds = e.currentTarget.getBoundingClientRect();
        if (
          e.clientX < bounds.left ||
          e.clientX > bounds.right ||
          e.clientY < bounds.top ||
          e.clientY > bounds.bottom
        )
          onClose();
      }}
    >
      <div className="dialog-heading">
        <h2>{title}</h2>
        <button autoFocus aria-label={`Close ${title}`} onClick={onClose}>
          ✕
        </button>
      </div>
      {children}
    </dialog>
  );
}
