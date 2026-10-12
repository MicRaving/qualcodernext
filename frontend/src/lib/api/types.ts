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
  /** Manually configured Rscript path (null = auto-detect). */
  custom?: string | null;
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
    /** Divergence watchdog: last repair time + consecutive repairs that healed rows. */
    repair?: { last_at: number; consecutive_applied: number };
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
  /** Update channel: `stable` (full releases) or `nightly` (`X.Y.Z_NNN` deltas). */
  channel: "stable" | "nightly";
}

export interface HotpatchVersion {
  app_version: string;
  frontend_version: string | null;
  previous_version: string | null;
  channel: "stable" | "nightly";
}

export interface HotpatchApplyRequest {
  version: string;
  url: string;
  sha256: string;
  signature: string;
}

export interface OverlayVersion {
  overlay_version: string | null;
  previous_version: string | null;
  overlay_active: boolean;
}

export interface OverlayApplyRequest {
  version: string;
  url: string;
  sha256: string;
  signature: string;
}

/** Backend-source patch reference inside a nightly manifest. */
export interface BackendPatchRef {
  url: string;
  sha256: string;
  signature: string;
  size?: number;
}

/** Native-file delta reference inside a nightly manifest. */
export interface NativePatchRef {
  from: string;
  to: string;
  url: string;
  sha256: string;
  signature: string;
  size: number;
}

export interface NativeVersion {
  staged: string | null;
  applied_from: string | null;
  applied_to: string | null;
  previous_to: string | null;
  bundle_base: string;
  pointer: string;
}

export interface NativeApplyRequest {
  version: string;
  from_version: string;
  url: string;
  sha256: string;
  signature: string;
  size: number;
}

