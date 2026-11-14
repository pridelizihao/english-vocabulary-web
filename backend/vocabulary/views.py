import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, F, Min, OuterRef, Q, Subquery, When
from django.db.models.functions import Mod, TruncDate
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import api_view, parser_classes, throttle_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .email_codes import (
    EmailCodeError,
    EmailDeliveryError,
    EmailRateLimitError,
    normalize_email,
    issue_code,
    send_code_email,
    verify_code,
)
from .models import AnswerLog, Dictionary, EmailAddress, EmailVerification, UserDictionary, UserWordProgress, Word
from .serializers import DictionarySerializer, ProgressSerializer, WordListSerializer, WordSerializer
from .services import (
    EARLY_REVIEW_LIMIT,
    EXTRA_NEW_LIMIT,
    MASTERED_INTERVAL_DAYS,
    MASTERED_STATUSES,
    NEW_WORD_LIMIT,
    NEW_WORD_HALVE_DUE,
    NEW_WORD_PAUSE_DUE,
    RATINGS,
    REVIEW_LIMIT,
    UNDO_WINDOW_MINUTES,
    ImportFileError,
    SentenceAudioError,
    adaptive_new_limit,
    derive_cloze_rating,
    describe_interval,
    import_words,
    parse_import_rows,
    preview_intervals,
    schedule,
    sentence_audio_file,
    status_for,
    steps_to_mastered,
)

User = get_user_model()
USERNAME_PATTERN = re.compile(r'^[\w.@+-]{3,30}$')
WORD_SEARCH_MAX_LENGTH = 50
WORDS_PAGE_SIZE = 50
WORDS_MAX_PAGE_SIZE = 200
WRONG_WORDS_LIMIT = 50
# 一题最多记几次试错（前端不会超过 3，留余量防脏数据）。
MAX_ANSWER_ATTEMPTS = 20
WORD_LIST_FILTERS = ('all', 'new', 'learning', 'mastered', 'due', 'wrong')


def _due_q(now=None, prefix=''):
    """到期复习的过滤条件：已归档的词不再进复习队列。

    `prefix` 用于联表场景（例如从 Dictionary 反查时是
    `words__userwordprogress__`）。
    """
    moment = now or timezone.now()
    return Q(**{f'{prefix}next_review_at__lte': moment}) & ~Q(**{f'{prefix}status': 'retired'})


# 「已掌握」的统计口径把已归档也算进去：归档必然已经掌握过。
MASTERED_Q = Q(status__in=MASTERED_STATUSES)
WORD_LIST_SORTS = ('alpha', 'recent', 'due', 'wrong')
# Core order: B1/B2 first (the CET core), then C1, then words outside the
# Oxford lists, then easy A2/A1 words; proper nouns always last.
STUDY_ORDERS = ('core', 'alpha', 'random')
CORE_LEVEL_RANKS = {'B1': 0, 'B2': 1, 'C1': 2, 'A2': 4, 'A1': 5}
CORE_LEVEL_DEFAULT = 3
UNDO_WINDOW = timedelta(minutes=UNDO_WINDOW_MINUTES)


class AuthThrottle(AnonRateThrottle):
    scope = 'auth'


class EmailCodeThrottle(AnonRateThrottle):
    scope = 'email_code'


