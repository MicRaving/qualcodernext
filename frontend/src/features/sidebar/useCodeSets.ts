/**
 * Code-set domain for the sidebar: list/active/applied state, CRUD actions,
 * membership editor state and the path-labeled code options list.
 * Extracted from components/shell/Sidebar.tsx — behavior-neutral.
 */
import { useEffect, useMemo, useState } from "react";
import {
  addCodeSetMembers,
  createCodeSet,
  deleteCodeSet,
  getCodeSet,
  listCodeSets,
  removeCodeSetMembers,
  renameCodeSet,
  type CodeSetSummary,
} from "@/lib/codeSetsApi";
import type { CodeTreeItem } from "@/lib/api";
import { useProjectStore } from "@/stores/project";
import { errorMessage } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import type { CodeSetOption } from "@/features/sidebar/CodeSetMembersModal";

export function useCodeSets(opts: {
  projectOpen: boolean;
  /** The sidebar's toolbar error banner. */
  onError: (msg: string | null) => void;
}) {
  const { projectOpen, onError } = opts;
  const { t } = useI18n();
  const toast = useToast();
  const codeTree = useProjectStore((s) => s.codeTree);

  const [codeSets, setCodeSets] = useState<CodeSetSummary[]>([]);
  const [activeSetId, setActiveSetId] = useState<number | null>(null);
  const [appliedSet, setAppliedSet] = useState<{ id: number; name: string; cids: Set<number> } | null>(null);
  const [manageMenu, setManageMenu] = useState<{ x: number; y: number } | null>(null);
  const [membersEditor, setMembersEditor] = useState<{ set: CodeSetSummary; members: Set<number> } | null>(null);

  // Refresh the set list whenever a project opens/closes. The applied
  // filter is a client-side snapshot and is dropped on close.
  useEffect(() => {
    if (!projectOpen) {
      setCodeSets([]);
      setActiveSetId(null);
      setAppliedSet(null);
      return;
    }
    listCodeSets()
      .then((sets) => {
        setCodeSets(sets);
        setActiveSetId((prev) =>
          prev != null && sets.some((s) => s.id === prev) ? prev : (sets[0]?.id ?? null),
        );
      })
      .catch((e) => {
        onError(errorMessage(e, t("codeSets.loadError")));
      });
  }, [projectOpen, t, onError]);

  /** Apply the active set: snapshot its members and filter the tree. */
  async function applyCodeSet() {
    if (activeSetId == null) return;
    onError(null);
    try {
      const detail = await getCodeSet(activeSetId);
      const set = codeSets.find((s) => s.id === activeSetId);
      const name = set?.name ?? `${activeSetId}`;
      setAppliedSet({ id: activeSetId, name, cids: new Set(detail.members.map((m) => m.cid)) });
      toast.success(t("codeSets.applied", { name }));
    } catch (e) {
      const detail = errorMessage(e, t("codeSets.applyError"));
      onError(detail);
      toast.error(detail);
    }
  }

  async function createSet() {
    const name = window.prompt(t("codeSets.createPrompt"));
    if (name == null) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    onError(null);
    try {
      const created = await createCodeSet(trimmed);
      setCodeSets((prev) => [...prev, created]);
      setActiveSetId(created.id);
      toast.success(t("codeSets.created", { name: trimmed }));
    } catch (e) {
      const detail = errorMessage(e, t("codeSets.createError"));
      onError(detail);
      toast.error(detail);
    }
  }

  async function renameActiveSet() {
    const set = codeSets.find((s) => s.id === activeSetId);
    if (!set) return;
    const name = window.prompt(t("codeSets.renamePrompt", { name: set.name }), set.name);
    if (name == null) return;
    const trimmed = name.trim();
    if (!trimmed || trimmed === set.name) return;
    onError(null);
    try {
      const updated = await renameCodeSet(set.id, trimmed);
      setCodeSets((prev) => prev.map((s) => (s.id === set.id ? { ...s, name: updated.name } : s)));
      if (appliedSet?.id === set.id) setAppliedSet({ ...appliedSet, name: updated.name });
      toast.success(t("codeSets.renamed", { name: trimmed }));
    } catch (e) {
      const detail = errorMessage(e, t("codeSets.renameError"));
      onError(detail);
      toast.error(detail);
    }
  }

  async function deleteActiveSet() {
    const set = codeSets.find((s) => s.id === activeSetId);
    if (!set) return;
    if (!window.confirm(t("codeSets.deleteConfirm", { name: set.name }))) return;
    onError(null);
    try {
      await deleteCodeSet(set.id);
      setCodeSets((prev) => prev.filter((s) => s.id !== set.id));
      if (appliedSet?.id === set.id) setAppliedSet(null);
      setActiveSetId(null);
      toast.success(t("codeSets.deleted", { name: set.name }));
    } catch (e) {
      const detail = errorMessage(e, t("codeSets.deleteError"));
      onError(detail);
      toast.error(detail);
    }
  }

  /** Open the membership editor for the active set (fetches its members). */
  async function openMembersEditor() {
    const set = codeSets.find((s) => s.id === activeSetId);
    if (!set) return;
    onError(null);
    try {
      const detail = await getCodeSet(set.id);
      setMembersEditor({ set, members: new Set(detail.members.map((m) => m.cid)) });
    } catch (e) {
      const detail = errorMessage(e, t("codeSets.loadError"));
      onError(detail);
      toast.error(detail);
    }
  }

  /** Sync the editor's checked codes: add/remove the diff, refresh counts,
   *  and re-snapshot the filter when the applied set was edited. */
  async function saveMembers(cids: number[]) {
    if (!membersEditor) return;
    const { set, members } = membersEditor;
    const toAdd = cids.filter((c) => !members.has(c));
    const toRemove = [...members].filter((c) => !cids.includes(c));
    if (toAdd.length > 0) await addCodeSetMembers(set.id, toAdd);
    if (toRemove.length > 0) await removeCodeSetMembers(set.id, toRemove);
    const updated = await listCodeSets();
    setCodeSets(updated);
    if (appliedSet?.id === set.id) {
      const detail = await getCodeSet(set.id);
      setAppliedSet({
        id: set.id,
        name: set.name,
        cids: new Set(detail.members.map((m) => m.cid)),
      });
    }
    setMembersEditor(null);
    toast.success(t("codeSets.membersSaved"));
  }

  /** Every code of the project as a path-labeled option list for the
   *  membership editor. Cycle-guarded like the backend tree (legacy
   *  projects can have self-references). */
  const codeSetOptions = useMemo<CodeSetOption[]>(() => {
    const cats = new Map<number, CodeTreeItem>();
    const codes = new Map<number, CodeTreeItem>();
    for (const item of codeTree) {
      if (item.kind === "category") cats.set(item.id, item);
      else codes.set(item.id, item);
    }
    const pathOf = (item: CodeTreeItem): string => {
      const parts: string[] = [];
      const seen = new Set<string>();
      let cur: CodeTreeItem | undefined = item;
      while (cur && !seen.has(`${cur.kind}:${cur.id}`)) {
        seen.add(`${cur.kind}:${cur.id}`);
        parts.push(cur.name);
        if (cur.kind === "category" || !cur.subcode) {
          cur = cur.parent_id != null ? cats.get(cur.parent_id) : undefined;
        } else {
          cur = cur.parent_id != null ? codes.get(cur.parent_id) : undefined;
        }
      }
      parts.reverse();
      return parts.join(" / ");
    };
    return codeTree
      .filter((item) => item.kind === "code")
      .map((item) => ({ cid: item.id, label: pathOf(item), color: item.color }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [codeTree]);

  return {
    codeSets,
    activeSetId,
    setActiveSetId,
    appliedSet,
    setAppliedSet,
    manageMenu,
    setManageMenu,
    membersEditor,
    setMembersEditor,
    applyCodeSet,
    createSet,
    renameActiveSet,
    deleteActiveSet,
    openMembersEditor,
    saveMembers,
    codeSetOptions,
  };
}
