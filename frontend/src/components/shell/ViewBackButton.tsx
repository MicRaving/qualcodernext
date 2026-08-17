/**
 * ViewBackButton - the uniform back button, first element of every center
 * view header. Returns to the Files view.
 */
import { ArrowLeft } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { useWorkspaceStore } from "@/stores/workspace";
import { cls } from "@/components/ui/tokens";

export function ViewBackButton() {
  const { t } = useI18n();
  const setView = useWorkspaceStore((s) => s.setView);
  return (
    <button
      type="button"
      onClick={() => setView({ kind: "files" })}
      aria-label={t("coder.back")}
      title={t("coder.back")}
      className={cls.ghost}
    >
      <ArrowLeft size={16} aria-hidden />
    </button>
  );
}
