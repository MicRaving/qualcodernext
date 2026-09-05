/**
 * All exported interfaces, type aliases, and the GRAPH_MODELS constant
 * for the QualCoder v4 API client.
 *
 * Pure type definitions — no runtime logic (except the const assertion).
 */

export interface ProjectSummary {
  databaseversion: string;
  project_date: string;
  project_memo: string;
  about: string;
  bookmark_file_id: number | null;
  bookmark_pos: number | null;
  files_count: number;
  cases_count: number;
  code_categories_count: number;
  codes_count: number;
  attributes_count: number;
  journals_count: number;
  bookmark_filename: string | null;
}

export interface OpenProjectResult {
  ok: boolean;
  project_path: string;
  project_name: string;
  migrations_applied: string[];
  error: string;
  lock_user: string;
  /** Another live instance is already open as the current coder (open only).
   *  Non-empty triggers a blocking warning before sync is allowed to corrupt
   *  the project. */
  duplicate_coder?: string;
  /** Shared-folder detection: true when the collaboration sync cycle should
   *  be switched on for this project (respects the per-project override). */
  sync_auto_enabled?: boolean;
  sync_auto_reason?: string;
}

export interface AppSettings {
  /** Packaged app: auto-open the most recent project on start (default on). */
  auto_open_project: boolean;
  /** GitHub token for the bug report (submitted issues / attachments).
   *  The backend settings model only knows auto_open_project — the GitHub
   *  fields travel in the same payload and are mirrored to localStorage
   *  (the backend drops unknown keys, so they would not survive a reload
   *  otherwise). */
  github_token?: string;
  /** Target repository as "owner/repo" for the bug report. */
  github_repo?: string;
}

export interface Source {
  id: number;
  name: string;
  fulltext: string | null;
  mediapath: string | null;
  memo: string;
  owner: string;
  date: string;
  av_text_id: number | null;
  risid: number | null;
  media_type: "text" | "pdf" | "image" | "audio" | "video";
  /** True when av_text_id points at a companion whose fulltext is non-empty. */
  has_transcript: boolean;
}

export interface CodeTreeItem {
  kind: "category" | "code";
  id: number;
  name: string;
  color: string | null;
  parent_id: number | null;
  memo: string;
  subcode?: boolean;
  /** Sibling order within the parent group (backend sorts by it). */
  position?: number;
}

export interface Code {
  cid: number;
  name: string;
  memo: string;
  catid: number | null;
  owner: string;
  date: string;
  color: string | null;
  supercid?: number | null;
}

export interface Category {
  catid: number;
  name: string;
  memo: string;
  owner: string;
  date: string;
  supercatid: number | null;
}

export interface CodeExample {
  ctid: number;
  fid: number;
  file_name: string;
  seltext: string;
  pos0: number;
  pos1: number;
}

export interface CodeDetails {
  code: Code;
  category_path: string[];
  coding_count: number;
  file_count: number;
  recent_examples: CodeExample[];
}

export interface SourceDetails {
  source: Source;
  text_codings: number;
  image_codings: number;
  av_codings: number;
  codes_used: { cid: number; name: string; color: string | null; count: number }[];
  cases: { caseid: number; name: string }[];
  attributes: { name: string; value: string; attr_type: string }[];
}

export interface Case {
  caseid: number;
  name: string;
  memo: string;
  owner: string;
  date: string;
}

export interface CaseFileLink {
  id: number;
  name: string;
  mediapath: string | null;
  memo: string;
  date: string;
}

export interface AttributeType {
  name: string;
  date: string;
  owner: string;
  memo: string;
  case_or_file: string;
  value_type: string;
  value_labels?: Record<string, string>;
}

export interface AttributeValue {
  attrid: number;
  name: string;
  attr_type: string;
  value: string;
  id: number;
  date: string;
  owner: string;
}

export interface Journal {
  jid: number;
  name: string;
  jentry: string;
  date: string;
  owner: string;
}

// --- Reports -----------------------------------------------------------

