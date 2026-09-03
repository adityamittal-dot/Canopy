from django.apps import AppConfig


class ExplorerConfig(AppConfig):
    name = 'explorer'
    
    def ready(self):
        from . import dash_apps 
