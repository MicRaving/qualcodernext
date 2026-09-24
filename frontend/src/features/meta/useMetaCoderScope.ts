/**
 * Keep the meta-analysis coder scope pinned to the app's current coder.
 *
 * The meta module writes (screening verdicts, extractions, conflict
 * resolution, analysis owner) default to the scoped coder; QCnext's current
 * coder is the source of truth until the user explicitly picks another scope
 * in the left bar (`coderScopeCustom`). Switching coders dispatches
 * `qc:codings-changed`, which also updates `coderName`; the scope follows it.
 */
import { useEffect } from "react";
import { useCoderStore } from "@/stores/coder";
import { useWorkspaceStore } from "@/stores/workspace";

export function useMetaCoderScope(): void {
  const coderName = useCoderStore((s) => s.coderName);
  useEffect(() => {
    const { metaUi, setMetaUi } = useWorkspaceStore.getState();
    if (!metaUi.coderScopeCustom && metaUi.coderScope !== coderName) {
      setMetaUi({ coderScope: coderName });
    }
  }, [coderName]);
}