export interface CodeFrequencyRow {
  cid: number;
  name: string;
  color: string | null;
  category: string;
  count: number;
}

export interface CodesBySegmentRow {
  ctid: number;
  file_name: string;
  code_name: string;
  category: string;
  seltext: string;
  owner: string;
  date: string;
}


export interface CooccurrenceTable {
  codes: { cid: number; name: string; color: string | null }[];
  counts: number[][];
}

export interface ExactMatchRow {
  seltext: string;
  count: number;
  files: string[];
}

export interface FileSummaryRow {
  fid: number;
  name: string;
  media_type: string;
  codes_count: number;
  segments_count: number;
  cases: string[];
  words: number;
}

export interface CoderComparisonRow {
  owner: string;
  codings_count: number;
  files_count: number;
}

export interface AttributeReportRow {
  name: string;
  value: string;
  attr_type: string;
  entity_kind: string;
  entity_name: string;
}

export interface InterraterResult {
  coder_a: string;
  coder_b: string;
  n_units: number;
  n_categories: number;
  n_pairs: number;
  both: number;
  only_a: number;
  only_b: number;
  neither: number;
  kappa: number | null;
  krippendorff: number | null;
  gwet_ac1: number | null;
}

export interface Coding {
  ctid: number;
  cid: number;
  fid: number;
  seltext: string;
  pos0: number;
  pos1: number;
  owner: string;
  date: string;
  memo: string;
  avid: number | null;
  important: number;
}

export interface ImageCoding {
  imid: number;
  id: number;
  x1: number;
  y1: number;
  width: number;
  height: number;
  cid: number;
  memo: string;
  date: string;
  owner: string;
  important: number;
  pdf_page: number | null;
}

export interface AVCoding {
  avid: number;
  id: number;
  pos0: number;
  pos1: number;
  cid: number;
  memo: string;
  date: string;
  owner: string;
  important: number;
}

export interface Annotation {
  anid: number;
  fid: number;
  pos0: number;
  pos1: number;
  memo: string;
  owner: string;
  date: string;
}

export interface CaseTextSpan {
  id: number;
  caseid: number;
  fid: number;
  pos0: number;
  pos1: number;
  owner: string;
  date: string;
  memo: string;
}

/** One shifted segment returned by the shift-positions endpoint. */
export interface ShiftedSegment {
  newpos0: number;
  newpos1: number;
}

export interface ShiftPositionsResponse {
  codings: (ShiftedSegment & { ctid?: number })[];
  annotations: (ShiftedSegment & { anid?: number })[];
  case_text: (ShiftedSegment & { id?: number })[];
  deletions: { code_text: number[]; annotation: number[]; case_text: number[] };
}

export interface CommitEditResponse {
  updated: { code_text: number; annotation: number; case_text: number };
  deleted: { code_text: number[]; annotation: number[]; case_text: number[] };
}

export interface AutocodeResponse {
  created: Coding[];
  count: number;
  suggested: { cid: number; name: string; reason: string }[];
}

export interface UndoCodingsResponse {
  restored: number;
}

// --- AI assistant -----------------------------------------------------

export interface AiStatus {
  enabled: boolean;
  configured: boolean;
  reason: string;
  provider: string;
  base_url: string;
  model: string;
  mcp_permissions?: string;
  /** MCP mode: "internal" (QCnext's own tools) or "external" (stdio server). */
  mcp_mode?: string;
  /** Effective AI-chat wrapping prompt (custom or the built-in default). */
  wrapping_prompt?: string;
  /** Live reachability of the provider (only when probed). */
  reachable?: boolean | null;
  probe_error?: string;
}

/** The AI-chat wrapping prompt + the built-in default (for "reset"). */
export interface AiWrappingPrompt {
  text: string;
  default: string;
}

export interface AiToolCallEvent {
  tool: string;
  arguments: Record<string, unknown>;
  result: unknown;
  /** True when the write was approved; false when rejected by the user. */
  approved?: boolean;
}

export interface AiPendingTool {
  name: string;
  arguments: Record<string, unknown>;
}

