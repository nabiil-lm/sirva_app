# core/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DossierViewSet, ArchitectureDocViewSet, RiskItemViewSet,
    RiskRegisterViewSet, IaCheckViewSet, IaCrossCheckViewSet,
    AuditLogViewSet, QuestionnaireTemplateViewSet, QuestionViewSet,
    QuestionnaireAnswerViewSet, home_dashboard
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
router.register(r'questionnaires', QuestionnaireTemplateViewSet, basename='questionnaire')

# ============================================================================
# URL Patterns
# ============================================================================
urlpatterns = [
    # ========== API ROUTES ==========
    # Main API router (all top-level endpoints at /api/)
    path('api/', include(router.urls)),

    # ========== REST FRAMEWORK AUTHENTICATION ==========
    # This enables the login/logout button in the Browsable API
    path('api-auth/', include('rest_framework.urls')),
    
    # ========== NESTED DOSSIER ROUTES ==========
    # Nested documents: /api/dossiers/{dossier_id}/documents/
    path('api/dossiers/<int:dossier_id>/documents/', 
         ArchitectureDocViewSet.as_view({'get': 'list', 'post': 'create'}), 
         name='dossier-documents-list'),
    path('api/dossiers/<int:dossier_id>/documents/<int:pk>/', 
         ArchitectureDocViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), 
         name='dossier-documents-detail'),
    path('api/dossiers/<int:dossier_id>/documents/<int:pk>/confirm/', 
         ArchitectureDocViewSet.as_view({'post': 'confirm'}), 
         name='dossier-documents-confirm'),
    path('api/dossiers/<int:dossier_id>/documents/<int:pk>/download/', 
         ArchitectureDocViewSet.as_view({'get': 'download'}), 
         name='dossier-documents-download'),
    path('api/dossiers/<int:dossier_id>/documents/<str:filename>/', 
         ArchitectureDocViewSet.as_view({'get': 'download_by_filename'}), 
         name='dossier-documents-download-by-filename'),
    
    # Nested risk register: /api/dossiers/{dossier_id}/risk-register/
    path('api/dossiers/<int:dossier_id>/risk-register/', 
         RiskRegisterViewSet.as_view({'get': 'list', 'post': 'create'}), 
         name='dossier-risk-register-list'),
    path('api/dossiers/<int:dossier_id>/risk-register/<int:pk>/', 
         RiskRegisterViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), 
         name='dossier-risk-register-detail'),
    path('api/dossiers/<int:dossier_id>/risk-register/<int:pk>/submit/', 
         RiskRegisterViewSet.as_view({'post': 'submit'}), 
         name='dossier-risk-register-submit'),
    
    # NEW: Nested risk items under risk register
    # /api/dossiers/{dossier_id}/risk-register/{register_id}/items/
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/', 
         RiskItemViewSet.as_view({'get': 'list', 'post': 'create'}), 
         name='risk-register-items-list'),
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/<int:pk>/', 
         RiskItemViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), 
         name='risk-register-items-detail'),
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/<int:pk>/delegate/', 
         RiskItemViewSet.as_view({'post': 'delegate'}), 
         name='risk-register-items-delegate'),
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/<int:pk>/accept/', 
         RiskItemViewSet.as_view({'post': 'accept'}), 
         name='risk-register-items-accept'),
    
    # NEW: Delegation
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/<int:pk>/delegate/', 
         RiskItemViewSet.as_view({'post': 'delegate'}), 
         name='risk-register-items-delegate'),
    
    # NEW: Refuse delegation
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/<int:pk>/refuse/', 
         RiskItemViewSet.as_view({'post': 'refuse'}), 
         name='risk-register-items-refuse'),
    
    # NEW: Contestation
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/<int:pk>/contest/', 
         RiskItemViewSet.as_view({'post': 'contest'}), 
         name='risk-register-items-contest'),
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/<int:pk>/accept_contestation/', 
         RiskItemViewSet.as_view({'post': 'accept_contestation'}), 
         name='risk-register-items-accept-contestation'),
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/<int:pk>/reject_contestation/', 
         RiskItemViewSet.as_view({'post': 'reject_contestation'}), 
         name='risk-register-items-reject-contestation'),
    
    # NEW: Delegation recipient action endpoint
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/delegation-action/', 
         RiskItemViewSet.as_view({'post': 'delegation_action'}), 
         name='risk-register-items-delegation-action'),

    # NEW: SO manages contested risk items
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/contested/', 
         RiskItemViewSet.as_view({'get': 'contested', 'post': 'contested'}), 
         name='risk-register-items-contested'),

    # Nested IA checks: /api/dossiers/{dossier_id}/ia-checks/
    path('api/dossiers/<int:dossier_id>/ia-checks/', 
         IaCheckViewSet.as_view({'get': 'list'}), 
         name='dossier-ia-checks-list'),
    path('api/dossiers/<int:dossier_id>/ia-checks/<int:pk>/', 
         IaCheckViewSet.as_view({'get': 'retrieve'}), 
         name='dossier-ia-checks-detail'),
    
    # Nested IA cross-checks: /api/dossiers/{dossier_id}/ia-cross-checks/
    path('api/dossiers/<int:dossier_id>/ia-cross-checks/', 
         IaCrossCheckViewSet.as_view({'get': 'list'}), 
         name='dossier-ia-cross-checks-list'),
    path('api/dossiers/<int:dossier_id>/ia-cross-checks/<int:pk>/', 
         IaCrossCheckViewSet.as_view({'get': 'retrieve'}), 
         name='dossier-ia-cross-checks-detail'),
    
    # Nested audit logs: /api/dossiers/{dossier_id}/audit-logs/
    path('api/dossiers/<int:dossier_id>/audit-logs/', 
         AuditLogViewSet.as_view({'get': 'list'}), 
         name='dossier-audit-logs-list'),
    path('api/dossiers/<int:dossier_id>/audit-logs/<int:pk>/', 
         AuditLogViewSet.as_view({'get': 'retrieve'}), 
         name='dossier-audit-logs-detail'),
    path('api/dossiers/<int:dossier_id>/audit-logs/<int:pk>/entries/', 
         AuditLogViewSet.as_view({'get': 'entries'}), 
         name='dossier-audit-logs-entries'),
    
    # ========== QUESTIONNAIRE ENDPOINTS ==========
    # Get available templates for dropdown
    path('api/questionnaires/available/', 
         QuestionnaireTemplateViewSet.as_view({'get': 'available'}), 
         name='questionnaires-available'),
    
    # Get template with all questions
    path('api/questionnaires/<int:pk>/with_questions/', 
         QuestionnaireTemplateViewSet.as_view({'get': 'with_questions'}), 
         name='questionnaire-with-questions'),
    
    # Questions nested routes: /api/questionnaires/{id}/questions/
    path('api/questionnaires/<int:questionnaire_id>/questions/', 
         QuestionViewSet.as_view({'get': 'list', 'post': 'create'}), 
         name='questionnaire-questions-list'),
    path('api/questionnaires/<int:questionnaire_id>/questions/<int:pk>/', 
         QuestionViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), 
         name='questionnaire-questions-detail'),
    
    # ========== ANSWER ENDPOINTS ==========
    # Bulk answer submission
    path('api/dossiers/<int:dossier_id>/answers/bulk_answer/', 
         QuestionnaireAnswerViewSet.as_view({'post': 'bulk_answer'}), 
         name='dossier-answers-bulk'),
    
    # Individual answer management
    path('api/dossiers/<int:dossier_id>/answers/', 
         QuestionnaireAnswerViewSet.as_view({'get': 'list', 'post': 'create'}), 
         name='dossier-answers-list'),
    path('api/dossiers/<int:dossier_id>/answers/<int:pk>/', 
         QuestionnaireAnswerViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), 
         name='dossier-answers-detail'),
    
    # ========== AUTHENTICATION ==========
    path('api/auth/', include('djoser.urls')),
    path('api/auth/', include('djoser.urls.jwt')),
    
    # ========== HOME DASHBOARD ==========
    path('', home_dashboard, name='home'),
]