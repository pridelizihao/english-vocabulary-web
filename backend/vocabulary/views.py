import re
from datetime import timedelta

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import api_view, parser_classes, throttle_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .models import AnswerLog, Dictionary, UserDictionary, UserWordProgress, Word
from .serializers import DictionarySerializer, ProgressSerializer, WordSerializer
from .services import (
    EARLY_REVIEW_LIMIT,
    EXTRA_NEW_LIMIT,
    NEW_WORD_LIMIT,
    RATINGS,
    REVIEW_LIMIT,
    ImportFileError,
    describe_interval,
    import_words,
    parse_import_rows,
    preview_intervals,
    schedule,
)

User = get_user_model()
USERNAME_PATTERN = re.compile(r'^[\w.@+-]{3,30}$')


class AuthThrottle(AnonRateThrottle):
    scope = 'auth'


def fail(message, status_code=status.HTTP_400_BAD_REQUEST):
    return Response({'detail': message}, status=status_code)


def require_authentication(request):
    if not request.user.is_authenticated:
        return fail('请先登录后再操作', status.HTTP_401_UNAUTHORIZED)
    return None


def current_user_payload(user):
    return {'user': {'id': user.id, 'username': user.username, 'is_staff': user.is_staff}}


def visible_dictionaries(user):
    """Published dictionaries the user may see: official ones plus their own."""
    query = Q(status='published')
    if user.is_authenticated:
        query &= Q(owner__isnull=True) | Q(owner=user)
    else:
        query &= Q(owner__isnull=True)
    return Dictionary.objects.filter(query)


def dictionary_for_user(request, dictionary_id):
    """Return (dictionary, error_response) honouring ownership rules."""
    dictionary = visible_dictionaries(request.user).filter(id=dictionary_id).first()
    if dictionary is None:
        return None, fail('词典不存在或你没有访问权限', status.HTTP_404_NOT_FOUND)
    return dictionary, None


def enrolled_dictionary(request, dictionary_id):
    dictionary, error = dictionary_for_user(request, dictionary_id)
    if error:
        return None, error
    if not UserDictionary.objects.filter(user=request.user, dictionary=dictionary).exists():
        return None, fail('请先开始学习这本词典', status.HTTP_403_FORBIDDEN)
    return dictionary, None


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

@api_view(['GET'])
@ensure_csrf_cookie
def csrf(request):
    return Response({'detail': 'csrf ready'})


@api_view(['POST'])
@parser_classes([JSONParser])
@throttle_classes([AuthThrottle])
def register(request):
    username = (request.data.get('username') or '').strip()
    password = request.data.get('password') or ''
    if not USERNAME_PATTERN.match(username):
        return fail('用户名需为 3-30 位字母、数字或 _ . @ + -')
    if User.objects.filter(username__iexact=username).exists():
        return fail('这个用户名已经被使用了')
    try:
        validate_password(password)
    except DjangoValidationError as exc:
        return fail(' '.join(exc.messages))
    user = User.objects.create_user(username=username, password=password)
    login(request, user)
    return Response(current_user_payload(user), status=status.HTTP_201_CREATED)


@api_view(['POST'])
@parser_classes([JSONParser])
@throttle_classes([AuthThrottle])
def sign_in(request):
    username = (request.data.get('username') or '').strip()
    password = request.data.get('password') or ''
    if not username or not password:
        return fail('请输入用户名和密码')
    user = authenticate(request, username=username, password=password)
    if not user:
        return fail('用户名或密码不正确')
    login(request, user)
    return Response(current_user_payload(user))


@api_view(['POST'])
def sign_out(request):
    logout(request)
    return Response({'detail': '已退出登录'})


@api_view(['GET'])
def me(request):
    error = require_authentication(request)
    if error:
        return error
    return Response(current_user_payload(request.user))


# ---------------------------------------------------------------------------
# Dictionaries
# ---------------------------------------------------------------------------

class DictionaryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = DictionarySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        queryset = visible_dictionaries(user)
        if user.is_authenticated:
            now = timezone.now()
            queryset = queryset.annotate(
                word_total=Count('words', distinct=True),
                learned_total=Count(
                    'words', filter=Q(words__userwordprogress__user=user), distinct=True,
                ),
                due_total=Count(
                    'words',
                    filter=Q(words__userwordprogress__user=user, words__userwordprogress__next_review_at__lte=now),
                    distinct=True,
                ),
            )
        else:
            queryset = queryset.annotate(word_total=Count('words', distinct=True))
        return queryset.order_by('id')

    def destroy(self, request, *args, **kwargs):
        dictionary = self.get_object()
        if not (request.user.is_staff or dictionary.owner_id == request.user.id):
            return fail('只能删除自己导入的词典', status.HTTP_403_FORBIDDEN)
        name = dictionary.name
        dictionary.delete()
        return Response({'detail': f'已删除《{name}》'}, status=status.HTTP_200_OK)


