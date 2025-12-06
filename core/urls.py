# core/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DossierViewSet, ArchitectureDocViewSet, RiskItemViewSet,
    RiskRegisterViewSet, IaCheckViewSet, IaCrossCheckViewSet,
    AuditLogViewSet, home_dashboard
)

# ============================================================================
# Main Router for Top-Level Resources
# ============================================================================
router = DefaultRouter()

# Register main ViewSets
router.register(r'dossiers', DossierViewSet, basename='dossier')
router.register(r'documents', ArchitectureDocViewSet, basename='document')
router.register(r'risk-items', RiskItemViewSet, basename='risk-item')
router.register(r'risk-registers', RiskRegisterViewSet, basename='risk-register')
router.register(r'ia-checks', IaCheckViewSet, basename='ia-check')
router.register(r'ia-cross-checks', IaCrossCheckViewSet, basename='ia-cross-check')
router.register(r'audit-logs', AuditLogViewSet, basename='audit-log')

# ============================================================================
# URL Patterns
# ============================================================================
urlpatterns = [
    # ========== API ROUTES ==========
    
    # Main API router (all top-level endpoints)
    path('api/', include(router.urls)),

    # ========== REST FRAMEWORK AUTHENTICATION ==========
    # This enables the login/logout button in the Browsable API
    path('api-auth/', include('rest_framework.urls')),
    
    # ========== DOSSIER NESTED ROUTES ==========
    # These provide convenient nested access to dossier sub-resources
    
    # GET  /api/dossiers/<id>/full/
    # POST /api/dossiers/<id>/submit/
    # (Already handled by DossierViewSet custom actions)
    
    # GET  /api/dossiers/<id>/documents/
    # POST /api/dossiers/<id>/documents/
    # (Filtered via ArchitectureDocViewSet.get_queryset)
    
    # GET  /api/dossiers/<id>/risk-items/
    # POST /api/dossiers/<id>/risk-items/
    # (Filtered via RiskItemViewSet.get_queryset)
    
    # GET  /api/dossiers/<id>/risk-register/
    # (Filtered via RiskRegisterViewSet.get_queryset)
    
    # GET  /api/dossiers/<id>/ia1/
    # (Filtered via IaCheckViewSet.get_queryset)
    
    # GET  /api/dossiers/<id>/ia2/
    # (Filtered via IaCrossCheckViewSet.get_queryset)
    
    # GET  /api/dossiers/<id>/audit-log/
    # (Filtered via AuditLogViewSet.get_queryset)
    
    # ========== AUTHENTICATION ==========
    path('api/auth/', include('djoser.urls')),
    path('api/auth/', include('djoser.urls.jwt')),
    
    # ========== HOME DASHBOARD ==========
    path('', home_dashboard, name='home'),
]