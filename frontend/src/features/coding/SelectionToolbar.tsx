/**
 * SelectionToolbar — floating coding toolbar for a text selection: code
 * with the active code (or pick/create one), annotate, in-vivo, segment
 * links (copy / paste) and "send to QTT". Owns ALL popover state (annotate,
 * in-vivo, QTT sheet picker, code picker) and every mutation it triggers,
 * so any coder surface can reuse it — the text coder and the CSV table view
 * both mount it next to their selection.
 *
 * Contract with the host:
 * - `anchor` / `selection` — where to show the popup and what it operates
 *   on (selection is in document-text coordinates). The component stays
 *   mounted when `anchor` is null so the code-picker modal survives outside
 *   clicks — the host only hides the popup via `onHide`.
 * - `refreshCodings` must return the FRESH coding list (it also updates the
 *   host state) so `onCoded` can highlight the just-created segment.
 * - `onChanged` reloads annotations/codes/links after non-coding mutations.
 */
import { errorMessage } from "@/lib/utils";
import { useEffect, useMemo, useRef, useState } from "react";
import { useAsyncEffect } from "@/lib/useAsync";
import {
  Check,
  Code,
  Link as LinkIcon,
  LoaderCircle,
  ScrollText,
  StickyNote,
  Tag,
} from "lucide-react";
import { Button, Input, Menu, MenuItem, Select, Textarea } from "@/components/ui/orchestrator";
import { api, type CodeTreeItem, type Coding } from "@/lib/api";
import { CodePicker, type PickedCode } from "@/features/coding/CodePicker";
import { listQttSheets, sendSegmentToQtt, type QttSheet } from "@/lib/qttApi";
import {
  copyLinkPayload,
  createLink,
  readLinkPayload,
  type LinkSpanTarget,
} from "@/features/coding/links";
import { useCoderStore } from "@/stores/coder";
import { useWorkspaceStore } from "@/stores/workspace";
import { useI18n } from "@/lib/i18n";
import { cls } from "@/components/ui/tokens";

export interface SelectionToolbarProps {
  /** Popup position; null hides the popup (the component stays mounted so
   *  the code-picker modal survives outside clicks). */
  anchor: { left: number; top: number } | null;
  /** Current selection in document-text coordinates (null = none). */
  selection: { pos0: number; pos1: number; text: string } | null;
  /** The file being coded. */
  fid: number;
  /** Flat code list — picker, names, in-vivo categories. */
  codes: CodeTreeItem[];
  /** Reload the codings (returns the fresh list — updates host state too). */
  refreshCodings: () => Promise<Coding[]>;
  /** Called after a coding was created with the fresh codings, so the host
   *  can highlight the new segment (e.g. auto-show details). */
  onCoded?: (created: Coding, next: Coding[]) => void;
  /** Reload annotations/codes/links after non-coding mutations. */
  onChanged: () => void;
  /** Hide the popup only — the selection stays (outside click). */
  onHide: () => void;
  /** Clear the host selection (after a completed action). */
  onClose: () => void;
  /** Surface an error to the host. */
  onError: (msg: string) => void;
}

