"""Generate TypeScript locale dictionaries from the upstream gettext .po files.

Maps each English UI key (en.ts value) to the upstream translation of the
same string. Keys without a translation are omitted — the frontend falls
back to English for them at runtime.

Usage: python scripts/gen_locales.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EN_TS = ROOT / "frontend" / "src" / "lib" / "locales" / "en.ts"
OUT_DIR = ROOT / "frontend" / "src" / "lib" / "locales"
UPSTREAM_I18N = ROOT / "upstreamQualcoder" / "QualCoder-master" / "src" / "qualcoder" / "i18n"
UPSTREAM_OTHER = ROOT / "upstreamQualcoder" / "QualCoder-master" / "other_languages"

LOCALES = {
    "es": UPSTREAM_I18N / "es.po",
    "fr": UPSTREAM_I18N / "fr.po",
    "eo": UPSTREAM_OTHER / "eo.po",
    "eu": UPSTREAM_OTHER / "eu.po",
    "fa": UPSTREAM_OTHER / "fa.po",
    "ht": UPSTREAM_OTHER / "ht.po",
    "it": UPSTREAM_OTHER / "it.po",
    "ja": UPSTREAM_OTHER / "ja.po",
    "pt": UPSTREAM_OTHER / "pt.po",
    "ro": UPSTREAM_OTHER / "ro.po",
    "sv": UPSTREAM_OTHER / "sv.po",
    "zh": UPSTREAM_OTHER / "zh.po",
}


def parse_en_ts(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    entries: dict[str, str] = {}
    for match in re.finditer(r'^\s*"([^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$', text, re.MULTILINE):
        key, value = match.group(1), match.group(2)
        value = value.replace('\\"', '"').replace("\\\\", "\\")
        entries[key] = value
    return entries


def unescape_po(s: str) -> str:
    s = s.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
    s = s.replace("\\\\", "\\")
    return s


def parse_po(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    translations: dict[str, str] = {}
    entries = re.split(r"\n\n+", text)
    for entry in entries:
        lines = [ln.rstrip("\r") for ln in entry.splitlines()]
        msgid_parts: list[str] = []
        msgstr_parts: list[str] = []
        section = None
        for line in lines:
            if line.startswith('msgid "'):
                section = "id"
                msgid_parts.append(line[7:-1])
            elif line.startswith('msgstr "'):
                section = "str"
                msgstr_parts.append(line[8:-1])
            elif line.startswith('msgstr['):
                # plural form: take the first non-empty
                if not msgstr_parts:
                    idx = line.find('"')
                    msgstr_parts.append(line[idx + 1 : -1] if idx >= 0 else "")
                section = None
            elif line.startswith("msgctxt"):
                section = None  # context-keyed entries are skipped
            elif section == "id" and line.startswith('"'):
                msgid_parts.append(line[1:-1])
            elif section == "str" and line.startswith('"'):
                msgstr_parts.append(line[1:-1])
        if not msgid_parts:
            continue
        msgid = unescape_po("".join(msgid_parts))
        msgstr = unescape_po("".join(msgstr_parts))
        if msgid and msgstr:
            translations[msgid] = msgstr
    return translations


def ts_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def find_translation(po: dict[str, str], value: str) -> str | None:
    """Exact → casefold → punctuation-stripped matching against the po."""
    if value in po:
        return po[value]
    folded = value.casefold()
    for k, v in po.items():
        if k.casefold() == folded:
            return v
    # Strip trailing punctuation (ellipsis, colon, exclamation).
    stripped = value.rstrip(" …:!.,")
    if stripped and stripped != value:
        return find_translation(po, stripped)
    return None


def main() -> None:
    en = parse_en_ts(EN_TS)
    report: dict[str, dict] = {}
    for lang, po_path in LOCALES.items():
        po = parse_po(po_path)
        out: dict[str, str] = {}
        for key, value in en.items():
            translation = find_translation(po, value)
            if translation:
                out[key] = translation
        # Curated overrides for chrome keys the upstream po does not cover.
        out.update(OVERRIDES.get(lang, {}))
        content = (
            "/**\n"
            f" * {lang} locale dictionary (generated from the upstream gettext .po file).\n"
            " * Untranslated keys fall back to English at runtime.\n"
            " */\n"
            f"export const {lang}: Record<string, string> = {{\n"
        )
        for key in en:
            if key in out:
                content += f'  "{key}": "{ts_escape(out[key])}",\n'
        content += "};\n"
        (OUT_DIR / f"{lang}.ts").write_text(content, encoding="utf-8")
        coverage = len(out) / max(1, len(en)) * 100
        report[lang] = {
            "translations": len(out),
            "total": len(en),
            "coverage_pct": round(coverage, 1),
        }
        print(f"{lang}: {len(out)}/{len(en)} ({coverage:.1f}%)")

    (OUT_DIR / ".." / "_locale_report.json").resolve().write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )


# Hand-written chrome translations for keys the upstream .po files do not
# contain (nav, common actions, media labels, settings, reports, AI).
OVERRIDES: dict[str, dict[str, str]] = {
    "es": {
        "nav.dashboard": "Panel",
        "nav.files": "Archivos",
        "nav.cases": "Casos",
        "nav.notes": "Notas",
        "nav.analyze": "Informes",
        "nav.graphs": "Grafos",
        "nav.history": "Historial",
        "nav.ai": "IA",
        "nav.settings": "Ajustes",
        "nav.code": "Codificar",
        "nav.codeGo": "Ir a codificar",
        "common.retry": "Reintentar",
        "common.dismiss": "Descartar",
        "common.save": "Guardar",
        "common.cancel": "Cancelar",
        "common.delete": "Eliminar",
        "common.close": "Cerrar",
        "common.refresh": "Actualizar",
        "common.loading": "Cargando…",
        "media.typeText": "Texto",
        "media.typePdf": "PDF",
        "media.typeImage": "Imagen",
        "media.typeAudio": "Audio",
        "media.typeVideo": "Vídeo",
        "settings.title": "Ajustes",
        "settings.appearance": "Apariencia",
        "settings.aiAssistant": "Asistente de IA",
        "settings.interchange": "Importar / Exportar",
        "settings.about": "Acerca de",
        "files.import": "Importar",
        "files.searchPlaceholder": "Buscar archivos…",
        "sidebar.addCode": "Código",
        "sidebar.addCategory": "Categoría",
        "sidebar.menuDetails": "Detalles",
        "sidebar.menuRename": "Renombrar…",
        "analyze.title": "Análisis",
        "ai.tabChat": "Chat",
        "ai.tabSearch": "Buscar",
        "history.undo": "Deshacer",
        "history.redo": "Rehacer",
        "interchange.exportButton": "Exportar proyecto (.qdp)",
        "graphs.title": "Grafos",
        "graphs.newGraph": "Nuevo grafo",
        "graphs.models": "Modelos…",
    },
    "fr": {
        "nav.dashboard": "Tableau de bord",
        "nav.files": "Fichiers",
        "nav.cases": "Cas",
        "nav.notes": "Notes",
        "nav.analyze": "Rapports",
        "nav.graphs": "Graphes",
        "nav.history": "Historique",
        "nav.ai": "IA",
        "nav.settings": "Paramètres",
        "nav.code": "Coder",
        "nav.codeGo": "Aller coder",
        "common.retry": "Réessayer",
        "common.dismiss": "Ignorer",
        "common.save": "Enregistrer",
        "common.cancel": "Annuler",
        "common.delete": "Supprimer",
        "common.close": "Fermer",
        "common.refresh": "Actualiser",
        "common.loading": "Chargement…",
        "media.typeText": "Texte",
        "media.typePdf": "PDF",
        "media.typeImage": "Image",
        "media.typeAudio": "Audio",
        "media.typeVideo": "Vidéo",
        "settings.title": "Paramètres",
        "settings.appearance": "Apparence",
        "settings.aiAssistant": "Assistant IA",
        "settings.interchange": "Importer / Exporter",
        "settings.about": "À propos",
        "files.import": "Importer",
        "files.searchPlaceholder": "Rechercher des fichiers…",
        "sidebar.addCode": "Code",
        "sidebar.addCategory": "Catégorie",
        "sidebar.menuDetails": "Détails",
        "sidebar.menuRename": "Renommer…",
        "analyze.title": "Analyse",
        "ai.tabChat": "Chat",
        "ai.tabSearch": "Recherche",
        "history.undo": "Annuler",
        "history.redo": "Rétablir",
        "interchange.exportButton": "Exporter le projet (.qdp)",
        "graphs.title": "Graphes",
        "graphs.newGraph": "Nouveau graphe",
        "graphs.models": "Modèles…",
    },
    "it": {
        "nav.dashboard": "Pannello",
        "nav.files": "File",
        "nav.cases": "Casi",
        "nav.notes": "Note",
        "nav.analyze": "Report",
        "nav.graphs": "Grafi",
        "nav.history": "Cronologia",
        "nav.ai": "IA",
        "nav.settings": "Impostazioni",
        "nav.code": "Codifica",
        "nav.codeGo": "Vai a codificare",
        "common.retry": "Riprova",
        "common.dismiss": "Ignora",
        "common.save": "Salva",
        "common.cancel": "Annulla",
        "common.delete": "Elimina",
        "common.close": "Chiudi",
        "common.refresh": "Aggiorna",
        "common.loading": "Caricamento…",
        "media.typeText": "Testo",
        "media.typePdf": "PDF",
        "media.typeImage": "Immagine",
        "media.typeAudio": "Audio",
        "media.typeVideo": "Video",
        "settings.title": "Impostazioni",
        "settings.appearance": "Aspetto",
        "settings.aiAssistant": "Assistente IA",
        "settings.interchange": "Importa / Esporta",
        "settings.about": "Informazioni",
        "files.import": "Importa",
        "files.searchPlaceholder": "Cerca file…",
        "sidebar.addCode": "Codice",
        "sidebar.addCategory": "Categoria",
        "sidebar.menuDetails": "Dettagli",
        "sidebar.menuRename": "Rinomina…",
        "analyze.title": "Analisi",
        "ai.tabChat": "Chat",
        "ai.tabSearch": "Cerca",
        "history.undo": "Annulla",
        "history.redo": "Ripeti",
        "interchange.exportButton": "Esporta progetto (.qdp)",
        "graphs.title": "Grafi",
        "graphs.newGraph": "Nuovo grafo",
        "graphs.models": "Modelli…",
    },
    "pt": {
        "nav.dashboard": "Painel",
        "nav.files": "Arquivos",
        "nav.cases": "Casos",
        "nav.notes": "Notas",
        "nav.analyze": "Relatórios",
        "nav.graphs": "Grafos",
        "nav.history": "Histórico",
        "nav.ai": "IA",
        "nav.settings": "Configurações",
        "nav.code": "Codificar",
        "nav.codeGo": "Ir codificar",
        "common.retry": "Tentar novamente",
        "common.dismiss": "Dispensar",
        "common.save": "Salvar",
        "common.cancel": "Cancelar",
        "common.delete": "Excluir",
        "common.close": "Fechar",
        "common.refresh": "Atualizar",
        "common.loading": "Carregando…",
        "media.typeText": "Texto",
        "media.typePdf": "PDF",
        "media.typeImage": "Imagem",
        "media.typeAudio": "Áudio",
        "media.typeVideo": "Vídeo",
        "settings.title": "Configurações",
        "settings.appearance": "Aparência",
        "settings.aiAssistant": "Assistente de IA",
        "settings.interchange": "Importar / Exportar",
        "settings.about": "Sobre",
        "files.import": "Importar",
        "files.searchPlaceholder": "Pesquisar arquivos…",
        "sidebar.addCode": "Código",
        "sidebar.addCategory": "Categoria",
        "sidebar.menuDetails": "Detalhes",
        "sidebar.menuRename": "Renomear…",
        "analyze.title": "Análise",
        "ai.tabChat": "Chat",
        "ai.tabSearch": "Pesquisar",
        "history.undo": "Desfazer",
        "history.redo": "Refazer",
        "interchange.exportButton": "Exportar projeto (.qdp)",
        "graphs.title": "Grafos",
        "graphs.newGraph": "Novo grafo",
        "graphs.models": "Modelos…",
    },
    "zh": {
        "nav.dashboard": "仪表盘",
        "nav.files": "文件",
        "nav.cases": "案例",
        "nav.notes": "笔记",
        "nav.analyze": "报告",
        "nav.graphs": "图表",
        "nav.history": "历史",
        "nav.ai": "AI",
        "nav.settings": "设置",
        "nav.code": "编码",
        "common.retry": "重试",
        "common.save": "保存",
        "common.cancel": "取消",
        "common.delete": "删除",
        "common.close": "关闭",
        "common.refresh": "刷新",
        "common.loading": "加载中…",
        "media.typeText": "文本",
        "media.typePdf": "PDF",
        "media.typeImage": "图片",
        "media.typeAudio": "音频",
        "media.typeVideo": "视频",
        "settings.title": "设置",
        "settings.appearance": "外观",
        "settings.aiAssistant": "AI 助手",
        "files.import": "导入",
        "sidebar.addCode": "代码",
        "sidebar.addCategory": "类别",
        "analyze.title": "分析",
        "ai.tabChat": "聊天",
        "ai.tabSearch": "搜索",
        "history.undo": "撤销",
        "history.redo": "重做",
        "graphs.title": "图表",
        "graphs.newGraph": "新建图表",
        "graphs.models": "模型…",
    },
    "ja": {
        "nav.dashboard": "ダッシュボード",
        "nav.files": "ファイル",
        "nav.cases": "ケース",
        "nav.notes": "ノート",
        "nav.analyze": "レポート",
        "nav.graphs": "グラフ",
        "nav.history": "履歴",
        "nav.ai": "AI",
        "nav.settings": "設定",
        "nav.code": "コーディング",
        "common.retry": "再試行",
        "common.save": "保存",
        "common.cancel": "キャンセル",
        "common.delete": "削除",
        "common.close": "閉じる",
        "common.refresh": "更新",
        "common.loading": "読み込み中…",
        "media.typeText": "テキスト",
        "media.typePdf": "PDF",
        "media.typeImage": "画像",
        "media.typeAudio": "音声",
        "media.typeVideo": "動画",
        "settings.title": "設定",
        "settings.appearance": "外観",
        "settings.aiAssistant": "AIアシスタント",
        "files.import": "インポート",
        "sidebar.addCode": "コード",
        "sidebar.addCategory": "カテゴリ",
        "analyze.title": "分析",
        "ai.tabChat": "チャット",
        "ai.tabSearch": "検索",
        "history.undo": "元に戻す",
        "history.redo": "やり直す",
        "graphs.title": "グラフ",
        "graphs.newGraph": "新しいグラフ",
        "graphs.models": "モデル…",
    },
    "sv": {
        "nav.dashboard": "Instrumentpanel",
        "nav.files": "Filer",
        "nav.cases": "Fall",
        "nav.notes": "Anteckningar",
        "nav.analyze": "Rapporter",
        "nav.graphs": "Grafer",
        "nav.history": "Historik",
        "nav.ai": "AI",
        "nav.settings": "Inställningar",
        "nav.code": "Koda",
        "common.retry": "Försök igen",
        "common.save": "Spara",
        "common.cancel": "Avbryt",
        "common.delete": "Ta bort",
        "common.close": "Stäng",
        "common.refresh": "Uppdatera",
        "common.loading": "Läser in…",
        "media.typeText": "Text",
        "media.typePdf": "PDF",
        "media.typeImage": "Bild",
        "media.typeAudio": "Ljud",
        "media.typeVideo": "Video",
        "settings.title": "Inställningar",
        "settings.appearance": "Utseende",
        "settings.aiAssistant": "AI-assistent",
        "files.import": "Importera",
        "sidebar.addCode": "Kod",
        "sidebar.addCategory": "Kategori",
        "analyze.title": "Analys",
        "ai.tabChat": "Chatt",
        "ai.tabSearch": "Sök",
        "history.undo": "Ångra",
        "history.redo": "Gör om",
        "graphs.title": "Grafer",
        "graphs.newGraph": "Ny graf",
        "graphs.models": "Modeller…",
    },
    "ro": {
        "nav.dashboard": "Tablou de bord",
        "nav.files": "Fișiere",
        "nav.cases": "Cazuri",
        "nav.notes": "Note",
        "nav.analyze": "Rapoarte",
        "nav.graphs": "Grafice",
        "nav.history": "Istoric",
        "nav.ai": "IA",
        "nav.settings": "Setări",
        "nav.code": "Codificare",
        "common.retry": "Reîncearcă",
        "common.save": "Salvează",
        "common.cancel": "Anulează",
        "common.delete": "Șterge",
        "common.close": "Închide",
        "common.refresh": "Actualizează",
        "common.loading": "Se încarcă…",
        "media.typeText": "Text",
        "media.typePdf": "PDF",
        "media.typeImage": "Imagine",
        "media.typeAudio": "Audio",
        "media.typeVideo": "Video",
        "settings.title": "Setări",
        "settings.appearance": "Aspect",
        "settings.aiAssistant": "Asistent AI",
        "files.import": "Importă",
        "sidebar.addCode": "Cod",
        "sidebar.addCategory": "Categorie",
        "analyze.title": "Analiză",
        "ai.tabChat": "Chat",
        "ai.tabSearch": "Caută",
        "history.undo": "Anulează",
        "history.redo": "Refă",
        "graphs.title": "Grafice",
        "graphs.newGraph": "Grafic nou",
        "graphs.models": "Modele…",
    },
    "eo": {
        "nav.dashboard": "Panelaro",
        "nav.files": "Dosieroj",
        "nav.cases": "Kazoj",
        "nav.notes": "Notoj",
        "nav.analyze": "Raportoj",
        "nav.graphs": "Grafoj",
        "nav.history": "Historio",
        "nav.ai": "AI",
        "nav.settings": "Agordoj",
        "nav.code": "Kodi",
        "common.retry": "Reprovi",
        "common.save": "Konservi",
        "common.cancel": "Nuligi",
        "common.delete": "Forigi",
        "common.close": "Fermi",
        "common.refresh": "Refreŝigi",
        "common.loading": "Ŝarĝado…",
        "media.typeText": "Teksto",
        "media.typePdf": "PDF",
        "media.typeImage": "Bildo",
        "media.typeAudio": "Aŭdio",
        "media.typeVideo": "Video",
        "settings.title": "Agordoj",
        "settings.appearance": "Aspekto",
        "settings.aiAssistant": "AI-asistanto",
        "files.import": "Importi",
        "sidebar.addCode": "Kodo",
        "sidebar.addCategory": "Kategorio",
        "analyze.title": "Analizo",
        "ai.tabChat": "Babilo",
        "ai.tabSearch": "Serĉi",
        "history.undo": "Malfari",
        "history.redo": "Refari",
        "graphs.title": "Grafoj",
        "graphs.newGraph": "Nova grafo",
        "graphs.models": "Modeloj…",
    },
    "eu": {
        "nav.dashboard": "Panela",
        "nav.files": "Fitxategiak",
        "nav.cases": "Kasuak",
        "nav.notes": "Oharrak",
        "nav.analyze": "Txostenak",
        "nav.graphs": "Grafikoak",
        "nav.history": "Historiala",
        "nav.ai": "AI",
        "nav.settings": "Ezarpenak",
        "nav.code": "Kodetu",
        "common.retry": "Saiatu berriro",
        "common.save": "Gorde",
        "common.cancel": "Utzi",
        "common.delete": "Ezabatu",
        "common.close": "Itxi",
        "common.refresh": "Eguneratu",
        "common.loading": "Kargatzen…",
        "media.typeText": "Testua",
        "media.typePdf": "PDF",
        "media.typeImage": "Irudia",
        "media.typeAudio": "Audioa",
        "media.typeVideo": "Bideoa",
        "settings.title": "Ezarpenak",
        "settings.appearance": "Itxura",
        "settings.aiAssistant": "AI laguntzailea",
        "files.import": "Inportatu",
        "sidebar.addCode": "Kodea",
        "sidebar.addCategory": "Kategoria",
        "analyze.title": "Analisia",
        "ai.tabChat": "Txata",
        "ai.tabSearch": "Bilatu",
        "history.undo": "Desegin",
        "history.redo": "Berregin",
        "graphs.title": "Grafikoak",
        "graphs.newGraph": "Grafiko berria",
        "graphs.models": "Modeloak…",
    },
    "fa": {
        "nav.dashboard": "داشبورد",
        "nav.files": "پرونده‌ها",
        "nav.cases": "موردها",
        "nav.notes": "یادداشت‌ها",
        "nav.analyze": "گزارش‌ها",
        "nav.graphs": "نمودارها",
        "nav.history": "تاریخچه",
        "nav.ai": "هوش مصنوعی",
        "nav.settings": "تنظیمات",
        "nav.code": "کدگذاری",
        "common.retry": "تلاش مجدد",
        "common.save": "ذخیره",
        "common.cancel": "انصراف",
        "common.delete": "حذف",
        "common.close": "بستن",
        "common.refresh": "تازه‌سازی",
        "common.loading": "در حال بارگذاری…",
        "media.typeText": "متن",
        "media.typePdf": "PDF",
        "media.typeImage": "تصویر",
        "media.typeAudio": "صدا",
        "media.typeVideo": "ویدیو",
        "settings.title": "تنظیمات",
        "settings.appearance": "ظاهر",
        "settings.aiAssistant": "دستیار هوش مصنوعی",
        "files.import": "وارد کردن",
        "sidebar.addCode": "کد",
        "sidebar.addCategory": "دسته",
        "analyze.title": "تحلیل",
        "ai.tabChat": "گفتگو",
        "ai.tabSearch": "جستجو",
        "history.undo": "واگردانی",
        "history.redo": "بازانجام",
        "graphs.title": "نمودارها",
        "graphs.newGraph": "نمودار جدید",
        "graphs.models": "مدل‌ها…",
    },
    "ht": {
        "nav.dashboard": "Tablodbò",
        "nav.files": "Fichye",
        "nav.cases": "Ka",
        "nav.notes": "Nòt",
        "nav.analyze": "Rapò",
        "nav.graphs": "Graf",
        "nav.history": "Istwa",
        "nav.ai": "AI",
        "nav.settings": "Anviwònman",
        "nav.code": "Kode",
        "common.retry": "Rekoumanse",
        "common.save": "Sere",
        "common.cancel": "Anile",
        "common.delete": "Efase",
        "common.close": "Fèmen",
        "common.refresh": "Aktualize",
        "common.loading": "Ap chaje…",
        "media.typeText": "Tèks",
        "media.typePdf": "PDF",
        "media.typeImage": "Imaj",
        "media.typeAudio": "Odyo",
        "media.typeVideo": "Videyo",
        "settings.title": "Anviwònman",
        "settings.appearance": "Aparans",
        "settings.aiAssistant": "Asistan AI",
        "files.import": "Enpòte",
        "sidebar.addCode": "Kòd",
        "sidebar.addCategory": "Kategori",
        "analyze.title": "Analiz",
        "ai.tabChat": "Chat",
        "ai.tabSearch": "Chèche",
        "history.undo": "Defè",
        "history.redo": "Refè",
        "graphs.title": "Graf",
        "graphs.newGraph": "Nouvo graf",
        "graphs.models": "Modèl…",
    },
}


if __name__ == "__main__":
    main()