def client_ip(request):
    """Best-effort client address; nginx forwards it in X-Forwarded-For."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()[:64]
    return (request.META.get('REMOTE_ADDR') or '')[:64]


def fail(message, status_code=status.HTTP_400_BAD_REQUEST):
    return Response({'detail': message}, status=status_code)


def require_authentication(request):
    if not request.user.is_authenticated:
        return fail('请先登录后再操作', status.HTTP_401_UNAUTHORIZED)
    return None


def current_user_payload(user):
    return {'user': {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'is_staff': user.is_staff,
    }}


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


# --- email codes ------------------------------------------------------------
# 验证码登录同时承担注册：邮箱第一次验证通过时就地建账号。所有「这个邮箱存不
# 存在」的差别都藏在返回文案里，避免把登录接口变成账号枚举器。

EMAIL_CODE_SENT = '如果这个邮箱可以使用，验证码已经发出，请查收'


def _username_for_email(email):
    """Derive a unique username (3-30 chars, see `USERNAME_PATTERN`)."""
    local = re.sub(r'[^\w.@+-]', '', email.split('@')[0])[:20].strip('._-')
    candidate = local if len(local) >= 3 else f'u_{secrets.token_hex(3)}'
    base = candidate
    suffix = 1
    while User.objects.filter(username__iexact=candidate).exists():
        suffix += 1
        candidate = f'{base[:30 - len(str(suffix))]}{suffix}'
    return candidate


def _account_for_email(email):
    """Return `(user, created)` for a verified address, creating the account lazily."""
    identity = EmailAddress.objects.select_related('user').filter(email=email).first()
    if identity is not None:
        return identity.user, False
    try:
        with transaction.atomic():
            user = User(username=_username_for_email(email), email=email)
            user.set_unusable_password()
            user.save()
            EmailAddress.objects.create(user=user, email=email)
    except IntegrityError:
        # A concurrent request created the same address first: adopt that account.
        identity = EmailAddress.objects.select_related('user').filter(email=email).first()
        if identity is None:
            raise
        return identity.user, False
    return user, True


def _code_sent_payload(sent, retry_after=None):
    return {
        'detail': EMAIL_CODE_SENT,
        'sent': sent,
        'expires_in': settings.EMAIL_CODE_TTL_MINUTES * 60,
        'retry_after': settings.EMAIL_CODE_COOLDOWN_SECONDS if retry_after is None else retry_after,
    }


@api_view(['POST'])
@parser_classes([JSONParser])
@throttle_classes([EmailCodeThrottle])
def send_email_code(request):
    purpose = (request.data.get('purpose') or EmailVerification.PURPOSE_LOGIN).strip()
    if purpose not in (EmailVerification.PURPOSE_LOGIN, EmailVerification.PURPOSE_RESET,
                       EmailVerification.PURPOSE_BIND):
        return fail('不支持的验证码类型')
    if purpose == EmailVerification.PURPOSE_BIND:
        error = require_authentication(request)
        if error:
            return error
    try:
        email = normalize_email(request.data.get('email'))
    except EmailCodeError as exc:
        return fail(str(exc))

    if purpose == EmailVerification.PURPOSE_RESET:
        # Pretend success for unknown addresses; the mail is simply not sent.
        if not EmailAddress.objects.filter(email=email).exists():
            return Response(_code_sent_payload(sent=False))
    if purpose == EmailVerification.PURPOSE_BIND:
        if EmailAddress.objects.filter(email=email).exclude(user=request.user).exists():
            return fail('这个邮箱已经绑定在别的账号上了')
        if EmailAddress.objects.filter(email=email, user=request.user).exists():
            return fail('这个邮箱已经绑定到你的账号了')

    try:
        verification, code = issue_code(email=email, purpose=purpose, ip=client_ip(request))
    except EmailRateLimitError as exc:
        return Response(
            {'detail': str(exc), 'retry_after': exc.retry_after},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    except EmailCodeError as exc:
        return fail(str(exc))

    try:
        send_code_email(email=email, code=code, purpose=purpose)
    except EmailDeliveryError as exc:
        # Drop the row so a failed delivery does not start the cooldown clock.
        verification.delete()
        return fail(str(exc), status.HTTP_502_BAD_GATEWAY)

    return Response(_code_sent_payload(sent=True))


@api_view(['POST'])
@parser_classes([JSONParser])
@throttle_classes([EmailCodeThrottle])
def verify_email_code(request):
    purpose = (request.data.get('purpose') or EmailVerification.PURPOSE_LOGIN).strip()
    if purpose not in (EmailVerification.PURPOSE_LOGIN, EmailVerification.PURPOSE_BIND):
        return fail('这个验证码不能在这里使用')
    if purpose == EmailVerification.PURPOSE_BIND:
        error = require_authentication(request)
        if error:
            return error
    try:
        email = normalize_email(request.data.get('email'))
    except EmailCodeError as exc:
        return fail(str(exc))
    try:
        verify_code(email=email, purpose=purpose, code=request.data.get('code'))
    except EmailCodeError as exc:
        return fail(str(exc))

    if purpose == EmailVerification.PURPOSE_BIND:
        if EmailAddress.objects.filter(email=email).exclude(user=request.user).exists():
            return fail('这个邮箱已经绑定在别的账号上了')
        with transaction.atomic():
            EmailAddress.objects.update_or_create(
                email=email, defaults={'user': request.user, 'verified_at': timezone.now()},
            )
            if not request.user.email:
                request.user.email = email
                request.user.save(update_fields=['email'])
        return Response({**current_user_payload(request.user), 'bound': True})

    user, created = _account_for_email(email)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return Response({**current_user_payload(user), 'created': created})


@api_view(['POST'])
@parser_classes([JSONParser])
@throttle_classes([EmailCodeThrottle])
def reset_password(request):
    try:
        email = normalize_email(request.data.get('email'))
    except EmailCodeError as exc:
        return fail(str(exc))
    password = request.data.get('password') or ''
    if len(password) < 8:
        return fail('密码至少需要 8 位')
    # Validate the password before spending the code: a rejected password must
    # not force the learner to request another mail.
    try:
        validate_password(password)
    except DjangoValidationError as exc:
        return fail(' '.join(exc.messages))
    try:
        verify_code(email=email, purpose=EmailVerification.PURPOSE_RESET, code=request.data.get('code'))
    except EmailCodeError as exc:
        return fail(str(exc))

    identity = EmailAddress.objects.select_related('user').filter(email=email).first()
    if identity is None:
        return fail('这个邮箱还没有绑定账号')
    user = identity.user
    user.set_password(password)
    user.save(update_fields=['password'])
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return Response({'detail': '密码已经重置，已为你登录', **current_user_payload(user)})


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
                    filter=Q(words__userwordprogress__user=user)
                    & _due_q(now, 'words__userwordprogress__'),
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


def _clean_search(value):
    return (value or '').strip()[:WORD_SEARCH_MAX_LENGTH]


def _word_filter_queryset(request, dictionary, name):
    """Words of one dictionary narrowed to a learning-state filter.

    Anonymous users have no progress, so only `new` is meaningful and it means
    "not learned by me" — which for them is every word.
    """
    words = Word.objects.filter(dictionary=dictionary)
    if name == 'all':
        return words
    if not request.user.is_authenticated:
        return words if name == 'new' else words.none()
    progress = UserWordProgress.objects.filter(user=request.user, word__dictionary=dictionary)
    if name == 'new':
        return words.exclude(id__in=progress.values('word_id'))
    if name == 'learning':
        return words.filter(id__in=progress.filter(status='learning').values('word_id'))
    if name == 'mastered':
        return words.filter(id__in=progress.filter(MASTERED_Q).values('word_id'))
    if name == 'due':
        return words.filter(id__in=progress.filter(_due_q()).values('word_id'))
    if name == 'wrong':
        return words.filter(id__in=progress.filter(wrong_count__gt=0).values('word_id'))
    return words


WORD_SORT_ORDERS = {
    'recent': (F('my_last_review').desc(nulls_last=True), 'spelling', 'id'),
    'due': (F('my_next_review').asc(nulls_last=True), 'spelling', 'id'),
    'wrong': (F('my_wrong').desc(nulls_last=True), 'spelling', 'id'),
}


def _annotate_word_progress(words, user):
    """Attach the current user's progress fields so the list can be sorted."""
    progress = UserWordProgress.objects.filter(user=user, word=OuterRef('pk'))
    return words.annotate(
        my_last_review=Subquery(progress.values('last_review_at')[:1]),
        my_next_review=Subquery(progress.values('next_review_at')[:1]),
        my_wrong=Subquery(progress.values('wrong_count')[:1]),
    )


