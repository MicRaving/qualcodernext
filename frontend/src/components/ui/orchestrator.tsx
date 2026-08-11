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
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { LoaderCircle, X } from "lucide-react";
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
  /** Show the uniform back button (default true). */
  back?: boolean;
  /** Interaction buttons rendered on the right. */
  actions?: ReactNode;
}

/** Center-view header: [back] [title] [meta] … [actions]. */
export function ViewHeader({ title, meta, back = true, actions, children, ...rest }: ViewHeaderProps) {
  return (
    <header className={cls.bar} {...rest}>
      {back && <ViewBackButton />}
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

/** Compact left/right bar header (h-5): [title] [count] … [actions]. */
export function BarHeader({ title, count, actions, children, ...rest }: BarHeaderProps) {
  return (
    <header className={cls.compactBar} {...rest}>
      <h1 className="truncate text-xs font-semibold text-text-primary">{title}</h1>
      {count !== undefined && <CountBadge value={count} />}
      <div className="flex-1" />
      {children ?? actions}
    </header>
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
