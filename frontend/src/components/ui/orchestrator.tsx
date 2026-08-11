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
  useEffect,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type ThHTMLAttributes,
} from "react";
import { ArrowLeft, LoaderCircle, X } from "lucide-react";
import { ViewBackButton } from "@/components/shell/ViewBackButton";
import { cls } from "@/components/ui/tokens";

/* ------------------------------------------------------------------ */
/* Buttons                                                             */
/* ------------------------------------------------------------------ */

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "primaryCompact" | "secondary" | "danger";
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
  size?: "sm" | "md";
}

/** Ghost icon button with a mandatory accessible name. */
export function IconButton({ label, title, size = "md", className = "", children, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={title ?? label}
      className={`${size === "sm" ? cls.ghostSmall : cls.ghost} ${className}`}
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
}

/** Center-view header: [back] [title] [meta] … [actions]. */
export function ViewHeader({ title, meta, back = true, actions, children, ...rest }: ViewHeaderProps) {
  return (
    <header className={cls.bar} {...rest}>
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
      <h1 className="truncate text-sm font-semibold text-text-primary">{title}</h1>
      {count !== undefined && <CountBadge value={count} />}
      <div className="flex-1" />
      {children ?? actions}
    </header>
  );
}

export interface LeftBarProps extends HTMLAttributes<HTMLElement> {
  width?: "sm" | "md";
  /** Which side the border sits on (right by default, left for the
   *  Inspector). */
  borderSide?: "r" | "l";
  /** Fixed header row (rendered OUTSIDE the scrollable area). */
  header?: ReactNode;
}

/** The uniform left/right bar shell: fixed header + scrollable body. */
export function LeftBar({
  width = "md",
  borderSide = "r",
  header,
  children,
  className = "",
  ...rest
}: LeftBarProps) {
  return (
    <aside
      className={`flex ${width === "sm" ? "w-64" : "w-72"} shrink-0 flex-col ${
        borderSide === "r" ? "border-r" : "border-l"
      } border-border bg-surface ${className}`}
      {...rest}
    >
      {header}
      <div className="qc-scroll min-h-0 flex-1 overflow-y-auto">{children}</div>
    </aside>
  );
}

/* ------------------------------------------------------------------ */
/* Small parts                                                         */
/* ------------------------------------------------------------------ */

export function CountBadge({ value }: { value: number | string }) {
  return <span className={cls.countBadge}>{value}</span>;
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
}: {
  children: ReactNode;
  onClose?: () => void;
}) {
  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-danger bg-danger/10 px-3 py-1.5 text-sm text-danger">
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
