# core/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DossierViewSet, home_dashboard # 🚨 NOUVELLE IMPORTATION 🚨


# Nous allons créer ces vues dans la prochaine sous-étape
# from .views import DossierViewSet 

router = DefaultRouter()
router.register(r'dossiers', DossierViewSet) # Sera activé plus tard

urlpatterns = [
    # Route pour les ViewSets (ex: /api/dossiers, /api/dossiers/1)
    # path('', include(router.urls)),

    # 🚨 NOUVELLE ROUTE : Le chemin vide est géré par la fonction home_dashboard 🚨
    path('', home_dashboard, name='home'), 
    
    # Route pour les ViewSets (ex: /api/dossiers)
    path('', include(router.urls)), # Le router gère les chemins comme 'dossiers' 
    
    # Route pour l'authentification (login/logout, etc.)
    path('auth/', include('djoser.urls')), # Nous utiliserons Djoser pour l'Auth
    path('auth/', include('djoser.urls.jwt')), # Configuration JWT
    
    path('auth/drf/', include('rest_framework.urls', namespace='rest_framework')),
]