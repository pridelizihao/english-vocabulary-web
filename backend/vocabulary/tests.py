import io
import json
import os
import re
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import Workbook
from rest_framework.test import APIClient
from unittest.mock import patch

from .email_codes import EmailDeliveryError
from .models import (
    AnswerLog, Dictionary, EmailAddress, EmailVerification, UserDictionary, UserWordProgress, Word,
)
from .services import (
    MASTERED_INTERVAL_DAYS,
    NEW_WORD_HALVE_DUE,
    NEW_WORD_LIMIT,
    NEW_WORD_PAUSE_DUE,
    RETIRE_INTERVAL_DAYS,
    RETIRE_STREAK,
    SentenceAudioError,
    adaptive_new_limit,
    derive_cloze_rating,
    schedule,
    status_for,
    steps_to_mastered,
)

PASSWORD = 'Str0ngPass!23'


class ApiTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username='learner', password=PASSWORD)
        self.admin = get_user_model().objects.create_user(username='admin', password=PASSWORD, is_staff=True)
        self.dictionary = Dictionary.objects.create(name='CET4 Demo', level='CET4', status='published')
        self.words = [
            Word.objects.create(dictionary=self.dictionary, spelling='abandon', meaning='放弃'),
            Word.objects.create(dictionary=self.dictionary, spelling='ability', meaning='能力'),
        ]

    def login(self, username='learner', password=PASSWORD):
        response = self.client.post('/api/auth/login', {'username': username, 'password': password}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def enroll(self):
        self.assertEqual(self.client.post(f'/api/dictionaries/{self.dictionary.id}/enroll').status_code, 200)

    def answer(self, word, rating, user=None):
        client = user or self.client
        return client.post(f'/api/study/{word.id}/answer', {'rating': rating}, format='json')

    def upload(self, name, content, url='/api/admin/dictionaries/import', extra=None):
        data = {'dictionary_id': self.dictionary.id, 'file': io.BytesIO(content)}
        data['file'].name = name
        data.update(extra or {})
        return self.client.post(url, data, format='multipart')


class AuthenticationTests(ApiTestCase):
    def test_me_requires_session_in_chinese(self):
        response = self.client.get('/api/auth/me')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data['detail'], '请先登录后再操作')

    def test_register_rejects_weak_password_and_duplicate_username(self):
        numeric = self.client.post('/api/auth/register', {'username': 'newbie', 'password': '12345678'}, format='json')
        self.assertEqual(numeric.status_code, 400)
        self.assertIn('数字', numeric.data['detail'])

        first = self.client.post('/api/auth/register', {'username': 'Newbie', 'password': PASSWORD}, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.client.get('/api/auth/me').data['user']['username'], 'Newbie')

        # usernames are compared case-insensitively
        self.client.post('/api/auth/logout')
        duplicate = self.client.post('/api/auth/register', {'username': 'newbie', 'password': PASSWORD}, format='json')
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(duplicate.data['detail'], '这个用户名已经被使用了')

    def test_login_wrong_password_and_logout(self):
        self.client.post('/api/auth/logout')
        wrong = self.client.post('/api/auth/login', {'username': 'learner', 'password': 'nope'}, format='json')
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(wrong.data['detail'], '用户名或密码不正确')

        self.login()
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)


class DictionaryVisibilityTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.other = get_user_model().objects.create_user(username='other', password=PASSWORD)
        self.other_client = APIClient()
        self.other_client.post('/api/auth/login', {'username': 'other', 'password': PASSWORD}, format='json')
        self.draft = Dictionary.objects.create(name='Draft only', status='draft')

    def test_draft_dictionaries_are_hidden(self):
        self.login()
        ids = [item['id'] for item in self.client.get('/api/dictionaries/').data]
        self.assertIn(self.dictionary.id, ids)
        self.assertNotIn(self.draft.id, ids)

    def test_personal_dictionary_is_invisible_to_other_users(self):
        self.login()
        upload = io.BytesIO(b'word,meaning\naliceonly,Alice private\n')
        upload.name = 'alice.csv'
        created = self.client.post('/api/dictionaries/import', {'name': 'Alice private', 'file': upload}, format='multipart')
        self.assertEqual(created.status_code, 201, created.data)
        personal_id = created.data['dictionary_id']

        self.assertIn(personal_id, [item['id'] for item in self.client.get('/api/dictionaries/').data])
        # another user cannot see, open, enroll in or delete it
        self.assertNotIn(personal_id, [item['id'] for item in self.other_client.get('/api/dictionaries/').data])
        self.assertEqual(self.other_client.get(f'/api/dictionaries/{personal_id}/').status_code, 404)
        self.assertEqual(self.other_client.post(f'/api/dictionaries/{personal_id}/enroll').status_code, 404)
        self.assertEqual(self.other_client.delete(f'/api/dictionaries/{personal_id}/').status_code, 404)

        # the owner can delete it
        self.assertEqual(self.client.delete(f'/api/dictionaries/{personal_id}/').status_code, 200)
        self.assertFalse(Dictionary.objects.filter(id=personal_id).exists())

    def test_owner_cannot_be_deleted_by_staff_of_another_tenant(self):
        self.login()
        personal = Dictionary.objects.create(name='Mine', owner=self.user, status='published')
        self.assertEqual(self.other_client.delete(f'/api/dictionaries/{personal.id}/').status_code, 404)
        self.assertTrue(Dictionary.objects.filter(id=personal.id).exists())

    def test_list_reports_progress_counts(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        item = next(entry for entry in self.client.get('/api/dictionaries/').data if entry['id'] == self.dictionary.id)
        self.assertEqual(item['word_count'], 2)
        self.assertEqual(item['learned_words'], 1)
        self.assertEqual(item['due_reviews'], 0)
        self.assertFalse(item['is_personal'])
        self.assertEqual(item['is_owned'], False)


class LearningFlowTests(ApiTestCase):
    def test_study_requires_enrollment(self):
        self.login()
        self.assertEqual(self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}').status_code, 403)
        self.enroll()
        self.assertEqual(self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}').status_code, 200)

    def test_daily_new_word_budget_is_enforced(self):
        for index in range(23):
            Word.objects.create(dictionary=self.dictionary, spelling=f'extra{index}', meaning='x')
        self.login()
        self.enroll()

        first = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}').data
        self.assertEqual(len(first['words']), 20)
        self.assertEqual(first['new_limit'], 20)
        self.assertEqual(first['new_learned_today'], 0)
        for word in first['words']:
            self.assertEqual(self.answer(Word.objects.get(id=word['id']), 'good').status_code, 200)

        second = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}').data
        self.assertEqual(second['words'], [])
        self.assertEqual(second['new_learned_today'], 20)
        self.assertEqual(second['remaining_new'], 5)

        stats = self.client.get(f'/api/statistics?dictionary_id={self.dictionary.id}').data
        self.assertEqual(stats['learned_words'], 20)
        self.assertEqual(stats['today_new'], 20)
        self.assertEqual(stats['remaining_new'], 5)

    def test_intervals_grow_and_again_resets(self):
        progress = UserWordProgress.objects.create(user=self.user, word=self.words[0])
        intervals = []
        for _ in range(5):
            schedule(progress, 'good')
            intervals.append(progress.interval_days)
        self.assertEqual(intervals, [1, 3, 7, 19, 52])
        self.assertEqual(progress.status, 'mastered')
        self.assertEqual(progress.streak, 5)

        schedule(progress, 'again')
        self.assertEqual(progress.interval_days, 0)
        self.assertEqual(progress.status, 'learning')
        self.assertEqual(progress.streak, 0)
        self.assertGreater(progress.next_review_at, timezone.now())
        self.assertLessEqual(progress.next_review_at, timezone.now() + timedelta(minutes=11))

        schedule(progress, 'good')
        self.assertEqual(progress.interval_days, 1)
        self.assertEqual(progress.status, 'learning')

    def test_answer_validation_and_immediate_review(self):
        self.login()
        self.assertNotEqual(self.answer(self.words[0], 'good').status_code, 200)  # not enrolled -> 403
        self.enroll()
        self.assertEqual(self.answer(self.words[0], 'nonsense').status_code, 400)
        self.assertEqual(self.answer(self.words[0], 'good').status_code, 200)

        # good on a new word is due tomorrow, so today's review list stays empty
        review = self.client.get(f'/api/review/today?dictionary_id={self.dictionary.id}').data
        self.assertEqual(review['words'], [])
        self.assertEqual(review['total'], 0)

        # force a due row and check it comes back with a preview
        progress = UserWordProgress.objects.get(user=self.user, word=self.words[0])
        progress.next_review_at = timezone.now() - timedelta(hours=1)
        progress.save(update_fields=['next_review_at'])
        review = self.client.get(f'/api/review/today?dictionary_id={self.dictionary.id}').data
        self.assertEqual(len(review['words']), 1)
        self.assertEqual(review['words'][0]['word']['spelling'], 'abandon')
        self.assertEqual(review['words'][0]['word']['preview']['again'], '10 分钟后')

    def test_answer_returns_next_review_label(self):
        self.login()
        self.enroll()
        response = self.answer(self.words[0], 'good')
        self.assertEqual(response.data['next_review_label'], '明天')
        self.assertEqual(response.data['preview']['easy'], '9 天后')