export interface AiChatReply {
  reply: string;
  model: string;
  /** Chat session the exchange was appended to (auto-created when new). */
  chat_id?: number;
  /** Agentic chat: the tools the model executed during this turn. */
  tool_calls?: AiToolCallEvent[];
  /** Present when an agentic turn is paused awaiting write approval. */
  status?: "awaiting_approval";
  token?: string;
  pending_tools?: AiPendingTool[];
}

export interface AiSearchResult {
  source_id: number;
  file_name: string;
  text: string;
  score: number;
}

export interface AiSearchResponse {
  results: AiSearchResult[];
  indexed: boolean;
}

export interface AiPromptInfo {
  id: string;
  mode: string;
  name: string;
  description: string;
  /** Friendly display label (falls back to ``name``). */
  label?: string;
  /** Backend flag for internal entries (e.g. ``_init``); never shown. */
  hidden?: boolean;
  /** Dropdown section: "analysis" | "specialized" | "custom" | "". */
  group?: string;
  /** True for user-defined templates stored in the project. */
  custom?: boolean;
  /** True for app-wide templates (usable in every project). */
  global?: boolean;
}

export interface AiChatInfo {
  id: number;
  title: string;
  created: string;
  updated: string;
}

export interface AiChatMessage {
  id: number;
  chat_id: number;
  role: string;
  text: string;
  request_json: string;
  created: string;
}

export interface AiChatDetail extends AiChatInfo {
  messages: AiChatMessage[];
}

export interface AiTemplateInfo {
  id: number;
  name: string;
  description: string;
  text: string;
  created: string;
  updated: string;
}

/** A per-chat-mode persona: the mode's system prompt, with its built-in
 *  default and the current text (default unless the user overrode it). */
export interface AiPersonaInfo {
  mode: string;
  default: string;
  text: string;
}

/** An editable entry in the template editor. */
export interface AiEditorTemplate {
  id: string;
  name: string;
  label: string;
  description: string;
  text: string;
  /** The shipped text for built-ins (null for user-created ones). */
  default: string | null;
  group: string;
  /** builtin = shipped template (editable via an app-wide override),
   *  app = saved app-wide, project = this project's row. */
  scope: "builtin" | "app" | "project";
}

export interface AiIndexStatus {
  indexed: boolean;
  model: string;
  chunks: number;
}

// --- Full-text search (literal/regex across project entities) ----------------

/** Backend entity-type names (the ``entities`` search-scope param). */
export type SearchEntityType =
  | "files"
  | "codes"
  | "categories"
  | "cases"
  | "journal"
  | "memos"
  | "attributes"
  | "comments";

/** Result ``kind`` value (singular) returned by the backend. */
export type SearchEntityKind =
  | "file"
  | "code"
  | "category"
  | "case"
  | "journal"
  | "memo"
  | "attribute"
  | "comment";

/** Entity types in stable display order (all preselectable scopes). */
export const SEARCH_ENTITY_TYPES: SearchEntityType[] = [
  "files",
  "codes",
  "categories",
  "cases",
  "journal",
  "memos",
  "attributes",
  "comments",
];

export interface SearchHit {
  pos0: number;
  pos1: number;
  /** Match offsets relative to ``context`` (yellow highlight in the UI). */
  rel0: number;
  rel1: number;
  context: string;
}

export interface SearchResultItem {
  /** Entity type the hit lives in (backend ``kind``). */
  kind: SearchEntityKind;
  /** Primary key of the matched entity (source id for files). */
  id: number;
  name: string;
  mediapath: string;
  match_count: number;
  hits: SearchHit[];
  /** Set for file hits (and file-owned memo hits) — the coder target. */
  source_id: number | null;
  /** Memo/comment hits: the owning entity kind + id. */
  ref_kind: string | null;
  ref_id: number | null;
}

export interface SearchResponse {
  total: number;
  results: SearchResultItem[];
}

// --- In-app help topics -----------------------------------------------------

export interface HelpTopic {
  id: string;
  title: string;
  description: string;
}

