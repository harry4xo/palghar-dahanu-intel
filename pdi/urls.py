from django.urls import path

from . import views

app_name = "pdi"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("projects/", views.project_list, name="project_list"),
    path("projects/<str:code>/", views.project_detail, name="project_detail"),
    path("map/", views.map_view, name="map"),
    path("api/projects.geojson", views.projects_geojson, name="projects_geojson"),
    path("markets/", views.markets, name="markets"),
    path("markets/<str:market>/", views.market_detail, name="market_detail"),
    path("organizations/", views.organization_list, name="organization_list"),
    path("organizations/<int:pk>/", views.organization_detail, name="organization_detail"),
    path("methodology/", views.methodology, name="methodology"),
    # Research desk (staff only)
    path("review/", views.review_queue, name="review_queue"),
    path("review/<str:kind>/<int:pk>/", views.review_action, name="review_action"),
    path("inbox/", views.inbox, name="inbox"),
    path("inbox/<int:pk>/ignore/", views.inbox_ignore, name="inbox_ignore"),
    path("inbox/<int:inbox_pk>/process/", views.fact_entry, name="inbox_process"),
    path("entry/", views.fact_entry, name="fact_entry"),
    path("research-log/new/", views.research_log_new, name="research_log_new"),
]