def _answer_history(user, word, limit=10):
    logs = AnswerLog.objects.filter(user=user, word=word, undone_at__isnull=True).order_by('-created_at', '-id')[:limit]
    return [
        {
            'id': log.id,
            'rating': log.rating,
            'rating_label': log.get_rating_display(),
            'created_at': log.created_at,
            'interval_before': log.interval_before,
            'interval_after': log.interval_after,
            'is_practice': log.is_practice,
            'is_skip': log.is_skip,
            'mode': log.mode,
            'attempts': log.attempts,
            'revealed': log.revealed,
        }
        for log in logs
    ]


def _progress_snapshot(progress, created):
    """Serialisable copy of a progress row taken before applying a rating."""
    return {
        'created': bool(created),
        'status': progress.status,
        'review_count': progress.review_count,
        'wrong_count': progress.wrong_count,
        'streak': progress.streak,
        'ease': progress.ease,
        'interval_days': progress.interval_days,
        'next_review_at': progress.next_review_at.isoformat() if progress.next_review_at else None,
        'first_learned_at': progress.first_learned_at.isoformat() if progress.first_learned_at else None,
    }


def _duplicate_answer_payload(log):
    """Response for a retried answer: same shape, without touching the schedule."""
    progress = UserWordProgress.objects.filter(user=log.user, word=log.word).first()
    if log.is_practice:
        payload = ProgressSerializer(progress).data if progress else {}
        payload['practice'] = True
        payload['next_review_label'] = '仅练习，不改间隔'
        payload['preview'] = preview_intervals(progress)
    else:
        payload = ProgressSerializer(progress).data if progress else {}
        payload['next_review_label'] = '一年后' if log.is_skip else describe_interval(log.interval_after, log.rating)
        payload['preview'] = preview_intervals(progress)
        payload['is_new'] = log.is_new
        payload['is_extra'] = log.is_extra
        payload['is_skip'] = log.is_skip
    payload['answer_log_id'] = log.id
    payload['duplicate'] = True
    return payload


