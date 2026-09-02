from django.db import models


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
