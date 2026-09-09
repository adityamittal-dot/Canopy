"""Shared per-IP rate limiting, used by both the analyze endpoint
(explorer/views.py) and the AI chat callback (explorer/ai_chat.py).

Uses Django's default cache (LocMemCache - process-local, no separate
service to run), so this is only correctly enforced with a single gunicorn
worker/replica, which is the deployed default (no --workers or
WEB_CONCURRENCY set). Scaling to multiple workers or replicas would split
traffic across processes that don't share the counter, silently multiplying
the effective limit - move to a shared cache (e.g. Redis) if that becomes
real.
"""

from django.core.cache import cache


def client_ip(request) -> str:
  # Render/Railway (and most PaaS hosts) put the app behind a proxy, so the
  # real client address arrives via X-Forwarded-For rather than REMOTE_ADDR.
  forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
  if forwarded:
    return forwarded.split(',')[0].strip()
  return request.META.get('REMOTE_ADDR', 'unknown')


def is_rate_limited(request, key_prefix: str, max_requests: int, window_seconds: int) -> bool:
  key = f'{key_prefix}:{client_ip(request)}'
  count = cache.get(key, 0)
  if count >= max_requests:
    return True
  cache.set(key, count + 1, timeout=window_seconds)
  return False