@api_view(['POST'])
def enroll_dictionary(request, dictionary_id):
    error = require_authentication(request)
    if error:
        return error
    dictionary, error = dictionary_for_user(request, dictionary_id)
    if error:
        return error
    _, created = UserDictionary.objects.get_or_create(user=request.user, dictionary=dictionary)
    return Response({'dictionary_id': dictionary.id, 'enrolled': True, 'created': created})


def _clamp_int(value, low, high, default=0):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _preview_for(progress=None):
    return preview_intervals(progress)


@api_view(['GET'])
def today_study(request):
    error = require_authentication(request)
    if error:
        return error
    dictionary_id = request.query_params.get('dictionary_id')
    if not dictionary_id:
        return fail('缺少 dictionary_id 参数')
    dictionary, error = enrolled_dictionary(request, dictionary_id)
    if error:
        return error

    progress = UserWordProgress.objects.filter(user=request.user, word__dictionary=dictionary)
    today = timezone.localdate()
    new_learned_today = progress.filter(first_learned_at__date=today).count()
    base_left = max(NEW_WORD_LIMIT - new_learned_today, 0)

    # "再来 20 个" only kicks in after the default daily budget is used up.
    extra_requested = _clamp_int(request.query_params.get('extra'), 0, EXTRA_NEW_LIMIT)
    extra_used_today = AnswerLog.objects.filter(
        user=request.user, is_new=True, is_extra=True, created_at__date=today,
    ).count()
    extra_left = max(EXTRA_NEW_LIMIT - extra_used_today, 0)
    extra_budget = min(extra_requested, extra_left) if base_left == 0 else 0
    budget = base_left + extra_budget

    remaining = Word.objects.filter(dictionary=dictionary).exclude(id__in=progress.values('word_id'))
    if request.query_params.get('order') == 'random':
        remaining = remaining.order_by('?')
    else:
        remaining = remaining.order_by('spelling', 'id')
    words = list(remaining[:budget]) if budget else []
    preview_map = {word.id: _preview_for(None) for word in words}
    due_reviews = progress.filter(next_review_at__lte=timezone.now()).count()
    return Response({
        'dictionary_id': dictionary.id,
        'words': WordSerializer(words, many=True, context={'preview_map': preview_map}).data,
        'total': len(words),
        'new_limit': NEW_WORD_LIMIT,
        'new_learned_today': new_learned_today,
        'extra_used_today': extra_used_today,
        'extra_limit': EXTRA_NEW_LIMIT,
        'extra_budget': extra_budget,
        'remaining_new': remaining.count(),
        'due_reviews': due_reviews,
    })


@api_view(['GET'])
def today_review(request):
    error = require_authentication(request)
    if error:
        return error
    dictionary_id = request.query_params.get('dictionary_id')
    if not dictionary_id:
        return fail('缺少 dictionary_id 参数')
    dictionary, error = enrolled_dictionary(request, dictionary_id)
    if error:
        return error
    queryset = UserWordProgress.objects.filter(
        user=request.user, word__dictionary=dictionary, next_review_at__lte=timezone.now(),
    ).select_related('word')
    total = queryset.count()
    queryset = queryset.order_by('?') if request.query_params.get('order') == 'random' else queryset.order_by('next_review_at', 'id')
    progress_list = list(queryset[:REVIEW_LIMIT])
    preview_map = {item.word_id: _preview_for(item) for item in progress_list}
    return Response({
        'dictionary_id': dictionary.id,
        'words': ProgressSerializer(progress_list, many=True, context={'preview_map': preview_map}).data,
        'total': total,
        'limit': REVIEW_LIMIT,
    })