export interface HelpTopicDetail extends HelpTopic {
  content: string;
}

export interface HelpSearchResult {
  id: string;
  title: string;
  snippet: string;
  /** Match span within ``snippet`` (for hit highlighting). */
  rel0?: number;
  rel1?: number;
}

export interface Pseudonym {
  original: string;
  pseudonym: string;
}

export interface SpeakerTurn {
  name: string;
  fid: number;
  filename: string;
  seltext: string;
  seltext_response: string;
  pos0: number;
  pos1: number;
}

export interface SpeakerInfo {
  name: string;
  count: number;
  files: string[];
  example: string;
}

export interface ReferenceEntry {
  risid: number;
  title: string;
  authors: string[];
  year: string;
  type: string;
  fields: Record<string, string[]>;
  sources: { id: number; name: string }[];
}

export interface BadLink {
  id: number;
  name: string;
  kind: string;
  path: string;
  exists: boolean;
  mediapath: string;
}

export interface FileFilter {
  filterid: number;
  name: string;
  filter: string;
  owner: string;
}

export interface Bookmarks {
  bookmark_file_id: number | null;
  bookmark_pos: number | null;
  av_bookmark_file_id: number | null;
  av_bookmark_msec: number | null;
  av_bookmark_textpos: number | null;
}

export interface CodeSegmentRow {
  kind: "text" | "image" | "av";
  id: number;
  file_name: string;
  seltext?: string;
  pos0?: number;
  pos1?: number;
  x1?: number;
  y1?: number;
  width?: number;
  height?: number;
  pdf_page?: number | null;
  owner: string;
  memo: string;
}

export interface CodeSummary {
  cid: number;
  name: string;
  memo: string;
  color: string;
  categories: string[];
  counts: { text: number; image: number; av: number };
  total: number;
  files: string[];
  file_count: number;
}


export interface CodeRelation {
  code_a: string;
  code_b: string;
  count: number;
}

export interface WordFrequencyRow {
  word: string;
  count: number;
}

export interface ChartSeries {
  cid: number;
  name: string;
  color: string;
  count?: number;
  cumulative?: number;
}

export interface ChartMatrix {
  kind: string;
  files?: { fid: number; name: string }[];
  cases?: { caseid: number; name: string }[];
  labels?: { fid?: number; caseid?: number; name: string }[];
  codes: ChartSeries[];
  counts?: number[][];
  series?: { cid: number; count: number }[][];
  rows?: { cid: number; name: string; color: string; value: number }[];
}

// --- Interchange (REFI-QDA etc.) --------------------------------------

export interface InterchangeResult {
  ok: boolean;
  message?: string;
  codes?: number;
  categories?: number;
  sources?: number;
  codings?: number;
  cases?: number;
  references?: number;
  attributes?: number;
}

// --- SQL console -------------------------------------------------------

export interface SqlResult {
  columns: string[];
  rows: unknown[][];
  truncated?: boolean;
}

export interface SavedQuery {
  title: string;
  description: string;
  grouper: string;
  ssql: string;
}

// --- Audit / history ---------------------------------------------------

export interface AuditRow {
  id: number;
  ts: string;
  user: string;
  action: string;
  entity: string;
  entity_id: number | null;
  source_id: number | null;
  detail: Record<string, unknown>;
  summary?: string;
  undoable?: boolean;
  undo_reason?: string | null;
}

export interface AuditResponse {
  rows: AuditRow[];
  total: number;
}

export interface AuditStatsRow {
  action: string;
  count: number;
}

// --- Transcription -----------------------------------------------------

export interface TranscribeSettings {
  engine: string;
  model: string;
  language: string | null;
  translate: boolean;
  beam_size: number;
  temperature: number;
  vad: boolean;
  device: string;
  segment_coding: boolean;
}

export interface TranscribeStatus {
  engines: { whisper: boolean };
  models_cached: string[];
  model_dir: string;
  models: string[];
  settings: TranscribeSettings;
}