@api_view(['GET'])
def dictionary_words(request, dictionary_id):
    """Browse / search one dictionary; works without enrolling in it."""
    dictionary, error = dictionary_for_user(request, dictionary_id)
    if error:
        return error
    user = request.user
    filter_name = request.query_params.get('filter', 'all')
    if filter_name not in WORD_LIST_FILTERS:
        filter_name = 'all'
    sort = request.query_params.get('sort', 'alpha')
    if sort not in WORD_LIST_SORTS:
        sort = 'alpha'
    query = _clean_search(request.query_params.get('q'))

    counts = {name: _word_filter_queryset(request, dictionary, name).count() for name in WORD_LIST_FILTERS}

    words = _word_filter_queryset(request, dictionary, filter_name)
    if query:
        words = words.filter(Q(spelling__icontains=query) | Q(meaning__icontains=query))
    if user.is_authenticated:
        words = _annotate_word_progress(words, user)
        ordering = WORD_SORT_ORDERS.get(sort)
        words = words.order_by(*(ordering or ('spelling', 'id')))
    else:
        words = words.order_by('spelling', 'id')

    page_size = _clamp_int(request.query_params.get('page_size'), 1, WORDS_MAX_PAGE_SIZE, WORDS_PAGE_SIZE)
    paginator = Paginator(words, page_size)
    page_number = _clamp_int(request.query_params.get('page'), 1, max(paginator.num_pages, 1), 1)
    page = paginator.page(page_number)
    page_words = list(page.object_list)

    progress_map = {}
    if user.is_authenticated and page_words:
        progress_map = {
            item.word_id: item
            for item in UserWordProgress.objects.filter(
                user=user, word_id__in=[word.id for word in page_words],
            )
        }

    enrolled = bool(
        user.is_authenticated
        and UserDictionary.objects.filter(user=user, dictionary=dictionary).exists()
    )
    return Response({
        'dictionary': {'id': dictionary.id, 'name': dictionary.name, 'word_count': counts['all']},
        'enrolled': enrolled,
        'filter': filter_name,
        'sort': sort,
        'query': query,
        'counts': counts,
        'total': paginator.count,
        'page': page.number,
        'page_size': page_size,
        'pages': paginator.num_pages,
        'results': WordListSerializer(page_words, many=True, context={'progress_map': progress_map}).data,
    })


