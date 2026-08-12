/**
 * InlineNameEdit — inplace name editing for list rows (left bars).
 *
 * Renders an auto-focused input; Enter or blur saves, Escape cancels, and
 * Tab jumps the edit to the NEXT row (the parent hands back the next item
 * id). The system-prompt rename flow is gone: rows switch into this editor
 * and the change applies directly.
 */
import { useEffect, useRef, useState } from "react";

export interface InlineNameEditProps {
  value: string;
  placeholder?: string;
  autoFocus?: boolean;
  onSave: (name: string) => void;
  onCancel: () => void;
  /** Called with the id of the row that should take over the edit (Tab). */
  onTab?: () => void;
}

export function InlineNameEdit({
  value,
  placeholder,
  autoFocus = true,
  onSave,
  onCancel,
  onTab,
}: InlineNameEditProps) {
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const doneRef = useRef(false);

  useEffect(() => {
    if (autoFocus && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [autoFocus]);

  function commit() {
    if (doneRef.current) return;
    doneRef.current = true;
    const name = draft.trim();
    if (name && name !== value) onSave(name);
    else onCancel();
  }

  return (
    <input
      ref={inputRef}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      placeholder={placeholder}
      aria-label={placeholder}
      data-testid="inline-name-edit"
      className="h-6 w-full min-w-0 rounded-sm border border-accent bg-bg px-1.5 text-sm text-text-primary outline-none"
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
        } else if (e.key === "Escape") {
          e.preventDefault();
          doneRef.current = true;
          onCancel();
        } else if (e.key === "Tab") {
          e.preventDefault();
          doneRef.current = true;
          const name = draft.trim();
          if (name && name !== value) onSave(name);
          onTab?.();
        }
      }}
      onBlur={commit}
    />
  );
}
