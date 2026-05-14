from django.urls import path
from db_display import views

urlpatterns = [
    path('', views.home, name='home'),
    path('telegram/', views.telegram_view, name='telegram'),
    path('telegram/stats-refresh/', views.telegram_stats_refresh, name='telegram_stats_refresh'),
    path('telegram/export-create/', views.telegram_export_create, name='telegram_export_create'),
    path('darknet/', views.darknet_view, name='darknet'),
    path('darknet/stats-refresh/', views.darknet_stats_refresh, name='darknet_stats_refresh'),
    path('darknet/export-create/', views.darknet_export_create, name='darknet_export_create'),
    path('setparams/', views.setparams_view, name='setparams'),
    path('parameter_config/', views.parameter_config_view, name='parameter_config'),
    path('telegram/export-excel/', views.telegram_export_excel, name='telegram_export_excel'),
    path('darknet/export-excel/', views.darknet_export_excel, name='darknet_export_excel'),
    path('export-task/<int:task_id>/status/', views.export_task_status, name='export_task_status'),
    path('export-task/<int:task_id>/download/', views.export_task_download, name='export_task_download'),
]
