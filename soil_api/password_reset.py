"""Email OTP password-reset endpoints for the JJMAP Django application."""

import re
import secrets

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.conf import settings

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


OTP_TTL_SECONDS = 10 * 60
RESET_TOKEN_TTL_SECONDS = 10 * 60
SEND_LIMIT = 3
SEND_WINDOW_SECONDS = 15 * 60
MAX_OTP_ATTEMPTS = 5


def _normalize_email(value):
    return str(value or '').strip().lower()


def _generic_response():
    # Avoid exposing whether an email address belongs to a registered account.
    return Response(
        {'message': 'If an account exists for this email, a verification code has been sent.'},
        status=status.HTTP_200_OK,
    )


def _increment_cache_counter(key, timeout):
    """Increment a cache counter while also handling a missing key."""
    try:
        return cache.incr(key)
    except ValueError:
        cache.add(key, 0, timeout=timeout)
        try:
            return cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=timeout)
            return 1


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def send_password_reset_otp(request):
    email = _normalize_email(request.data.get('email'))

    if not email or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        return Response(
            {'error': 'Please provide a valid email address.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    send_count = _increment_cache_counter(
        f'password_reset_send_count:{email}', SEND_WINDOW_SECONDS
    )
    if send_count > SEND_LIMIT:
        return Response(
            {'error': 'Too many requests. Please try again in 15 minutes.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    users = User.objects.filter(email__iexact=email, is_active=True)
    # Require one unambiguous active account for this email.
    if users.count() != 1:
        return _generic_response()

    user = users.first()
    otp = f'{secrets.randbelow(1_000_000):06d}'
    cache.set(f'password_reset_otp:{email}', otp, timeout=OTP_TTL_SECONDS)
    cache.set(f'password_reset_attempts:{email}', 0, timeout=OTP_TTL_SECONDS)
    cache.delete(f'password_reset_token:{email}')

    try:
        send_mail(
            subject='JJMAP - Password Reset Verification Code',
            message=(
                f'Hello {user.first_name or user.username},\n\n'
                f'Your JJMAP password reset verification code is: {otp}\n\n'
                'This code expires in 10 minutes. If you did not request a password '
                'reset, you can safely ignore this email.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception:
        cache.delete(f'password_reset_otp:{email}')
        return Response(
            {'error': 'We could not send the email right now. Please try again later.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return _generic_response()


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def verify_password_reset_otp(request):
    email = _normalize_email(request.data.get('email'))
    otp = str(request.data.get('otp') or '').strip()

    if not email or not re.fullmatch(r'\d{6}', otp):
        return Response(
            {'error': 'A valid email address and 6-digit OTP are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    attempts_key = f'password_reset_attempts:{email}'
    attempts = _increment_cache_counter(attempts_key, OTP_TTL_SECONDS)
    if attempts > MAX_OTP_ATTEMPTS:
        cache.delete(f'password_reset_otp:{email}')
        return Response(
            {'error': 'Too many incorrect attempts. Request a new verification code.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    saved_otp = cache.get(f'password_reset_otp:{email}')
    if not saved_otp or not secrets.compare_digest(str(saved_otp), otp):
        return Response(
            {'error': 'Invalid or expired verification code.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if not user:
        return Response(
            {'error': 'Invalid or expired verification code.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    reset_token = secrets.token_urlsafe(32)
    cache.set(
        f'password_reset_token:{email}',
        reset_token,
        timeout=RESET_TOKEN_TTL_SECONDS,
    )
    # OTP is single-use after successful verification.
    cache.delete(f'password_reset_otp:{email}')
    cache.delete(attempts_key)

    return Response(
        {
            'message': 'Email verified. You may now create a new password.',
            'reset_token': reset_token,
        },
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def confirm_password_reset(request):
    email = _normalize_email(request.data.get('email'))
    reset_token = str(request.data.get('reset_token') or '')
    new_password = str(request.data.get('new_password') or '')

    if not email or not reset_token or not new_password:
        return Response(
            {'error': 'Email, reset token, and new password are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    token_key = f'password_reset_token:{email}'
    saved_token = cache.get(token_key)
    if not saved_token or not secrets.compare_digest(str(saved_token), reset_token):
        return Response(
            {'error': 'Your password reset session is invalid or expired. Please start again.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if not user:
        return Response(
            {'error': 'Your password reset session is invalid or expired. Please start again.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        return Response(
            {'error': ' '.join(exc.messages)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user.set_password(new_password)
    user.save(update_fields=['password'])

    # Remove existing DRF tokens; the user must sign in again with the new password.
    try:
        from rest_framework.authtoken.models import Token
        Token.objects.filter(user=user).delete()
    except Exception:
        # Password has been updated even if token cleanup is unavailable.
        pass

    cache.delete(token_key)
    cache.delete(f'password_reset_otp:{email}')
    cache.delete(f'password_reset_attempts:{email}')
    cache.delete(f'password_reset_send_count:{email}')

    return Response(
        {'message': 'Your password has been changed successfully. Please log in again.'},
        status=status.HTTP_200_OK,
    )
