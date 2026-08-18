/**
 * AiView — the AI assistant as a toggleable right-bar pane. The instruction
 * picker (analysis / specialized / custom templates), the chat-history menu
 * and the template editor live in the pane's top bar; the chat panel fills
 * the pane body. The chat mode is derived automatically by the backend from
 * the context picker selections, so no mode dropdown is shown.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useAsyncEffect } from "@/lib/useAsync";
import { Check, FileText, HelpCircle, History, Plus, Trash2 } from "lucide-react";
import { api, type AiChatInfo, type AiPromptInfo } from "@/lib/api";
import {
  BarHeader,
  HelpFlyout,
  IconButton,
  LeftBar,
  MenuItem,
  Select,
} from "@/components/ui/orchestrator";
import { InlineNameEdit } from "@/components/ui/InlineNameEdit";
import { useI18n } from "@/lib/i18n";
import { AiChatPanel } from "@/features/ai/AiChatPanel";
import { AiTemplateEditor } from "@/features/ai/AiTemplateEditor";

/**
 * Prompt catalog entries the backend may extend with ``label``/``hidden``/
 * ``group``/``custom`` — keep the old shape working until the fields ship.
 */
type CatalogPrompt = AiPromptInfo & {
  label?: string;
  hidden?: boolean;
  group?: string;
  custom?: boolean;
};

/** Internal prompts (``_init``, ``_help``, search scaffolding, …) are never
 *  user-pickable — the dropdown shows analysis / specialized / custom only. */
function isUsablePrompt(p: AiPromptInfo): boolean {
  const ext = p as CatalogPrompt;
  if (ext.hidden) return false;
  if (p.id.startsWith("_") || p.id.endsWith("/_init")) return false;
  if (p.mode === "search" || p.mode === "help") return false;
  return true;
}

function promptLabel(p: AiPromptInfo): string {
  return (p as CatalogPrompt).label ?? p.name;
}

function promptGroup(p: AiPromptInfo): string {
  return (p as CatalogPrompt).group ?? "";
}

const GROUP_LABELS: Record<string, string> = {
  analysis: "ai.groupAnalysis",
  specialized: "ai.groupSpecialized",
  custom: "ai.groupCustom",
};

/** Anchored popover for the chat-history menu (fixed positioning, clamped,
 *  closes on outside click / Escape). */
function AnchorPopover({
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
      className={`fixed z-50 ${className}`}
      style={pos ? { left: pos.left, top: pos.top } : { visibility: "hidden" }}
    >
      {children}
    </div>
  );
}