/** Nightly patch manifest (`qcnext-nightly.json`, see scripts/build-patch.py). */
export interface NightlyManifest {
  version: string;
  base: string;
  notes?: string;
  pub_date?: string;
  url?: string;
  sha256?: string;
  signature?: string;
  size?: number;
  backend?: BackendPatchRef;
  native?: NativePatchRef;
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


// ── Meta-analysis pipeline ───────────────────────────────────────────

export interface MetaHit {
  hit_id: number;
  title: string;
  abstract?: string | null;
  authors?: string | null;
  doi?: string | null;
  year?: string | null;
  source?: string | null;
  language?: string | null;
  search_run?: string | null;
  status: string;
  eligible?: boolean;
  screened?: boolean;
  created: string;
  updated: string;
}

/** Screening criterion decision kind (contract §1/§3). */
export type MetaCriterionKind = "verdict" | "classify" | "number";

export interface MetaCriterion {
  id: number;
  position: number;
  key: string;
  label: string;
  prompt_text: string;
  created: string;
  // ── codebook v2 (all optional so v1 payloads keep working) ──
  kind?: MetaCriterionKind;
  /** Choices offered for `classify` / `number` criteria. */
  options?: string[];
  /** Values that PASS the criterion. */
  pass_values?: string[];
  /** PRISMA exclusion label used when the criterion fails. */
  exclude_reason?: string;
  /** `false`/0 = informational; never blocks inclusion. */
  gating?: boolean | number;
  /** Guidance shown beside the criterion. */
  help?: string;
}

export interface MetaScreening {
  id: number;
  hit_id: number;
  owner: string;
  run_id: string;
  verdicts: Record<string, { applies: string; certainty: string; reason?: string }>;
  intervention_type?: string | null;
  rationale?: string | null;
  origin: string;
  /** Screening stage (contract §1): `abstract` | `fulltext`. */
  stage?: string;
  /** Structured exclusion reason (else derived). */
  reason?: string;
  model?: string | null;
  prompt_hash?: string | null;
  created: string;
  updated: string;
}

// ── Extraction record model (contract §4) ─────────────────────────────

export interface MetaExtractionMetric {
  [name: string]: unknown;
}

/** One study/experiment record: study-level vars + its metrics list. */
export interface MetaExtractionRecord {
  study: Record<string, unknown>;
  metrics: MetaExtractionMetric[];
}

export interface MetaExtractionStudyVars {
  records: MetaExtractionRecord[];
  [key: string]: unknown;
}

export interface MetaDocument {
  id: number;
  hit_id: number;
  source_id?: number | null;
  retrieval_method?: string | null;
  url?: string | null;
  status: string;
  message?: string | null;
  title?: string;
  doi?: string | null;
  created: string;
  updated: string;
}

export interface MetaExtraction {
  id: number;
  hit_id: number;
  source_id?: number | null;
  owner: string;
  scheme: string;
  scheme_label?: string;
  study_vars: MetaExtractionStudyVars;
  /** Derived flat list (study role values merged into each metric). */
  dv_metrics: Record<string, unknown>[];
  prescreen?: Record<string, unknown> | null;
  model?: string | null;
  prompt_hash?: string | null;
  status: string;
  missing_reason?: string | null;
  title?: string;
  doi?: string | null;
  created: string;
  updated: string;
}

/** Manual extraction save payload (contract §4/§10). */
export interface MetaExtractionSaveRequest {
  hit_id: number;
  owner?: string;
  scheme?: string;
  study_vars: MetaExtractionStudyVars;
  status?: string;
  missing_reason?: string | null;
}

/** `PUT /meta/extractions` envelope — the caller unwraps `.extraction`. */
export interface MetaExtractionSaveResult {
  ok: boolean;
  id: number;
  hit_id: number;
  owner: string;
  status: string;
  missing?: unknown;
  extraction: MetaExtraction;
  [key: string]: unknown;
}

export interface MetaScheme {
  id: number;
  name: string;
  label?: string | null;
  description?: string | null;
  prescreen_prompt?: string | null;
  coding_prompt?: string | null;
  codebook?: string | null;
  created: string;
  updated: string;
}

// ── Codebook v2 (contract §2/§3) ──────────────────────────────────────

/** Study/experiment-level role vocabulary (backend `STUDY_ROLES`). */
export const STUDY_ROLES = [
  "study_id",
  "parent_study_id",
  "year",
  "doi",
  "authors",
  "title",
  "description",
  "notes",
  "design",
  "country",
  "setting",
  "sample_n",
  "intervention_type",
  "dataset_url",
] as const;

/** Metric/contrast-level role vocabulary (backend `METRIC_ROLES`). */
export const METRIC_ROLES = [
  "dv_name",
  "dv_domain",
  "score_types",
  "discernment",
  "polarity",
  "scale_type",
  "scale_points",
  "scale_min",
  "scale_max",
  "contrast_type",
  "eligible_primary",
  "comparison_label",
  "group1_label",
  "group2_label",
  "timepoint_1",
  "timepoint_2",
  "posttest_type",
  "delay_weeks",
  "n1",
  "n2",
  "n_total",
  "m1",
  "m2",
  "sd1",
  "sd2",
  "n1_pre",
  "m1_pre",
  "sd1_pre",
  "n2_pre",
  "m2_pre",
  "sd2_pre",
  "n1_post",
  "m1_post",
  "sd1_post",
  "n2_post",
  "m2_post",
  "sd2_post",
  "t",
  "df_num",
  "df_den",
  "F",
  "chi2",
  "z",
  "r",
  "p",
  "p_censored",
  "yi",
  "vi",
  "sei",
  "d",
  "g",
  "d_ci_low",
  "d_ci_high",
  "g_ci_low",
  "g_ci_high",
  "d_se",
  "g_se",
  "or",
  "or_ci_low",
  "or_ci_high",
  "log_odds",
  "rr",
  "beta",
  "beta_se",
  "eta2p",
  "eta2p_ci_low",
  "eta2p_ci_high",
  "effect_type_reported",
  "effect_favors",
  "effect_direction_meaning",
  "conversion_method",
  "conversion_inputs",
  "cell_descriptives",
  "missing_reason",
] as const;

/** Controlled role vocabulary a scheme field may carry. */
export type FieldRole = (typeof STUDY_ROLES)[number] | (typeof METRIC_ROLES)[number];

export type SchemeFieldType =
  | "string"
  | "integer"
  | "number"
  | "boolean"
  | "list"
  | "object";

export type SchemeFieldEditor =
  | "text"
  | "textarea"
  | "number"
  | "boolean"
  | "select"
  | "multiselect"
  | "date"
  | "json"
  | "objectlist"
  | "kv";

export interface SchemeFieldColumn {
  name: string;
  type: string;
}

export interface SchemeField {
  name: string;
  label: string;
  group: string;
  type: SchemeFieldType | string;
  editor: SchemeFieldEditor | string;
  required: boolean;
  description: string;
  instruction?: string;
  options?: string[];
  columns?: SchemeFieldColumn[];
  role?: FieldRole | null;
  /** Offered as a subgroup/moderator variable (default true). */
  moderator?: boolean;
}

export interface SchemeGroup {
  name: string;
  label: string;
}

export interface SchemeMetrics {
  enabled: boolean;
  group: string;
  label: string;
  fields: SchemeField[];
}

export interface SchemeCodeField {
  name: string;
  label: string;
  instruction: string;
}

/** Effect-size families the editor can preset fields for (contract §3). */
export const EFFECT_FAMILIES = [
  "descriptives",
  "t",
  "F",
  "r",
  "yi",
  "d_g",
  "odds_ratio",
  "beta",
  "eta2p",
  "chi2",
] as const;

export type MetaEffectFamily = (typeof EFFECT_FAMILIES)[number];

export interface MetaSchemeCodebookV2 {
  version: 2;
  category: string;
  groups: SchemeGroup[];
  /** Study/experiment-level fields. */
  fields: SchemeField[];
  metrics: SchemeMetrics;
  effect_families: MetaEffectFamily[];
  code_fields: SchemeCodeField[];
  /** v1 alias of `fields`, kept so the publish path keeps working. */
  study_fields?: SchemeField[];
  [key: string]: unknown;
}

/** Portable scheme bundle used by export/import. */
export interface MetaSchemeExport {
  name: string;
  label?: string | null;
  description?: string | null;
  prescreen_prompt?: string | null;
  coding_prompt?: string | null;
  codebook: MetaSchemeCodebookV2;
}

// ── Analysis & reporting results (contract §6–§10) ────────────────────

export interface MetaEffectRow {
  study_id: string;
  effect: number;
  variance: number;
  se?: number | null;
  domain?: string | null;
  hit_id?: number;
  record_index?: number;
  metric_index?: number;
  scheme?: string;
  owner?: string;
  [key: string]: unknown;
}

/** Pooling estimator the analysis endpoints accept (`POST /meta/analysis/*`). */
export type MetaPoolModel = "dl" | "two_level" | "fixed";

/** Consensus synthesis report (`POST /meta/analysis/pooled` → `consensus`).
 *  Present only when the request carried no `owner` filter: unanimous fields
 *  kept, disagreements settled by the `master` adjudication or excluded +
 *  counted, underivable contrasts dropped + counted. */
export interface MetaConsensusReport {
  n_hits: number;
  n_groups: number;
  n_single_owner: number;
  n_consensus_units: number;
  n_fields_unanimous: number;
  n_master_resolved: number;
  n_dropped_conflicts: number;
  n_dropped_metrics: number;
  [key: string]: unknown;
}

export interface MetaPooledResult {
  k: number;
  estimate: number;
  se: number;
  ci_low: number;
  ci_high: number;
  tau2: number;
  q: number;
  q_df: number;
  q_p: number;
  i2: number;
  p: number;
  /** Distinguishes the estimator that produced the row ("dl" | "fixed"). */
  model?: string;
  n_studies?: number;
  /** Present when the request asked for `model="two_level"`. */
  tau2_within?: number | null;
  tau2_between?: number | null;
  var_within_share?: number | null;
  var_between_share?: number | null;
  var_sampling_share?: number | null;
  /** Consensus transparency counts (only when no `owner` filter was sent). */
  consensus?: MetaConsensusReport | null;
  [key: string]: unknown;
}

/** Legacy two-level shape (the fields now travel on `MetaPooledResult`). */
export type MetaTwoLevelResult = MetaPooledResult & {
  tau2_within: number;
  tau2_between: number;
  var_within_share: number;
  var_between_share: number;
};

export interface MetaForestRow {
  study_id: string;
  effect: number;
  variance?: number;
  se?: number;
  ci_low?: number;
  ci_high?: number;
  weight?: number;
  domain?: string | null;
  [key: string]: unknown;
}

export interface MetaForest {
  rows: MetaForestRow[];
  pooled?: MetaPooledResult | null;
  [key: string]: unknown;
}

export interface MetaSubgroupLevel {
  key: string;
  /** Canonical level id/label (backends may send `value`/`label`). */
  value?: string;
  label?: string;
  k: number;
  n_studies?: number;
  estimate: number;
  se?: number;
  ci_low?: number;
  ci_high?: number;
  tau2?: number;
  i2?: number;
  [key: string]: unknown;
}

export interface MetaSubgroupResult {
  key: string;
  groups: MetaSubgroupLevel[];
  /** Cochrane between-group Q (`qm` is the canonical name). */
  qm?: number | null;
  qm_df?: number | null;
  qm_p?: number | null;
  /** Legacy aliases a backend may still send. */
  q_between?: number;
  q_between_df?: number;
  q_between_p?: number;
  [key: string]: unknown;
}

/** One variable offered as a subgroup/moderator (`GET /meta/moderators`). */
export interface MetaModerator {
  name: string;
  label?: string | null;
  group?: string | null;
  /** Study-level vs per-contrast (metric) variable. */
  kind?: "study" | "metric" | string;
  role?: string | null;
  type?: string | null;
  editor?: string | null;
  /** Schemes defining this variable. */
  schemes?: string[];
  [key: string]: unknown;
}

export interface MetaModeratorResult {
  role: string;
  k?: number;
  /** Moderator terms in the model (`Intercept`, `term:level`, …). */
  terms?: string[];
  /** Interaction pairs echoed back from the request. */
  interactions?: [string, string][];
  names?: string[];
  /** Effects dropped for missing moderator/interaction values. */
  n_dropped?: number;
  n_clusters?: number;
  /** `CR1` (study-clustered robust) or `model` covariance. */
  covariance?: string;
  /** Fitted coefficients (canonical name). */
  coefficients?: MetaModeratorTerm[];
  estimate?: number | null;
  se?: number | null;
  qm?: number | null;
  qm_df?: number | null;
  qm_p?: number | null;
  r2?: number | null;
  r2_tau?: number | null;
  tau2?: number | null;
  note?: string;
  [key: string]: unknown;
}

export interface MetaModeratorTerm {
  term: string;
  estimate: number;
  se?: number | null;
  z?: number | null;
  p?: number | null;
  ci_low?: number | null;
  ci_high?: number | null;
  [key: string]: unknown;
}

export interface MetaEggerResult {
  intercept: number;
  se: number;
  t: number;
  p: number;
  k?: number;
  [key: string]: unknown;
}

/** Egger regression as returned by the publication-bias suite (adds the
 *  precision slope next to the legacy intercept terms). */
export interface MetaPublicationBiasEgger {
  intercept: number;
  se: number;
  t: number;
  p: number;
  slope: number;
  slope_se: number;
  slope_p: number;
  [key: string]: unknown;
}

/** One PET / PEESE regression arm. */
export interface MetaPetPeeseArm {
  intercept: number;
  se: number;
  t: number;
  p: number;
  [key: string]: unknown;
}

export interface MetaPetPeese {
  pet: MetaPetPeeseArm;
  peese: MetaPetPeeseArm;
  /** Which arm the backend recommends ("pet" | "peese"). */
  recommended: string;
  [key: string]: unknown;
}

export interface MetaTrimAndFill {
  /** Imputed (missing) studies. */
  k0: number;
  side: string;
  estimate: number;
  se: number;
  ci_low: number;
  ci_high: number;
  [key: string]: unknown;
}

export interface MetaPCurve {
  n_significant: number;
  n_p_lt_025: number;
  p_half: number;
  evidential: boolean | number;
  note: string;
  [key: string]: unknown;
}

/** `POST /meta/analysis/publication-bias` — Egger, PET-PEESE, trim-and-fill
 *  and p-curve in one payload. */
export interface MetaPublicationBiasResult {
  k: number;
  k_total: number;
  egger?: MetaPublicationBiasEgger | null;
  pet_peese?: MetaPetPeese | null;
  trim_and_fill?: MetaTrimAndFill | null;
  p_curve?: MetaPCurve | null;
  [key: string]: unknown;
}

// ── Multiverse specification curve (contract §6) ──────────────────────

/** One dimension of the multiverse grid and its candidate levels. */
export interface MetaMultiverseDimension {
  name: string;
  levels: string[];
  [key: string]: unknown;
}

/** One analytic specification: the level chosen per dimension + its fit. */
export interface MetaMultiverseSpec {
  id: string | number;
  /** dimension name -> chosen level (or levels for a multiselect). */
  choices: Record<string, unknown>;
  k: number;
  estimate: number;
  se?: number | null;
  ci_low?: number | null;
  ci_high?: number | null;
  tau2?: number | null;
  i2?: number | null;
  [key: string]: unknown;
}

/** Distribution of the specification-curve estimates. */
export interface MetaMultiverseSummary {
  n_specs: number;
  n_ok: number;
  median: number;
  min: number;
  max: number;
  pct_positive: number;
  ci_low?: number | null;
  ci_high?: number | null;
  [key: string]: unknown;
}

/** `POST /meta/analysis/multiverse` — every analytic combination. */
export interface MetaMultiverseResult {
  k_total: number;
  n_specs: number;
  dimensions: MetaMultiverseDimension[];
  specs: MetaMultiverseSpec[];
  summary: MetaMultiverseSummary;
  [key: string]: unknown;
}

// ── Variable audit / coverage (contract §11) ──────────────────────────

/** One codebook field's coverage across the extracted records. */
export interface MetaAuditField {
  name: string;
  label?: string;
  group?: string;
  kind?: string;
  role?: string | null;
  editor?: string;
  /** Records/metrics where the field is populated. */
  set: number;
  /** Records/metrics in scope. */
  total: number;
  /** Populated share (0–1). */
  coverage: number;
  /** Per-field issue messages (empty when the field is clean). */
  issues: string[];
  [key: string]: unknown;
}

/** One audit finding, severity-coded for the UI. */
export interface MetaAuditIssue {
  severity: string;
  field: string;
  message: string;
  count: number;
  [key: string]: unknown;
}

/** `GET /meta/audit` — extraction/metric coverage + findings. */
export interface MetaAuditResult {
  n_extractions: number;
  n_records: number;
  n_metrics: number;
  fields: MetaAuditField[];
  issues: MetaAuditIssue[];
  [key: string]: unknown;
}

// ── Bayesian pooled model (contract §6) ───────────────────────────────

export interface MetaBayesRequest extends MetaAnalysisRequest {
  /** Requested µ prior SD: N(0, mu_sd²). */
  mu_sd?: number;
  /** τ prior family (e.g. "half-normal" | "half-cauchy"). */
  tau_prior?: string;
  /** τ prior scale. */
  tau_scale?: number;
}

export interface MetaBayesMu {
  mean: number;
  median: number;
  ci_low: number;
  ci_high: number;
  p_gt0: number;
  p_two_sided: number;
  [key: string]: unknown;
}

export interface MetaBayesTau {
  mean: number;
  median: number;
  ci_low: number;
  ci_high: number;
  [key: string]: unknown;
}

export interface MetaBayesPrior {
  mu_sd: number;
  tau_prior: string;
  tau_scale: number;
  [key: string]: unknown;
}

/** One row of the prior-sensitivity grid. */
export interface MetaBayesSensitivityRow {
  mu_sd: number;
  tau_prior: string;
  tau_scale: number;
  mean: number;
  ci_low: number;
  ci_high: number;
  bf10: number;
  [key: string]: unknown;
}

export interface MetaBayesResult {
  k: number;
  k_total: number;
  mu?: MetaBayesMu | null;
  tau?: MetaBayesTau | null;
  bf10: number;
  bf01_tau0: number;
  prior?: MetaBayesPrior | null;
  sensitivity?: MetaBayesSensitivityRow[];
  /** Posterior density curve (µ on the x-grid) for the `bayes.png` figure. */
  posterior?: { mu: number[]; density: number[] } | null;
  [key: string]: unknown;
}

export interface MetaLeaveOneOutRow {
  study_id: string;
  estimate: number;
  ci_low: number;
  ci_high: number;
  tau2?: number;
  i2?: number;
  [key: string]: unknown;
}

export interface MetaLeaveOneOutResult {
  rows: MetaLeaveOneOutRow[];
  [key: string]: unknown;
}

export interface MetaPrismaReason {
  reason: string;
  n: number;
  /** Legacy alias of `n`. */
  count?: number;
  [key: string]: unknown;
}

export interface MetaPrismaIdentification {
  total: number;
  database: number;
  other: number;
  [key: string]: unknown;
}

export interface MetaPrismaScreening {
  screened: number;
  excluded: number;
  included: number;
  reasons: MetaPrismaReason[];
  [key: string]: unknown;
}

export interface MetaPrismaFulltext {
  sought: number;
  retrieved: number;
  not_retrieved: number;
  assessed: number;
  excluded: number;
  included: number;
  reasons: MetaPrismaReason[];
  [key: string]: unknown;
}

export interface MetaPrismaInclusion {
  included: number;
  studies: number;
  reports: number;
  [key: string]: unknown;
}

/** `GET /meta/prisma` — nested PRISMA 2020 flow counts. */
export interface MetaPrismaCounts {
  identification: MetaPrismaIdentification;
  screening: MetaPrismaScreening;
  fulltext: MetaPrismaFulltext;
  inclusion: MetaPrismaInclusion;
  exclusion_reasons: MetaPrismaReason[];
  /** Legacy flat fields, kept so a pre-nesting backend still renders. */
  identified?: number;
  after_duplicates?: number;
  included?: number;
  extracted?: number;
  [key: string]: unknown;
}

export interface MetaSummaryLevel {
  value: string;
  /** Level count (canonical); `count` is a legacy alias. */
  n: number;
  /** Distinct studies behind the level (canonical); `studies` is legacy. */
  n_studies: number;
  count?: number;
  studies?: number;
  [key: string]: unknown;
}

export interface MetaSummaryField {
  name: string;
  label?: string;
  group?: string;
  kind?: string;
  role?: FieldRole | null;
  levels: MetaSummaryLevel[];
  [key: string]: unknown;
}

export interface MetaSummaryResult {
  n_extractions?: number;
  n_records?: number;
  n_studies?: number;
  studies?: number;
  fields: MetaSummaryField[];
  [key: string]: unknown;
}

/** One field's reliability row (contract §7). Backends may return only the
 *  overall figures; the per-field list is optional so both shapes render. */
export interface MetaAgreementField {
  name: string;
  label?: string;
  group?: string;
  kind?: string;
  unit?: string;
  n_levels?: number;
  multi?: boolean;
  n_multi?: number;
  n_items?: number;
  n_raters?: number;
  ac1?: number | null;
  ac2?: number | null;
  /** level id -> display label (optional). */
  labels?: Record<string, string>;
  levels?: string[];
  [key: string]: unknown;
}

export interface MetaAgreementRater {
  rater: string;
  keys?: number;
  experiments?: number;
  is_reference?: boolean;
  [key: string]: unknown;
}

/** A screening record the LLM excluded but a human rater would include. */
export interface MetaLlmExcludedRow {
  key: string;
  title?: string;
  authors?: string;
  year?: string;
  an?: string;
  include_raters?: string[];
  [key: string]: unknown;
}

export interface MetaAgreementResult {
  unit: string;
  n_units: number;
  n_raters?: number;
  ac1?: number | null;
  ac2?: number | null;
  percent?: number;
  kappa?: number;
  /** Per-field breakdown (may be absent for an overall-only response). */
  fields?: MetaAgreementField[];
  raters?: MetaAgreementRater[];
  reference?: string;
  exclude?: string[];
  overall?: {
    ac1?: number | null;
    ac2?: number | null;
    n_fields?: number;
    n_items_total?: number;
    [key: string]: unknown;
  };
  /** Screening: records the LLM excluded that a rater would include. */
  llm_excluded?: MetaLlmExcludedRow[];
  [key: string]: unknown;
}

export interface MetaConflictValue {
  owner: string;
  value: unknown;
  [key: string]: unknown;
}

/**
 * One disagreement cell (contract §7). Screening rows carry
 * `criterion_key`; extraction rows carry `field`/`field_name` plus the
 * record/metric coordinates used to resolve them.
 */
export interface MetaConflictRow {
  key: string;
  hit_id: number;
  criterion_key?: string;
  field: string;
  field_name?: string;
  record_index?: number;
  metric_key?: string;
  metric_index?: number;
  kind: string;
  /** rater -> value map (only raters disagreeing with the master). */
  values: Record<string, unknown>;
  settled: boolean;
  settled_value?: unknown;
  [key: string]: unknown;
}

export interface MetaConflictField {
  name: string;
  label?: string;
  group?: string;
  kind?: string;
  multi?: boolean;
  open?: number;
  settled?: number;
  [key: string]: unknown;
}

export interface MetaConflictStudy {
  key: string | number;
  label: string;
  n_open: number;
  n_settled: number;
  n_fields: number;
  [key: string]: unknown;
}

/** Conflicts envelope returned by both screening and extraction conflicts. */
export interface MetaConflictsResult {
  total: number;
  offset: number;
  limit: number;
  rows: MetaConflictRow[];
  fields: MetaConflictField[];
  studies: MetaConflictStudy[];
  master: string;
  raters: string[];
  [key: string]: unknown;
}

export interface MetaConflictResolution {
  hit_id: number;
  value: unknown;
  master?: string;
  /** Screening: the criterion key. */
  criterion_key?: string;
  run_id?: string;
  stage?: string;
  /** Extraction: the codebook field name (NOT `field`). */
  field_name?: string;
  record_index?: number;
  metric_key?: string;
  metric_index?: number;
  scheme?: string;
  [key: string]: unknown;
}

export interface MetaAnalysisRequest {
  scheme?: string;
  owner?: string;
  /** Restrict to primary contrasts (canonical key). */
  primary?: boolean;
  /** Pooling estimator; `two_level` adds the variance decomposition. */
  model?: MetaPoolModel;
  /** Restrict effects to a domain / effect-size families. */
  domain?: string;
  families?: MetaEffectFamily[];
  [key: string]: unknown;
}

export interface MetaSubgroupRequest extends MetaAnalysisRequest {
  key: string;
  /** Chosen codebook field name (canonical selector; `key` kept as alias). */
  field?: string;
}

export interface MetaModeratorRequest extends MetaAnalysisRequest {
  role: string;
  terms?: string[];
  /** Interaction pairs (`[a, b]`) multiplied into the regression design. */
  interactions?: [string, string][];
  /** Chosen codebook field name (canonical selector; `role` kept as alias). */
  field?: string;
}

/** Multiverse request: an analysis request plus a spec-count cap. */
export interface MetaMultiverseRequest extends MetaAnalysisRequest {
  max_specs?: number;
}

export interface MetaReportRequest {
  scheme?: string;
  format?: "md" | "markdown" | "docx" | "pptx";
  owner?: string;
  [key: string]: unknown;
}

export interface MetaJob {
  id: string;
  kind: string;
  label: string;
  state: string;
  progress: number;
  message: string;
  result?: unknown;
  error?: string | null;
  paused: boolean;
  started: number;
}

export interface MetaImportPreview {
  format: string;
  structured: boolean;
  sheets: string[];
  sheet: string;
  header_row: number;
  columns: string[];
  head_rows: string[][];
  rows_sample: string[][];
  mapping: Record<string, number | null>;
  fields: string[];
}

/** Scan of a CodingStudio project folder (preview before import). */
export interface MetaCodingStudioPreview {
  folder: string;
  exists: boolean;
  papers: number;
  texts: number;
  extraction_files: number;
  study_count: number;
  screenings: { coder: string; rows: number }[];
  workbook: { rows: number; path: string } | null;
  schema_version: string | null;
  sample_studies: { key: string; title: string; doi: string; records: number }[];
  errors: string[];
}

/** Result counts from importing a CodingStudio project folder. */
export interface MetaCodingStudioImportResult {
  ok: boolean;
  scheme: string;
  hits_imported: number;
  hits_skipped: number;
  screening_rows: number;
  extractions_imported: number;
  pdfs_linked: number;
  errors: string[];
}

/** Per-status paper counts for the download stage — the `documents` block of
 *  `GET /meta/status`, grouped from `meta_document.status`. Drives the
 *  Download left bar's progress indicator. */
export interface MetaDocumentCounts {
  done: number;
  failed: number;
  pending: number;
  working: number;
  unretrievable: number;
  /** Documents being tracked (sum of the status buckets). */
  total: number;
  /** The backend may report further buckets (e.g. `skipped`). */
  [key: string]: number;
}

export interface MetaStatus {
  hits: number;
  criteria: number;
  schemes: number;
  screening_rows: number;
  eligible: number;
  documents_done: number;
  extracted: number;
  /** Distinct hits with an abstract screening row (matches the To-screen /
   *  Screened filters); `hits` is the denominator. */
  screened_hits?: number;
  /** Per-status paper counts for the Download tab indicator; absent on older
   *  backends, which only expose the flat `documents_done`. */
  documents?: MetaDocumentCounts;
  tabs?: { screening: number; downloads: number; extraction: number };
  by_status: Record<string, number>;
}