@api_view(['POST'])
@parser_classes([JSONParser])
def answer_word(request, word_id):
    error = require_authentication(request)
    if error:
        return error
    word = get_object_or_404(Word, id=word_id, dictionary__status='published')
    if not UserDictionary.objects.filter(user=request.user, dictionary=word.dictionary).exists():
        return fail('请先开始学习这本词典', status.HTTP_403_FORBIDDEN)
    rating = request.data.get('rating')
    if rating not in RATINGS:
        return fail('rating 只能是 again / hard / good / easy')
    practice = bool(request.data.get('practice'))
    today = timezone.localdate()

    with transaction.atomic():
        if practice:
            progress = UserWordProgress.objects.filter(user=request.user, word=word).first()
            if progress is None:
                return fail('这个词还没有学过，不能练习')
            AnswerLog.objects.create(
                user=request.user, word=word, dictionary=word.dictionary, rating=rating,
                is_practice=True, interval_before=progress.interval_days,
                interval_after=progress.interval_days,
            )
            payload = ProgressSerializer(progress).data
            payload['practice'] = True
            payload['next_review_label'] = '仅练习，不改间隔'
            payload['preview'] = preview_intervals(progress)
            return Response(payload)

        progress, created = UserWordProgress.objects.select_for_update().get_or_create(user=request.user, word=word)
        new_today_before = UserWordProgress.objects.filter(
            user=request.user, word__dictionary=word.dictionary, first_learned_at__date=today,
        ).count()
        is_extra = bool(created and new_today_before >= NEW_WORD_LIMIT)
        interval_before = progress.interval_days
        schedule(progress, rating)
        progress.save(update_fields=[
            'status', 'review_count', 'wrong_count', 'streak', 'ease',
            'next_review_at', 'last_review_at', 'first_learned_at', 'interval_days',
        ])
        AnswerLog.objects.create(
            user=request.user, word=word, dictionary=word.dictionary, rating=rating,
            is_new=created, is_extra=is_extra, interval_before=interval_before,
            interval_after=progress.interval_days,
        )
    payload = ProgressSerializer(progress).data
    payload['next_review_label'] = describe_interval(progress.interval_days, rating)
    payload['preview'] = preview_intervals(progress)
    payload['is_new'] = created
    payload['is_extra'] = is_extra
    return Response(payload)


@api_view(['GET'])
def statistics(request):
    error = require_authentication(request)
    if error:
        return error
    dictionary_id = request.query_params.get('dictionary_id')
    if not dictionary_id:
        return fail('缺少 dictionary_id 参数')
    dictionary, error = enrolled_dictionary(request, dictionary_id)
    if error:
        return error
    progress = UserWordProgress.objects.filter(user=request.user, word__dictionary=dictionary)
    total = dictionary.words.count()
    learned = progress.count()
    now = timezone.now()
    today = timezone.localdate()
    next_review = (
        progress.filter(next_review_at__gt=now).order_by('next_review_at')
        .values_list('next_review_at', flat=True).first()
    )
    new_learned_today = progress.filter(first_learned_at__date=today).count()
    extra_used_today = AnswerLog.objects.filter(
        user=request.user, is_new=True, is_extra=True, created_at__date=today,
    ).count()
    return Response({
        'total_words': total,
        'learned_words': learned,
        'mastered_words': progress.filter(status='mastered').count(),
        'due_reviews': progress.filter(next_review_at__lte=now).count(),
        'today_completed': progress.filter(last_review_at__date=today).count(),
        'today_new': new_learned_today,
        'new_limit': NEW_WORD_LIMIT,
        'remaining_new': max(total - learned, 0),
        'progress_percent': round(learned / total * 100, 1) if total else 0,
        'next_review_at': next_review,
        'extra_used_today': extra_used_today,
        'extra_limit': EXTRA_NEW_LIMIT,
    })


@api_view(['GET'])
def early_review(request):
    error = require_authentication(request)
    if error:
        return error
    dictionary_id = request.query_params.get('dictionary_id')
    if not dictionary_id:
        return fail('缺少 dictionary_id 参数')
    dictionary, error = enrolled_dictionary(request, dictionary_id)
    if error:
        return error

    now = timezone.now()
    queryset = UserWordProgress.objects.filter(
        user=request.user, word__dictionary=dictionary, next_review_at__gt=now,
    ).select_related('word')
    total = queryset.count()
    order = request.query_params.get('order', 'weak')
    if order == 'random':
        queryset = queryset.order_by('?')
    elif order == 'due':
        queryset = queryset.order_by('next_review_at', 'id')
    else:
        queryset = queryset.order_by('streak', 'next_review_at', 'id')
    limit = _clamp_int(request.query_params.get('limit'), 1, EARLY_REVIEW_LIMIT, EARLY_REVIEW_LIMIT)
    items = list(queryset[:limit])
    preview_map = {item.word_id: _preview_for(item) for item in items}
    return Response({
        'dictionary_id': dictionary.id,
        'words': ProgressSerializer(items, many=True, context={'preview_map': preview_map}).data,
        'total': total,
        'limit': limit,
        'mode': 'early',
    })


