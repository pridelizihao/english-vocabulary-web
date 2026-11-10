import csv
import io
import json
from pathlib import Path
from datetime import timedelta

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import Dictionary, UserDictionary, UserWordProgress, Word
from .serializers import DictionarySerializer, ProgressSerializer, WordSerializer

User = get_user_model()
NEW_WORD_LIMIT = 20
REVIEW_LIMIT = 50
INTERVALS = {'again': 0, 'hard': 1, 'good': 3, 'easy': 7}


def current_user_payload(user):
    return {'user': {'id': user.id, 'username': user.username, 'is_staff': user.is_staff}}


def require_authentication(request):
    if not request.user.is_authenticated:
        return Response({'detail': 'authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
    return None


@api_view(['GET'])
@ensure_csrf_cookie
def csrf(request):
    return Response({'detail': 'csrf ready'})


@api_view(['POST'])
@parser_classes([JSONParser])
def register(request):
    username = (request.data.get('username') or '').strip()
    password = request.data.get('password') or ''
    if not username:
        return Response({'detail': 'username is required'}, status=400)
    if len(password) < 6:
        return Response({'detail': 'password must be at least 6 characters'}, status=400)
    if User.objects.filter(username=username).exists():
        return Response({'detail': 'username already exists'}, status=400)
    user = User.objects.create_user(username=username, password=password)
    login(request, user)
    return Response(current_user_payload(user), status=201)


@api_view(['POST'])
@parser_classes([JSONParser])
def sign_in(request):
    user = authenticate(request, username=request.data.get('username'), password=request.data.get('password'))
    if not user:
        return Response({'detail': 'invalid credentials'}, status=400)
    login(request, user)
    return Response(current_user_payload(user))


@api_view(['POST'])
def sign_out(request):
    logout(request)
    return Response({'detail': 'logged out'})


@api_view(['GET'])
def me(request):
    error = require_authentication(request)
    if error:
        return error
    return Response(current_user_payload(request.user))


class DictionaryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dictionary.objects.filter(status='published').prefetch_related('words')
    serializer_class = DictionarySerializer


@api_view(['POST'])
def enroll_dictionary(request, dictionary_id):
    error = require_authentication(request)
    if error:
        return error
    dictionary = get_object_or_404(Dictionary, id=dictionary_id, status='published')
    enrollment, created = UserDictionary.objects.get_or_create(user=request.user, dictionary=dictionary)
    return Response({'dictionary_id': dictionary.id, 'enrolled': True, 'created': created})


def selected_dictionary(request, dictionary_id):
    dictionary = get_object_or_404(Dictionary, id=dictionary_id, status='published')
    if not UserDictionary.objects.filter(user=request.user, dictionary=dictionary).exists():
        return None, Response({'detail': 'enroll in this dictionary first'}, status=403)
    return dictionary, None


@api_view(['GET'])
def today_study(request):
    error = require_authentication(request)
    if error:
        return error
    dictionary_id = request.query_params.get('dictionary_id')
    if not dictionary_id:
        return Response({'detail': 'dictionary_id is required'}, status=400)
    dictionary, error = selected_dictionary(request, dictionary_id)
    if error:
        return error
    progressed_ids = UserWordProgress.objects.filter(user=request.user, word__dictionary=dictionary).values('word_id')
    words_qs = Word.objects.filter(dictionary=dictionary).exclude(id__in=progressed_ids)
    order = request.query_params.get('order', 'alpha')
    words_qs = words_qs.order_by('?') if order == 'random' else words_qs.order_by('spelling', 'id')
    words = words_qs[:NEW_WORD_LIMIT]
    completed = UserWordProgress.objects.filter(user=request.user, word__dictionary=dictionary, last_review_at__date=timezone.localdate()).count()
    total = dictionary.words.count()
    return Response({
        'dictionary_id': dictionary.id,
        'words': WordSerializer(words, many=True).data,
        'total': words.count(),
        'completed_today': completed,
        'remaining_new': max(total - UserWordProgress.objects.filter(user=request.user, word__dictionary=dictionary).count(), 0),
    })


@api_view(['GET'])
def today_review(request):
    error = require_authentication(request)
    if error:
        return error
    dictionary_id = request.query_params.get('dictionary_id')
    if not dictionary_id:
        return Response({'detail': 'dictionary_id is required'}, status=400)
    dictionary, error = selected_dictionary(request, dictionary_id)
    if error:
        return error
    qs = UserWordProgress.objects.filter(user=request.user, word__dictionary=dictionary, next_review_at__lte=timezone.now()).select_related('word')
    qs = qs.order_by('?') if request.query_params.get('order') == 'random' else qs.order_by('next_review_at', 'id')
    qs = qs[:REVIEW_LIMIT]
    return Response({'dictionary_id': dictionary.id, 'words': ProgressSerializer(qs, many=True).data, 'total': qs.count()})


@api_view(['POST'])
@parser_classes([JSONParser])
def answer_word(request, word_id):
    error = require_authentication(request)
    if error:
        return error
    word = get_object_or_404(Word, id=word_id, dictionary__status='published')
    if not UserDictionary.objects.filter(user=request.user, dictionary=word.dictionary).exists():
        return Response({'detail': 'enroll in this dictionary first'}, status=403)
    rating = request.data.get('rating')
    if rating not in INTERVALS:
        return Response({'detail': 'rating must be again, hard, good or easy'}, status=400)
    interval = INTERVALS[rating]
    progress, _ = UserWordProgress.objects.get_or_create(user=request.user, word=word)
    progress.review_count += 1
    progress.status = 'learning' if rating in {'again', 'hard'} else 'mastered'
    progress.wrong_count += int(rating == 'again')
    progress.interval_days = interval
    progress.last_review_at = timezone.now()
    progress.next_review_at = timezone.now() + timedelta(days=interval)
    progress.save(update_fields=['review_count', 'status', 'wrong_count', 'interval_days', 'last_review_at', 'next_review_at'])
    return Response(ProgressSerializer(progress).data)


@api_view(['GET'])
def statistics(request):
    error = require_authentication(request)
    if error:
        return error
    dictionary_id = request.query_params.get('dictionary_id')
    if not dictionary_id:
        return Response({'detail': 'dictionary_id is required'}, status=400)
    dictionary, error = selected_dictionary(request, dictionary_id)
    if error:
        return error
    progress = UserWordProgress.objects.filter(user=request.user, word__dictionary=dictionary)
    total = dictionary.words.count()
    learned = progress.count()
    return Response({
        'total_words': total,
        'learned_words': learned,
        'mastered_words': progress.filter(status='mastered').count(),
        'due_reviews': progress.filter(next_review_at__lte=timezone.now()).count(),
        'today_completed': progress.filter(last_review_at__date=timezone.localdate()).count(),
        'progress_percent': round((learned / total * 100) if total else 0, 2),
    })


def parse_import_rows(upload):
    filename = upload.name.lower()
    if filename.endswith('.json'):
        rows = json.loads(upload.read().decode('utf-8-sig'))
        if not isinstance(rows, list):
            raise ValueError('JSON must contain an array of word objects')
        return rows
    if filename.endswith(('.xlsx', '.xlsm')):
        workbook = load_workbook(upload, read_only=True, data_only=True)
        values = list(workbook.active.values)
        return [dict(zip(values[0], row)) for row in values[1:]] if values else []
    return list(csv.DictReader(io.StringIO(upload.read().decode('utf-8-sig'))))


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def import_dictionary(request):
    error = require_authentication(request)
    if error:
        return error
    if not request.user.is_staff:
        return Response({'detail': 'admin permission required'}, status=403)
    dictionary = get_object_or_404(Dictionary, id=request.data.get('dictionary_id'))
    upload = request.FILES.get('file')
    if not upload:
        return Response({'detail': 'file is required'}, status=400)
    try:
        rows = parse_import_rows(upload)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Response({'detail': f'invalid import file: {exc}'}, status=400)
    if not rows or not {'word', 'meaning'}.issubset({str(key).strip() for key in rows[0].keys()}):
        return Response({'detail': 'file must contain word and meaning columns'}, status=400)
    created = updated = skipped = 0
    errors = []
    with transaction.atomic():
        for line_number, raw_row in enumerate(rows, start=2):
            row = {str(key).strip(): ('' if value is None else str(value).strip()) for key, value in raw_row.items()}
            spelling = row.get('word', '')
            meaning = row.get('meaning', '')
            if not spelling or not meaning:
                skipped += 1
                errors.append({'line': line_number, 'error': 'word and meaning are required'})
                continue
            _, was_created = Word.objects.update_or_create(
                dictionary=dictionary,
                spelling=spelling,
                defaults={'phonetic': row.get('phonetic', ''), 'part_of_speech': row.get('part_of_speech', ''), 'meaning': meaning, 'example': row.get('example', ''), 'audio_url': row.get('audio_url', '')},
            )
            if was_created:
                created += 1
            else:
                updated += 1
    return Response({'created': created, 'updated': updated, 'skipped': skipped, 'total_rows': len(rows), 'errors': errors})


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def import_personal_dictionary(request):
    error = require_authentication(request)
    if error:
        return error
    upload = request.FILES.get('file')
    if not upload:
        return Response({'detail': 'file is required'}, status=400)
    try:
        rows = parse_import_rows(upload)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Response({'detail': f'invalid import file: {exc}'}, status=400)
    if not rows or not {'word', 'meaning'}.issubset({str(key).strip() for key in rows[0].keys()}):
        return Response({'detail': 'file must contain word and meaning columns'}, status=400)
    name = (request.data.get('name') or Path(upload.name).stem or '我的自定义词典').strip()[:120]
    dictionary = Dictionary.objects.create(name=name, description=f'{request.user.username} 导入的自定义词典', level='自定义', status='published')
    created = skipped = 0
    for raw_row in rows:
        row = {str(key).strip(): ('' if value is None else str(value).strip()) for key, value in raw_row.items()}
        if not row.get('word') or not row.get('meaning'):
            skipped += 1
            continue
        Word.objects.update_or_create(dictionary=dictionary, spelling=row['word'], defaults={'meaning': row['meaning'], 'phonetic': row.get('phonetic', ''), 'part_of_speech': row.get('part_of_speech', ''), 'example': row.get('example', ''), 'audio_url': row.get('audio_url', '')})
        created += 1
    UserDictionary.objects.get_or_create(user=request.user, dictionary=dictionary)
    return Response({'dictionary_id': dictionary.id, 'name': dictionary.name, 'created': created, 'skipped': skipped}, status=201)
