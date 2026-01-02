from django.shortcuts import render

# core/views.py
from rest_framework import viewsets, permissions
from .models import Dossier, Role, DossierStatus
from .serializers import DossierSerializer
from .permissions import IsApplicationManager # Nous allons créer cette permission ensuite

class DossierViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour les opérations CRUD sur les Dossiers.
    """
    queryset = Dossier.objects.all().order_by('-updated_at')
    serializer_class = DossierSerializer
    
    # Par défaut, seul l'AM propriétaire du dossier peut le modifier ou le supprimer.
    permission_classes = [permissions.IsAuthenticated, IsApplicationManager] 
    
    def get_queryset(self):
        """
        Filtrer les dossiers pour n'afficher que ceux de l'utilisateur connecté (AM).
        """
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN:
            # L'Admin voit tous les dossiers
            return Dossier.objects.all().order_by('-updated_at')
        
        # Le SO et l'AM voient seulement leurs dossiers (AM est le propriétaire)
        return Dossier.objects.filter(am=user).order_by('-updated_at')

    def perform_create(self, serializer):
        """
        Lors de la création, l'AM du dossier est automatiquement l'utilisateur connecté.
        """
        # Utilise l'utilisateur connecté comme Application Manager (am) du dossier
        serializer.save(am=self.request.user, status=DossierStatus.EN_EDITION)

# Vue pour la page d'accueil/dashboard
def home_dashboard(request):
    # Ceci renverra un template HTML que nous créerons plus tard
    return render(request, 'core/dashboard.html')
# Create your views here.
