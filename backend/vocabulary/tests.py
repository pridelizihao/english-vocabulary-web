import io
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from openpyxl import Workbook
from rest_framework.test import APIClient

from .models import Dictionary, UserDictionary, UserWordProgress, Word
from .services import schedule

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