export interface TranscribeJob {
  id: string;
  state: string;
  progress: number;
  message: string;
  segments: unknown[];
  error: string | null;
  transcript_source_id?: number | null;
  /** Partial "[mm:ss] text" transcript while the job is still running. */
  live_text?: string | null;
  result?: unknown[];
  paused?: boolean;
}

/** A background AI-autocode job (one per source file). */
export interface AutocodeJob {
  id: string;
  state: string;
  progress: number;
  message: string;
  source_id: number;
  paused?: boolean;
  error?: string | null;
  result?: { count: number; suggested: { cid: number; name: string; reason: string }[] } | null;
}

// --- R integration (Rscript bridge) ------------------------------------

/** R installation status as probed by the backend bridge. */
export interface RStatus {
  available: boolean;
  path: string | null;
  version: string | null;
  error: string | null;
}

/** A background R-script job (runs through the same queue as the others). */
export interface RJob {
  id: string;
  state: string;
  progress: number;
  message: string;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  error: string | null;
  /** Artifact file names produced by the job (subset of GET /r/artifacts). */
  artifacts?: string[];
}

/** An artifact file in the R exchange directory. */
export interface RArtifact {
  name: string;
  kind: "png" | "csv" | "other";
  size: number;
  modified: string;
}

/** A saved R script (per project, like stored SQL queries). */
export interface RScript {
  name: string;
  script: string;
  updated: string;
}

/** Response of POST /r/prepare-report: a template stub + prepared files. */
export interface RPrepareResult {
  stub: string;
  files: string[];
}

export interface CoderInfo {
  name: string;
  coding_count: number;
}

export interface CodersResponse {
  current: string;
  coders: CoderInfo[];
}

// --- Graphs (code-map editor) -----------------------------------------

export interface GraphSummary {
  grid: number;
  name: string;
  description: string;
  date: string;
  scene_width: number;
  scene_height: number;
}

export interface CdctItem {
  gtextid: number;
  grid: number;
  x: number;
  y: number;
  supercatid: number | null;
  catid: number | null;
  cid: number | null;
  font_size: number;
  bold: number;
  isvisible: number;
  displaytext: string;
}

export interface CaseItem {
  gcaseid: number;
  grid: number;
  x: number;
  y: number;
  caseid: number;
  font_size: number;
  bold: number;
  color: string | null;
  displaytext: string;
}

export interface FileItem {
  gfileid: number;
  grid: number;
  x: number;
  y: number;
  fid: number;
  font_size: number;
  bold: number;
  color: string | null;
  displaytext: string;
}

export interface FreeItem {
  gfreeid: number;
  grid: number;
  freetextid: number;
  x: number;
  y: number;
  free_text: string;
  color: string | null;
  font_size: number;
  bold: number;
}

export interface MemoItem {
  gmemoid: number;
  grid: number;
  memo_source_type: string;
  memo_source_id: number;
  x: number;
  y: number;
  color: string | null;
  font_size: number;
}

export interface CdctLine {
  glineid: number;
  grid: number;
  fromcatid: number | null;
  fromcid: number | null;
  tocatid: number | null;
  tocid: number | null;
  color: string | null;
  linewidth: number;
  linetype: string | null;
  isvisible: number;
  label: string | null;
  arrow_mode: string | null;
}

export interface FreeLine {
  gflineid: number;
  grid: number;
  fromfreetextid: number | null;
  fromcatid: number | null;
  fromcid: number | null;
  fromcaseid: number | null;
  fromfileid: number | null;
  fromimid: number | null;
  fromavid: number | null;
  tofreetextid: number | null;
  tocatid: number | null;
  tocid: number | null;
  tocaseid: number | null;
  tofileid: number | null;
  toimid: number | null;
  toavid: number | null;
  color: string | null;
  linewidth: number;
  linetype: string | null;
  label: string | null;
  arrow_mode: string | null;
}

