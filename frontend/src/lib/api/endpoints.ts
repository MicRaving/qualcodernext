/**
 * Endpoint methods for the QualCoder v4 API client.
 *
 * Every method on the `api` object delegates to `request()` (from
 * transport.ts) and references types from types.ts.
 */

import { request, apiBaseSync, handleJson } from "./transport";
import type {
  Annotation,
  AppSettings,
  AttributeReportRow,
  AttributeType,
  AttributeValue,
  AutocodeJob,
  AutocodeResponse,
  AuditResponse,
  AuditRow,
  AuditStatsRow,
  AiChatReply,
  AiIndexStatus,
  AiPromptInfo,
  AiStatus,
  AiChatInfo,
  AiChatDetail,
  AiTemplateInfo,
  AVCoding,
  BadLink,
  Bookmarks,
  Case,
  CaseFileLink,
  CaseItem,
  CdctItem,
  CdctLine,
  ChartMatrix,
  Code,
  CodeDetails,
  CodeFrequencyRow,
  CodeRelation,
  CodeSegmentRow,
  CodeSummary,
  CodeTreeItem,
  CodesBySegmentRow,
  Category,
  Coding,
  CoderComparisonRow,
  CooccurrenceTable,
  CodersResponse,
  ColorScheme,
  CommitEditResponse,
  CompactResult,
  ExactMatchRow,
  FileFilter,
  FileItem,
  FileSummaryRow,
  FreeItem,
  FreeLine,
  GraphData,
  GraphSummary,
  ImageCoding,
  InterraterResult,
  Journal,
  MaintenanceSettings,
  MemoItem,
  OpenProjectResult,
  ProjectSummary,
  Pseudonym,
  RArtifact,
  RJob,
  RPrepareResult,
  RScript,
  RStatus,
  ReferenceEntry,
  SavedQuery,
  ShiftPositionsResponse,
  Source,
  SourceDetails,
  SpeakerInfo,
  SpeakerTurn,
  SqlResult,
  SyncResult,
  SyncStatus,
  PresenceResponse,
  TranscribeJob,
  TranscribeStatus,
  UndoCodingsResponse,
  UpdatesSettings,
  WordFrequencyRow,
} from "./types";

// --- GitHub bug-report settings (mirrored to localStorage) -------------

const GITHUB_SETTINGS_KEY = "qc-github-settings";

function githubLocalSettings(): { github_token: string; github_repo: string } {
  if (typeof window === "undefined") return { github_token: "", github_repo: "" };
  try {
    const raw = window.localStorage.getItem(GITHUB_SETTINGS_KEY);
    if (!raw) return { github_token: "", github_repo: "" };
    const data = JSON.parse(raw) as { github_token?: unknown; github_repo?: unknown };
    return {
      github_token: typeof data.github_token === "string" ? data.github_token : "",
      github_repo: typeof data.github_repo === "string" ? data.github_repo : "",
    };
  } catch {
    return { github_token: "", github_repo: "" };
  }
}