class ImportTests(ApiTestCase):
    def test_import_requires_staff(self):
        self.login()
        self.assertEqual(self.upload('words.csv', b'word,meaning\nnew,New word\n').status_code, 403)

    def test_admin_csv_import_reports_row_errors(self):
        self.login('admin')
        response = self.upload('words.csv', b'word,meaning\nnew,New word\n,Missing word\n')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['created'], 1)
        self.assertEqual(response.data['skipped'], 1)
        self.assertEqual(response.data['errors'][0]['line'], 3)

    def test_json_variants(self):
        self.login('admin')
        bad = self.upload('bad.json', json.dumps(['a', 'b']).encode())
        self.assertEqual(bad.status_code, 400, bad.data)
        self.assertIn('不是对象', bad.data['detail'])

        not_list = self.upload('object.json', json.dumps({'word': 'x'}).encode())
        self.assertEqual(not_list.status_code, 400)

        good = self.upload('words.json', json.dumps([{'word': 'jsonword', 'meaning': 'JSON'}]).encode())
        self.assertEqual(good.status_code, 200, good.data)
        self.assertEqual(good.data['created'], 1)

    def test_gbk_csv_and_xlsx_import(self):
        self.login('admin')
        gbk = self.upload('gbk.csv', 'word,meaning\n中文词,释义\n'.encode('gbk'))
        self.assertEqual(gbk.status_code, 200, gbk.data)
        self.assertEqual(gbk.data['created'], 1)

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(['word', 'meaning'])
        worksheet.append(['xlsxword', 'XLSX'])
        buffer = io.BytesIO()
        workbook.save(buffer)
        xlsx = self.upload('words.xlsx', buffer.getvalue())
        self.assertEqual(xlsx.status_code, 200, xlsx.data)
        self.assertEqual(xlsx.data['created'], 1)

    def test_case_variants_are_merged(self):
        self.login('admin')
        response = self.upload('dup.csv', b'word,meaning\nAbandon,x\nabandon,y\nABANDON,z\n')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Word.objects.filter(dictionary=self.dictionary, spelling__iexact='abandon').count(), 1)
        self.assertEqual(response.data['merged'], 2)

    def test_import_reads_example_and_translation(self):
        self.login('admin')
        content = (
            'word,meaning,example,example_translation\n'
            '例句词,释义,She used the word in a sentence.,她把这个词用在了句子里。\n'
        )
        response = self.upload('examples.csv', content.encode('utf-8'))
        self.assertEqual(response.status_code, 200, response.data)
        word = Word.objects.get(dictionary=self.dictionary, spelling='例句词')
        self.assertEqual(word.example, 'She used the word in a sentence.')
        self.assertEqual(word.example_translation, '她把这个词用在了句子里。')

    def test_answer_payload_includes_example_fields(self):
        self.words[0].example = 'He abandoned the plan.'
        self.words[0].example_translation = '他放弃了这个计划。'
        self.words[0].save(update_fields=['example', 'example_translation'])
        self.login()
        self.enroll()
        response = self.answer(self.words[0], 'good')
        self.assertEqual(response.data['word']['example'], 'He abandoned the plan.')
        self.assertEqual(response.data['word']['example_translation'], '他放弃了这个计划。')

    def test_personal_import_is_idempotent_and_owned(self):
        self.login()
        first = self.upload(
            'mine.csv', b'word,meaning\nfirst,First\n',
            url='/api/dictionaries/import', extra={'name': 'My list'},
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertTrue(first.data['dictionary_created'])

        second = self.upload(
            'mine.csv', b'word,meaning\nsecond,Second\n',
            url='/api/dictionaries/import', extra={'name': 'My list'},
        )
        self.assertEqual(second.status_code, 200, second.data)
        self.assertFalse(second.data['dictionary_created'])
        dictionaries = Dictionary.objects.filter(name='My list')
        self.assertEqual(dictionaries.count(), 1)
        self.assertEqual(dictionaries.first().owner_id, self.user.id)
        self.assertEqual(dictionaries.first().words.count(), 2)
        self.assertTrue(UserDictionary.objects.filter(user=self.user, dictionary=dictionaries.first()).exists())

    def test_empty_and_header_only_files_are_rejected(self):
        self.login('admin')
        header_only = self.upload('empty.csv', b'word,meaning\n')
        self.assertEqual(header_only.status_code, 400)
        wrong_columns = self.upload('wrong.csv', b'term,definition\nx,y\n')
        self.assertEqual(wrong_columns.status_code, 400)

class EnrichExamplesTests(ApiTestCase):
    def write_examples(self, payload):
        handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
        json.dump(payload, handle, ensure_ascii=False)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_enrich_fills_missing_examples_only(self):
        self.words[0].example = ''
        self.words[0].save(update_fields=['example'])
        self.words[1].example = 'Existing example.'
        self.words[1].save(update_fields=['example'])
        path = self.write_examples({'words': {
            'abandon': {'example': 'He abandoned the plan.', 'zh': '他放弃了这个计划。'},
            'ability': {'example': 'She has the ability to lead.', 'zh': '她有领导能力。'},
            'nothere': {'example': 'not a real word', 'zh': '不存在'},
        }})
        call_command('enrich_examples', path=path, stdout=io.StringIO())
        self.words[0].refresh_from_db()
        self.words[1].refresh_from_db()
        self.assertEqual(self.words[0].example, 'He abandoned the plan.')
        self.assertEqual(self.words[0].example_translation, '他放弃了这个计划。')
        # existing, different example must not receive a translation of another sentence
        self.assertEqual(self.words[1].example, 'Existing example.')
        self.assertEqual(self.words[1].example_translation, '')

    def test_enrich_attaches_translation_to_identical_example(self):
        self.words[0].example = 'He abandoned the plan.'
        self.words[0].save(update_fields=['example'])
        path = self.write_examples({'words': {'abandon': {'example': 'He abandoned the plan.', 'zh': '他放弃了这个计划。'}}})
        call_command('enrich_examples', path=path, stdout=io.StringIO())
        self.words[0].refresh_from_db()
        self.assertEqual(self.words[0].example_translation, '他放弃了这个计划。')

    def test_enrich_force_overwrites_existing(self):
        self.words[0].example = 'Old example.'
        self.words[0].save(update_fields=['example'])
        path = self.write_examples({'words': {'abandon': {'example': 'New example here.', 'zh': '新的例句。'}}})
        call_command('enrich_examples', path=path, force=True, stdout=io.StringIO())
        self.words[0].refresh_from_db()
        self.assertEqual(self.words[0].example, 'New example here.')
        self.assertEqual(self.words[0].example_translation, '新的例句。')

class SeedDictionariesTests(ApiTestCase):
    def test_seed_creates_only_the_two_official_dictionaries(self):
        Dictionary.objects.all().delete()
        call_command('seed_dictionaries', stdout=io.StringIO())
        names = set(Dictionary.objects.values_list('name', flat=True))
        self.assertEqual(names, {'大学英语四级 3500 词', '大学英语六级 5000 词'})
        self.assertFalse(Dictionary.objects.filter(name='示例英语词汇').exists())
        # running it twice must not duplicate anything
        call_command('seed_dictionaries', stdout=io.StringIO())
        self.assertEqual(Dictionary.objects.count(), 2)

class ActivityAndPracticeTests(ApiTestCase):
    def test_answer_writes_an_answer_log(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        log = AnswerLog.objects.get(user=self.user, word=self.words[0])
        self.assertTrue(log.is_new)
        self.assertFalse(log.is_extra)
        self.assertFalse(log.is_practice)
        self.assertEqual(log.interval_before, 0)
        self.assertEqual(log.interval_after, 1)

        self.answer(self.words[0], 'good')
        logs = AnswerLog.objects.filter(user=self.user, word=self.words[0]).order_by('id')
        self.assertEqual(logs.count(), 2)
        self.assertFalse(logs[1].is_new)
        self.assertEqual(logs[1].interval_before, 1)
        self.assertEqual(logs[1].interval_after, 3)

    def test_practice_answer_does_not_touch_schedule(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        progress = UserWordProgress.objects.get(user=self.user, word=self.words[0])
        snapshot = (progress.interval_days, progress.review_count, progress.next_review_at, progress.streak)
        response = self.client.post(
            f'/api/study/{self.words[0].id}/answer', {'rating': 'again', 'practice': True}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['practice'])
        progress.refresh_from_db()
        self.assertEqual(
            (progress.interval_days, progress.review_count, progress.next_review_at, progress.streak), snapshot,
        )
        log = AnswerLog.objects.get(is_practice=True)
        self.assertEqual(log.rating, 'again')

        unlearned = self.client.post(
            f'/api/study/{self.words[1].id}/answer', {'rating': 'good', 'practice': True}, format='json',
        )
        self.assertEqual(unlearned.status_code, 400)

    def test_extra_budget_is_opt_in_and_logged(self):
        extra_words = [
            Word.objects.create(dictionary=self.dictionary, spelling=f'extra{i:02d}', meaning='m')
            for i in range(40)
        ]
        self.login()
        self.enroll()
        now = timezone.now()
        for word in Word.objects.filter(dictionary=self.dictionary)[:20]:
            UserWordProgress.objects.create(user=self.user, word=word, first_learned_at=now)

        base = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}').data
        self.assertEqual(base['words'], [])
        self.assertEqual(base['extra_used_today'], 0)

        extra = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}&extra=20').data
        self.assertEqual(len(extra['words']), 20)
        self.assertEqual(extra['extra_budget'], 20)

        first = Word.objects.get(id=extra['words'][0]['id'])
        answer = self.answer(first, 'good')
        self.assertTrue(answer.data['is_extra'])
        self.assertEqual(AnswerLog.objects.get(user=self.user, word=first).is_extra, True)

        again = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}&extra=20').data
        self.assertEqual(again['extra_used_today'], 1)
        self.assertEqual(len(again['words']), 20)

    def test_early_review_orders_by_weakness(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        self.answer(self.words[1], 'good')
        weak = UserWordProgress.objects.get(user=self.user, word=self.words[1])
        weak.streak = 0
        weak.save(update_fields=['streak'])

        due = self.client.get(f'/api/review/today?dictionary_id={self.dictionary.id}').data
        self.assertEqual(due['words'], [])
        early = self.client.get(f'/api/review/early?dictionary_id={self.dictionary.id}').data
        self.assertEqual([item['word']['spelling'] for item in early['words']], ['ability', 'abandon'])
        self.assertEqual(early['mode'], 'early')

    def test_profile_summary_tracks_days_and_streak(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        self.answer(self.words[1], 'again')
        yesterday = timezone.now() - timedelta(days=1)
        log = AnswerLog.objects.order_by('-created_at').first()
        AnswerLog.objects.filter(id=log.id).update(created_at=yesterday)

        data = self.client.get('/api/profile/summary?days=7').data
        self.assertEqual(data['days'], 7)
        self.assertEqual(len(data['daily']), 7)
        self.assertEqual(data['today']['answers'], 1)
        self.assertEqual(data['today']['review'], 0)
        self.assertEqual(data['streak'], 2)
        self.assertEqual(data['totals']['answers'], 2)
        self.assertEqual(data['totals']['learned'], 2)
        names = [item['name'] for item in data['dictionaries']]
        self.assertIn('CET4 Demo', names)
        self.assertEqual(data['extra']['used_today'], 0)

    def test_statistics_reports_extra_usage(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        data = self.client.get(f'/api/statistics?dictionary_id={self.dictionary.id}').data
        self.assertEqual(data['extra_used_today'], 0)
        self.assertEqual(data['extra_limit'], 60)


class WordBrowserTests(ApiTestCase):
    def url(self, **params):
        query = '&'.join(f'{key}={value}' for key, value in params.items())
        return f'/api/dictionaries/{self.dictionary.id}/words?{query}'

    def test_search_matches_spelling_and_meaning(self):
        self.login()
        found = self.client.get(self.url(q='aban')).data
        self.assertEqual([item['spelling'] for item in found['results']], ['abandon'])

        by_meaning = self.client.get(self.url(q='能力')).data
        self.assertEqual([item['spelling'] for item in by_meaning['results']], ['ability'])
        self.assertEqual(by_meaning['query'], '能力')

        nothing = self.client.get(self.url(q='zzzz')).data
        self.assertEqual(nothing['results'], [])
        self.assertEqual(nothing['total'], 0)

    def test_filters_and_counts_reflect_progress(self):
        Word.objects.create(dictionary=self.dictionary, spelling='zebra', meaning='斑马')
        now = timezone.now()
        UserWordProgress.objects.create(
            user=self.user, word=self.words[0], status='mastered', interval_days=30,
            streak=5, wrong_count=2, first_learned_at=now - timedelta(days=40),
            next_review_at=now + timedelta(days=30),
        )
        UserWordProgress.objects.create(
            user=self.user, word=self.words[1], status='learning', interval_days=1,
            next_review_at=now - timedelta(hours=1), first_learned_at=now - timedelta(days=1),
        )
        self.login()
        data = self.client.get(self.url()).data
        self.assertEqual(data['counts'], {'all': 3, 'new': 1, 'learning': 1, 'mastered': 1, 'due': 1, 'wrong': 1})
        zebra = next(item for item in data['results'] if item['spelling'] == 'zebra')
        self.assertEqual(zebra['status'], 'new')
        self.assertEqual(zebra['interval_days'], 0)

        mastered = self.client.get(self.url(filter='mastered')).data
        self.assertEqual([item['spelling'] for item in mastered['results']], ['abandon'])
        self.assertEqual(mastered['results'][0]['wrong_count'], 2)
        self.assertEqual(mastered['results'][0]['status'], 'mastered')

        due = self.client.get(self.url(filter='due')).data
        self.assertEqual([item['spelling'] for item in due['results']], ['ability'])

        wrong = self.client.get(self.url(filter='wrong')).data
        self.assertEqual([item['spelling'] for item in wrong['results']], ['abandon'])

    def test_sorting_options_are_stable(self):
        self.login()
        for sort in ('alpha', 'recent', 'due', 'wrong', 'unknown'):
            response = self.client.get(self.url(sort=sort))
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(len(response.data['results']), 2)
        self.assertEqual(self.client.get(self.url(sort='alpha')).data['sort'], 'alpha')
        self.assertEqual(self.client.get(self.url(sort='unknown')).data['sort'], 'alpha')

    def test_pagination_is_clamped(self):
        self.login()
        first = self.client.get(self.url(page_size=1)).data
        self.assertEqual(first['pages'], 2)
        self.assertEqual(first['page'], 1)
        self.assertEqual(len(first['results']), 1)

        beyond = self.client.get(self.url(page_size=1, page=99)).data
        self.assertEqual(beyond['page'], 2)
        self.assertEqual(len(beyond['results']), 1)

    def test_anonymous_can_browse_official_without_progress(self):
        response = APIClient().get(self.url())
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertFalse(data['enrolled'])
        self.assertEqual(data['counts']['all'], 2)
        self.assertEqual(data['counts']['new'], 2)
        self.assertEqual(data['counts']['due'], 0)
        self.assertEqual(data['results'][0]['status'], 'new')
        self.assertEqual(APIClient().get(self.url(filter='due')).data['results'], [])

    def test_personal_dictionary_is_not_browsable_by_others(self):
        personal = Dictionary.objects.create(name='Mine', owner=self.user, status='published')
        Word.objects.create(dictionary=personal, spelling='secret', meaning='秘密')
        other = get_user_model().objects.create_user(username='browser', password=PASSWORD)
        other_client = APIClient()
        other_client.post('/api/auth/login', {'username': 'browser', 'password': PASSWORD}, format='json')
        self.assertEqual(other_client.get(f'/api/dictionaries/{personal.id}/words').status_code, 404)
        self.assertEqual(other_client.get('/api/words/' + str(Word.objects.get(spelling='secret').id)).status_code, 404)


class WordDetailTests(ApiTestCase):
    def test_detail_includes_progress_preview_and_history(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        response = self.client.get(f'/api/words/{self.words[0].id}')
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        self.assertEqual(data['spelling'], 'abandon')
        self.assertEqual(data['dictionary']['id'], self.dictionary.id)
        self.assertEqual(data['progress']['interval_days'], 1)
        self.assertEqual(set(data['preview']), {'again', 'hard', 'good', 'easy'})
        self.assertEqual(len(data['history']), 1)
        self.assertEqual(data['history'][0]['rating'], 'good')
        self.assertFalse(data['history'][0]['is_practice'])

    def test_detail_labels_practice_history(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        self.client.post(f'/api/study/{self.words[0].id}/answer', {'rating': 'again', 'practice': True}, format='json')
        history = self.client.get(f'/api/words/{self.words[0].id}').data['history']
        self.assertEqual([item['rating'] for item in history], ['again', 'good'])
        self.assertTrue(history[0]['is_practice'])

    def test_unknown_word_returns_404(self):
        self.login()
        response = self.client.get('/api/words/999999')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['detail'], '单词不存在或没有访问权限')

    def test_anonymous_detail_has_no_progress(self):
        data = APIClient().get(f'/api/words/{self.words[0].id}').data
        self.assertIsNone(data['progress'])
        self.assertEqual(data['history'], [])


class WrongWordTests(ApiTestCase):
    def test_wrong_list_only_contains_missed_words(self):
        now = timezone.now()
        self.login()
        self.enroll()
        for index, wrong in enumerate((3, 1)):
            word = Word.objects.create(dictionary=self.dictionary, spelling=f'wrong{index}', meaning='x')
            UserWordProgress.objects.create(
                user=self.user, word=word, wrong_count=wrong, last_review_at=now - timedelta(days=index),
            )
        data = self.client.get(f'/api/review/wrong?dictionary_id={self.dictionary.id}').data
        self.assertEqual(data['total'], 2)
        self.assertEqual(len(data['words']), 2)
        self.assertEqual([item['word']['spelling'] for item in data['words']], ['wrong0', 'wrong1'])

        limited = self.client.get(f'/api/review/wrong?dictionary_id={self.dictionary.id}&limit=1&order=recent').data
        self.assertEqual(len(limited['words']), 1)
        self.assertEqual(limited['words'][0]['word']['spelling'], 'wrong0')

    def test_wrong_list_requires_enrollment(self):
        self.login()
        self.assertEqual(self.client.get(f'/api/review/wrong?dictionary_id={self.dictionary.id}').status_code, 403)


class UndoTests(ApiTestCase):
    def latest_log(self):
        return AnswerLog.objects.filter(user=self.user, undone_at__isnull=True).order_by('-created_at', '-id').first()

    def test_undo_restores_previous_interval(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        self.answer(self.words[0], 'good')
        progress = UserWordProgress.objects.get(user=self.user, word=self.words[0])
        self.assertEqual((progress.interval_days, progress.review_count), (3, 2))

        response = self.client.post(f'/api/answers/{self.latest_log().id}/undo')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['deleted_progress'])
        progress.refresh_from_db()
        self.assertEqual((progress.interval_days, progress.review_count, progress.streak), (1, 1, 1))

        first = self.client.post(f'/api/answers/{self.latest_log().id}/undo')
        self.assertEqual(first.status_code, 200, first.data)
        self.assertTrue(first.data['deleted_progress'])
        self.assertFalse(UserWordProgress.objects.filter(user=self.user, word=self.words[0]).exists())

    def test_undo_rejects_expired_and_practice_answers(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        log = self.latest_log()
        AnswerLog.objects.filter(id=log.id).update(created_at=timezone.now() - timedelta(minutes=30))
        expired = self.client.post(f'/api/answers/{log.id}/undo')
        self.assertEqual(expired.status_code, 400)
        self.assertIn('10 分钟', expired.data['detail'])

        self.answer(self.words[1], 'good')
        practice = self.client.post(
            f'/api/study/{self.words[1].id}/answer', {'rating': 'again', 'practice': True}, format='json',
        )
        response = self.client.post(f"/api/answers/{practice.data['answer_log_id']}/undo")
        self.assertEqual(response.status_code, 400)
        self.assertIn('练习', response.data['detail'])

    def test_undo_rejects_non_latest_and_foreign_answers(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        first_log = self.latest_log()
        self.answer(self.words[1], 'good')
        stale = self.client.post(f'/api/answers/{first_log.id}/undo')
        self.assertEqual(stale.status_code, 400)
        self.assertEqual(stale.data['detail'], '只能撤销最近一次作答')

        other = get_user_model().objects.create_user(username='intruder', password=PASSWORD)
        other_client = APIClient()
        other_client.post('/api/auth/login', {'username': 'intruder', 'password': PASSWORD}, format='json')
        foreign = other_client.post(f'/api/answers/{self.latest_log().id}/undo')
        self.assertEqual(foreign.status_code, 404)

    def test_undo_rolls_back_statistics(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        stats = self.client.get(f'/api/statistics?dictionary_id={self.dictionary.id}').data
        self.assertEqual(stats['today_completed'], 1)
        self.assertEqual(stats['today_new'], 1)

        self.client.post(f'/api/answers/{self.latest_log().id}/undo')
        stats = self.client.get(f'/api/statistics?dictionary_id={self.dictionary.id}').data
        profile = self.client.get('/api/profile/summary?days=7').data
        self.assertEqual(stats['today_completed'], 0)
        self.assertEqual(stats['today_new'], 0)
        self.assertEqual(profile['today']['answers'], 0)
        self.assertEqual(profile['totals']['answers'], 0)


class AnswerIdempotencyTests(ApiTestCase):
    def post_answer(self, word, rating, token):
        return self.client.post(
            f'/api/study/{word.id}/answer',
            {'rating': rating, 'client_token': token},
            format='json',
        )

    def test_same_token_is_applied_once(self):
        self.login()
        self.enroll()
        first = self.post_answer(self.words[0], 'good', 'token-1')
        second = self.post_answer(self.words[0], 'good', 'token-1')
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertTrue(second.data['duplicate'])
        self.assertEqual(second.data['answer_log_id'], first.data['answer_log_id'])
        self.assertEqual(second.data['interval_days'], 1)
        self.assertEqual(AnswerLog.objects.filter(user=self.user).count(), 1)
        progress = UserWordProgress.objects.get(user=self.user, word=self.words[0])
        self.assertEqual(progress.review_count, 1)

    def test_token_is_single_use_across_words(self):
        self.login()
        self.enroll()
        self.post_answer(self.words[0], 'good', 'shared')
        response = self.post_answer(self.words[1], 'good', 'shared')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'], '这个请求标识已经用于另一个单词')

    def test_token_can_be_reused_after_undo(self):
        self.login()
        self.enroll()
        first = self.post_answer(self.words[0], 'good', 'retry-me')
        self.client.post(f"/api/answers/{first.data['answer_log_id']}/undo")
        again = self.post_answer(self.words[0], 'good', 'retry-me')
        self.assertEqual(again.status_code, 200, again.data)
        self.assertFalse(again.data.get('duplicate', False))
        self.assertEqual(AnswerLog.objects.filter(user=self.user).count(), 2)


class StatisticsConsistencyTests(ApiTestCase):
    def test_today_completed_matches_profile_answers(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        self.answer(self.words[1], 'again')
        self.client.post(f'/api/study/{self.words[0].id}/answer', {'rating': 'good', 'practice': True}, format='json')

        stats = self.client.get(f'/api/statistics?dictionary_id={self.dictionary.id}').data
        profile = self.client.get('/api/profile/summary?days=7').data
        self.assertEqual(stats['today_completed'], 2)
        self.assertEqual(profile['today']['answers'], 3)
        self.assertEqual(profile['today']['practice'], 1)
        self.assertEqual(stats['wrong_words'], 1)

class CoreOrderTests(ApiTestCase):
    def test_core_order_prefers_exam_levels_and_pushes_proper_nouns_last(self):
        Word.objects.all().delete()
        specs = [
            ('access', 'B1', False),
            ('achieve', 'B2', False),
            ('abolish', 'C1', False),
            ('relic', '', False),
            ('apple', 'A1', False),
            ('AIDS', '', True),
        ]
        for spelling, level, proper in specs:
            Word.objects.create(
                dictionary=self.dictionary, spelling=spelling, meaning='x', cefr=level, is_proper=proper,
            )
        self.login()
        self.enroll()
        expected = ['access', 'achieve', 'abolish', 'relic', 'apple', 'AIDS']
        core = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}&order=core').data
        self.assertEqual([item['spelling'] for item in core['words']], expected)
        # core is the default when no order is given
        default = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}').data
        self.assertEqual([item['spelling'] for item in default['words']], expected)

        alpha = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}&order=alpha').data
        self.assertEqual([item['spelling'] for item in alpha['words']], sorted(expected))

    def test_core_order_is_stable_for_the_day(self):
        Word.objects.all().delete()
        for spelling in ('alpha', 'bravo', 'charlie', 'delta', 'echo'):
            Word.objects.create(dictionary=self.dictionary, spelling=spelling, meaning='x', cefr='B1')
        self.login()
        self.enroll()
        first = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}&order=core').data
        second = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}&order=core').data
        names_first = [item['spelling'] for item in first['words']]
        self.assertEqual(names_first, [item['spelling'] for item in second['words']])
        self.assertEqual(sorted(names_first), ['alpha', 'bravo', 'charlie', 'delta', 'echo'])


class CefrImportTests(ApiTestCase):
    def test_import_reads_cefr_and_marks_proper_nouns(self):
        self.login('admin')
        content = 'word,meaning,cefr\naccess,进入,B1\nAIDS,艾滋病,\nbroken,坏,X9\n'
        response = self.upload('cefr.csv', content.encode('utf-8'))
        self.assertEqual(response.status_code, 200, response.data)

        access = Word.objects.get(dictionary=self.dictionary, spelling='access')
        self.assertEqual(access.cefr, 'B1')
        self.assertFalse(access.is_proper)

        aids = Word.objects.get(dictionary=self.dictionary, spelling='AIDS')
        self.assertEqual(aids.cefr, '')
        self.assertTrue(aids.is_proper)

        broken = Word.objects.get(dictionary=self.dictionary, spelling='broken')
        self.assertEqual(broken.cefr, '')


class AdaptiveNewWordTests(ApiTestCase):
    """复习积压时自动少给新词，避免「每天 20 个」把队列越拖越长。"""

    def add_words(self, count, prefix='extra'):
        return [
            Word.objects.create(dictionary=self.dictionary, spelling=f'{prefix}{index}', meaning='补充词')
            for index in range(count)
        ]

    def make_due(self, count):
        words = self.add_words(count, prefix='due')
        now = timezone.now()
        for word in words:
            UserWordProgress.objects.create(
                user=self.user, word=word, status='learning', interval_days=1,
                next_review_at=now - timedelta(minutes=5),
                first_learned_at=now - timedelta(days=3),
            )
        return words

    def test_limit_halves_then_pauses(self):
        self.assertEqual(adaptive_new_limit(0), NEW_WORD_LIMIT)
        self.assertEqual(adaptive_new_limit(NEW_WORD_HALVE_DUE - 1), NEW_WORD_LIMIT)
        self.assertEqual(adaptive_new_limit(NEW_WORD_HALVE_DUE), 10)
        self.assertEqual(adaptive_new_limit(NEW_WORD_PAUSE_DUE - 1), 10)
        self.assertEqual(adaptive_new_limit(NEW_WORD_PAUSE_DUE), 0)
        self.assertEqual(adaptive_new_limit(200), 0)

    def test_no_backlog_keeps_full_budget(self):
        self.add_words(30)
        self.login()
        self.enroll()
        data = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}').data
        self.assertEqual(data['new_limit'], NEW_WORD_LIMIT)
        self.assertEqual(data['new_limit_note'], '')
        self.assertEqual(len(data['words']), NEW_WORD_LIMIT)

    def test_backlog_halves_the_budget(self):
        self.add_words(30)
        self.make_due(NEW_WORD_HALVE_DUE)
        self.login()
        self.enroll()
        data = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}').data
        self.assertEqual(data['due_reviews'], NEW_WORD_HALVE_DUE)
        self.assertEqual(data['new_limit'], 10)
        self.assertEqual(data['new_limit_base'], NEW_WORD_LIMIT)
        self.assertIn('新词减到 10 个', data['new_limit_note'])
        self.assertEqual(len(data['words']), 10)

    def test_statistics_reports_the_same_adaptive_limit(self):
        """完成页读的是 /api/statistics，口径必须和学习页一致。"""
        self.add_words(30)
        self.make_due(NEW_WORD_HALVE_DUE)
        self.login()
        self.enroll()
        stats = self.client.get(f'/api/statistics?dictionary_id={self.dictionary.id}').data
        self.assertEqual(stats['due_reviews'], NEW_WORD_HALVE_DUE)
        self.assertEqual(stats['new_limit'], 10)
        self.assertEqual(stats['new_limit_base'], NEW_WORD_LIMIT)
        self.assertIn('新词减到 10 个', stats['new_limit_note'])

    def test_heavy_backlog_pauses_new_words(self):
        self.add_words(30)
        self.make_due(NEW_WORD_PAUSE_DUE)
        self.login()
        self.enroll()
        data = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}').data
        self.assertEqual(data['new_limit'], 0)
        self.assertEqual(data['words'], [])
        self.assertIn('新词暂停', data['new_limit_note'])

        # 「再来 20 个」也不能绕过：先清复习。
        extra = self.client.get(
            f'/api/study/today?dictionary_id={self.dictionary.id}&extra=20',
        ).data
        self.assertEqual(extra['words'], [])