@api_view(['GET'])
def example_audio(request, word_id):
    """Cached MP3 of the example sentence, synthesised with edge-tts."""
    word = Word.objects.filter(id=word_id).first()
    if word is None:
        return fail('单词不存在或没有访问权限', status.HTTP_404_NOT_FOUND)
    _, error = dictionary_for_user(request, word.dictionary_id)
    if error:
        return fail('单词不存在或没有访问权限', status.HTTP_404_NOT_FOUND)
    if not word.example.strip():
        return fail('这个词还没有例句', status.HTTP_404_NOT_FOUND)
    try:
        audio = sentence_audio_file(word.example, settings.AUDIO_CACHE_DIR)
    except SentenceAudioError:
        return fail('例句语音生成失败，请稍后再试', status.HTTP_503_SERVICE_UNAVAILABLE)
    response = FileResponse(open(audio, 'rb'), content_type='audio/mpeg')
    response['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@api_view(['GET'])
def word_detail(request, word_id):
    word = Word.objects.select_related('dictionary').filter(id=word_id).first()
    if word is None:
        return fail('单词不存在或没有访问权限', status.HTTP_404_NOT_FOUND)
    dictionary, error = dictionary_for_user(request, word.dictionary_id)
    if error:
        return fail('单词不存在或没有访问权限', status.HTTP_404_NOT_FOUND)

    progress = None
    history = []
    if request.user.is_authenticated:
        progress = UserWordProgress.objects.filter(user=request.user, word=word).first()
        history = _answer_history(request.user, word)
    payload = WordSerializer(word, context={'preview_map': {word.id: preview_intervals(progress)}}).data
    payload['dictionary'] = {'id': dictionary.id, 'name': dictionary.name}
    payload['progress'] = ProgressSerializer(progress).data if progress else None
    # 距掌握还差几次：直接拿调度器往前推，和真实规则保持一致。
    payload['steps_to_mastered'] = steps_to_mastered(progress) if progress else None
    payload['history'] = history
    return Response(payload)


@api_view(['POST'])
def relearn_word(request, word_id):
    """把已归档的词放回复习队列（手动「重新学习」）。"""
    error = require_authentication(request)
    if error:
        return error
    word = Word.objects.filter(id=word_id).first()
    if word is None:
        return fail('单词不存在或没有访问权限', status.HTTP_404_NOT_FOUND)
    _, error = dictionary_for_user(request, word.dictionary_id)
    if error:
        return fail('单词不存在或没有访问权限', status.HTTP_404_NOT_FOUND)
    with transaction.atomic():
        progress = (
            UserWordProgress.objects.select_for_update()
            .filter(user=request.user, word=word)
            .first()
        )
        if progress is None:
            return fail('这个词还没有学习记录', status.HTTP_400_BAD_REQUEST)
        if progress.status != 'retired':
            return fail('只有已归档的词才需要重新学习', status.HTTP_400_BAD_REQUEST)
        progress.status = 'learning'
        progress.streak = 0
        progress.interval_days = 0
        progress.next_review_at = timezone.now()
        progress.save(update_fields=['status', 'streak', 'interval_days', 'next_review_at'])
    payload = ProgressSerializer(progress).data
    payload['preview'] = preview_intervals(progress)
    return Response(payload)


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
    now = timezone.now()
    new_learned_today = progress.filter(first_learned_at__date=today).count()
    due_reviews = progress.filter(_due_q(now)).count()
    # 复习积压越多，今天的新词越少；额度不再是无条件的 20 个。
    daily_limit = adaptive_new_limit(due_reviews)
    base_left = max(daily_limit - new_learned_today, 0)

    # "再来 20 个" only kicks in after the default daily budget is used up.
    extra_requested = _clamp_int(request.query_params.get('extra'), 0, EXTRA_NEW_LIMIT)
    extra_used_today = AnswerLog.objects.filter(
        user=request.user, is_new=True, is_extra=True, created_at__date=today, undone_at__isnull=True,
    ).count()
    extra_left = max(EXTRA_NEW_LIMIT - extra_used_today, 0)
    # 复习积压到停发新词时，「再来 20 个」也不能绕过：先把复习清完。
    extra_budget = min(extra_requested, extra_left) if base_left == 0 and daily_limit > 0 else 0
    budget = base_left + extra_budget

    remaining = Word.objects.filter(dictionary=dictionary).exclude(id__in=progress.values('word_id'))
    order = request.query_params.get('order', 'core')
    if order not in STUDY_ORDERS:
        order = 'core'
    if order == 'random':
        remaining = remaining.order_by('?')
    elif order == 'core':
        # Same level should not read like a dictionary column: give every user
        # a stable pseudo-random order per day (changes tomorrow, not on refresh).
        seed = (request.user.id * 7919 + today.toordinal() * 104729) % 2147483647
        remaining = remaining.annotate(
            proper_rank=Case(When(is_proper=True, then=1), default=0),
            level_rank=Case(
                *[When(cefr=level, then=rank) for level, rank in CORE_LEVEL_RANKS.items()],
                default=CORE_LEVEL_DEFAULT,
            ),
            shuffle_key=Mod(F('id') * 1103515245 + seed, 2147483647),
        ).order_by('proper_rank', 'level_rank', 'shuffle_key', 'id')
    else:
        remaining = remaining.order_by('spelling', 'id')
    words = list(remaining[:budget]) if budget else []
    preview_map = {word.id: _preview_for(None) for word in words}
    return Response({
        'dictionary_id': dictionary.id,
        'words': WordSerializer(words, many=True, context={'preview_map': preview_map}).data,
        'total': len(words),
        'new_limit': daily_limit,
        'new_limit_base': NEW_WORD_LIMIT,
        'new_limit_note': _adaptive_note(daily_limit, due_reviews),
        'new_learned_today': new_learned_today,
        'extra_used_today': extra_used_today,
        'extra_limit': EXTRA_NEW_LIMIT,
        'extra_budget': extra_budget,
        'remaining_new': remaining.count(),
        'due_reviews': due_reviews,
    })


def _adaptive_note(limit, due_reviews):
    """告诉前端今天为什么不是 20 个新词。"""
    if limit >= NEW_WORD_LIMIT:
        return ''
    if limit == 0:
        return f'今天到期复习有 {due_reviews} 个，先清复习，新词暂停一天'
    return f'今天到期复习有 {due_reviews} 个，新词减到 {limit} 个'


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
        user=request.user, word__dictionary=dictionary,
    ).filter(_due_q()).select_related('word')
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
    practice = bool(request.data.get('practice'))
    known = bool(request.data.get('known'))
    mode = request.data.get('mode') or 'card'
    if mode not in ('card', 'cloze'):
        return fail('mode 只能是 card 或 cloze')
    attempts = _clamp_int(request.data.get('attempts'), 1, MAX_ANSWER_ATTEMPTS, 1)
    revealed = bool(request.data.get('revealed'))
    correct = request.data.get('correct')
    rating = request.data.get('rating')
    if known:
        # 「我已经会了」不看证据，直接归档。
        rating = 'easy'
    elif mode == 'cloze':
        # 填空有客观证据：评分由服务器按「错了几次 / 有没有看答案」推导，
        # 客户端传什么 rating 都不作数（否则偷看之后重试就能洗白）。
        if correct is None:
            return fail('填空模式需要提交 correct')
        rating = derive_cloze_rating(attempts, revealed, bool(correct))
    elif rating not in RATINGS:
        return fail('rating 只能是 again / hard / good / easy')
    if known and practice:
        return fail('练习模式不能标记为已掌握')
    token = (request.data.get('client_token') or '').strip()[:64]
    today = timezone.localdate()

    # A retried request (timeout, flaky network) must not schedule twice.
    if token:
        existing = AnswerLog.objects.filter(user=request.user, client_token=token).first()
        if existing is not None:
            if existing.word_id != word.id:
                return fail('这个请求标识已经用于另一个单词')
            return Response(_duplicate_answer_payload(existing))

    try:
        with transaction.atomic():
            if practice:
                progress = UserWordProgress.objects.filter(user=request.user, word=word).first()
                if progress is None:
                    return fail('这个词还没有学过，不能练习')
                log = AnswerLog.objects.create(
                    user=request.user, word=word, dictionary=word.dictionary, rating=rating,
                    is_practice=True, interval_before=progress.interval_days,
                    interval_after=progress.interval_days, client_token=token,
                    mode=mode, attempts=attempts, revealed=revealed,
                )
                payload = ProgressSerializer(progress).data
                payload['practice'] = True
                payload['next_review_label'] = '仅练习，不改间隔'
                payload['preview'] = preview_intervals(progress)
                payload['answer_log_id'] = log.id
                return Response(payload)

            progress, created = UserWordProgress.objects.select_for_update().get_or_create(user=request.user, word=word)
            snapshot = _progress_snapshot(progress, created)
            new_today_before = UserWordProgress.objects.filter(
                user=request.user, word__dictionary=word.dictionary, first_learned_at__date=today,
            ).count()
            is_extra = bool(created and new_today_before >= NEW_WORD_LIMIT)
            interval_before = progress.interval_days
            if known:
                now = timezone.now()
                progress.interval_days = 365
                progress.review_count += 1
                progress.streak = max(progress.streak, 1)
                progress.last_review_at = now
                progress.next_review_at = now + timedelta(days=365)
                if progress.first_learned_at is None:
                    progress.first_learned_at = now
                # 标「已会」等于直接归档：不再进每日复习队列。
                progress.status = status_for(progress)
            else:
                schedule(progress, rating)
            progress.save(update_fields=[
                'status', 'review_count', 'wrong_count', 'streak', 'ease',
                'next_review_at', 'last_review_at', 'first_learned_at', 'interval_days',
            ])
            log = AnswerLog.objects.create(
                user=request.user, word=word, dictionary=word.dictionary, rating=rating,
                is_new=created, is_extra=is_extra, is_skip=known, interval_before=interval_before,
                interval_after=progress.interval_days, state_before=snapshot, client_token=token,
                mode=mode, attempts=attempts, revealed=revealed,
            )
    except IntegrityError:
        # Two concurrent retries of the same token: the loser replays the winner.
        existing = AnswerLog.objects.filter(user=request.user, client_token=token).first() if token else None
        if existing is None:
            raise
        return Response(_duplicate_answer_payload(existing))

    payload = ProgressSerializer(progress).data
    payload['rating'] = rating
    payload['next_review_label'] = '已移出复习' if known else describe_interval(progress.interval_days, rating)
    payload['preview'] = preview_intervals(progress)
    payload['is_new'] = created
    payload['is_extra'] = is_extra
    payload['is_skip'] = known
    payload['answer_log_id'] = log.id
    return Response(payload)


