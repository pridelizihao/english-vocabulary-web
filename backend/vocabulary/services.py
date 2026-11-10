"""Domain logic shared by views and management commands.

Keeping the review scheduler and the import parser here makes both testable
without going through HTTP.
"""
import csv
import io
import json
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from .models import Word

NEW_WORD_LIMIT = 20
REVIEW_LIMIT = 50
MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 20000
MAX_IMPORT_ERRORS = 50
MIN_EASE = 1.3
MAX_EASE = 3.2
MASTERED_INTERVAL_DAYS = 21
AGAIN_DELAY = timedelta(minutes=10)
MAX_INTERVAL_DAYS = 365
RATINGS = ('again', 'hard', 'good', 'easy')
WORD_FIELDS = ('spelling', 'phonetic', 'part_of_speech', 'meaning', 'example', 'example_translation', 'audio_url')


class ImportFileError(ValueError):
    """Raised when an uploaded file cannot be parsed into word rows."""


# ---------------------------------------------------------------------------
# Review scheduling
# ---------------------------------------------------------------------------

def _good_interval(streak, interval, ease):
    if streak <= 1:
        return 1
    if streak == 2:
        return 3
    if streak == 3:
        return 7
    return min(MAX_INTERVAL_DAYS, max(1, round(max(interval, 1) * ease)))


def _easy_interval(streak, interval, ease):
    if streak <= 1:
        return 4
    if streak == 2:
        return 9
    return min(MAX_INTERVAL_DAYS, max(1, round(max(interval, 1) * ease * 1.3)))


def schedule(progress, rating, now=None):
    """Apply a rating to `progress` in memory and return it.

    Rules:
      again  -> 10 minutes later, ease down, streak reset, back to learning
      hard   -> +20% interval (at least one day), ease down slightly
      good   -> 1 / 3 / 7 days for the first three streak steps, then `interval * ease`
      easy   -> 4 / 9 days for the first two steps, then `interval * ease * 1.3`
    A word is "mastered" once its interval reaches three weeks.
    """
    if rating not in RATINGS:
        raise ValueError(f'unknown rating: {rating}')
    now = now or timezone.now()
    ease = progress.ease or 2.5
    interval = progress.interval_days or 0
    progress.review_count += 1
    progress.last_review_at = now
    if progress.first_learned_at is None:
        progress.first_learned_at = now

    if rating == 'again':
        progress.streak = 0
        progress.ease = max(MIN_EASE, ease - 0.2)
        progress.interval_days = 0
        progress.next_review_at = now + AGAIN_DELAY
        progress.status = 'learning'
        progress.wrong_count += 1
        return progress

    if rating == 'hard':
        progress.ease = max(MIN_EASE, ease - 0.15)
        progress.streak = max(progress.streak, 1)
        progress.interval_days = min(MAX_INTERVAL_DAYS, max(1, round(max(interval, 1) * 1.2)))
        progress.next_review_at = now + timedelta(days=progress.interval_days)
        progress.status = 'learning'
        return progress

    progress.streak += 1
    if rating == 'good':
        progress.ease = min(MAX_EASE, ease + 0.05)
        progress.interval_days = _good_interval(progress.streak, interval, progress.ease)
    else:
        progress.ease = min(MAX_EASE, ease + 0.15)
        progress.interval_days = _easy_interval(progress.streak, interval, progress.ease)
    progress.next_review_at = now + timedelta(days=progress.interval_days)
    progress.status = 'mastered' if progress.interval_days >= MASTERED_INTERVAL_DAYS else 'learning'
    return progress


def preview_intervals(progress=None, now=None):
    """Return the human-readable next interval for each rating button."""
    preview = {}
    for rating in RATINGS:
        clone = _clone_progress(progress)
        schedule(clone, rating, now)
        preview[rating] = describe_interval(clone.interval_days, rating)
    return preview


def _clone_progress(progress):
    class _Draft:
        pass

    draft = _Draft()
    draft.ease = getattr(progress, 'ease', 2.5) or 2.5
    draft.interval_days = getattr(progress, 'interval_days', 0) or 0
    draft.streak = getattr(progress, 'streak', 0) or 0
    draft.review_count = getattr(progress, 'review_count', 0) or 0
    draft.wrong_count = getattr(progress, 'wrong_count', 0) or 0
    draft.status = getattr(progress, 'status', 'new')
    draft.first_learned_at = getattr(progress, 'first_learned_at', None)
    return draft


def describe_interval(days, rating=None):
    if rating == 'again' or not days:
        return '10 分钟后'
    if days == 1:
        return '明天'
    if days < 30:
        return f'{days} 天后'
    months = round(days / 30)
    return f'{months} 个月后'


# ---------------------------------------------------------------------------
# Import parsing
# ---------------------------------------------------------------------------

def _decode(upload):
    raw = upload.read()
    if len(raw) > MAX_IMPORT_BYTES:
        raise ImportFileError('文件过大，请拆分后导入（单次上限 10 MB）')
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportFileError('无法识别文件编码，请另存为 UTF-8 或 GBK 的 CSV 后重试')


