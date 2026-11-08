from django.urls import path

from . import views

app_name = "schauto"

urlpatterns = [
    path("", views.index, name="index"),
    path("venues/", views.venues, name="venues"),
    path("venues/<int:pk>/update", views.VenueUpdateView.as_view(), name="venue_update"),
    path("venues/<int:pk>/delete", views.VenueDeleteView.as_view(), name="venue_delete"),
    path("orders/", views.orders, name="orders"),
    path("orders/import/", views.orders_import, name="orders_import"),
    path("mapping/", views.mapping, name="mapping"),
    path("mapping/person/", views.mapping_person, name="mapping_person"),
    path("mapping/place/", views.mapping_place, name="mapping_place"),
    path("plan/", views.plan, name="plan"),
    path("plan/<int:pk>/", views.plan_detail, name="plan_detail"),
    path("plan/<int:pk>/action/", views.plan_action, name="plan_action"),
    path("routes/", views.routes, name="routes"),
    path("routes/export/", views.routes_export, name="routes_export"),
    path("routes/import/", views.routes_import, name="routes_import"),
    path("routes/<int:pk>/update", views.RouteUpdateView.as_view(), name="route_update"),
    path("routes/<int:pk>/delete", views.RouteDeleteView.as_view(), name="route_delete"),
]
