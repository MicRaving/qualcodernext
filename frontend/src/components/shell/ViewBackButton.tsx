/**
 * ViewBackButton — the uniform back button, first element of every center
 * view header. Returns to the Files view.
 */
import { ArrowLeft } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

export function ViewBackButton() {
  const { t } = useI18n();
  const setView = useProjectStore((s) => s.setView);
  return (
    <button
      type="button"
      onClick={() => setView({ kind: "files" })}
      aria-label={t("coder.back")}
      title={t("coder.back")}
      className="rounded-sm p-1.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
    >
      <ArrowLeft size={16} aria-hidden />
    </button>
  );
}
