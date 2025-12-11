# core/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers
from .views import (
    DossierViewSet,
    ArchitectureDocViewSet,
    RiskRegisterViewSet,
    RiskItemViewSet,
    IaCheckViewSet,
    IaCrossCheckViewSet,
    QuestionnaireTemplateViewSet,
    QuestionViewSet,
    QuestionnaireAnswerViewSet,
    AuditLogViewSet,
    home_dashboard,
    LoginView
)

# ============================================================================
# Main Router for Top-Level Resources
# ============================================================================
router = DefaultRouter()

# Register main ViewSets
router.register(r'dossiers', DossierViewSet, basename='dossier')
router.register(r'questionnaires', QuestionnaireTemplateViewSet, basename='questionnaire')

# Nested routes under dossiers/{dossier_id}/
dossiers_router = routers.NestedDefaultRouter(router, 'dossiers', lookup='dossier')
dossiers_router.register(r'ia1', IaCheckViewSet, basename='ia1-check')
dossiers_router.register(r'ia2', IaCrossCheckViewSet, basename='ia2-check')
dossiers_router.register(r'documents', ArchitectureDocViewSet, basename='documents')
dossiers_router.register(r'risk-register', RiskRegisterViewSet, basename='risk-register')
dossiers_router.register(r'answers', QuestionnaireAnswerViewSet, basename='answers')
dossiers_router.register(r'audit-log', AuditLogViewSet, basename='audit-log')

# Nested routes under questionnaires/{questionnaire_id}/
questionnaires_router = routers.NestedDefaultRouter(router, 'questionnaires', lookup='questionnaire')
questionnaires_router.register(r'questions', QuestionViewSet, basename='questionnaire-questions')

# ============================================================================
# URL Patterns
# ============================================================================
urlpatterns = [
    # ========== API ROUTES ==========
    # Main API router (all top-level endpoints at /api/)
    path('api/', include(router.urls)),
    path('api/', include(dossiers_router.urls)),
    path('api/', include(questionnaires_router.urls)),

    # ========== REST FRAMEWORK AUTHENTICATION ==========
    # This enables the login/logout button in the Browsable API
    path('api-auth/', include('rest_framework.urls')),
    
    # ========== QUESTIONNAIRE ENDPOINTS ==========
    # Get available templates for dropdown
    path('api/questionnaires/available/', 
         QuestionnaireTemplateViewSet.as_view({'get': 'available'}), 
         name='questionnaires-available'),
    
    # Get template with all questions
    path('api/questionnaires/<int:pk>/with_questions/', 
         QuestionnaireTemplateViewSet.as_view({'get': 'with_questions'}), 
         name='questionnaire-with-questions'),
    
    # ========== DOSSIER ACTION ENDPOINTS ==========
    # Dossier submit and change_status actions
    path('api/dossiers/<int:pk>/submit/', 
         DossierViewSet.as_view({'post': 'submit'}), 
         name='dossier-submit'),
    path('api/dossiers/<int:pk>/change_status/', 
         DossierViewSet.as_view({'get': 'change_status', 'post': 'change_status'}), 
         name='dossier-change-status'),
    path('api/dossiers/<int:pk>/full/', 
         DossierViewSet.as_view({'get': 'full'}), 
         name='dossier-full'),
    
    # ========== DOCUMENT ENDPOINTS ==========
    # Document confirm and download actions
    path('api/dossiers/<int:dossier_id>/documents/<int:pk>/confirm/', 
         ArchitectureDocViewSet.as_view({'post': 'confirm'}), 
         name='dossier-documents-confirm'),
    path('api/dossiers/<int:dossier_id>/documents/<int:pk>/download/', 
         ArchitectureDocViewSet.as_view({'get': 'download'}), 
         name='dossier-documents-download'),
    path('api/dossiers/<int:dossier_id>/documents/<str:filename>/', 
         ArchitectureDocViewSet.as_view({'get': 'download_by_filename'}), 
         name='dossier-documents-download-by-filename'),
    
    # NEW: Submit documents endpoint
    path('api/dossiers/<int:dossier_id>/documents/submit_documents/', 
         ArchitectureDocViewSet.as_view({'post': 'submit_documents'}), 
         name='dossier-documents-submit'),

    # ========== RISK REGISTER ENDPOINTS ==========
    # Risk register submit action
    path('api/dossiers/<int:dossier_id>/risk-register/<int:pk>/submit/', 
         RiskRegisterViewSet.as_view({'post': 'submit'}), 
         name='dossier-risk-register-submit'),
    
    # ========== RISK ITEM ENDPOINTS ==========
    # Risk item actions: contest, contested (SO manages), delegation_action
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/<int:pk>/contest/', 
         RiskItemViewSet.as_view({'post': 'contest'}), 
         name='risk-item-contest'),
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/contested/', 
         RiskItemViewSet.as_view({'get': 'contested', 'post': 'contested'}), 
         name='risk-item-contested'),
    path('api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/delegation-action/', 
         RiskItemViewSet.as_view({'post': 'delegation_action'}), 
         name='risk-item-delegation-action'),
    
    # ========== ANSWER ENDPOINTS ==========
    # Bulk answer submission
    path('api/dossiers/<int:dossier_id>/answers/bulk_answer/', 
         QuestionnaireAnswerViewSet.as_view({'post': 'bulk_answer'}), 
         name='dossier-answers-bulk'),
    
    # ========== AUTHENTICATION ==========
    path('api/auth/', include('djoser.urls')),
    path('api/auth/', include('djoser.urls.jwt')),
    
    # ========== HOME DASHBOARD ==========
    path('', home_dashboard, name='home'),
    path('auth/login/', LoginView.as_view(), name='login'),
]

# Risk Items nested under Risk Register
urlpatterns += [
    # Risk Items endpoints (nested under risk-register)
    path(
        'api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/',
        RiskItemViewSet.as_view({'get': 'list', 'post': 'create'}),
        name='risk-items-list'
    ),
    path(
        'api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/<int:pk>/',
        RiskItemViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'}),
        name='risk-items-detail'
    ),
    path(
        'api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/<int:pk>/contest/',
        RiskItemViewSet.as_view({'post': 'contest'}),
        name='risk-item-contest'
    ),
    path(
        'api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/contested/',
        RiskItemViewSet.as_view({'get': 'list'}),
        name='risk-item-contested'
    ),
    path(
        'api/dossiers/<int:dossier_id>/risk-register/<int:register_id>/items/delegation-action/',
        RiskItemViewSet.as_view({'post': 'delegation_action'}),
        name='risk-item-delegation-action'
    ),
]