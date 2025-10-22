# core/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from .managers import CustomUserManager # 🚨 NOUVELLE IMPORTATION 🚨

# --- Énumérations (Enums) ---

class Role(models.TextChoices):
    AM = 'AM', _('Application Manager')
    SO = 'SO', _('Security Officer')
    ADMIN = 'ADMIN', _('Administrator')

class DossierStatus(models.TextChoices):
    EN_EDITION = 'EN_EDITION', _('En Édition')
    QUESTIONNAIRE_SOUMIS = 'QUESTIONNAIRE_SOUMIS', _('Questionnaire Soumis')
    IA1_INCOHERENT = 'IA1_INCOHERENT', _('IA1 Incohérent')
    IA1_COHERENT = 'IA1_COHERENT', _('IA1 Cohérent')
    ARCHI_UPLOAD_EN_COURS = 'ARCHI_UPLOAD_EN_COURS', _('Architecture Upload En Cours')
    IA2_INCOHERENT = 'IA2_INCOHERENT', _('IA2 Incohérent')
    IA2_COHERENT = 'IA2_COHERENT', _('IA2 Cohérent')
    RISQUES_EN_COURS = 'RISQUES_EN_COURS', _('Risques En Cours')
    PRET_VALIDATION = 'PRET_VALIDATION', _('Prêt pour Validation Finale')
    VALIDE = 'VALIDE', _('Validé')

# --- 1. Modèle Utilisateur Personnalisé (Role-Based Access Control) ---

class User(AbstractUser):
    # AbstractUser fournit déjà username, email, first_name, last_name, password...
    # Nous ajoutons le champ Role, clé pour le RBAC
    role = models.CharField(
        max_length=5,
        choices=Role.choices,
        default=Role.AM, # Par défaut, Application Manager
        verbose_name=_("Rôle de l'utilisateur")
    )
    # L'email est utilisé comme identifiant unique
    email = models.EmailField(_("Adresse e-mail"), unique=True)
    username = None # Supprime le champ username par défaut
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    # 🚨 LIAISON DU GESTIONNAIRE PERSONNALISÉ 🚨
    objects = CustomUserManager()

    def __str__(self):
        return self.email

# --- 2. Modèle Dossier ---

class Dossier(models.Model):
    title = models.CharField(max_length=255)
    
    status = models.CharField(
        max_length=30,
        choices=DossierStatus.choices,
        default=DossierStatus.EN_EDITION,
        verbose_name=_("Statut du Dossier")
    )

    # Relation : Un Dossier est géré par un AM (Application Manager)
    am = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='dossiers',
        verbose_name=_("Application Manager")
    )

    # Données du Questionnaire (Utilisation du champ JSONField de PostgreSQL)
    questionnaire_json = models.JSONField(default=dict) # structure des réponses + métadonnées
    questionnaire_model = models.JSONField(default=dict) # copie immuable du modèle utilisé

    # Concurrence Optimiste
    autosave_version = models.IntegerField(default=0)
    is_submitted = models.BooleanField(default=False)

    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.status})"