@api_view(['POST'])
def undo_answer(request, log_id):
    """Undo the latest, recent, non-practice answer of the current user."""
    error = require_authentication(request)
    if error:
        return error
    log = AnswerLog.objects.filter(id=log_id, user=request.user).select_related('word').first()
    if log is None:
        return fail('找不到这条答题记录', status.HTTP_404_NOT_FOUND)
    if log.is_practice:
        return fail('练习记录不会改变间隔，不需要撤销')
    if log.undone_at is not None:
        return fail('这条作答已经撤销过了')
    latest = (
        AnswerLog.objects.filter(user=request.user, undone_at__isnull=True)
        .order_by('-created_at', '-id').only('id').first()
    )
    if latest is None or latest.id != log.id:
        return fail('只能撤销最近一次作答')
    if timezone.now() - log.created_at > UNDO_WINDOW:
        return fail(f'超过 {UNDO_WINDOW_MINUTES} 分钟，已经不能撤销了')
    snapshot = log.state_before or {}
    if not snapshot:
        return fail('这条记录太旧，无法撤销')

    with transaction.atomic():
        progress = UserWordProgress.objects.select_for_update().filter(user=request.user, word=log.word).first()
        deleted = False
        if snapshot.get('created'):
            if progress is not None:
                progress.delete()
                deleted = True
        elif progress is None:
            return fail('这条作答对应的学习进度已经不存在，无法撤销')
        else:
            next_review = parse_datetime(snapshot.get('next_review_at') or '')
            first_learned = parse_datetime(snapshot.get('first_learned_at') or '')
            progress.status = snapshot.get('status', progress.status)
            progress.review_count = snapshot.get('review_count', progress.review_count)
            progress.wrong_count = snapshot.get('wrong_count', progress.wrong_count)
            progress.streak = snapshot.get('streak', progress.streak)
            progress.ease = snapshot.get('ease', progress.ease)
            progress.interval_days = snapshot.get('interval_days', progress.interval_days)
            progress.next_review_at = next_review or timezone.now()
            progress.last_review_at = None if snapshot.get('created') else progress.last_review_at
            progress.first_learned_at = first_learned
            progress.save(update_fields=[
                'status', 'review_count', 'wrong_count', 'streak', 'ease',
                'next_review_at', 'last_review_at', 'first_learned_at', 'interval_days',
            ])
        # Clearing the token lets the learner submit the answer again with the
        # same client key instead of tripping the unique constraint.
        log.undone_at = timezone.now()
        log.client_token = ''
        log.save(update_fields=['undone_at', 'client_token'])

    return Response({
        'detail': '已撤销这一题',
        'word_id': log.word_id,
        'deleted_progress': deleted,
        'progress': ProgressSerializer(progress).data if (progress and not deleted) else None,
    })


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
        progress.exclude(status='retired').filter(next_review_at__gt=now).order_by('next_review_at')
        .values_list('next_review_at', flat=True).first()
    )
    new_learned_today = progress.filter(first_learned_at__date=today).count()
    due_now = progress.filter(_due_q(now)).count()
    # 和学习页保持同一口径：复习积压时额度会被削减。
    daily_limit = adaptive_new_limit(due_now)
    active_logs = AnswerLog.objects.filter(user=request.user, undone_at__isnull=True)
    extra_used_today = active_logs.filter(
        is_new=True, is_extra=True, created_at__date=today,
    ).count()
    today_completed = active_logs.filter(created_at__date=today, is_practice=False).count()
    return Response({
        'total_words': total,
        'learned_words': learned,
        'mastered_words': progress.filter(MASTERED_Q).count(),
        'retired_words': progress.filter(status='retired').count(),
        'due_reviews': due_now,
        'today_completed': today_completed,
        'today_new': new_learned_today,
        'wrong_words': progress.filter(wrong_count__gt=0).count(),
        'new_limit': daily_limit,
        'new_limit_base': NEW_WORD_LIMIT,
        'new_limit_note': _adaptive_note(daily_limit, due_now),
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
    ).exclude(status='retired').select_related('word')
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
def wrong_review(request):
    """Words the learner has answered wrong at least once (practice queue)."""
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
        user=request.user, word__dictionary=dictionary, wrong_count__gt=0,
    ).select_related('word')
    total = queryset.count()
    if request.query_params.get('order') == 'recent':
        queryset = queryset.order_by('-last_review_at', '-id')
    else:
        queryset = queryset.order_by('-wrong_count', '-last_review_at', '-id')
    limit = _clamp_int(request.query_params.get('limit'), 1, WRONG_WORDS_LIMIT, 20)
    items = list(queryset[:limit])
    preview_map = {item.word_id: _preview_for(item) for item in items}
    return Response({
        'dictionary_id': dictionary.id,
        'words': ProgressSerializer(items, many=True, context={'preview_map': preview_map}).data,
        'total': total,
        'limit': limit,
    })