class RetiredWordTests(ApiTestCase):
    """归档：间隔够长或连对够多就不再进每日复习队列。"""

    def retire_by_answers(self, word, times=RETIRE_STREAK):
        for _ in range(times):
            response = self.answer(word, 'good')
            self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_status_thresholds(self):
        progress = UserWordProgress.objects.create(user=self.user, word=self.words[0])
        progress.interval_days = MASTERED_INTERVAL_DAYS
        progress.streak = 4
        self.assertEqual(status_for(progress), 'mastered')

        progress.interval_days = RETIRE_INTERVAL_DAYS
        self.assertEqual(status_for(progress), 'retired')

        progress.interval_days = 30
        progress.streak = RETIRE_STREAK
        self.assertEqual(status_for(progress), 'retired')

    def test_streak_retires_and_leaves_the_review_queue(self):
        self.login()
        self.enroll()
        response = self.retire_by_answers(self.words[0])
        self.assertEqual(response.data['status'], 'retired')

        progress = UserWordProgress.objects.get(user=self.user, word=self.words[0])
        # 即使到期，归档的词也不再进复习队列
        progress.next_review_at = timezone.now() - timedelta(days=1)
        progress.save(update_fields=['next_review_at'])
        review = self.client.get(f'/api/review/today?dictionary_id={self.dictionary.id}').data
        self.assertEqual(review['words'], [])
        self.assertEqual(review['total'], 0)

        stats = self.client.get(f'/api/statistics?dictionary_id={self.dictionary.id}').data
        self.assertEqual(stats['mastered_words'], 1)  # 归档计入已掌握
        self.assertEqual(stats['retired_words'], 1)
        self.assertEqual(stats['due_reviews'], 0)

    def test_relearn_puts_it_back(self):
        self.login()
        self.enroll()
        self.retire_by_answers(self.words[0])
        progress = UserWordProgress.objects.get(user=self.user, word=self.words[0])
        progress.next_review_at = timezone.now() - timedelta(days=1)
        progress.save(update_fields=['next_review_at'])

        response = self.client.post(f'/api/words/{self.words[0].id}/relearn')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'learning')
        self.assertEqual(response.data['interval_days'], 0)

        review = self.client.get(f'/api/review/today?dictionary_id={self.dictionary.id}').data
        self.assertEqual(review['total'], 1)

    def test_relearn_rejects_words_that_are_not_retired(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        response = self.client.post(f'/api/words/{self.words[0].id}/relearn')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'], '只有已归档的词才需要重新学习')

    def test_relearn_needs_login(self):
        response = self.client.post(f'/api/words/{self.words[0].id}/relearn')
        self.assertEqual(response.status_code, 401)


class ClozeEvidenceTests(ApiTestCase):
    """填空模式：评分由客观证据决定，客户端说「我记住了」不作数。"""

    def cloze(self, **payload):
        body = {'mode': 'cloze'}
        body.update(payload)
        return self.client.post(f'/api/study/{self.words[0].id}/answer', body, format='json')

    def test_rating_is_derived_from_evidence(self):
        self.assertEqual(derive_cloze_rating(1, False, True), 'good')
        self.assertEqual(derive_cloze_rating(2, False, True), 'hard')
        self.assertEqual(derive_cloze_rating(3, False, True), 'again')
        self.assertEqual(derive_cloze_rating(1, False, False), 'again')
        # 看过答案：不管之后答得多干净，都只算没想起来
        self.assertEqual(derive_cloze_rating(1, True, True), 'again')
        self.assertEqual(derive_cloze_rating(2, True, True), 'again')

    def test_first_try_correct_counts_as_good(self):
        self.login()
        self.enroll()
        response = self.cloze(correct=True, attempts=1, revealed=False)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['rating'], 'good')
        self.assertEqual(response.data['interval_days'], 1)

    def test_second_try_correct_counts_as_hard(self):
        self.login()
        self.enroll()
        response = self.cloze(correct=True, attempts=2, revealed=False)
        self.assertEqual(response.data['rating'], 'hard')
        self.assertEqual(response.data['interval_days'], 1)

    def test_peeking_forces_again_even_when_client_claims_easy(self):
        self.login()
        self.enroll()
        # 客户端可以随便传 rating，服务器只认 correct / attempts / revealed
        response = self.cloze(correct=True, attempts=1, revealed=True, rating='easy')
        self.assertEqual(response.data['rating'], 'again')
        self.assertEqual(response.data['interval_days'], 0)
        self.assertEqual(response.data['next_review_label'], '10 分钟后')

    def test_wrong_answer_is_again_and_counts_as_mistake(self):
        self.login()
        self.enroll()
        response = self.cloze(correct=False, attempts=2, revealed=True)
        self.assertEqual(response.data['rating'], 'again')
        progress = UserWordProgress.objects.get(user=self.user, word=self.words[0])
        self.assertEqual(progress.wrong_count, 1)
        self.assertEqual(progress.streak, 0)

    def test_evidence_is_stored_on_the_log(self):
        self.login()
        self.enroll()
        self.cloze(correct=True, attempts=2, revealed=False)
        log = AnswerLog.objects.get(user=self.user, word=self.words[0])
        self.assertEqual(log.mode, 'cloze')
        self.assertEqual(log.attempts, 2)
        self.assertFalse(log.revealed)

        detail = self.client.get(f'/api/words/{self.words[0].id}').data
        entry = detail['history'][0]
        self.assertEqual(entry['mode'], 'cloze')
        self.assertEqual(entry['attempts'], 2)
        self.assertFalse(entry['revealed'])

    def test_peeking_never_advances_streak(self):
        """看答案不能把 streak 刷到归档。"""
        self.login()
        self.enroll()
        for _ in range(10):
            self.cloze(correct=True, attempts=1, revealed=True)
        progress = UserWordProgress.objects.get(user=self.user, word=self.words[0])
        self.assertEqual(progress.streak, 0)
        self.assertNotEqual(progress.status, 'retired')

    def test_card_mode_still_requires_a_rating(self):
        self.login()
        self.enroll()
        response = self.client.post(
            f'/api/study/{self.words[0].id}/answer',
            {'mode': 'card'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_cloze_mode_requires_correct_flag(self):
        self.login()
        self.enroll()
        response = self.cloze()
        self.assertEqual(response.status_code, 400)
        self.assertIn('correct', response.data['detail'])


class MasteredProgressTests(ApiTestCase):
    """「距掌握还差几次」必须和真实调度器一致。"""

    def progress(self, **fields):
        """不落库的临时进度：steps_to_mastered 只读属性，不需要写数据库。"""
        return UserWordProgress(user=self.user, word=self.words[0], **fields)

    def test_steps_shrink_as_interval_grows(self):
        self.assertEqual(steps_to_mastered(self.progress()), 5)
        self.assertEqual(steps_to_mastered(self.progress(streak=1, interval_days=1)), 4)
        self.assertEqual(steps_to_mastered(self.progress(streak=3, interval_days=7)), 2)
        self.assertEqual(steps_to_mastered(self.progress(streak=4, interval_days=19)), 1)
        # 已经跨过 21 天就是 0
        self.assertEqual(steps_to_mastered(self.progress(streak=5, interval_days=52, status='mastered')), 0)

    def test_word_detail_exposes_steps_to_mastered(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        detail = self.client.get(f'/api/words/{self.words[0].id}').data
        self.assertEqual(detail['steps_to_mastered'], 4)

    def test_word_detail_without_progress_returns_null(self):
        self.login()
        self.enroll()
        detail = self.client.get(f'/api/words/{self.words[0].id}').data
        self.assertIsNone(detail['progress'])
        self.assertIsNone(detail['steps_to_mastered'])

    def test_profile_reports_the_closest_word(self):
        self.login()
        self.enroll()
        UserWordProgress.objects.create(user=self.user, word=self.words[0], streak=4, interval_days=19)
        other = Word.objects.create(dictionary=self.dictionary, spelling='zebra', meaning='斑马')
        UserWordProgress.objects.create(user=self.user, word=other, streak=1, interval_days=1)
        summary = self.client.get('/api/profile/summary').data
        closest = summary['closest_to_mastered']
        self.assertEqual(closest['spelling'], 'abandon')
        self.assertEqual(closest['steps'], 1)
        self.assertEqual(closest['interval_days'], 19)

    def test_profile_closest_ignores_mastered_and_empty(self):
        self.login()
        self.enroll()
        summary = self.client.get('/api/profile/summary').data
        self.assertIsNone(summary['closest_to_mastered'])

        UserWordProgress.objects.create(
            user=self.user, word=self.words[0], streak=5, interval_days=52, status='mastered',
        )
        summary = self.client.get('/api/profile/summary').data
        self.assertIsNone(summary['closest_to_mastered'])


class KnownWordTests(ApiTestCase):
    def test_known_marks_mastered_and_undo_restores(self):
        self.login()
        self.enroll()
        response = self.client.post(
            f'/api/study/{self.words[0].id}/answer', {'rating': 'good', 'known': True}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['interval_days'], 365)
        # 标记「已会」等于归档：不再进每日复习队列。
        self.assertEqual(response.data['status'], 'retired')
        self.assertTrue(response.data['is_skip'])
        self.assertEqual(response.data['next_review_label'], '已移出复习')

        log = AnswerLog.objects.get(user=self.user, word=self.words[0])
        self.assertTrue(log.is_skip)
        self.assertEqual(log.rating, 'easy')
        self.assertEqual(log.interval_after, 365)

        undo = self.client.post(f"/api/answers/{response.data['answer_log_id']}/undo")
        self.assertEqual(undo.status_code, 200, undo.data)
        self.assertFalse(UserWordProgress.objects.filter(user=self.user, word=self.words[0]).exists())

    def test_known_after_review_restores_previous_interval(self):
        self.login()
        self.enroll()
        self.answer(self.words[0], 'good')
        response = self.client.post(
            f'/api/study/{self.words[0].id}/answer', {'rating': 'good', 'known': True}, format='json',
        )
        self.assertEqual(response.data['interval_days'], 365)
        progress = UserWordProgress.objects.get(user=self.user, word=self.words[0])
        self.assertEqual(progress.review_count, 2)

        self.client.post(f"/api/answers/{response.data['answer_log_id']}/undo")
        progress.refresh_from_db()
        self.assertEqual(progress.interval_days, 1)
        self.assertEqual(progress.status, 'learning')

    def test_known_rejects_practice(self):
        self.login()
        self.enroll()
        response = self.client.post(
            f'/api/study/{self.words[0].id}/answer',
            {'rating': 'good', 'known': True, 'practice': True},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'], '练习模式不能标记为已掌握')


class SeedDemoTests(ApiTestCase):
    """演示数据生成器：只碰目标账号，产出的数据要能驱动面板指标。"""

    def run_seed(self, **options):
        call_command('seed_demo', stdout=io.StringIO(), **options)

    def test_creates_demo_user_with_history(self):
        for index in range(6):
            Word.objects.create(
                dictionary=self.dictionary, spelling=f'w{index}', meaning='词',
                example=f'This is w{index}.', example_translation='例句',
            )
        self.run_seed(username='demo', password='Demo12345678', words=6, days=5, seed=7)

        user = get_user_model().objects.get(username='demo')
        self.assertTrue(user.check_password('Demo12345678'))
        self.assertTrue(UserWordProgress.objects.filter(user=user).exists())
        self.assertTrue(AnswerLog.objects.filter(user=user).exists())
        self.assertTrue(UserDictionary.objects.filter(user=user, dictionary=self.dictionary).exists())

    def test_does_not_touch_other_users(self):
        Word.objects.create(
            dictionary=self.dictionary, spelling='keep', meaning='保持',
            example='Keep it.', example_translation='留着',
        )
        UserWordProgress.objects.create(user=self.user, word=self.dictionary.words.first(), interval_days=9)
        before = AnswerLog.objects.count()

        self.run_seed(username='demo', words=1, days=2, seed=11)

        self.assertTrue(UserWordProgress.objects.filter(user=self.user, interval_days=9).exists())
        self.assertEqual(AnswerLog.objects.filter(user=self.user).count(), before)

    def test_reset_rebuilds_the_account(self):
        Word.objects.create(
            dictionary=self.dictionary, spelling='foo', meaning='词',
            example='Foo bar.', example_translation='例句',
        )
        self.run_seed(username='demo2', words=1, days=2, seed=3)
        first = get_user_model().objects.get(username='demo2').id
        self.run_seed(username='demo2', words=1, days=2, seed=3, reset=True)
        second = get_user_model().objects.get(username='demo2').id
        self.assertNotEqual(first, second)

    def test_requires_words_with_examples(self):
        with self.assertRaises(Exception):
            self.run_seed(username='demo3', words=5)

    def test_rejects_unknown_dictionary(self):
        with self.assertRaises(Exception):
            self.run_seed(dictionary='不存在的词典')


class AnnotateCefrTests(ApiTestCase):
    def test_command_backfills_levels_and_proper_flag(self):
        Word.objects.create(dictionary=self.dictionary, spelling='access', meaning='x')
        Word.objects.create(dictionary=self.dictionary, spelling='April', meaning='x')
        payload = {
            'Oxford3000': {'access': {'B1': [['v.']]}, 'April': {'A1': [['n.']]}},
            'Oxford5000': {},
        }
        handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
        json.dump(payload, handle, ensure_ascii=False)
        handle.close()
        self.addCleanup(os.unlink, handle.name)

        call_command('annotate_cefr', file=handle.name, stdout=io.StringIO())

        access = Word.objects.get(dictionary=self.dictionary, spelling='access')
        april = Word.objects.get(dictionary=self.dictionary, spelling='April')
        self.assertEqual(access.cefr, 'B1')
        self.assertFalse(access.is_proper)
        self.assertEqual(april.cefr, 'A1')
        self.assertTrue(april.is_proper)

class SentenceAudioTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.words[0].example = 'She had read the previous chapter.'
        self.words[0].save(update_fields=['example'])

    def test_audio_is_generated_once_and_then_cached(self):
        def fake(text, voice, target):
            target.write_bytes(b'ID3fake-audio')

        with tempfile.TemporaryDirectory() as cache, override_settings(AUDIO_CACHE_DIR=cache):
            with patch('vocabulary.services._synthesise_sentence', side_effect=fake) as synth:
                first = self.client.get(f'/api/words/{self.words[0].id}/example-audio')
                self.assertEqual(first.status_code, 200)
                self.assertEqual(first['Content-Type'], 'audio/mpeg')
                self.assertEqual(b''.join(first.streaming_content), b'ID3fake-audio')

                second = self.client.get(f'/api/words/{self.words[0].id}/example-audio')
                self.assertEqual(second.status_code, 200)
                self.assertEqual(b''.join(second.streaming_content), b'ID3fake-audio')

                self.assertEqual(synth.call_count, 1)
                self.assertEqual(len(os.listdir(cache)), 1)

    def test_missing_example_returns_404(self):
        self.words[1].example = ''
        self.words[1].save(update_fields=['example'])
        response = self.client.get(f'/api/words/{self.words[1].id}/example-audio')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['detail'], '这个词还没有例句')

    def test_synthesis_failure_returns_503(self):
        with tempfile.TemporaryDirectory() as cache, override_settings(AUDIO_CACHE_DIR=cache):
            with patch('vocabulary.services._synthesise_sentence', side_effect=SentenceAudioError('boom')):
                response = self.client.get(f'/api/words/{self.words[0].id}/example-audio')
                self.assertEqual(response.status_code, 503)
                self.assertIn('例句语音', response.data['detail'])

    def test_personal_dictionary_audio_is_private(self):
        personal = Dictionary.objects.create(name='Mine', owner=self.user, status='published')
        word = Word.objects.create(dictionary=personal, spelling='secret', meaning='x', example='A secret example.')
        other = get_user_model().objects.create_user(username='listener', password=PASSWORD)
        other_client = APIClient()
        other_client.post('/api/auth/login', {'username': 'listener', 'password': PASSWORD}, format='json')
        self.assertEqual(other_client.get(f'/api/words/{word.id}/example-audio').status_code, 404)

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailAuthTests(ApiTestCase):
    EMAIL = 'learner@example.com'

    def send(self, email=None, purpose='login', ip='10.0.0.1'):
        return self.client.post(
            '/api/auth/email/send',
            {'email': self.EMAIL if email is None else email, 'purpose': purpose},
            format='json', REMOTE_ADDR=ip,
        )

    def latest_code(self):
        self.assertTrue(mail.outbox, 'expected a verification email')
        match = re.search(r'\b(\d{6})\b', mail.outbox[-1].body)
        self.assertIsNotNone(match, mail.outbox[-1].body)
        return match.group(1)

    def verify(self, code, email=None, purpose='login', ip='10.0.0.2'):
        return self.client.post(
            '/api/auth/email/verify',
            {'email': self.EMAIL if email is None else email, 'code': code,
             'purpose': purpose},
            format='json', REMOTE_ADDR=ip,
        )

    def test_email_login_creates_account_and_session(self):
        response = self.send()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['sent'])
        code = self.latest_code()

        verified = self.verify(code)
        self.assertEqual(verified.status_code, 200, verified.data)
        self.assertTrue(verified.data['created'])
        self.assertEqual(verified.data['user']['email'], self.EMAIL)

        me = self.client.get('/api/auth/me')
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data['user']['email'], self.EMAIL)
        self.assertTrue(EmailAddress.objects.filter(email=self.EMAIL).exists())

    def test_second_login_reuses_the_account(self):
        self.assertEqual(self.send().status_code, 200)
        first = self.verify(self.latest_code())
        self.assertEqual(first.status_code, 200, first.data)
        # 冷却窗口是真实时间，测试里把上一次的发送时间往前挪。
        EmailVerification.objects.update(created_at=timezone.now() - timedelta(minutes=5))
        cache.clear()
        self.client.logout()
        self.assertEqual(self.send(ip='10.0.0.3').status_code, 200)
        second = self.verify(self.latest_code(), ip='10.0.0.4')
        self.assertEqual(second.status_code, 200, second.data)
        self.assertFalse(second.data['created'])
        self.assertEqual(second.data['user']['id'], first.data['user']['id'])

    def test_code_cannot_be_used_twice(self):
        self.assertEqual(self.send().status_code, 200)
        code = self.latest_code()
        self.assertEqual(self.verify(code, ip='10.0.0.5').status_code, 200)
        cache.clear()
        reused = self.verify(code, ip='10.0.0.6')
        self.assertEqual(reused.status_code, 400)
        self.assertIn('失效', reused.data['detail'])

    def test_wrong_code_burns_the_budget(self):
        self.assertEqual(self.send().status_code, 200)
        code = self.latest_code()
        for attempt in range(4):
            wrong = self.verify('000000' if code != '000000' else '111111', ip=f'10.0.1.{attempt}')
            self.assertEqual(wrong.status_code, 400, wrong.data)
            self.assertEqual(wrong.data['detail'], '验证码不正确')
        # Fifth miss spends the code; even the right one is now rejected.
        self.assertEqual(self.verify('000000', ip='10.0.1.9').status_code, 400)
        locked = self.verify(code, ip='10.0.1.10')
        self.assertEqual(locked.status_code, 400)
        self.assertIn('重新获取', locked.data['detail'])

    def test_expired_code_is_rejected(self):
        self.assertEqual(self.send().status_code, 200)
        code = self.latest_code()
        EmailVerification.objects.filter(email=self.EMAIL).update(
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        response = self.verify(code)
        self.assertEqual(response.status_code, 400)
        self.assertIn('过期', response.data['detail'])

    def test_resend_is_cooled_down(self):
        self.assertEqual(self.send().status_code, 200)
        again = self.send(ip='10.0.0.7')
        self.assertEqual(again.status_code, 429, again.data)
        self.assertGreater(again.data['retry_after'], 0)
        self.assertIn('秒后再试', again.data['detail'])

    def test_send_rejects_bad_address_in_chinese(self):
        response = self.send(email='not-an-email')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'], '邮箱格式不正确')

    def test_email_is_normalized_before_storage(self):
        self.assertEqual(self.send(email='  LEARNER@Example.COM ').status_code, 200)
        self.assertEqual(EmailVerification.objects.filter(email=self.EMAIL).count(), 1)
        self.assertEqual(mail.outbox[-1].to, [self.EMAIL])

    def test_reset_password_unknown_address_looks_successful(self):
        response = self.send(purpose='reset')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['sent'])
        self.assertFalse(mail.outbox)

    def test_reset_password_updates_credentials(self):
        EmailAddress.objects.create(user=self.user, email=self.EMAIL)
        EmailAddress.objects.filter(user=self.user).update(user=self.user)
        self.assertEqual(self.send(purpose='reset').status_code, 200)
        code = self.latest_code()
        response = self.client.post('/api/auth/password/reset', {
            'email': self.EMAIL, 'code': code, 'password': 'FreshPass!2026',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)

        self.client.logout()
        old = self.client.post('/api/auth/login', {'username': 'learner', 'password': PASSWORD}, format='json')
        self.assertEqual(old.status_code, 400)
        new = self.client.post('/api/auth/login', {'username': 'learner', 'password': 'FreshPass!2026'}, format='json')
        self.assertEqual(new.status_code, 200, new.data)

    def test_reset_password_rejects_weak_password_without_burning_code(self):
        EmailAddress.objects.create(user=self.user, email=self.EMAIL)
        self.assertEqual(self.send(purpose='reset').status_code, 200)
        code = self.latest_code()
        weak = self.client.post('/api/auth/password/reset', {
            'email': self.EMAIL, 'code': code, 'password': '12345678',
        }, format='json')
        self.assertEqual(weak.status_code, 400)
        good = self.client.post('/api/auth/password/reset', {
            'email': self.EMAIL, 'code': code, 'password': 'FreshPass!2026',
        }, format='json')
        self.assertEqual(good.status_code, 200, good.data)

    def test_bind_email_requires_login_and_rejects_taken_address(self):
        anonymous = self.send(email='someone@example.com', purpose='bind')
        self.assertEqual(anonymous.status_code, 401)

        other = get_user_model().objects.create_user(username='other', password=PASSWORD)
        EmailAddress.objects.create(user=other, email='taken@example.com')
        self.login()
        taken = self.send(email='taken@example.com', purpose='bind')
        self.assertEqual(taken.status_code, 400)

        fresh = self.send(email='bound@example.com', purpose='bind', ip='10.0.2.1')
        self.assertEqual(fresh.status_code, 200, fresh.data)
        verified = self.verify(self.latest_code(), email='bound@example.com', purpose='bind', ip='10.0.2.2')
        self.assertEqual(verified.status_code, 200, verified.data)
        self.assertTrue(EmailAddress.objects.filter(email='bound@example.com', user=self.user).exists())
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'bound@example.com')

    def test_login_code_cannot_be_used_for_reset(self):
        self.assertEqual(self.send().status_code, 200)
        code = self.latest_code()
        response = self.client.post('/api/auth/password/reset', {
            'email': self.EMAIL, 'code': code, 'password': 'FreshPass!2026',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_delivery_failure_does_not_start_cooldown(self):
        with patch('vocabulary.views.send_code_email', side_effect=EmailDeliveryError('smtp down')):
            failed = self.send()
        self.assertEqual(failed.status_code, 502)
        self.assertFalse(EmailVerification.objects.filter(email=self.EMAIL).exists())
        retried = self.send(ip='10.0.3.1')
        self.assertEqual(retried.status_code, 200, retried.data)


class InsightsTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def log(self, word, rating, interval_before=0, interval_after=0, when=None, practice=False):
        entry = AnswerLog.objects.create(
            user=self.user, word=word, dictionary=self.dictionary, rating=rating,
            interval_before=interval_before, interval_after=interval_after,
            is_practice=practice,
        )
        if when is not None:
            AnswerLog.objects.filter(id=entry.id).update(created_at=when)
        return entry

    def test_retention_curve_buckets_reviews_only(self):
        now = timezone.now()
        self.log(self.words[0], 'good', interval_before=3, when=now - timedelta(days=3))
        self.log(self.words[0], 'again', interval_before=3, when=now - timedelta(days=2))
        # First sighting (interval 0) is not a memory test.
        self.log(self.words[1], 'again', interval_before=0, when=now - timedelta(days=2))
        # Practice answers would skew retention with hand-picked weak words.
        self.log(self.words[1], 'again', interval_before=5, when=now - timedelta(days=2), practice=True)

        response = self.client.get('/api/profile/insights')
        self.assertEqual(response.status_code, 200)
        buckets = {row['label']: row for row in response.data['retention']}
        self.assertEqual(buckets['2–3 天']['attempts'], 2)
        self.assertEqual(buckets['2–3 天']['kept'], 1)
        self.assertEqual(buckets['2–3 天']['rate'], 0.5)
        self.assertIsNone(buckets['8–14 天']['rate'])
        self.assertEqual(response.data['sample']['recall_answers'], 2)

    def test_calibration_pairs_adjacent_answers(self):
        now = timezone.now()
        # easy -> next time forgotten
        self.log(self.words[0], 'easy', interval_before=0, when=now - timedelta(days=4))
        self.log(self.words[0], 'again', interval_before=9, when=now - timedelta(days=2))
        # good -> next time remembered
        self.log(self.words[1], 'good', interval_before=0, when=now - timedelta(days=4))
        self.log(self.words[1], 'good', interval_before=3, when=now - timedelta(days=1))

        response = self.client.get('/api/profile/insights')
        rows = {row['rating']: row for row in response.data['calibration']}
        self.assertEqual(rows['easy']['samples'], 1)
        self.assertEqual(rows['easy']['forgotten'], 1)
        self.assertEqual(rows['easy']['forgotten_rate'], 1.0)
        self.assertEqual(rows['good']['samples'], 1)
        self.assertEqual(rows['good']['forgotten'], 0)
        self.assertEqual(rows['again']['samples'], 0)
        self.assertIsNone(rows['again']['forgotten_rate'])

    def test_same_round_requeue_is_not_a_calibration_pair(self):
        now = timezone.now()
        self.log(self.words[0], 'again', interval_before=0, when=now - timedelta(minutes=30))
        self.log(self.words[0], 'good', interval_before=0, when=now - timedelta(minutes=20))
        response = self.client.get('/api/profile/insights')
        self.assertEqual(response.data['sample']['pairs'], 0)

    def test_progress_series_is_cumulative(self):
        today = timezone.localdate()
        early = today - timedelta(days=4)
        later = today - timedelta(days=1)
        UserWordProgress.objects.create(
            user=self.user, word=self.words[0], status='learning',
            first_learned_at=timezone.now() - timedelta(days=4),
        )
        UserWordProgress.objects.create(
            user=self.user, word=self.words[1], status='learning',
            first_learned_at=timezone.now() - timedelta(days=1),
        )
        response = self.client.get('/api/profile/insights?days=7')
        series = {row['date']: row for row in response.data['progress']}
        self.assertEqual(series[early.isoformat()]['learned'], 1)
        self.assertEqual(series[later.isoformat()]['learned'], 2)
        self.assertEqual(response.data['progress'][-1]['date'], today.isoformat())
        self.assertEqual(len(response.data['progress']), 7)

    def test_insights_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get('/api/profile/insights').status_code, 401)
