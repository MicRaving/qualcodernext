/**
 * Minimal toast notification system (no dependencies).
 *
 * Mount `<ToastProvider>` once at the root, then call `useToast()` anywhere
 * below it to push success / error / info notifications.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { CheckCircle2, CircleAlert, Info, X, type LucideIcon } from "lucide-react";
import { IconButton } from "@/components/ui/orchestrator";
import {
  addToast,
  removeToast,
  type Toast,
  type ToastKind,
} from "@/lib/toast-core";
import { designTokens } from "@/lib/tokens";

const SUCCESS_DURATION = 4000;
const ERROR_DURATION = 7000;
const INFO_DURATION = 4000;
const EXIT_DURATION = parseInt(designTokens.motion.fast, 10);

const KIND_ICON: Record<ToastKind, LucideIcon> = {
  success: CheckCircle2,
  error: CircleAlert,
  info: Info,
};

const KIND_BORDER: Record<ToastKind, string> = {
  success: "border-success/50",
  error: "border-danger/50",
  info: "border-border",
};

const KIND_TEXT: Record<ToastKind, string> = {
  success: "text-success",
  error: "text-danger",
  info: "text-text-secondary",
};

function kindDuration(kind: ToastKind): number {
  switch (kind) {
    case "success":
      return SUCCESS_DURATION;
    case "error":
      return ERROR_DURATION;
    case "info":
      return INFO_DURATION;
  }
}

interface ToastApi {
  success(message: string): void;
  error(message: string): void;
  info(message: string): void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return ctx;
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setLeaving(true), kindDuration(toast.kind));
    return () => window.clearTimeout(timer);
  }, [toast.id, toast.kind]);

  useEffect(() => {
    if (!leaving) return;
    const timer = window.setTimeout(() => onDismiss(toast.id), EXIT_DURATION);
    return () => window.clearTimeout(timer);
  }, [leaving, toast.id, onDismiss]);

  const Icon = KIND_ICON[toast.kind];
  return (
    <div
      role="status"
      className={`qc-toast ${leaving ? "qc-toast-out" : ""} rounded-lg border bg-surface px-3 py-2 shadow-qc-md ${KIND_BORDER[toast.kind]}`}
    >
      <div className="flex items-start gap-2">
        <Icon size={14} className={`mt-px shrink-0 ${KIND_TEXT[toast.kind]}`} aria-hidden />
        <p className="min-w-0 flex-1 text-sm font-medium text-text-primary">{toast.message}</p>
        <IconButton
          label="Dismiss notification"
          size="sm"
          onClick={() => setLeaving(true)}
        >
          <X size={12} aria-hidden />
        </IconButton>
      </div>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((kind: ToastKind, message: string) => {
    setToasts((prev) => addToast(prev, kind, message));
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => removeToast(prev, id));
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      success: (message: string) => push("success", message),
      error: (message: string) => push("error", message),
      info: (message: string) => push("info", message),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        role="region"
        aria-label="Notifications"
        className="fixed bottom-4 right-4 z-50 flex w-80 max-w-[90vw] flex-col gap-2"
      >
        {toasts.map((t) => (
          <ToastCard key={t.id} toast={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
