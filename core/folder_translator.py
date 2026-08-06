"""
folder_translator.py — IMAP folder name translation and localization module.

Supports translating Russian, English, and Turkish mail folder names to:
  - "original": Keep original folder name
  - "tr": Translate to Turkish (e.g. Входящие / INBOX -> Gelen Kutusu)
  - "en": Translate to English (e.g. Входящие / Gelen Kutusu -> INBOX)
"""

import re
import logging
from typing import Dict

logger = logging.getLogger(__name__)

# Direct folder mappings (normalized lowercase -> target name)
_MAP_TO_TR: Dict[str, str] = {
    # Russian IMAP standard folders
    "входящие": "Gelen Kutusu",
    "отправленные": "Gönderilenler",
    "отправленные messages": "Gönderilenler",
    "отправленные items": "Gönderilenler",
    "отправленные e-mails": "Gönderilenler",
    "черновики": "Taslaklar",
    "корзина": "Çöp Kutusu",
    "удаленные": "Çöp Kutusu",
    "удалённые": "Çöp Kutusu",
    "спам": "Spam",
    "сомнительные": "Spam",
    "архив": "Arşiv",
    "исходящие": "Giden Kutusu",
    "важное": "Önemli",
    "помеченные": "Yıldızlı",
    "шаблоны": "Şablonlar",
    # Common custom Russian folders
    "работа": "İş",
    "документы": "Belgeler",
    "отчеты": "Raporlar",
    "отчёты": "Raporlar",
    "счета": "Faturalar",
    "клиенты": "Müşteriler",
    "проекты": "Projeler",
    "личное": "Kişisel",
    "персональное": "Kişisel",
    "задачи": "Görevler",

    # English IMAP standard folders
    "inbox": "Gelen Kutusu",
    "sent": "Gönderilenler",
    "sent messages": "Gönderilenler",
    "sent items": "Gönderilenler",
    "sent-mail": "Gönderilenler",
    "drafts": "Taslaklar",
    "draft": "Taslaklar",
    "trash": "Çöp Kutusu",
    "deleted": "Çöp Kutusu",
    "deleted items": "Çöp Kutusu",
    "bin": "Çöp Kutusu",
    "junk": "Spam",
    "junk e-mail": "Spam",
    "spam": "Spam",
    "archive": "Arşiv",
    "archives": "Arşiv",
    "outbox": "Giden Kutusu",
    "important": "Önemli",
    "starred": "Yıldızlı",
    "templates": "Şablonlar",
    "work": "İş",
    "documents": "Belgeler",
    "reports": "Raporlar",
    "invoices": "Faturalar",
    "clients": "Müşteriler",
    "projects": "Projeler",
    "personal": "Kişisel",
    "tasks": "Görevler",
}

_MAP_TO_EN: Dict[str, str] = {
    # Russian IMAP standard folders
    "входящие": "INBOX",
    "отправленные": "Sent",
    "отправленные messages": "Sent",
    "отправленные items": "Sent",
    "отправленные e-mails": "Sent",
    "черновики": "Drafts",
    "корзина": "Trash",
    "удаленные": "Trash",
    "удалённые": "Trash",
    "спам": "Junk",
    "сомнительные": "Junk",
    "архив": "Archive",
    "исходящие": "Outbox",
    "важное": "Important",
    "помеченные": "Starred",
    "шаблоны": "Templates",
    # Common custom Russian folders
    "работа": "Work",
    "документы": "Documents",
    "отчеты": "Reports",
    "отчёты": "Reports",
    "счета": "Invoices",
    "клиенты": "Clients",
    "проекты": "Projects",
    "личное": "Personal",
    "персональное": "Personal",
    "задачи": "Tasks",

    # Turkish IMAP standard folders
    "gelen kutusu": "INBOX",
    "gönderilenler": "Sent",
    "gönderilen öğeler": "Sent",
    "gönderilmiş postalar": "Sent",
    "taslaklar": "Drafts",
    "çöp kutusu": "Trash",
    "silinmiş öğeler": "Trash",
    "spam": "Junk",
    "gereksiz e-posta": "Junk",
    "arşiv": "Archive",
    "giden kutusu": "Outbox",
    "önemli": "Important",
    "yıldızlı": "Starred",
    "şablonlar": "Templates",
    "iş": "Work",
    "belgeler": "Documents",
    "raporlar": "Reports",
    "faturalar": "Invoices",
    "müşteriler": "Clients",
    "projeler": "Projects",
    "kişisel": "Personal",
    "görevler": "Tasks",
}

# Cyrillic to Latin transliteration table for unmapped custom Russian words
_CYRILLIC_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '',
    'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
    'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
    'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
    'Ф': 'F', 'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch', 'Ъ': '',
    'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
}


def transliterate_cyrillic(text: str) -> str:
    """Transliterate Cyrillic characters to Latin characters."""
    return "".join(_CYRILLIC_TRANSLIT.get(c, c) for c in text)


def translate_folder_name(folder: str, target_lang: str = "original") -> str:
    """Translates a folder name according to target_lang.

    Args:
        folder: Name of the folder (e.g., 'Входящие', 'INBOX/SubFolder', 'Sent Messages')
        target_lang: 'original', 'tr' (Turkish), or 'en' (English)

    Returns:
        Translated or original folder name.
    """
    if not folder or target_lang == "original":
        return folder

    target_lang = target_lang.lower().strip()
    if target_lang not in ("tr", "en"):
        return folder

    # Split hierarchical folder paths (e.g. INBOX/SubFolder or Входящие/Подпапка)
    delimiter = None
    for delim in ("/", "."):
        if delim in folder:
            delimiter = delim
            break

    if delimiter:
        parts = folder.split(delimiter)
        translated_parts = [translate_single_folder(p, target_lang) for p in parts]
        return delimiter.join(translated_parts)
    else:
        return translate_single_folder(folder, target_lang)


def translate_single_folder(folder_name: str, target_lang: str) -> str:
    """Translates a single folder name segment."""
    clean = folder_name.strip()
    clean_lower = clean.lower()

    if target_lang == "tr":
        if clean_lower in _MAP_TO_TR:
            return _MAP_TO_TR[clean_lower]
        # Check if text contains Cyrillic
        if re.search(r'[\u0400-\u04FF]', clean):
            return transliterate_cyrillic(clean)
        return clean

    elif target_lang == "en":
        if clean_lower in _MAP_TO_EN:
            return _MAP_TO_EN[clean_lower]
        if re.search(r'[\u0400-\u04FF]', clean):
            return transliterate_cyrillic(clean)
        return clean

    return folder_name
