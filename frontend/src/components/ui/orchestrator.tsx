/**
 * Design orchestrator — the single source of UI primitives.
 *
 * Every view builds its chrome from these parts instead of hardcoding
 * design classes. The layout slots (ribbon / menu bar / left bar / center /
 * right bar) come from `WorkspaceLayout`; the parts below are the building
 * blocks that fill them.
 *
 * Classes are centralized here so a design change lands in ONE place.
 */
import {
  useContext,
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
  type ThHTMLAttributes,
} from "react";
import { ArrowLeft, CircleAlert, LoaderCircle, X } from "lucide-react";
import { ViewBackButton } from "@/components/shell/ViewBackButton";
import { cls } from "@/components/ui/tokens";
import { BarWidthContext, useIsCompactBar } from "@/components/ui/barWidth";
import { useI18n } from "@/lib/i18n";

/* ------------------------------------------------------------------ */
/* Buttons                                                             */
/* ------------------------------------------------------------------ */

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?:
    | "primary"
    | "primaryCompact"
    | "secondary"
    | "danger"
    | "toolbar"
    | "toolbarPrimary"
    | "toolbarDanger"
    | "toolbarIcon"
    | "toolbarIconPrimary";
  icon?: ReactNode;
}

export function Button({ variant = "secondary", icon, className = "", children, ...rest }: ButtonProps) {
  const base =
    variant === "primary"
      ? cls.primary
      : variant === "primaryCompact"
        ? cls.primaryCompact
        : variant === "danger"
          ? cls.danger
          : variant === "toolbar"
            ? cls.toolbarBtn
            : variant === "toolbarPrimary"
              ? cls.toolbarBtnPrimary
              : variant === "toolbarDanger"
                ? cls.toolbarBtnDanger
                : variant === "toolbarIcon"
                  ? cls.toolbarIconBtn
                  : variant === "toolbarIconPrimary"
                    ? cls.toolbarIconBtnPrimary
                    : cls.secondary;
  return (
    <button type="button" className={`flex items-center gap-1 ${base} ${className}`} {...rest}>
      {icon}
      {children}
    </button>
  );
}

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  title?: string;
  size?: "sm" | "md" | "row";
}