@api_view(['GET'])
def profile_summary(request):
    error = require_authentication(request)
    if error:
        return error
    days = _clamp_int(request.query_params.get('days'), 7, 371, 371)
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    logs = AnswerLog.objects.filter(user=request.user, undone_at__isnull=True)
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
        mastered=Count('id', filter=MASTERED_Q),
        due=Count('id', filter=_due_q(now)),
        wrong=Count('id', filter=Q(wrong_count__gt=0)),
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
            'wrong': row['wrong'],
        })
    dictionaries.sort(key=lambda item: item['name'])

    extra_used_today = logs.filter(is_extra=True, created_at__date=today).count()
    # 离掌握最近的那个词：间隔最长的未掌握词，告诉用户还差几次。
    candidate = (
        progress.exclude(status__in=MASTERED_STATUSES)
        .select_related('word')
        .order_by('-interval_days', '-streak', 'id')
        .first()
    )
    closest = None
    if candidate is not None:
        closest = {
            'word_id': candidate.word_id,
            'spelling': candidate.word.spelling,
            'dictionary_id': candidate.word.dictionary_id,
            'interval_days': candidate.interval_days,
            'streak': candidate.streak,
            'steps': steps_to_mastered(candidate),
        }
    return Response({
        'days': days,
        'today': daily[-1],
        'streak': streak,
        'totals': {
            'answers': logs.count(),
            'active_days': len(active_days),
            'learned': progress.count(),
            'mastered': progress.filter(MASTERED_Q).count(),
            'due': progress.filter(_due_q(now)).count(),
        },
        'daily': daily,
        'dictionaries': dictionaries,
        'extra': {'used_today': extra_used_today, 'limit': EXTRA_NEW_LIMIT},
        'closest_to_mastered': closest,
    })


# ---------------------------------------------------------------------------
# Insights: retention curve, progress series, rating calibration
# ---------------------------------------------------------------------------

