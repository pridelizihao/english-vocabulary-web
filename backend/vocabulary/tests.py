import io
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from openpyxl import Workbook
from rest_framework.test import APIClient

from .models import Dictionary, UserDictionary, UserWordProgress, Word


class LearningFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username='learner', password='secret123')
        self.admin = get_user_model().objects.create_user(username='admin', password='secret123', is_staff=True)
        self.dictionary = Dictionary.objects.create(name='CET4 Demo', level='CET4', status='published')
        self.words = [
            Word.objects.create(dictionary=self.dictionary, spelling='abandon', meaning='放弃'),
            Word.objects.create(dictionary=self.dictionary, spelling='ability', meaning='能力'),
        ]

    def login(self, username='learner'):
        self.assertEqual(self.client.post('/api/auth/login', {'username': username, 'password': 'secret123'}, format='json').status_code, 200)

    def test_auth_and_protected_routes(self):
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.login()
        self.assertEqual(self.client.get('/api/auth/me').data['user']['username'], 'learner')
        self.assertEqual(self.client.get(f'/api/review/today?dictionary_id={self.dictionary.id}').status_code, 403)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)

    def test_learning_and_statistics_flow(self):
        self.login()
        self.assertEqual(self.client.post(f'/api/dictionaries/{self.dictionary.id}/enroll').status_code, 200)
        self.assertEqual(UserDictionary.objects.filter(user=self.user, dictionary=self.dictionary).count(), 1)
        self.client.post(f'/api/dictionaries/{self.dictionary.id}/enroll')
        self.assertEqual(UserDictionary.objects.filter(user=self.user, dictionary=self.dictionary).count(), 1)
        study = self.client.get(f'/api/study/today?dictionary_id={self.dictionary.id}')
        self.assertEqual(len(study.data['words']), 2)
        answer = self.client.post(f'/api/study/{self.words[0].id}/answer', {'rating': 'good'}, format='json')
        self.assertEqual(answer.data['interval_days'], 3)
        progress = UserWordProgress.objects.get(user=self.user, word=self.words[0])
        self.assertEqual(progress.next_review_at.date(), (timezone.now() + timedelta(days=3)).date())
        stats = self.client.get(f'/api/statistics?dictionary_id={self.dictionary.id}')
        self.assertEqual(stats.data['learned_words'], 1)
        self.assertEqual(stats.data['mastered_words'], 1)

    def test_import_requires_admin_and_reports_rows(self):
        self.login()
        upload = io.BytesIO(b'word,meaning\nnew,New word\n,Missing word\n')
        self.assertEqual(self.client.post('/api/admin/dictionaries/import', {'dictionary_id': self.dictionary.id, 'file': upload}, format='multipart').status_code, 403)
        self.client.post('/api/auth/logout')
        self.login('admin')
        upload = io.BytesIO(b'word,meaning\nnew,New word\n,Missing word\n')
        response = self.client.post('/api/admin/dictionaries/import', {'dictionary_id': self.dictionary.id, 'file': upload}, format='multipart')
        self.assertEqual(response.data['created'], 1)
        self.assertEqual(response.data['skipped'], 1)
        self.assertEqual(response.data['errors'][0]['line'], 3)

    def test_published_filter_and_json_xlsx_import(self):
        draft = Dictionary.objects.create(name='Draft', status='draft')
        self.assertEqual(self.client.get('/api/dictionaries/').status_code, 200)
        self.assertNotIn(draft.id, [item['id'] for item in self.client.get('/api/dictionaries/').data])
        self.login('admin')
        json_upload = io.BytesIO(b'[{"word":"json-word","meaning":"JSON"}]')
        json_upload.name = 'words.json'
        response = self.client.post('/api/admin/dictionaries/import', {'dictionary_id': self.dictionary.id, 'file': json_upload}, format='multipart')
        self.assertEqual(response.data['created'], 1)
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(['word', 'meaning'])
        worksheet.append(['xlsx-word', 'XLSX'])
        xlsx_upload = io.BytesIO()
        workbook.save(xlsx_upload)
        xlsx_upload.seek(0)
        xlsx_upload.name = 'words.xlsx'
        response = self.client.post('/api/admin/dictionaries/import', {'dictionary_id': self.dictionary.id, 'file': xlsx_upload}, format='multipart')
        self.assertEqual(response.data['created'], 1)