function storeGithubLocalSettings(patch: { github_token?: string; github_repo?: string }): void {
  if (typeof window === "undefined") return;
  const next = { ...githubLocalSettings(), ...patch };
  try {
    window.localStorage.setItem(GITHUB_SETTINGS_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable — the GitHub fields just stay session-only */
  }
}

export const api = {
  recentProjects: (timeoutMs?: number) =>
    request<{ recent: string[] }>("/projects", undefined, timeoutMs),
  createProject: (project_path: string, codername?: string) =>
    request<OpenProjectResult>("/projects", {
      method: "POST",
      body: JSON.stringify({ project_path, codername }),
    }),
  openProject: (project_path: string, codername?: string) =>
    request<OpenProjectResult>("/projects/open", {
      method: "POST",
      body: JSON.stringify({ project_path, codername }),
    }),
  closeProject: () => request<OpenProjectResult>("/projects/close", { method: "POST" }),
  projectSummary: () => request<{ summary: ProjectSummary }>("/projects/current/summary"),
  projectOpeners: () => request<{ openers: { user: string; pid: number; ts: number }[] }>("/projects/openers"),

  // --- Coders ------------------------------------------------------------

  coders: () => request<CodersResponse>("/coders"),
  createCoder: (name: string) =>
    request<CodersResponse>("/coders", { method: "POST", body: JSON.stringify({ name }) }),
  switchCoder: (name: string) =>
    request<CodersResponse>("/coders/current", {
      method: "PUT",
      body: JSON.stringify({ name }),
    }),
  deleteCoder: (name: string, reassign_to?: string) =>
    request<CodersResponse>(`/coders/${encodeURIComponent(name)}`, {
      method: "DELETE",
      body: JSON.stringify({ reassign_to }),
    }),
  renameCoder: (name: string, new_name: string) =>
    request<CodersResponse>(`/coders/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify({ new_name }),
    }),
  coderStats: (name: string) =>
    request<{ coder: string; tables: { entity: string; count: number }[]; total: number }>(
      `/coders/${encodeURIComponent(name)}/stats`,
    ),
  coderVisibility: () => request<{ visibility: Record<string, number> }>("/coders/visibility"),
  setCoderVisibility: (name: string, visible: boolean) =>
    request<{ ok: boolean }>(`/coders/${encodeURIComponent(name)}/visibility`, {
      method: "PUT",
      body: JSON.stringify({ visible }),
    }),

  sources: () => request<Source[]>("/sources"),
  getSource: (id: number) => request<Source>(`/sources/${id}`),
  importSource: (file: File, owner?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("owner", owner ?? "");
    return fetch(`${apiBaseSync()}/sources/import`, { method: "POST", body: form }).then(
      handleJson<Source>,
    );
  },
  deleteSource: (id: number) => request<void>(`/sources/${id}`, { method: "DELETE" }),
  patchSource: (id: number, body: { name?: string; memo?: string; owner?: string }) =>
    request<Source>(`/sources/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  /** Create an EMPTY transcript companion for an audio/video source and link
   *  it via av_text_id (the manual-transcription target). Idempotent: when a
   *  companion already exists the media source is returned unchanged. */
  createTranscript: (sourceId: number, name?: string) =>
    request<Source>(`/sources/${sourceId}/transcript`, {
      method: "POST",
      body: JSON.stringify(name ? { name } : {}),
    }),
  /** Delete the media source's transcript companion and clear av_text_id. */
  deleteTranscript: (sourceId: number) =>
    request<void>(`/sources/${sourceId}/transcript`, { method: "DELETE" }),

  codeTree: () => request<CodeTreeItem[]>("/codes"),
  codesFlat: () => request<CodeTreeItem[]>("/codes"),
  createCode: (name: string, opts: { catid?: number | null; color?: string; owner?: string; supercid?: number | null } = {}) =>
    request<{ cid: number }>("/codes", {
      method: "POST",
      body: JSON.stringify({ name, owner: opts.owner, catid: opts.catid ?? null, color: opts.color, supercid: opts.supercid ?? null }),
    }),
  createCategory: (name: string, opts: { supercatid?: number | null; owner?: string; memo?: string } = {}) =>
    request<{ catid: number }>("/codes/categories", {
      method: "POST",
      body: JSON.stringify({
        name,
        owner: opts.owner,
        supercatid: opts.supercatid ?? null,
        memo: opts.memo,
      }),
    }),
  codeDetails: (cid: number) => request<CodeDetails>(`/codes/${cid}/details`),
  patchCode: (cid: number, body: { name?: string; memo?: string; color?: string; catid?: number | null; supercid?: number | null }) =>
    request<Code>(`/codes/${cid}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteCode: (cid: number) => request<void>(`/codes/${cid}`, { method: "DELETE" }),
  deleteCategory: (catid: number) => request<void>(`/codes/categories/${catid}`, { method: "DELETE" }),
  patchCategory: (catid: number, body: { name: string }) =>
    request<Category>(`/codes/categories/${catid}`, { method: "PATCH", body: JSON.stringify(body) }),
  mergeCode: (cid: number, targetCid: number) =>
    request<Code>(`/codes/${cid}/merge`, {
      method: "POST",
      body: JSON.stringify({ target_cid: targetCid }),
    }),
  mergeCategory: (catid: number, targetCatid: number) =>
    request<void>(`/codes/categories/${catid}/merge`, {
      method: "POST",
      body: JSON.stringify({ target_catid: targetCatid }),
    }),
  promoteCode: (cid: number) =>
    request<Code>(`/codes/${cid}/promote`, { method: "POST" }),
  demoteCode: (cid: number) =>
    request<Code>(`/codes/${cid}/demote`, { method: "POST" }),
  promoteCategory: (catid: number) =>
    request<Category>(`/codes/categories/${catid}/promote`, { method: "POST" }),
  demoteCategory: (catid: number) =>
    request<Category>(`/codes/categories/${catid}/demote`, { method: "POST" }),
  /** Move a code within the tree (drag & drop). The destination is the
   *  category ``parent_catid`` (null = root), the parent code ``supercid``
   *  (sub-code), or the sibling group of ``after_cid``/``before_cid``. */
  moveCode: (
    cid: number,
    opts: {
      parent_catid?: number | null;
      supercid?: number | null;
      after_cid?: number | null;
      before_cid?: number | null;
    } = {},
  ) =>
    request<Code>(`/codes/${cid}/move`, {
      method: "POST",
      body: JSON.stringify(opts),
    }),
  /** Move a category within the tree (drag & drop). The destination is the
   *  parent category ``supercatid`` (null = root) or the sibling group of
   *  ``after_catid``/``before_catid``. */
  moveCategory: (
    catid: number,
    opts: {
      supercatid?: number | null;
      after_catid?: number | null;
      before_catid?: number | null;
    } = {},
  ) =>
    request<Category>(`/codes/categories/${catid}/move`, {
      method: "POST",
      body: JSON.stringify(opts),
    }),

  sourceDetails: (id: number) => request<SourceDetails>(`/sources/${id}/details`),

  cases: () => request<Case[]>("/cases"),

  sourceCoding: (fid: number) => request<Coding[]>(`/codings/text/${fid}`),
  createTextCoding: (body: {
    cid: number;
    fid: number;
    seltext: string;
    pos0: number;
    pos1: number;
    owner?: string;
  }) =>
    request<Coding>("/codings/text", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteTextCoding: (ctid: number) => request<void>(`/codings/text/${ctid}`, { method: "DELETE" }),
  undoCodings: (items: object[]) =>
    request<UndoCodingsResponse>("/codings/undo", {
      method: "POST",
      body: JSON.stringify({ items }),
    }),

  imageCodings: (sourceId: number) => request<ImageCoding[]>(`/codings/image/${sourceId}`),
  /** Map a selection made over a rendered PDF page to plain-text offsets
   *  (the same text the plain-text mode codes against). */
  pdfTextLocate: (fid: number, body: { page: number; text: string }) =>
    request<{ pos0: number; pos1: number; seltext: string }>(
      `/sources/${fid}/pdf-text-locate`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  createImageCoding: (body: {
    id: number;
    x1: number;
    y1: number;
    width: number;
    height: number;
    cid: number;
    owner?: string;
    memo?: string;
    important?: number;
    pdf_page?: number | null;
  }) =>
    request<ImageCoding>("/codings/image", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteImageCoding: (imid: number) =>
    request<void>(`/codings/image/${imid}`, { method: "DELETE" }),
  patchImageCoding: (
    imid: number,
    body: { x1?: number; y1?: number; width?: number; height?: number; memo?: string; cid?: number },
  ) =>
    request<ImageCoding>(`/codings/image/${imid}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  avCodings: (sourceId: number) => request<AVCoding[]>(`/codings/av/${sourceId}`),
  createAvCoding: (body: {
    id: number;
    pos0: number;
    pos1: number;
    cid: number;
    owner?: string;
    memo?: string;
    important?: number;
  }) =>
    request<AVCoding>("/codings/av", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteAvCoding: (avid: number) => request<void>(`/codings/av/${avid}`, { method: "DELETE" }),

  fileAnnotations: (fid: number) => request<Annotation[]>(`/annotations/${fid}`),
  createAnnotation: (body: { fid: number; pos0: number; pos1: number; memo: string; owner?: string }) =>    request<Annotation>("/annotations", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteAnnotation: (anid: number) => request<void>(`/annotations/${anid}`, { method: "DELETE" }),
  updateAnnotation: (anid: number, memo: string) =>
    request<Annotation>(`/annotations/${anid}`, {
      method: "PATCH",
      body: JSON.stringify({ memo }),
    }),

  shiftPositions: (body: {
    prev_text: string;
    new_text: string;
    codings: { ctid: number; pos0: number; pos1: number }[];
    annotations: { anid: number; pos0: number; pos1: number }[];
    case_text: { id: number; pos0: number; pos1: number }[];
  }) =>
    request<ShiftPositionsResponse>("/codings/shift-positions", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  commitEdit: (body: { fid: number; new_text: string }) =>
    request<CommitEditResponse>("/codings/commit-edit", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  autocode: (body: {
    fid: number | null;
    cids: number[];
    find_texts?: string[];
    mode?: string;
    use_regex?: boolean;
    prompt?: string;
    suggest?: boolean;
    owner?: string;
  }) =>
    request<AutocodeResponse>("/codings/autocode", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // --- Bookmarks ---------------------------------------------------------

  bookmarks: () => request<Bookmarks>("/bookmarks"),
  setBookmark: (file_id: number | null, pos: number | null) =>
    request<Bookmarks>("/bookmarks", {
      method: "PUT",
      body: JSON.stringify({ file_id, pos }),
    }),
  setAvBookmark: (file_id: number | null, msec: number | null, textpos: number | null) =>
    request<Bookmarks>("/bookmarks/av", {
      method: "PUT",
      body: JSON.stringify({ file_id, msec, textpos }),
    }),

  // --- Pseudonyms ----------------------------------------------------------

  pseudonyms: () => request<{ pseudonyms: Pseudonym[] }>("/pseudonyms"),
  addPseudonym: (original: string, pseudonym = "") =>
    request<{ pseudonym: Pseudonym }>("/pseudonyms", {
      method: "POST",
      body: JSON.stringify({ original, pseudonym }),
    }),
  deletePseudonym: (original: string) =>
    request<{ ok: boolean }>(`/pseudonyms/${encodeURIComponent(original)}`, { method: "DELETE" }),

  // --- Speakers ------------------------------------------------------------

  speakersDetect: (body: { fid?: number | null; identifiers: string[]; custom_regex?: string }) =>
    request<{ turns: SpeakerTurn[]; speakers: SpeakerInfo[] }>("/speakers/detect", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  speakersMark: (body: { fid?: number | null; identifiers: string[]; custom_regex?: string; selected?: string[] }) =>
    request<{ ok: boolean; turns_marked: number; codes_created: number }>("/speakers/mark", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // --- References -----------------------------------------------------------

  references: () => request<{ references: ReferenceEntry[] }>("/references"),
  deleteReference: (risid: number) => request<void>(`/references/${risid}`, { method: "DELETE" }),

  // --- Bad links + file replacement ----------------------------------------

  badLinks: () => request<{ links: BadLink[] }>("/sources/bad-links"),
  fixLink: (sourceId: number, mediapath: string) =>
    request<{ ok: boolean }>(`/sources/${sourceId}/mediapath`, {
      method: "PATCH",
      body: JSON.stringify({ mediapath }),
    }),
  bulkRenamePath: (old: string, newPath: string) =>
    request<{ ok: boolean; updated: number }>("/sources/bulk-rename-path", {
      method: "POST",
      body: JSON.stringify({ old, new: newPath }),
    }),
  replaceSource: (sourceId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${apiBaseSync()}/sources/${sourceId}/replace`, {
      method: "POST",
      body: form,
    }).then(handleJson<{ ok: boolean; message: string }>);
  },

  // --- Saved file filters ----------------------------------------------------

  fileFilters: () => request<{ filters: FileFilter[] }>("/sources/filters"),
  createFileFilter: (name: string, filter: string, owner?: string) =>
    request<{ ok: boolean; filterid: number }>("/sources/filters", {
      method: "POST",
      body: JSON.stringify({ name, filter, owner }),
    }),
  deleteFileFilter: (filterid: number) =>
    request<void>(`/sources/filters/${filterid}`, { method: "DELETE" }),

  // --- Cases -----------------------------------------------------------

  createCase: (name: string, owner?: string, memo = "") =>
    request<Case>("/cases", {
      method: "POST",
      body: JSON.stringify({ name, owner, memo }),
    }),
  updateCase: (caseid: number, body: { name?: string; memo?: string }) =>
    request<Case>(`/cases/${caseid}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteCase: (caseid: number) => request<void>(`/cases/${caseid}`, { method: "DELETE" }),
  caseFiles: (caseid: number) => request<CaseFileLink[]>(`/cases/${caseid}/files`),
  linkFileToCase: (caseid: number, fid: number, owner?: string) =>
    request<unknown>(`/cases/${caseid}/files`, {
      method: "POST",
      body: JSON.stringify({ fid, owner }),
    }),
  unlinkFileFromCase: (caseid: number, fid: number) =>
    request<void>(`/cases/${caseid}/files/${fid}`, { method: "DELETE" }),

  // --- Attributes ------------------------------------------------------

  attributeTypes: () => request<AttributeType[]>("/attributes/types"),
  attributeValues: () => request<AttributeValue[]>("/attributes/values"),
  setAttributeValue: (
    name: string,
    attr_type: string,
    entityId: number,
    value: string,
    owner?: string,
  ) =>
    request<AttributeValue>(`/attributes/values/${name}?attr_type=${attr_type}&entity_id=${entityId}`, {
      method: "PUT",
      body: JSON.stringify({ value, owner }),
    }),

  // --- Journals --------------------------------------------------------

  journals: () => request<Journal[]>("/journals"),
  createJournal: (name: string, jentry: string, owner?: string) =>
    request<Journal>("/journals", {
      method: "POST",
      body: JSON.stringify({ name, jentry, owner }),
    }),
  updateJournal: (jid: number, body: { name?: string; jentry?: string }) =>
    request<Journal>(`/journals/${jid}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteJournal: (jid: number) => request<void>(`/journals/${jid}`, { method: "DELETE" }),

  // --- Notes workspace ----------------------------------------------------

  annotationsAll: () =>
    request<
      (Annotation & { file_name: string })[]
    >("/annotations"),
  reports: {
    codeFrequencies: () => request<{ rows: CodeFrequencyRow[] }>("/reports/code-frequencies"),
    codesBySegments: () => request<{ rows: CodesBySegmentRow[] }>("/reports/codes-by-segments"),
    cooccurrence: () => request<CooccurrenceTable>("/reports/co-occurrence"),
    exactMatches: () => request<{ rows: ExactMatchRow[] }>("/reports/exact-matches"),
    fileSummary: () => request<{ rows: FileSummaryRow[] }>("/reports/file-summary"),
    coderComparison: () => request<{ rows: CoderComparisonRow[] }>("/reports/coder-comparison"),
    attributes: () => request<{ rows: AttributeReportRow[] }>("/reports/attributes"),
    interrater: (coderA: string, coderB: string) =>
      request<InterraterResult>("/reports/interrater", {
        method: "POST",
        body: JSON.stringify({ coder_a: coderA, coder_b: coderB }),
      }),
    codeSegments: (cid: number) =>
      request<{ rows: CodeSegmentRow[] }>(`/reports/code-segments/${cid}`),
    codeSummary: (cid: number) => request<CodeSummary>(`/reports/code-summary/${cid}`),
    codeRelations: (owner?: string) =>
      request<{ owner: string; relations: CodeRelation[] }>(
        `/reports/code-relations${owner ? `?owner=${encodeURIComponent(owner)}` : ""}`,
      ),
    wordFrequencies: (sourceId: number | null, limit = 100, stopwords = true) =>
      request<{ rows: WordFrequencyRow[] }>(
        `/reports/word-frequencies?limit=${limit}&stopwords=${stopwords}${sourceId ? `&source_id=${sourceId}` : ""}`,
      ),
    charts: (kind: string) => request<ChartMatrix>(`/reports/charts?kind=${kind}`),
    codebook: (memos = false) => request<{ text: string }>(`/reports/codebook?memos=${memos}`),
  },

  // --- Interchange (REFI-QDA and friends) ------------------------------

  interchange: {
    exportRefiUrl: () => `${apiBaseSync()}/interchange/export/refi`,
  },
  aiStatus: (probe = false) =>
    request<AiStatus>(`/ai/status${probe ? "?probe=1" : ""}`),
  aiModels: (opts?: { provider?: string; api_base?: string; api_key?: string }) => {
    const qs = new URLSearchParams(
      Object.fromEntries(
        Object.entries(opts ?? {}).filter(([, v]) => v !== undefined && v !== ""),
      ) as Record<string, string>,
    ).toString();
    return request<{ models: string[]; error?: string }>(
      `/ai/models${qs ? `?${qs}` : ""}`,
    );
  },
  aiSaveSettings: (body: {
    enabled: boolean;
    provider: string;
    api_base: string;
    model: string;
    api_key: string;
    mcp_permissions?: string;
  }) =>
    request<unknown>("/ai/settings", { method: "PUT", body: JSON.stringify(body) }),
  aiChat: (
    message: string,
    context = "",
    mode = "auto",
    promptId?: string,
    ids?: { memoIds?: number[]; codeIds?: number[]; sourceIds?: number[]; sourceId?: number; chatId?: number },
  ) =>
    request<AiChatReply>("/ai/chat", {
      method: "POST",
      body: JSON.stringify({
        message,
        context,
        mode,
        prompt_id: promptId,
        memo_ids: ids?.memoIds,
        code_ids: ids?.codeIds,
        source_ids: ids?.sourceIds,
        source_id: ids?.sourceId,
        chat_id: ids?.chatId,
      }),
    }),
  aiPrompts: () => request<{ prompts: AiPromptInfo[] }>("/ai/prompts"),
  aiChats: () => request<{ chats: AiChatInfo[] }>("/ai/chats"),
  aiChatCreate: (title = "") =>
    request<AiChatInfo>("/ai/chats", { method: "POST", body: JSON.stringify({ title }) }),
  aiChatGet: (chatId: number) => request<AiChatDetail>(`/ai/chats/${chatId}`),
  aiChatRename: (chatId: number, title: string) =>
    request<{ id: number; title: string }>(`/ai/chats/${chatId}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  aiChatDelete: (chatId: number) => request<void>(`/ai/chats/${chatId}`, { method: "DELETE" }),
  aiTemplates: () => request<{ templates: AiTemplateInfo[] }>("/ai/templates"),
  aiTemplateCreate: (body: { name: string; description?: string; text: string }) =>
    request<AiTemplateInfo>("/ai/templates", { method: "POST", body: JSON.stringify(body) }),
  aiTemplateUpdate: (
    templateId: number,
    body: { name: string; description?: string; text: string },
  ) =>
    request<AiTemplateInfo>(`/ai/templates/${templateId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  aiTemplateDelete: (templateId: number) =>
    request<void>(`/ai/templates/${templateId}`, { method: "DELETE" }),
  aiIndexStatus: () => request<AiIndexStatus>("/ai/index"),
  aiIndexBuild: () => request<AiIndexStatus>("/ai/index", { method: "POST", body: "{}" }),
  aiIndexDelete: () => request<void>("/ai/index", { method: "DELETE" }),
  sqlRun: (sql: string) =>
    request<SqlResult>("/sql/run", { method: "POST", body: JSON.stringify({ sql }) }),
  savedQueries: () => request<{ rows: SavedQuery[] }>("/sql/saved"),
  saveQuery: (q: { title: string; description?: string; grouper?: string; ssql: string }) =>
    request<unknown>("/sql/saved", { method: "POST", body: JSON.stringify(q) }),
  deleteQuery: (title: string) =>
    request<void>(`/sql/saved/${encodeURIComponent(title)}`, { method: "DELETE" }),

  // --- Audit / history ---------------------------------------------------

  audit: (params: {
    limit?: number;
    offset?: number;
    action?: string;
    user?: string;
    entity?: string;
    q?: string;
    summary?: boolean;
  } = {}) =>
    request<AuditResponse>(
      `/audit?${new URLSearchParams(
        Object.fromEntries(
          Object.entries(params).filter(([, v]) => v !== undefined && v !== ""),
        ) as Record<string, string>,
      ).toString()}`,
    ),
  auditStats: () => request<AuditStatsRow[]>("/audit/stats"),
  auditUsers: () => request<string[]>("/audit/users"),
  auditGet: (id: number) => request<AuditRow>(`/audit/${id}`),
  auditUndoable: (id: number, undo = true) =>
    request<{ undoable: boolean; reason: string | null }>(
      `/audit/${id}/undoable?undo=${undo ? "true" : "false"}`,
    ),
  auditRedoPending: () =>
    request<{ count: number; next_id: number | null }>("/audit/redo-pending"),
  auditUndo: (id: number) =>
    request<{ ok: boolean; message: string }>("/audit/undo", {
      method: "POST",
      body: JSON.stringify({ id }),
    }),
  auditRedo: (id: number) =>
    request<{ ok: boolean; message: string }>("/audit/redo", {
      method: "POST",
      body: JSON.stringify({ id }),
    }),

  // --- Transcription ------------------------------------------------------

  transcribeStatus: () => request<TranscribeStatus>("/transcribe/status"),
  transcribeStart: (body: {
    source_id: number;
    engine?: string;
    model?: string;
    language?: string | null;
    translate?: boolean;
    beam_size?: number;
    temperature?: number;
    vad?: boolean;
    device?: string;
    timestamps?: boolean;
    segment_coding?: boolean;
    segment_cid?: number | null;
    start?: boolean;
  }) => request<{ job_id: string }>("/transcribe", { method: "POST", body: JSON.stringify(body) }),
  transcribeJob: (jobId: string) => request<TranscribeJob>(`/transcribe/jobs/${jobId}`),
  /** start | pause | resume | cancel */
  transcribeJobControl: (jobId: string, action: string) =>
    request<{ ok: boolean }>(`/transcribe/jobs/${jobId}/${action}`, { method: "POST" }),
  transcribeJobDelete: (jobId: string) =>
    request<{ ok: boolean }>(`/transcribe/jobs/${jobId}`, { method: "DELETE" }),

  // --- Batch autocode (background jobs) --------------------------------

  autocodeBatch: (body: {
    source_ids: number[];
    cids: number[];
    prompt: string;
    suggest?: boolean;
    owner?: string | null;
  }) => request<{ job_ids: string[] }>("/codings/autocode/batch", {
    method: "POST",
    body: JSON.stringify(body),
  }),
  autocodeJob: (jobId: string) =>
    request<AutocodeJob>(`/codings/autocode/jobs/${jobId}`),
  /** start | pause | resume | cancel */
  autocodeJobControl: (jobId: string, action: string) =>
    request<{ ok: boolean }>(`/codings/autocode/jobs/${jobId}/${action}`, { method: "POST" }),
  autocodeJobDelete: (jobId: string) =>
    request<{ ok: boolean }>(`/codings/autocode/jobs/${jobId}`, { method: "DELETE" }),

  // --- R integration (Rscript bridge) ----------------------------------

  rStatus: () => request<RStatus>("/r/status"),
  rRun: (script: string, name?: string) =>
    request<{ job_id: string }>("/r/run", {
      method: "POST",
      body: JSON.stringify({ script, name }),
    }),
  rJob: (jobId: string) => request<RJob>(`/r/jobs/${jobId}`),
  rJobDelete: (jobId: string) =>
    request<{ ok: boolean }>(`/r/jobs/${jobId}`, { method: "DELETE" }),
  rArtifacts: () => request<{ artifacts: RArtifact[] }>("/r/artifacts"),
  rScripts: () => request<{ scripts: RScript[] }>("/r/scripts"),
  rScriptCreate: (name: string, script: string) =>
    request<RScript>("/r/scripts", {
      method: "POST",
      body: JSON.stringify({ name, script }),
    }),
  rScriptPatch: (name: string, script: string) =>
    request<RScript>(`/r/scripts/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify({ script }),
    }),
  rScriptDelete: (name: string) =>
    request<void>(`/r/scripts/${encodeURIComponent(name)}`, { method: "DELETE" }),
  rPrepareReport: (reportId: string) =>
    request<RPrepareResult>("/r/prepare-report", {
      method: "POST",
      body: JSON.stringify({ report_id: reportId }),
    }),

  // --- Graphs (code-map editor) ----------------------------------------

  graphs: () => request<{ graphs: GraphSummary[] }>("/graphs"),
  patchPath: (path: string, body: Record<string, unknown>) =>
    request<unknown>(path, { method: "PATCH", body: JSON.stringify(body) }),
  createGraph: (name: string, description = "") =>
    request<GraphSummary>("/graphs", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  deleteGraph: (grid: number) => request<void>(`/graphs/${grid}`, { method: "DELETE" }),
  graphData: (grid: number) => request<GraphData>(`/graphs/${grid}`),

  graphAddCdctItem: (grid: number, body: { kind: string; ref_id: number; x: number; y: number }) =>
    request<CdctItem>(`/graphs/${grid}/items/cdct`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphDeleteCdctItem: (grid: number, gtextid: number) =>
    request<void>(`/graphs/${grid}/items/cdct/${gtextid}`, { method: "DELETE" }),

  graphAddCaseItem: (grid: number, body: { caseid: number; x: number; y: number }) =>
    request<CaseItem>(`/graphs/${grid}/items/case`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphDeleteCaseItem: (grid: number, gcaseid: number) =>
    request<void>(`/graphs/${grid}/items/case/${gcaseid}`, { method: "DELETE" }),

  graphAddFileItem: (grid: number, body: { fid: number; x: number; y: number }) =>
    request<FileItem>(`/graphs/${grid}/items/file`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphDeleteFileItem: (grid: number, gfileid: number) =>
    request<void>(`/graphs/${grid}/items/file/${gfileid}`, { method: "DELETE" }),

  graphAddFreeItem: (grid: number, body: { x: number; y: number; free_text: string }) =>
    request<FreeItem>(`/graphs/${grid}/items/free`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphDeleteFreeItem: (grid: number, gfreeid: number) =>
    request<void>(`/graphs/${grid}/items/free/${gfreeid}`, { method: "DELETE" }),

  graphAddMemoItem: (
    grid: number,
    body: { memo_source_type: string; memo_source_id: number; x: number; y: number },
  ) =>
    request<MemoItem>(`/graphs/${grid}/items/memo`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphAddCdctLine: (
    grid: number,
    body: { from_node: number; to_node: number; label?: string; arrow_mode?: string },
  ) =>
    request<CdctLine>(`/graphs/${grid}/lines/cdct`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphDeleteCdctLine: (grid: number, glineid: number) =>
    request<void>(`/graphs/${grid}/lines/cdct/${glineid}`, { method: "DELETE" }),

  graphAddEntityLine: (
    grid: number,
    body: { from_kind: string; from_id: number; to_kind: string; to_id: number; label?: string },
  ) =>
    request<FreeLine>(`/graphs/${grid}/lines/entity`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  graphDeleteEntityLine: (grid: number, gflineid: number) =>
    request<void>(`/graphs/${grid}/lines/entity/${gflineid}`, { method: "DELETE" }),

  graphGenerateModel: (
    model: string,
    name: string,
    fileIds?: number[],
    caseIds?: number[],
  ) =>
    request<{ grid: number; model: string }>("/graphs/models", {
      method: "POST",
      body: JSON.stringify({ model, name, file_ids: fileIds, case_ids: caseIds }),
    }),

  // --- Reference attachments -------------------------------------------

  attachReferenceFile: (risid: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${apiBaseSync()}/references/${risid}/attach`, {
      method: "POST",
      body: form,
    }).then(handleJson<{ ok: boolean; source_id: number; name: string; risid: number }>);
  },
  detachReferenceFile: (risid: number, sourceId: number) =>
    request<void>(`/references/${risid}/attach/${sourceId}`, { method: "DELETE" }),

  // --- Code color scheme --------------------------------------------------

  colorScheme: () => request<ColorScheme>("/color-scheme"),
  syncStatus: () => request<SyncStatus>("/sync/status"),
  syncPresence: () => request<PresenceResponse>("/sync/presence"),
  /** Report the source this instance is currently working on (null leaves the
   *  coder view). Broadcast to other instances as live presence. */
  setPresenceActivity: (fileId: number | null, fileName: string) =>
    request<{ ok: boolean }>("/sync/presence/activity", {
      method: "POST",
      body: JSON.stringify({ file_id: fileId, file_name: fileName }),
    }),
  syncNow: () => request<SyncResult>("/sync/now", { method: "POST" }),
  setSyncEnabled: (enabled: boolean) =>
    request<{ enabled: boolean }>("/sync/settings", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  /** Remember a per-project sync decision: "on"/"off" win over the
   *  auto-detection on the next open; "auto" re-detects. */
  syncSetOverride: (projectPath: string, mode: "auto" | "on" | "off") =>
    request<{ ok: boolean; mode: string }>("/sync/override", {
      method: "PUT",
      body: JSON.stringify({ project_path: projectPath, mode }),
    }),

  // --- App settings -----------------------------------------------------

  appSettings: async () => {
    const base = await request<AppSettings>("/app/settings");
    return { ...base, ...githubLocalSettings() };
  },
  saveAppSettings: async (body: AppSettings) => {
    // Only mirror the GitHub fields when the caller actually sent them —
    // settings saves that only touch auto_open_project must not wipe them.
    const patch: { github_token?: string; github_repo?: string } = {};
    if (body.github_token !== undefined) patch.github_token = body.github_token;
    if (body.github_repo !== undefined) patch.github_repo = body.github_repo;
    if (Object.keys(patch).length > 0) storeGithubLocalSettings(patch);
    const base = await request<AppSettings>("/app/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    });
    return { ...base, ...patch };
  },

  // --- App updates -----------------------------------------------------

  updatesSettings: () => request<UpdatesSettings>("/updates/settings"),
  setUpdatesSettings: (body: UpdatesSettings) =>
    request<UpdatesSettings>("/updates/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  // --- Maintenance -----------------------------------------------------

  maintenanceSettings: () => request<MaintenanceSettings>("/maintenance/settings"),
  saveMaintenanceSettings: (body: { compact_on_close: boolean }) =>
    request<MaintenanceSettings>("/maintenance/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  compactProject: () => request<CompactResult>("/projects/compact", { method: "POST" }),
};