export interface GraphData {
  graph: GraphSummary;
  cdct_items: CdctItem[];
  case_items: CaseItem[];
  file_items: FileItem[];
  free_items: FreeItem[];
  memo_items: MemoItem[];
  cdct_lines: CdctLine[];
  free_lines: FreeLine[];
  categories: { catid: number; name: string; supercatid: number | null }[];
  codes: { cid: number; name: string; color: string | null; catid: number | null; supercid: number | null; memo: string | null }[];
  cases: { caseid: number; name: string }[];
  sources: { id: number; name: string }[];
}

export interface ColorScheme {
  colors: string[];
  ranges: { name: string; min: number; max: number }[];
}

export const GRAPH_MODELS = [
  "category-hierarchy",
  "file-hierarchy",
  "file-comparison",
  "case-hierarchy",
  "case-comparison",
  "cooccurrence-network",
] as const;

// --- Collaboration sync (Option C: versioned sidecars + conflict resolution) --

/** Pending conflict detected during sync — both local and remote row
 *  snapshots are stored so the user can resolve via the ConflictResolver. */
export interface SyncConflictV2 {
  id: number;
  entity: string;
  pk: string;
  pk_name: string;
  local_rev: number;
  remote_rev: number;
  local_row: Record<string, unknown> | null;
  remote_row: Record<string, unknown> | null;
  remote_instance: string;
  remote_coder: string;
  detected_at: string;
  /** Human-readable label for the entity (e.g. "Code (5)"). */
  entity_label: string;
}

/** Live coder presence — an instance actively working on the open project
 *  (broadcast via per-instance presence files inside the project folder). */
export interface PresenceEntry {
  coder: string;
  os_user: string;
  pid: number;
  /** Last heartbeat (epoch seconds); "live" when recent. */
  ts: number;
  /** The source currently being worked on (null = not in a file). */
  file_id: number | null;
  file_name: string;
  /** Stable instance identifier (UUID). */
  instance: string;
}

export interface PresenceResponse {
  ok: boolean;
  presence: PresenceEntry[];
}

/** Per-instance collaborator info (replaces SyncCollaborator). */
export interface SyncCollaboratorV2 {
  instance: string;
  coder: string;
  last_sync: number; // sidecar mtime (epoch seconds)
  pending_import: number;
  state: "active" | "stale" | "offline";
}

export interface SyncSettings {
  enabled: boolean;
  /** Background sync cadence in seconds (1 min default; 15s-5min dropdown). */
  interval_secs: number;
}

export interface SyncStatus {
  ok: boolean;
  reason?: string;
  enabled?: boolean;
  /** This instance's stable ID. */
  instance_id?: string;
  /** Authoritative sync state: "active" | "syncing" | "conflict" | "error". */
  state?: "active" | "syncing" | "conflict" | "error" | "offline";
  user?: string;
  pending_export: number;
  pending_import: number;
  /** Total pending conflicts (drives the red indicator). */
  pending_conflicts: number;
  collaborators: SyncCollaboratorV2[];
  last_sync: number; // epoch seconds of the last successful cycle (0 = never)
  last_error: string;
  last_error_at: number;
}

/** Legacy conflict type (kept for SyncResult backward compat). */
export interface SyncConflict {
  seq: number;
  entity: string;
  pk: string;
  action: string;
  reason: string;
}

/** Legacy collaborator type (kept for backwards compat). */
export interface SyncCollaborator {
  user: string;
  last_sync: number;
  pending_import: number;
  pending_conflicts: number;
  conflicts?: SyncConflict[];
}

export interface UpdatesSettings {
  check_interval: "daily" | "weekly" | "never";
  auto_update: boolean;
}

export interface MaintenanceSettings {
  compact_on_close: boolean;
  last_compact: string;
}

export interface CompactResult {
  ok: boolean;
  before_bytes: number;
  after_bytes: number;
  freed_bytes: number;
  indexes_dropped: number;
  indexes_recreated: number;
}

export interface SyncResult {
  ok: boolean;
  reason?: string;
  exported?: number;
  imported?: Record<string, { applied: number; conflicts: SyncConflict[] }>;
  repaired?: boolean;
}