# 间隔分档：横轴是「上次见面到这次回忆隔了多久」，纵轴是还记得的比例。
RETENTION_BUCKETS = (
    (1, 1, '1 天'),
    (2, 3, '2–3 天'),
    (4, 7, '4–7 天'),
    (8, 14, '8–14 天'),
    (15, 30, '15–30 天'),
    (31, 60, '31–60 天'),
    (61, 10 ** 9, '60 天以上'),
)
# 一声「记住了」之后不足一小时又被问一次，属于同一轮的重新排队，不是回忆测试。
CALIBRATION_MIN_GAP = timedelta(hours=1)
RATING_LABELS = dict(AnswerLog.RATING_CHOICES)


@api_view(['GET'])
def profile_insights(request):
    error = require_authentication(request)
    if error:
        return error
    days = _clamp_int(request.query_params.get('days'), 7, 371, 180)
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    logs = AnswerLog.objects.filter(
        user=request.user, undone_at__isnull=True, is_practice=False, is_skip=False,
    )
    window = logs.filter(created_at__date__gte=start)

    # --- 保持率 -------------------------------------------------------------
    # interval_before == 0 是第一次见这个词，没有「回忆」可言，必须排除。
    recall_rows = window.filter(interval_before__gt=0).values('interval_before').annotate(
        attempts=Count('id'),
        kept=Count('id', filter=Q(rating__in=('good', 'easy'))),
    )
    retention = []
    for low, high, label in RETENTION_BUCKETS:
        attempts = 0
        kept = 0
        for row in recall_rows:
            if low <= row['interval_before'] <= high:
                attempts += row['attempts']
                kept += row['kept']
        retention.append({
            'label': label,
            'low': low,
            'high': None if high >= 10 ** 9 else high,
            'attempts': attempts,
            'kept': kept,
            'rate': round(kept / attempts, 4) if attempts else None,
        })

    # --- 累计进度 -----------------------------------------------------------
    progress = UserWordProgress.objects.filter(user=request.user)
    learned_before = progress.filter(
        first_learned_at__isnull=False, first_learned_at__date__lt=start,
    ).count()
    learned_rows = progress.filter(
        first_learned_at__isnull=False, first_learned_at__date__gte=start,
    ).annotate(day=TruncDate('first_learned_at')).values('day').annotate(n=Count('id'))
    learned_by_day = {row['day']: row['n'] for row in learned_rows}

    # “掌握”没有单独时间戳，用第一次把间隔推到 21 天以上的那条作答近似。
    mastered_by_day = {}
    mastered_before = 0
    mastered_rows = (
        logs.filter(interval_after__gte=MASTERED_INTERVAL_DAYS)
        .values('word_id').annotate(first=Min('created_at'))
    )
    for row in mastered_rows:
        day = timezone.localtime(row['first']).date()
        if day < start:
            mastered_before += 1
        else:
            mastered_by_day[day] = mastered_by_day.get(day, 0) + 1

    progress_series = []
    learned = learned_before
    mastered = mastered_before
    for offset in range(days):
        day = start + timedelta(days=offset)
        learned += learned_by_day.get(day, 0)
        mastered += mastered_by_day.get(day, 0)
        progress_series.append({
            'date': day.isoformat(),
            'learned': learned,
            'mastered': mastered,
        })

    # --- 评分校准 -----------------------------------------------------------
    # 只统计卡片模式（真正的自评）。填空的评分是服务器按证据推出来的，
    # 混进来会让「自评 vs 下次实际表现」这个标题不成立。
    rows = list(
        window.filter(mode='card').order_by('word_id', 'created_at', 'id')
        .values_list('word_id', 'rating', 'created_at', 'interval_before')
    )
    calib = {rating: {'samples': 0, 'forgotten': 0} for rating in RATINGS}
    for prev, nxt in zip(rows, rows[1:]):
        if prev[0] != nxt[0]:
            continue
        if nxt[3] <= 0:
            continue
        if nxt[2] - prev[2] < CALIBRATION_MIN_GAP:
            continue
        bucket = calib[prev[1]]
        bucket['samples'] += 1
        if nxt[1] in ('again', 'hard'):
            bucket['forgotten'] += 1

    calibration = [
        {
            'rating': rating,
            'label': RATING_LABELS[rating],
            'samples': calib[rating]['samples'],
            'forgotten': calib[rating]['forgotten'],
            'forgotten_rate': (
                round(calib[rating]['forgotten'] / calib[rating]['samples'], 4)
                if calib[rating]['samples'] else None
            ),
        }
        for rating in RATINGS
    ]

    return Response({
        'days': days,
        'start': start.isoformat(),
        'retention': retention,
        'progress': progress_series,
        'calibration': calibration,
        'sample': {
            'recall_answers': sum(row['attempts'] for row in recall_rows),
            'pairs': sum(item['samples'] for item in calibration),
        },
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
