from django.contrib import admin

from .models import CommitAnalysis, GitHubAccount, Repo


@admin.register(GitHubAccount)
class GitHubAccountAdmin(admin.ModelAdmin):
    list_display = ('username', 'user', 'github_id', 'created_at')
    search_fields = ('username', 'user__username')


@admin.register(Repo)
class RepoAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'created_at')
    search_fields = ('name', 'url')


@admin.register(CommitAnalysis)
class CommitAnalysisAdmin(admin.ModelAdmin):
    list_display = ('repo', 'commit_hash', 'created_at')
    list_filter = ('repo',)
    search_fields = ('commit_hash',)