export function SelectionToolbar({
  anchor,
  selection,
  fid,
  codes,
  refreshCodings,
  onCoded,
  onChanged,
  onHide,
  onClose,
  onError,
}: SelectionToolbarProps) {
  const { t } = useI18n();
  const activeCodeId = useCoderStore((s) => s.activeCodeId);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [annotateOpen, setAnnotateOpen] = useState(false);
  const [annotateMemo, setAnnotateMemo] = useState("");
  const [inVivoOpen, setInVivoOpen] = useState(false);
  const [inVivoName, setInVivoName] = useState("");
  const [inVivoCat, setInVivoCat] = useState<number | null>(null);
  const [inVivoBusy, setInVivoBusy] = useState(false);

  /* Segment links: whether a qcnext-link payload is on the clipboard (the
     "Paste link here" button) + a transient "copied" feedback. */
  const [clipboardLink, setClipboardLink] = useState<LinkSpanTarget | null>(null);
  const [linkCopied, setLinkCopied] = useState(false);
  const linkCopiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* "Send to QTT": pick a worksheet in a small inline menu and store the
     selected span as a segment item (transient "sent" feedback). */
  const [qttOpen, setQttOpen] = useState(false);
  const [qttSheets, setQttSheets] = useState<QttSheet[]>([]);
  const [qttLoading, setQttLoading] = useState(false);
  const [qttSending, setQttSending] = useState<number | null>(null);
  const [qttSent, setQttSent] = useState(false);
  const qttSentTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const popupRef = useRef<HTMLDivElement | null>(null);

  useEffect(
    () => () => {
      if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
      if (qttSentTimer.current) clearTimeout(qttSentTimer.current);
    },
    [],
  );

  const codeById = useMemo(() => {
    const m = new Map<number, CodeTreeItem>();
    for (const c of codes) if (c.kind === "code") m.set(c.id, c);
    return m;
  }, [codes]);

  /** Lazy name lookup for an active code the host's list does not know yet
   *  (it was created while the coder was open) — the toolbar must still
   *  label its primary button correctly. */
  const [extraNames, setExtraNames] = useState<Map<number, string> | null>(null);
  useAsyncEffect(async (signal) => {
    if (activeCodeId == null || codeById.has(activeCodeId)) return;
    try {
      const flat = await api.codesFlat();
      signal.throwIfAborted();
      setExtraNames(new Map(flat.filter((c) => c.kind === "code").map((c) => [c.id, c.name])));
    } catch {
      /* a lazy-name fetch failure should not disturb the toolbar */
    }
  }, [activeCodeId, codeById]);

  const activeCodeName =
    (activeCodeId != null ? codeById.get(activeCodeId)?.name : undefined) ??
    (activeCodeId != null ? extraNames?.get(activeCodeId) : undefined);

  /** Top-level code categories for the in-vivo popover's optional target. */
  const categories = useMemo(
    () => codes.filter((c) => c.kind === "category"),
    [codes],
  );

  /* ------------------------------------------------------------------ ops */

  /** Code the pending selection with the given code id. */
  function codeSelection(cid: number) {
    const sel = selection;
    if (!sel) return;
    void (async () => {
      try {
        const created = await api.createTextCoding({
          cid,
          fid,
          seltext: sel.text,
          pos0: sel.pos0,
          pos1: sel.pos1,
        });
        const next = await refreshCodings();
        onCoded?.(created, next);
        onChanged();
        onClose();
      } catch (e) {
        // Keep the selection so the user can retry without re-selecting.
        onError(errorMessage(e, t("coder.createError")));
      }
    })();
  }

  /** In-vivo coding: create a NEW code from the selection text, then code
   *  the current selection with it. */
  function codeInVivo() {
    const name = inVivoName.trim();
    const sel = selection;
    if (!name || inVivoBusy || !sel) return;
    setInVivoBusy(true);
    void (async () => {
      try {
        const res = await api.createCode(name, { catid: inVivoCat });
        const created = await api.createTextCoding({
          cid: res.cid,
          fid,
          seltext: sel.text,
          pos0: sel.pos0,
          pos1: sel.pos1,
        });
        const next = await refreshCodings();
        onCoded?.(created, next);
        onChanged();
        onClose();
      } catch (e) {
        // Keep the selection so the user can retry without re-selecting.
        onError(errorMessage(e, t("coder.inVivoCreateError")));
      } finally {
        setInVivoBusy(false);
      }
    })();
  }

  function saveAnnotation() {
    const sel = selection;
    if (!sel || !annotateMemo.trim()) return;
    void (async () => {
      try {
        await api.createAnnotation({
          fid,
          pos0: sel.pos0,
          pos1: sel.pos1,
          memo: annotateMemo.trim(),
        });
        onChanged();
        onClose();
      } catch (e) {
        // Keep the selection so the user can retry without re-selecting.
        onError(errorMessage(e, t("coder.annotationCreateError")));
      }
    })();
  }

  function copySegmentLink() {
    const sel = selection;
    if (!sel) return;
    void (async () => {
      try {
        await copyLinkPayload(fid, sel.pos0, sel.pos1);
        setClipboardLink({ fid, pos0: sel.pos0, pos1: sel.pos1 });
        setLinkCopied(true);
        if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
        linkCopiedTimer.current = setTimeout(() => setLinkCopied(false), 1500);
      } catch (e) {
        onError(errorMessage(e, t("coder.linkCopyError")));
      }
    })();
  }

  /** Create one link from the current selection to the copied segment. */
  function pasteSegmentLink() {
    const sel = selection;
    const target = clipboardLink;
    if (!sel || !target) return;
    void (async () => {
      try {
        await createLink({
          from_fid: fid,
          from_pos0: sel.pos0,
          from_pos1: sel.pos1,
          to_fid: target.fid,
          to_pos0: target.pos0,
          to_pos1: target.pos1,
        });
        onChanged();
        onClose();
      } catch (e) {
        // Keep the selection so the user can retry without re-selecting.
        onError(errorMessage(e, t("coder.linkCreateError")));
      }
    })();
  }

  /** Open the worksheet picker for the current selection. */
  function openQttPicker() {
    setQttOpen(true);
    setQttLoading(true);
    void listQttSheets()
      .then((sheets) => setQttSheets(sheets))
      .catch((e) => {
        onError(errorMessage(e, t("qtt.sendError")));
        setQttOpen(false);
      })
      .finally(() => setQttLoading(false));
  }

  /** Store the selected span as a segment item on the given worksheet. The
   *  selection stays put so the "sent" feedback remains visible. */
  function sendSelectionToSheet(sheet: QttSheet) {
    const sel = selection;
    if (!sel || qttSending != null) return;
    setQttSending(sheet.id);
    void (async () => {
      try {
        await sendSegmentToQtt(sheet.id, {
          fid,
          pos0: sel.pos0,
          pos1: sel.pos1,
        });
        setQttOpen(false);
        setQttSent(true);
        if (qttSentTimer.current) clearTimeout(qttSentTimer.current);
        qttSentTimer.current = setTimeout(() => setQttSent(false), 1500);
        // An open QTT workspace refreshes its sheets/items.
        const { qttUi, setQttUi } = useWorkspaceStore.getState();
        setQttUi({ tick: qttUi.tick + 1 });
      } catch (e) {
        onError(errorMessage(e, t("qtt.sendError")));
      } finally {
        setQttSending(null);
      }
    })();
  }

  /* ------------------------------------------------------------ listeners */

  // Clicking a code in the left sidebar assigns it to the selected part.
  useEffect(() => {
    const onAssign = (e: Event) => {
      const cid = (e as CustomEvent<{ cid: number }>).detail?.cid;
      if (typeof cid !== "number") return;
      setPickerOpen(false);
      codeSelection(cid);
    };
    window.addEventListener("qc:assign-code", onAssign);
    return () => window.removeEventListener("qc:assign-code", onAssign);
  });

  // Track whether a qcnext-link payload is on the clipboard so the toolbar
  // can offer "Paste link here".
  useAsyncEffect(async (signal) => {
    const target = await readLinkPayload();
    signal.throwIfAborted();
    setClipboardLink(target);
  }, [selection]);

  // Escape closes the inner popovers FIRST — capture phase + stop
  // immediate propagation, so the host's own Escape handler (which clears
  // the whole selection) never fires while a popover is open. Without a
  // popover open, the host closes the popup and selection itself.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (qttOpen) {
        setQttOpen(false);
        e.stopImmediatePropagation();
        return;
      }
      if (pickerOpen) {
        setPickerOpen(false);
        e.stopImmediatePropagation();
        return;
      }
      if (annotateOpen) {
        setAnnotateOpen(false);
        e.stopImmediatePropagation();
        return;
      }
      if (inVivoOpen) {
        setInVivoOpen(false);
        e.stopImmediatePropagation();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [qttOpen, pickerOpen, annotateOpen, inVivoOpen]);

  // Clicking outside the popup hides it (the code picker is a modal and
  // survives — matches the popup/selection split the host expects).
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (!target) return;
      if (!popupRef.current?.contains(target)) onHide();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onHide]);

  /* -------------------------------------------------------------- rendering */

  const popupVisible = anchor != null && selection != null;

  return (
    <>
      {popupVisible && (
        <div ref={popupRef} className="fixed z-40" style={{ left: anchor.left, top: anchor.top }}>
          {annotateOpen ? (
            <div
              className={`w-72 p-2 ${cls.popup}`}
              role="dialog"
              aria-modal="true"
              aria-label={t("coder.addAnnotation")}
            >
              <Textarea
                autoFocus
                value={annotateMemo}
                onChange={(e) => setAnnotateMemo(e.target.value)}
                placeholder={t("coder.annotationMemoPlaceholder")}
                className="h-20 w-full resize-none p-1.5"
              />
              <div className="mt-2 flex justify-end gap-1.5">
                <Button variant="secondary" onClick={() => setAnnotateOpen(false)}>
                  {t("common.cancel")}
                </Button>
                <Button variant="primary" icon={<Check size={12} aria-hidden />} onClick={saveAnnotation}>
                  {t("common.save")}
                </Button>
              </div>
            </div>
          ) : inVivoOpen ? (
            <div
              className={`w-64 p-2 ${cls.popup}`}
              role="dialog"
              aria-modal="true"
              aria-label={t("coder.inVivo")}
            >
              <Input
                autoFocus
                value={inVivoName}
                onChange={(e) => setInVivoName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") codeInVivo();
                }}
                placeholder={t("coder.inVivoNamePlaceholder")}
                aria-label={t("coder.inVivoNamePlaceholder")}
              />
              <Select
                value={inVivoCat ?? ""}
                onChange={(e) => setInVivoCat(e.target.value === "" ? null : Number(e.target.value))}
                aria-label={t("coder.inVivoCategory")}
                className="mt-1.5 w-full"
              >
                <option value="">{t("coder.inVivoNoCategory")}</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
              <div className="mt-2 flex justify-end gap-1.5">
                <Button variant="secondary" onClick={() => setInVivoOpen(false)}>
                  {t("common.cancel")}
                </Button>
                <Button
                  variant="primary"
                  icon={inVivoBusy ? <LoaderCircle size={12} className="animate-spin" aria-hidden /> : <Tag size={12} aria-hidden />}
                  onClick={codeInVivo}
                  disabled={inVivoBusy || inVivoName.trim() === ""}
                >
                  {t("common.create")}
                </Button>
              </div>
            </div>
          ) : qttOpen ? (
            <Menu role="menu" className="w-64" aria-label={t("qtt.sendTitle")}>
              <div className="border-b border-border px-2 py-1 text-[11px] font-medium uppercase tracking-wide text-text-secondary">
                {t("qtt.sendTitle")}
              </div>
              {qttLoading ? (
                <div className="flex items-center gap-1.5 px-2 py-2 text-xs text-text-secondary">
                  <LoaderCircle size={12} className="animate-spin" aria-hidden />
                  {t("qtt.loading")}
                </div>
              ) : qttSheets.length === 0 ? (
                <div className="px-2 py-2 text-xs text-text-secondary">{t("qtt.sendEmpty")}</div>
              ) : (
                qttSheets.map((sheet) => (
                  <MenuItem
                    key={sheet.id}
                    role="menuitem"
                    disabled={qttSending != null}
                    onClick={() => sendSelectionToSheet(sheet)}
                    className={qttSending === sheet.id ? "opacity-60" : ""}
                  >
                    {qttSending === sheet.id ? (
                      <LoaderCircle size={12} className="animate-spin" aria-hidden />
                    ) : (
                      <ScrollText size={12} aria-hidden />
                    )}
                    <span className="min-w-0 flex-1 truncate">{sheet.name}</span>
                    <span className="shrink-0 rounded-sm bg-surface-higher px-1 py-px text-[10px] font-medium uppercase text-text-secondary">
                      {sheet.kind === "mixed" ? t("qtt.kindMixed") : t("qtt.kindQual")}
                    </span>
                  </MenuItem>
                ))
              )}
            </Menu>
          ) : (
            <div
              className={`flex items-center gap-1 p-1 ${cls.popup}`}
              role="toolbar"
              aria-label={t("coder.selectionActions")}
            >
              <Button
                variant="primary"
                icon={<Code size={12} aria-hidden />}
                className="max-w-56"
                onClick={() => {
                  if (activeCodeId != null) codeSelection(activeCodeId);
                  else setPickerOpen(true);
                }}
                title={
                  activeCodeId != null
                    ? t("coder.codeWithActive", { name: activeCodeName ?? "" })
                    : t("coder.codeAction")
                }
              >
                <span className="truncate">
                  {activeCodeId != null ? activeCodeName ?? t("coder.codeAction") : t("coder.codeAction")}
                </span>
              </Button>
              <Button
                variant="secondary"
                icon={<StickyNote size={12} aria-hidden />}
                onClick={() => {
                  setAnnotateMemo("");
                  setInVivoOpen(false);
                  setAnnotateOpen(true);
                }}
              >
                {t("coder.annotate")}
              </Button>
              <Button
                variant="secondary"
                icon={<Tag size={12} aria-hidden />}
                onClick={() => {
                  setInVivoName("");
                  setInVivoCat(null);
                  setAnnotateOpen(false);
                  setInVivoOpen(true);
                }}
                title={t("coder.inVivo")}
              >
                {t("coder.inVivo")}
              </Button>
              <Button
                variant="secondary"
                icon={<LinkIcon size={12} aria-hidden />}
                onClick={copySegmentLink}
                title={t("coder.linkCopied")}
              >
                {linkCopied ? t("coder.copyLinkDone") : t("coder.copyLink")}
              </Button>
              {clipboardLink && (
                <Button
                  variant="secondary"
                  icon={<LinkIcon size={12} aria-hidden />}
                  onClick={pasteSegmentLink}
                  title={t("coder.linkCopied")}
                >
                  {t("coder.pasteLinkHere")}
                </Button>
              )}
              <Button
                variant="secondary"
                icon={
                  qttSent ? <Check size={12} aria-hidden /> : <ScrollText size={12} aria-hidden />
                }
                onClick={openQttPicker}
                title={t("qtt.sendTitle")}
              >
                {qttSent ? t("qtt.sendDone") : t("qtt.send")}
              </Button>
            </div>
          )}
        </div>
      )}

      <CodePicker
        open={pickerOpen}
        codes={codes}
        onClose={() => setPickerOpen(false)}
        onPick={(picked: PickedCode) => {
          setPickerOpen(false);
          codeSelection(picked.cid);
        }}
      />
    </>
  );
}