def _normalise_row(raw):
    row = {}
    for key, value in raw.items():
        name = str(key).strip().lower().replace('\ufeff', '')
        row[name] = '' if value is None else str(value).strip()
    return row


def _parse_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ImportFileError('CSV 没有任何列，表头至少需要 word 和 meaning')
    return [_normalise_row(row) for row in reader]


def _parse_json(text):
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImportFileError(f'JSON 解析失败：{exc.msg}') from exc
    if not isinstance(payload, list):
        raise ImportFileError('JSON 必须是由单词对象组成的数组')
    rows = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ImportFileError(f'JSON 第 {index} 项不是对象，无法读取 word/meaning')
        rows.append(_normalise_row(item))
    return rows


def _parse_xlsx(upload):
    try:
        workbook = load_workbook(upload, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises several unrelated types
        raise ImportFileError(f'Excel 文件无法打开：{exc}') from exc
    sheet = workbook.active
    values = list(sheet.values) if sheet is not None else []
    if not values:
        raise ImportFileError('Excel 是空的，至少需要一行表头和单词数据')
    header = ['' if cell is None else str(cell).strip().lower() for cell in values[0]]
    rows = []
    for row in values[1:]:
        if row is None or all(cell is None or str(cell).strip() == '' for cell in row):
            continue
        rows.append(_normalise_row(dict(zip(header, row))))
    return rows


def parse_import_rows(upload):
    """Parse CSV / JSON / XLSX into normalised rows. Raises ImportFileError."""
    name = (getattr(upload, 'name', '') or '').lower()
    if name.endswith(('.xlsx', '.xlsm')):
        rows = _parse_xlsx(upload)
    else:
        text = _decode(upload)
        rows = _parse_json(text) if name.endswith('.json') else _parse_csv(text)
    if len(rows) > MAX_IMPORT_ROWS:
        raise ImportFileError(f'单次最多导入 {MAX_IMPORT_ROWS} 行，请拆分文件')
    if not rows:
        raise ImportFileError('文件里没有数据行')
    columns = set(rows[0].keys())
    missing = {'word', 'meaning'} - columns
    if missing:
        raise ImportFileError('文件必须包含 word 和 meaning 两列')
    return rows


# ---------------------------------------------------------------------------
# Import writing
# ---------------------------------------------------------------------------

def import_words(dictionary, rows):
    """Insert/update words for `dictionary`. Duplicates (case-insensitive) merge."""
    session = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': [], 'merged': 0}
    prepared = {}
    for line_number, row in enumerate(rows, start=2):
        spelling = row.get('word', '').strip()
        meaning = row.get('meaning', '').strip()
        if not spelling or not meaning:
            _reject(session, line_number, 'word 和 meaning 不能为空')
            continue
        if len(spelling) > 120:
            _reject(session, line_number, '单词超过 120 个字符')
            continue
        if len(meaning) > 2000:
            _reject(session, line_number, '释义超过 2000 个字符')
            continue
        key = spelling.casefold()
        payload = {
            'spelling': spelling,
            'meaning': meaning,
            'phonetic': row.get('phonetic', ''),
            'part_of_speech': row.get('part_of_speech', ''),
            'example': row.get('example', '')[:2000],
            'example_translation': (row.get('example_translation') or row.get('example_zh') or '')[:2000],
            'audio_url': row.get('audio_url', ''),
        }
        if key in prepared:
            # keep the richest variant when a file repeats a word in different case
            merged = prepared[key]
            for field, value in payload.items():
                if value:
                    merged[field] = value
            session['merged'] += 1
            _reject(session, line_number, f'与前面的 {key} 重复，已合并', count_skipped=False)
            continue
        prepared[key] = payload

    if not prepared:
        raise ImportFileError('没有可导入的有效行（请检查 word / meaning 是否为空）')

    existing = {word.spelling.casefold(): word for word in Word.objects.filter(dictionary=dictionary)}
    to_create = []
    to_update = []
    for key, payload in prepared.items():
        word = existing.get(key)
        if word is None:
            to_create.append(Word(dictionary=dictionary, **payload))
            session['created'] += 1
            continue
        changed = False
        for field, value in payload.items():
            if getattr(word, field) != value:
                setattr(word, field, value)
                changed = True
        if changed:
            to_update.append(word)
        session['updated'] += 1

    with transaction.atomic():
        if to_create:
            Word.objects.bulk_create(to_create, batch_size=500)
        if to_update:
            Word.objects.bulk_update(to_update, fields=list(WORD_FIELDS), batch_size=500)
    return session


def _reject(session, line_number, message, count_skipped=True):
    if count_skipped:
        session['skipped'] += 1
    if len(session['errors']) < MAX_IMPORT_ERRORS:
        session['errors'].append({'line': line_number, 'error': message})