/** Ghost icon button with a mandatory accessible name. */
export function IconButton({ label, title, size = "md", className = "", children, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={title ?? label}
      className={`${
        size === "sm" ? cls.ghostSmall : size === "row" ? cls.ghostRow : cls.ghost
      } ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Bars and headers                                                    */
/* ------------------------------------------------------------------ */

export interface ViewHeaderProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  /** The name of the open thing, shown after the back button. */
  title: ReactNode;
  /** Secondary meta text after the title (memo, version, date…). */
  meta?: ReactNode;
  /** Show the uniform back button (default true); a function overrides
   *  the default "back to Files" navigation. */
  back?: boolean | (() => void);
  /** Interaction buttons rendered on the right. */
  actions?: ReactNode;
  /** Allow the row to wrap to a second line (coder headers with many
   *  controls). */
  wrap?: boolean;
}

/** Center-view header: [back] [title] [meta] … [actions]. */
export function ViewHeader({ title, meta, back = true, actions, wrap = false, children, ...rest }: ViewHeaderProps) {
  return (
    <header className={wrap ? cls.barWrap : cls.bar} {...rest}>
      {back !== false &&
        (typeof back === "function" ? (
          <button
            type="button"
            onClick={back}
            aria-label="Back"
            title="Back"
            className={cls.ghost}
          >
            <ArrowLeft size={16} aria-hidden />
          </button>
        ) : (
          <ViewBackButton />
        ))}
      <h1 className="min-w-0 truncate text-sm font-semibold text-text-primary">{title}</h1>
      {meta && <span className="hidden min-w-0 truncate text-xs text-text-secondary xl:inline">{meta}</span>}
      <div className="flex-1" />
      {children ?? actions}
    </header>
  );
}

export interface BarHeaderProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  title: ReactNode;
  count?: number | string;
  /** Right-side actions (add/import buttons, dropdowns…). */
  actions?: ReactNode;
}

/** Left/right bar header (h-10, same height as the center header):
 *  [title] [count] … [actions]. Never part of the scrollable area. */
export function BarHeader({ title, count, actions, children, ...rest }: BarHeaderProps) {
  return (
    <header className={cls.bar} {...rest}>
      <h1 className="min-w-0 truncate text-sm font-semibold text-text-primary">{title}</h1>
      {count !== undefined && <CountBadge value={count} />}
      <div className="flex-1" />
      {children ?? actions}
    </header>
  );
}

/** Responsive bar title: icon + label, hides label when the bar is too narrow
 *  (shows icon + counter via BarHeader's count prop, or icon only for right bars). */
export function BarTitle({
  icon: Icon,
  label,
}: {
  icon: React.ComponentType<{ size?: number; className?: string; "aria-hidden"?: boolean }>;
  label: string;
}) {
  const isCompact = useIsCompactBar();
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <Icon size={15} className="shrink-0" aria-hidden />
      {!isCompact && <span className="truncate">{label}</span>}
    </span>
  );
}

/** Pixel width injected by WorkspaceLayout's border-drag resize (null when
 *  the bar should use its preset width). */
export interface LeftBarProps extends HTMLAttributes<HTMLElement> {
  width?: "sm" | "md" | "lg";
  /** Exact pixel width (overrides the preset widths). */
  widthPx?: number;
  /** Which side the border sits on (right by default, left for the
   *  Inspector). */
  borderSide?: "r" | "l";
  /** Fixed header row (rendered OUTSIDE the scrollable area). */
  header?: ReactNode;
  /** Fixed footer row (rendered OUTSIDE the scrollable area, at the very
   *  bottom). */
  footer?: ReactNode;
  /** Wrap children in the scrollable body (default true; set false for
   *  panes that manage their own scrolling, e.g. the AI chat). */
  scroll?: boolean;
}

/** The uniform left/right bar shell: fixed header + scrollable body. */
export function LeftBar({
  width = "md",
  widthPx,
  borderSide = "r",
  header,
  footer,
  scroll = true,
  children,
  className = "",
  style,
  ...rest
}: LeftBarProps) {
  const ctxWidth = useContext(BarWidthContext);
  const resolved = ctxWidth ?? widthPx;
  return (
    <aside
      className={`flex ${
        width === "sm" ? "w-64" : width === "lg" ? "w-96" : "w-72"
      } shrink-0 flex-col ${
        borderSide === "r" ? "border-r" : "border-l"
      } border-border bg-surface ${className}`}
      style={resolved != null ? { ...style, width: resolved } : style}
      {...rest}
    >
      {header}
      {scroll ? <div className="qc-scroll min-h-0 flex-1 overflow-y-auto">{children}</div> : children}
      {footer}
    </aside>
  );
}

/* ------------------------------------------------------------------ */
/* Inputs                                                              */
/* ------------------------------------------------------------------ */

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  className?: string;
}

export function Input({ className = "", ...rest }: InputProps) {
  return <input className={`${cls.input} ${className}`} {...rest} />;
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  className?: string;
}

export function Select({ className = "", ...rest }: SelectProps) {
  return <select className={`${cls.select} ${className}`} {...rest} />;
}

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  className?: string;
}

export function Textarea({ className = "", ...rest }: TextareaProps) {
  return <textarea className={`${cls.textarea} ${className}`} {...rest} />;
}

export function Field({ label, children, className = "" }: { label: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={`block ${className}`}>
      <span className={cls.fieldLabel}>{label}</span>
      {children}
    </label>
  );
}

/* ------------------------------------------------------------------ */
/* Modals and menus                                                    */
/* ------------------------------------------------------------------ */

const MODAL_SIZES = {
  sm: "w-80 max-w-[92vw]",
  md: "w-[26rem] max-w-[92vw]",
  lg: "w-[32rem] max-w-[92vw]",
  xl: "w-[36rem] max-w-[92vw]",
} as const;

export interface ModalProps {
  open: boolean;
  /** Enables the close X, Escape and backdrop-click dismissal. */
  onClose?: () => void;
  /** Title rendered in the default header (with the close X). */
  title?: ReactNode;
  /** Small icon before the title. */
  icon?: ReactNode;
  /** Panel width; ignored when panelClassName is given. */
  size?: keyof typeof MODAL_SIZES;
  /** Replaces the panel class entirely (custom width, pointer-events…). */
  panelClassName?: string;
  /** Overrides the overlay classes (e.g. pointer-events-none). */
  overlayClassName?: string;
  /** Keeps the X visible but inert and blocks Escape/backdrop (busy forms). */
  closeDisabled?: boolean;
  /** Accessible name (falls back to `title` when it is a string). */
  ariaLabel?: string;
  /** Actions rendered in the header between the spacer and the close X. */
  headerActions?: ReactNode;
  children?: ReactNode;
}

/** The uniform modal: overlay + panel (+ optional header). Handles Escape
 *  and backdrop-click dismissal itself — views never re-implement it. */
export function Modal({
  open,
  onClose,
  title,
  icon,
  size = "md",
  panelClassName,
  overlayClassName = "",
  closeDisabled = false,
  ariaLabel,
  headerActions,
  children,
}: ModalProps) {
  useEffect(() => {
    if (!open || !onClose) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !closeDisabled) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, closeDisabled]);

  if (!open) return null;
  return (
    <div
      className={`${cls.modalOverlay} qc-modal-backdrop ${overlayClassName}`}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !closeDisabled) onClose?.();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={typeof title === "string" ? title : ariaLabel}
    >
      <div className={`${cls.modalPanel} qc-modal-panel ${panelClassName ?? MODAL_SIZES[size]}`}>
        {title !== undefined && (
          <div className={cls.modalHeader}>
            {icon}
            <span className="truncate text-sm font-semibold text-text-primary">{title}</span>
            <div className="flex-1" />
            {headerActions}
            <IconButton
              label="Close"
              size="sm"
              onClick={onClose}
              disabled={closeDisabled}
              className="disabled:opacity-40"
            >
              <X size={14} aria-hidden />
            </IconButton>
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

export function Menu({
  className = "",
  position = "absolute",
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { position?: "absolute" | "fixed" }) {
  return (
    <div
      className={`${
        position === "fixed"
          ? "fixed z-40 rounded-md border border-border bg-surface py-1 shadow-qc-md"
          : cls.menu
      } qc-popover ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

export interface MenuItemProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  className?: string;
}

export function MenuItem({ className = "", children, ...rest }: MenuItemProps) {
  return (
    <button type="button" className={`${cls.menuItem} ${className}`} {...rest}>
      {children}
    </button>
  );
}

/**
 * HelpFlyout — a consistent question-mark popover. Renders fixed at the
 * anchor button, clamped inside the window (never cut off by boundaries),
 * closes on outside click or Escape.
 */
export function HelpFlyout({
  anchor,
  onClose,
  children,
  className = "",
}: {
  anchor: HTMLElement | null;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  useEffect(() => {
    const place = () => {
      const a = anchor?.getBoundingClientRect();
      const el = ref.current;
      if (!a || !el) return;
      const w = el.offsetWidth;
      const h = el.offsetHeight;
      const left = Math.max(8, Math.min(a.left, window.innerWidth - w - 8));
      let top = a.bottom + 6;
      if (top + h > window.innerHeight - 8) {
        top = Math.max(8, a.top - h - 6);
      }
      setPos({ left, top });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [anchor]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (target && !ref.current?.contains(target) && !anchor?.contains(target)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [anchor, onClose]);

  return (
    <div
      ref={ref}
      role="dialog"
      className={`fixed z-50 w-72 p-3 ${cls.popup} ${pos ? "qc-popover" : ""} ${className}`}
      style={pos ? { left: pos.left, top: pos.top } : { visibility: "hidden" }}
    >
      {children}
    </div>
  );
}

export interface TableHeadProps extends ThHTMLAttributes<HTMLTableCellElement> {
  className?: string;
}

export function TableHead({ className = "", children, ...rest }: TableHeadProps) {
  return (
    <th className={`${cls.tableHead} ${className}`} {...rest}>
      {children}
    </th>
  );
}

/* ------------------------------------------------------------------ */
/* Small parts                                                         */
/* ------------------------------------------------------------------ */

export function CountBadge({ value }: { value: number | string }) {
  return <span className={cls.countBadge}>{value}</span>;
}

/** Neutral status pill (positions, scopes, counts); `tone="accent"` for
 *  new/selected markers; `size="md"` for report-row badges (text-xs). */
export function Pill({
  tone = "neutral",
  size = "sm",
  className = "",
  children,
}: {
  tone?: "neutral" | "accent";
  size?: "sm" | "md";
  className?: string;
  children: ReactNode;
}) {
  const sizeCls = size === "md" ? "text-xs" : "";
  return (
    <span className={`${tone === "accent" ? cls.pillAccent : cls.pill} ${sizeCls} ${className}`}>
      {children}
    </span>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return <div className={`mb-1 ${cls.sectionLabel}`}>{children}</div>;
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`${cls.card} ${className}`}>{children}</div>;
}

export function ErrorBanner({
  children,
  onClose,
  tone = "danger",
}: {
  children: ReactNode;
  onClose?: () => void;
  tone?: "danger" | "warning" | "success";
}) {
  const bannerCls =
    tone === "warning"
      ? "flex shrink-0 items-center gap-2 border-b border-warning bg-warning/10 px-3 py-1.5 text-sm text-warning"
      : tone === "success"
        ? "flex shrink-0 items-center gap-2 border-b border-border bg-surface px-3 py-1.5 text-sm text-success"
        : "flex shrink-0 items-center gap-2 border-b border-danger bg-danger/10 px-3 py-1.5 text-sm text-danger";
  return (
    <div className={`${bannerCls} qc-enter-fade`} role="status">
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {onClose && (
        <IconButton label="Dismiss" size="sm" onClick={onClose} className="text-danger hover:text-danger">
          <X size={12} aria-hidden />
        </IconButton>
      )}
    </div>
  );
}

export function LoadingState({ children }: { children?: ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center gap-2 bg-bg text-text-secondary">
      <LoaderCircle size={16} className="animate-spin" aria-hidden />
      {children ?? "Loading…"}
    </div>
  );
}

export function EmptyState({ icon, children }: { icon?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex h-full flex-1 flex-col items-center justify-center gap-2 text-text-secondary">
      {icon}
      <p className="text-sm">{children}</p>
    </div>
  );
}

/** The uniform toggle switch (settings rows, panes). */
export function Toggle({
  checked,
  onChange,
  label,
  ariaLabel,
  hint,
}: {
  checked: boolean;
  onChange: () => void;
  label?: ReactNode;
  ariaLabel?: string;
  hint?: ReactNode;
}) {
  return (
    <div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={ariaLabel ?? (typeof label === "string" ? label : undefined)}
        onClick={onChange}
        className="flex items-center gap-2"
      >
        <span
          className={`relative h-4 w-8 shrink-0 rounded-full transition-colors ${
            checked ? "bg-accent" : "bg-border"
          }`}
        >
          <span
            className="absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all"
            style={{ left: checked ? 18 : 2 }}
          />
        </span>
        {label != null && <span className="text-xs text-text-primary">{label}</span>}
      </button>
      {hint != null && <p className="mt-1 text-xs text-text-secondary">{hint}</p>}
    </div>
  );
}

/** Full-surface load error with a retry button (coder surfaces). */
export function LoadError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex h-full items-center justify-center bg-bg">
      <div className="max-w-md text-center">
        <p className="flex items-center justify-center gap-1.5 text-sm text-danger">
          <CircleAlert size={16} aria-hidden />
          {message}
        </p>
        <Button variant="secondary" className="mt-3" onClick={onRetry}>
          {t("common.retry")}
        </Button>
      </div>
    </div>
  );
}
