# Files \& Import

[← Back to Documentation Hub](README.md)

This guide covers file management, document import options, batch processing, metadata tagging, and interoperability with other Qualitative Data Analysis (QDA) software through standard interchange formats. Access the File Manager by clicking **Coding** (or the file manager icon) in the ribbon. The **left bar** displays all files in the project, including a search and quick options. You can import files and URLs (featuring a web scraper) here. The **Center View** displays additional options and allows for sorting and additional options.

When you select multiple files, you have the option to batch Autocode and Transcribe them with identical settings; QCnext only selects previously unprocessed files and adds them to the background queue. You can also batch delete files here.

!\[File Manager](screenshots/files.jpg)

## Importing Material

QCnext supports a wide range of document types and data formats:

### Supported Primary Files

|File Type|Supported Formats|Description|
|-|-|-|
|**Plain Text \& Transcripts**|`.txt`, `.md`, `.docx`, `.odt`, `.rtf`|Interview transcripts, field notes, articles. Extracted to UTF-8 text.|
|**PDF Documents**|`.pdf`|Multi-page PDF files. Rendered visually via PDF.js while text is extracted for text coding.|
|**Images \& Graphic Material**|`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.bmp`, `.svg`|Photos, diagrams, field drawings, scanned documents.|
|**Spreadsheets \& Data Tables**|`.csv`, `.tsv`|Survey responses, tabular data, social media comments. Parsed with RFC-4180 compatibility.|
|**Webpages \& HTML Captures**|`.html`, `.htm`, or via URL|Web articles, forum threads, online posts. Preserves layout snapshots safely.|
|**Audio \& Video Media**|`.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac`, `.mp4`, `.mov`, `.mkv`, `.webm`|Media files for timeline coding and Whisper automated transcription.|

### Webpage \& URL Import

Entering a URL into the **Import URL** dialog provides two import modes:

1. **Article Text**: Extracts clean body text, removing navigation elements, ads, and footers.
2. **Full Snapshot**: Captures full HTML, stylesheets, and images into a self-contained snapshot for visual webpage coding.
3. **YouTube Import**: Scrapes video comments and organizes them in a worksheet.

\---

## File Management \& Batch Jobs

### Organizing \& Grouping Files

* **Multiselect**: Select multiple files using `Ctrl+Click` or `Shift+Click` to move, assign cases, or delete in bulk.
* **File Memos \& Attributes**: Attach analytical notes to any file or assign structured attributes (e.g., source medium, collection date).

### Batch Processing

* **Batch AI / Dictionary Autocode**: Select multiple files in the File Manager and click **Autocode** to queue background coding across all selected files.
* **Batch Export**: Export raw files or coded document reports for selected subsets of material.

\---

### Supported Interchange Formats

QCnext offers broad interoperability with other QDA software, allowing you to migrate projects seamlessly to and from external platforms.

Access the Interchange tool via **Settings → Import / Export**.

|Format / Source|Extension|Details \& Capability|
|-|-|-|
|**REFI-QDA Standard**|`.qdp`, `.qdc`|Full open-standard export and import. Transfers codebooks, documents, codings, cases, and memos across compliant tools (NVivo, MAXQDA, ATLAS.ti).|
|**RQDA**|`.rqda`|Import legacy QualCoder v3 and RQDA SQLite project files.|
|**Taguette**|`.tag`, `.json`|Import codes, documents, and coded excerpts from Taguette projects.|
|**Transana**|`.tprd`|Import media transcripts, time-coded segments, and keyword codes.|
|**NVivo**|`.nvpx`|Best-effort import of NVivo XML export archives (documents, codes, and text codings).|
|**ATLAS.ti**|—|Export your ATLAS.ti project to REFI-QDA (`.qdp`) format, then import into QCnext.|
|**Bibliographic RIS / Zotero**|`.ris`, Zotero API|Import reference lists and linked PDF attachments directly into the bibliography manager.|
|**Survey CSV / Excel / SPSS**|`.csv`, `.xlsx`, `.sav`|Multi-column survey files. Quant variables map to case attributes; open-ended text columns are automatically split into individual text documents per respondent.|
|**Codebooks**|`.txt`, `.csv`|Plain-text codebooks formatted as `Category>>Subcategory>>Code`.|
|**Project Merge**|`.zip`|Merge another QCnext `.qda` project directory directly into your open project.|

### Automatic Format Detection \& Preview

When importing external files or projects, QCnext inspects content markers and headers (e.g., XML schemas, magic numbers) rather than relying solely on file extensions. Before committing changes, a read-only preview card displays expected imports (count of files, codes, codings, cases, and attributes to be created).

\---

[← Back to Documentation Hub](README.md)

