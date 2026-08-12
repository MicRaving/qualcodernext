/**
 * Accessibility controls: the display mode drop-down (visual impairments /
 * screen readers) and a compact screen-reader toggle. Mounted in the
 * dashboard and in the Settings view (General section).
 */
import { Accessibility } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { useProjectStore, type A11yMode } from "@/stores/project";
import { Select } from "@/components/ui/orchestrator";

const A11Y_MODES: { mode: A11yMode; labelKey: string; hintKey: string }[] = [
  { mode: "off", labelKey: "a11y.off", hintKey: "a11y.offHint" },
  { mode: "screenreader", labelKey: "a11y.screenreader", hintKey: "a11y.screenreaderHint" },
  { mode: "high-contrast", labelKey: "a11y.highContrast", hintKey: "a11y.highContrastHint" },
  { mode: "large-text", labelKey: "a11y.largeText", hintKey: "a11y.largeTextHint" },
  { mode: "reduced-motion", labelKey: "a11y.reducedMotion", hintKey: "a11y.reducedMotionHint" },
  { mode: "colorblind", labelKey: "a11y.colorblind", hintKey: "a11y.colorblindHint" },
];

function A11yModePicker() {
  const { t } = useI18n();
  const a11yMode = useProjectStore((s) => s.a11yMode);
  const setA11yMode = useProjectStore((s) => s.setA11yMode);
  const current = A11Y_MODES.find((m) => m.mode === a11yMode) ?? A11Y_MODES[0];
  return (
    <div className="flex flex-col gap-1">
      <Select
        value={a11yMode}
        onChange={(e) => setA11yMode(e.target.value as A11yMode)}
        className="w-full"
        aria-label={t("a11y.mode")}
      >
        {A11Y_MODES.map((m) => (
          <option key={m.mode} value={m.mode}>
            {t(m.labelKey)}
          </option>
        ))}
      </Select>
      <p className="text-xs text-text-secondary">{t(current.hintKey)}</p>
    </div>
  );
}

/** Compact variant used on the dashboard (label + drop-down). */
export function A11yControls() {
  const { t } = useI18n();
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 text-xs font-medium text-text-secondary">
        <Accessibility size={14} aria-hidden />
        <span>{t("a11y.section")}</span>
      </div>
      <A11yModePicker />
    </div>
  );
}

/** Screen-reader-only focus helper: a visible skip link when SR mode is on. */
export function A11ySkipLink() {
  const { t } = useI18n();
  const a11yMode = useProjectStore((s) => s.a11yMode);
  if (a11yMode !== "screenreader") return null;
  return (
    <a
      href="#qc-main"
      className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-[100] focus:rounded-sm focus:bg-accent focus:px-2 focus:py-1 focus:text-xs focus:text-white"
    >
      {t("a11y.skipLink")}
    </a>
  );
}
