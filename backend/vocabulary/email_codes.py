"""Email verification codes: generation, throttling, delivery, redemption.

Kept out of `services.py` (scheduling / import) because nothing here takes part
in the study loop. Callers only deal with three exceptions, all mapped to
Chinese `detail` responses in `views.py`.
"""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from .models import EmailVerification

CODE_DIGITS = 6
PURPOSES = (
    EmailVerification.PURPOSE_LOGIN,
    EmailVerification.PURPOSE_RESET,
    EmailVerification.PURPOSE_BIND,
)
# Rows older than this are noise; purged opportunistically when a code is issued.
CODE_RETENTION = timedelta(days=3)

SUBJECTS = {
    EmailVerification.PURPOSE_LOGIN: '登录验证码',
    EmailVerification.PURPOSE_RESET: '重置密码验证码',
    EmailVerification.PURPOSE_BIND: '绑定邮箱验证码',
}


class EmailCodeError(Exception):
    """The submitted code is wrong, expired or already used."""


class EmailRateLimitError(Exception):
    """Too many codes requested for this address or IP."""

    def __init__(self, message, retry_after=60):
        super().__init__(message)
        self.retry_after = retry_after


class EmailDeliveryError(Exception):
    """The mail server refused the message."""


def normalize_email(raw):
    """Trim + lowercase, reject obviously malformed input with a Chinese error."""
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    email = (raw or '').strip().lower()
    if not email:
        raise EmailCodeError('请输入邮箱地址')
    if len(email) > 254:
        raise EmailCodeError('邮箱地址太长了')
    try:
        validate_email(email)
    except ValidationError as exc:
        raise EmailCodeError('邮箱格式不正确') from exc
    return email


def hash_code(code, salt):
    return hashlib.sha256(f'{salt}:{code}'.encode('utf-8')).hexdigest()


def generate_code():
    return f'{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}'


def purge_old_codes(now=None):
    cutoff = (now or timezone.now()) - CODE_RETENTION
    EmailVerification.objects.filter(created_at__lt=cutoff).delete()


def _check_throttle(email, purpose, ip, now):
    cooldown = settings.EMAIL_CODE_COOLDOWN_SECONDS
    if cooldown > 0:
        recent = EmailVerification.objects.filter(
            email=email, purpose=purpose, created_at__gt=now - timedelta(seconds=cooldown),
        ).order_by('-created_at').first()
        if recent is not None:
            retry_after = int((recent.created_at + timedelta(seconds=cooldown) - now).total_seconds()) + 1
            raise EmailRateLimitError(
                f'请求太频繁了，请 {max(retry_after, 1)} 秒后再试', retry_after=max(retry_after, 1),
            )

    hourly = now - timedelta(hours=1)
    email_limit = settings.EMAIL_CODE_EMAIL_HOURLY_LIMIT
    if email_limit > 0 and EmailVerification.objects.filter(
        email=email, created_at__gt=hourly,
    ).count() >= email_limit:
        raise EmailRateLimitError('这个邮箱今天收的验证码太多了，请过一小时再试', retry_after=3600)

    ip_limit = settings.EMAIL_CODE_IP_HOURLY_LIMIT
    if ip and ip_limit > 0 and EmailVerification.objects.filter(
        ip=ip, created_at__gt=hourly,
    ).count() >= ip_limit:
        raise EmailRateLimitError('这台设备请求得太频繁了，请过一小时再试', retry_after=3600)


def issue_code(*, email, purpose, ip=''):
    """Create a code row and return `(verification, plain_code)`.

    Any older unused code for the same address and purpose is spent first, so
    "the last mail you received" is always the only valid one.
    """
    if purpose not in PURPOSES:
        raise EmailCodeError('不支持的验证码类型')
    now = timezone.now()
    purge_old_codes(now)
    _check_throttle(email, purpose, ip, now)
    code = generate_code()
    salt = secrets.token_hex(8)
    with transaction.atomic():
        EmailVerification.objects.filter(
            email=email, purpose=purpose, consumed_at__isnull=True,
        ).update(consumed_at=now)
        verification = EmailVerification.objects.create(
            email=email,
            purpose=purpose,
            code_hash=hash_code(code, salt),
            salt=salt,
            expires_at=now + timedelta(minutes=settings.EMAIL_CODE_TTL_MINUTES),
            ip=ip,
        )
    return verification, code


def send_code_email(*, email, code, purpose):
    minutes = settings.EMAIL_CODE_TTL_MINUTES
    label = SUBJECTS.get(purpose, '验证码')
    subject = f'【英语单词记忆】{label}：{code}'
    text = (
        f'你的{label}是：{code}\n\n'
        f'{minutes} 分钟内有效，只能使用一次。\n'
        '如果不是你本人操作，请忽略这封邮件，你的账号不会有任何变化。'
    )
    html = (
        f'<p>你的{label}是：</p>'
        f'<p style="font-size:28px;font-weight:700;letter-spacing:6px">{code}</p>'
        f'<p>{minutes} 分钟内有效，只能使用一次。</p>'
        '<p style="color:#888">如果不是你本人操作，请忽略这封邮件，你的账号不会有任何变化。</p>'
    )
    message = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email],
    )
    message.attach_alternative(html, 'text/html')
    try:
        message.send(fail_silently=False)
    except Exception as exc:  # SMTP / network / auth failures all land here
        raise EmailDeliveryError('验证码邮件发送失败，请稍后再试') from exc


def verify_code(*, email, purpose, code):
    """Spend `code` for `(email, purpose)` or raise `EmailCodeError`."""
    code = (code or '').strip()
    if not code:
        raise EmailCodeError('请输入验证码')
    now = timezone.now()
    verification = EmailVerification.objects.filter(
        email=email, purpose=purpose, consumed_at__isnull=True,
    ).order_by('-created_at').first()
    if verification is None:
        raise EmailCodeError('验证码已失效，请重新获取')
    if verification.is_expired:
        verification.consumed_at = now
        verification.save(update_fields=['consumed_at'])
        raise EmailCodeError('验证码已过期，请重新获取')

    max_attempts = settings.EMAIL_CODE_MAX_ATTEMPTS
    if not secrets.compare_digest(verification.code_hash, hash_code(code, verification.salt)):
        # Count the miss; the code dies once the budget is gone so a six digit
        # space cannot be brute forced one request at a time.
        verification.attempts += 1
        fields = ['attempts']
        if max_attempts > 0 and verification.attempts >= max_attempts:
            verification.consumed_at = now
            fields.append('consumed_at')
        verification.save(update_fields=fields)
        if verification.consumed_at is not None:
            raise EmailCodeError('验证码错误次数太多，请重新获取')
        raise EmailCodeError('验证码不正确')

    verification.consumed_at = now
    verification.save(update_fields=['consumed_at'])
