/**
 * Shared weight stepper (Minus / value / Plus, clamped 0–100) used in the
 * coder details footers and memo-gutter cards — previously four divergent
 * copies (Av/Image/Pdf + DetailsBars).
 */
import { Minus, Plus } from "lucide-react";
import { IconButton } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";

export function WeightStepper(props: {
  value: number;
  onChange: (next: number) => void;
  size?: 12 | 13 | 14;
}) {
  const { t } = useI18n();
  const { value, onChange, size = 12 } = props;
  return (
    <span className="flex items-center gap-0.5">
      <IconButton
        size="row"
        label={t("coder.weightDown")}
        title={t("coder.weightDown")}
        disabled={value <= 0}
        onClick={() => onChange(Math.max(0, value - 10))}
      >
        <Minus size={size} aria-hidden />
      </IconButton>
      <span className="min-w-5 text-center text-xs text-text-secondary" aria-label={t("coder.weight")}>
        {value}
      </span>
      <IconButton
        size="row"
        label={t("coder.weightUp")}
        title={t("coder.weightUp")}
        disabled={value >= 100}
        onClick={() => onChange(Math.min(100, value + 10))}
      >
        <Plus size={size} aria-hidden />
      </IconButton>
    </span>
  );
}