export function AiView() {
  const { t } = useI18n();
  const [prompts, setPrompts] = useState<AiPromptInfo[]>([]);
  const [promptId, setPromptId] = useState("");
  const [chatId, setChatId] = useState<number | null>(null);
  const [chats, setChats] = useState<AiChatInfo[]>([]);
  const [historyAnchor, setHistoryAnchor] = useState<HTMLElement | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [helpAnchor, setHelpAnchor] = useState<HTMLElement | null>(null);
  const [templatesOpen, setTemplatesOpen] = useState(false);

  useAsyncEffect(async (signal) => {
    const [promptsRes, chatsRes] = await Promise.allSettled([api.aiPrompts(), api.aiChats()]);
    if (promptsRes.status === "fulfilled") setPrompts(promptsRes.value.prompts);
    if (chatsRes.status === "fulfilled") setChats(chatsRes.value.chats);
    signal.throwIfAborted();
  }, []);

  const usable = prompts.filter(isUsablePrompt);
  const groups = ["analysis", "specialized", "custom"].filter((g) =>
    usable.some((p) => promptGroup(p) === g),
  );
  const activeChat = chats.find((c) => c.id === chatId) ?? null;

  function openChat(id: number) {
    setChatId(id);
    setPromptId((prev) => prev);
    setHistoryAnchor(null);
  }

  function startNewChat() {
    setChatId(null);
    setHistoryAnchor(null);
  }

  async function deleteChat(id: number) {
    await api.aiChatDelete(id);
    setChats((prev) => prev.filter((c) => c.id !== id));
    if (chatId === id) setChatId(null);
    setHistoryAnchor(null);
    setConfirmDelete(false);
  }

  return (
    <LeftBar
      borderSide="l"
      scroll={false}
      className="h-full min-h-0 max-w-full overflow-hidden"
      header={
        <BarHeader
          title="AI"
          actions={
            <>
              <Select
                value={promptId}
                onChange={(e) => setPromptId(e.target.value)}
                aria-label={t("ai.promptLabel")}
                title={t("ai.promptLabel")}
                className="min-w-0 max-w-full"
              >
                <option value="">{t("ai.promptNone")}</option>
                {groups.map((group) => (
                  <optgroup key={group} label={t(GROUP_LABELS[group] ?? "ai.groupAnalysis")}>
                    {usable
                      .filter((p) => promptGroup(p) === group)
                      .map((p) => (
                        <option key={p.id} value={p.id} title={p.description}>
                          {promptLabel(p)}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </Select>
              <IconButton
                label={t("ai.historyAria")}
                title={t("ai.historyTitle")}
                size="sm"
                aria-expanded={historyAnchor !== null}
                onClick={(e) => setHistoryAnchor(historyAnchor ? null : e.currentTarget)}
              >
                <History size={14} aria-hidden />
              </IconButton>
              {historyAnchor && (
                <AnchorPopover
                  anchor={historyAnchor}
                  onClose={() => {
                    setHistoryAnchor(null);
                    setRenaming(false);
                    setConfirmDelete(false);
                  }}
                  className="w-60 rounded-md border border-border bg-surface py-1 shadow-qc-md"
                >
                  {renaming && activeChat ? (
                    <div className="px-2 py-1.5">
                      <InlineNameEdit
                        value={activeChat.title}
                        placeholder={t("ai.historyRenamePlaceholder")}
                        onSave={(name) => {
                          void api.aiChatRename(activeChat.id, name).then(() => {
                            setChats((prev) =>
                              prev.map((c) => (c.id === activeChat.id ? { ...c, title: name } : c)),
                            );
                            setRenaming(false);
                          });
                        }}
                        onCancel={() => setRenaming(false)}
                      />
                    </div>
                  ) : (
                    <>
                      <MenuItem onClick={startNewChat} className="gap-2">
                        <Plus size={14} aria-hidden />
                        {t("ai.historyNew")}
                      </MenuItem>
                      <div className="qc-scroll max-h-56 overflow-y-auto">
                        {chats.length === 0 ? (
                          <p className="px-3 py-2 text-xs text-text-secondary">{t("ai.historyEmpty")}</p>
                        ) : (
                          chats.map((chat) => (
                            <MenuItem
                              key={chat.id}
                              onClick={() => openChat(chat.id)}
                              className="gap-2"
                            >
                              {chat.id === chatId && <Check size={12} className="shrink-0 text-accent" aria-hidden />}
                              <span className="min-w-0 flex-1 truncate text-left">{chat.title || "…"}</span>
                            </MenuItem>
                          ))
                        )}
                      </div>
                      <div className="flex items-center gap-1 border-t border-border px-1 py-1">
                        <MenuItem
                          disabled={!activeChat}
                          onClick={() => {
                            setConfirmDelete(false);
                            setRenaming(true);
                          }}
                          className="flex-1 gap-1.5 text-xs"
                        >
                          <FileText size={12} aria-hidden />
                          {t("ai.historyRename")}
                        </MenuItem>
                        {confirmDelete && activeChat ? (
                          <button
                            type="button"
                            onClick={() => void deleteChat(activeChat.id)}
                            className="flex-1 rounded-sm bg-danger px-2 py-1 text-xs text-white"
                          >
                            {t("ai.historyConfirmDelete")}
                          </button>
                        ) : (
                          <MenuItem
                            disabled={!activeChat}
                            onClick={() => {
                              setRenaming(false);
                              setConfirmDelete(true);
                            }}
                            className="flex-1 gap-1.5 text-xs text-danger"
                          >
                            <Trash2 size={12} aria-hidden />
                            {t("ai.historyDelete")}
                          </MenuItem>
                        )}
                      </div>
                    </>
                  )}
                </AnchorPopover>
              )}
              <IconButton
                label={t("ai.templatesAria")}
                title={t("ai.templatesTitle")}
                size="sm"
                onClick={() => setTemplatesOpen(true)}
              >
                <FileText size={14} aria-hidden />
              </IconButton>
              <IconButton
                label={t("ai.promptHelp")}
                title={t("ai.promptHelp")}
                size="sm"
                aria-expanded={helpAnchor !== null}
                onClick={(e) => setHelpAnchor(helpAnchor ? null : e.currentTarget)}
              >
                <HelpCircle size={14} aria-hidden />
              </IconButton>
              {helpAnchor && (
                <HelpFlyout anchor={helpAnchor} onClose={() => setHelpAnchor(null)}>
                  <p className="text-xs leading-relaxed text-text-secondary">{t("ai.promptHelp")}</p>
                </HelpFlyout>
              )}
            </>
          }
        />
      }
    >
      <AiChatPanel
        chatId={chatId}
        promptId={promptId}
        onChatId={(id) => {
          setChatId(id);
          void api.aiChats().then((res) => setChats(res.chats));
        }}
      />
      <AiTemplateEditor open={templatesOpen} onClose={() => setTemplatesOpen(false)} />
    </LeftBar>
  );
}