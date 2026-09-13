from django.conf import settings
from django.db import models


class GitHubAccount(models.Model):
    """Links a Django User to the GitHub identity they signed in with -
    id/username/avatar only. No access token: see explorer/github_oauth.py
    for why signing in never needs or stores one."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='github_account')
    github_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=255)
    avatar_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.username


class Repo(models.Model):
    url = models.URLField(unique=True)
    name = models.CharField(unique=True, max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name or self.url


class CommitAnalysis(models.Model):
    repo = models.ForeignKey(Repo, on_delete=models.CASCADE, related_name='analysis')
    commit_hash = models.CharField(max_length=40)
    graph = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('repo', 'commit_hash')

    def __str__(self):
        return f'{self.repo} @ {self.commit_hash[:7]}'