@api_view(['GET'])
def profile_summary(request):
    error = require_authentication(request)
    if error:
        return error
    days = _clamp_int(request.query_params.get('days'), 7, 371, 371)
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    logs = AnswerLog.objects.filter(user=request.user)
    rows = logs.filter(created_at__date__gte=start).annotate(day=TruncDate('created_at')).values('day').annotate(
        answers=Count('id'),
        new=Count('id', filter=Q(is_new=True)),
        review=Count('id', filter=Q(is_new=False, is_practice=False)),
        practice=Count('id', filter=Q(is_practice=True)),
        extra=Count('id', filter=Q(is_extra=True)),
    ).order_by('day')
    by_day = {row['day']: row for row in rows}
    daily = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        row = by_day.get(day)
        daily.append({
            'date': day.isoformat(),
            'new': row['new'] if row else 0,
            'review': row['review'] if row else 0,
            'practice': row['practice'] if row else 0,
            'extra': row['extra'] if row else 0,
            'answers': row['answers'] if row else 0,
        })

    active_days = set(logs.annotate(day=TruncDate('created_at')).values_list('day', flat=True).distinct())
    cursor = today if today in active_days else today - timedelta(days=1)
    streak = 0
    while cursor in active_days:
        streak += 1
        cursor -= timedelta(days=1)

    now = timezone.now()
    progress = UserWordProgress.objects.filter(user=request.user)
    dictionary_rows = progress.values('word__dictionary').annotate(
        learned=Count('id'),
        mastered=Count('id', filter=Q(status='mastered')),
        due=Count('id', filter=Q(next_review_at__lte=now)),
    )
    names = Dictionary.objects.in_bulk([row['word__dictionary'] for row in dictionary_rows])
    dictionaries = []
    for row in dictionary_rows:
        dictionary = names.get(row['word__dictionary'])
        if dictionary is None or dictionary.status != 'published':
            continue
        if dictionary.owner_id and dictionary.owner_id != request.user.id:
            continue
        dictionaries.append({
            'id': dictionary.id,
            'name': dictionary.name,
            'learned': row['learned'],
            'mastered': row['mastered'],
            'due': row['due'],
        })
    dictionaries.sort(key=lambda item: item['name'])

    extra_used_today = logs.filter(is_extra=True, created_at__date=today).count()
    return Response({
        'days': days,
        'today': daily[-1],
        'streak': streak,
        'totals': {
            'answers': logs.count(),
            'active_days': len(active_days),
            'learned': progress.count(),
            'mastered': progress.filter(status='mastered').count(),
            'due': progress.filter(next_review_at__lte=now).count(),
        },
        'daily': daily,
        'dictionaries': dictionaries,
        'extra': {'used_today': extra_used_today, 'limit': EXTRA_NEW_LIMIT},
    })


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _read_upload(request):
    upload = request.FILES.get('file')
    if not upload:
        return None, fail('请选择要导入的文件（CSV / JSON / XLSX）')
    return upload, None


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def import_personal_dictionary(request):
    error = require_authentication(request)
    if error:
        return error
    upload, error = _read_upload(request)
    if error:
        return error
    try:
        rows = parse_import_rows(upload)
    except ImportFileError as exc:
        return fail(str(exc))
    name = (request.data.get('name') or '').strip()[:120]
    if not name:
        name = (upload.name.rsplit('.', 1)[0] or '我的自定义词典').strip()[:120] or '我的自定义词典'
    with transaction.atomic():
        dictionary, dictionary_created = Dictionary.objects.get_or_create(
            owner=request.user,
            name=name,
            defaults={
                'description': f'{request.user.username} 导入的个人词典',
                'level': '自定义',
                'status': 'published',
            },
        )
        if not dictionary_created and dictionary.status != 'published':
            dictionary.status = 'published'
            dictionary.save(update_fields=['status'])
        result = import_words(dictionary, rows)
        UserDictionary.objects.get_or_create(user=request.user, dictionary=dictionary)
    payload = {
        'dictionary_id': dictionary.id,
        'name': dictionary.name,
        'dictionary_created': dictionary_created,
        'total_rows': len(rows),
        **result,
    }
    return Response(payload, status=status.HTTP_201_CREATED if dictionary_created else status.HTTP_200_OK)


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def import_dictionary(request):
    error = require_authentication(request)
    if error:
        return error
    if not request.user.is_staff:
        return fail('需要管理员权限', status.HTTP_403_FORBIDDEN)
    dictionary = get_object_or_404(Dictionary, id=request.data.get('dictionary_id'))
    upload, error = _read_upload(request)
    if error:
        return error
    try:
        rows = parse_import_rows(upload)
    except ImportFileError as exc:
        return fail(str(exc))
    with transaction.atomic():
        result = import_words(dictionary, rows)
    return Response({'total_rows': len(rows), **result})
