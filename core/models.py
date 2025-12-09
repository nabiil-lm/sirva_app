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

class QuestionType(models.TextChoices):
    """Types of questions in a questionnaire"""
    TRUE_FALSE = 'TRUE_FALSE', _('Vrai/Faux')
    MULTIPLE_CHOICE = 'MULTIPLE_CHOICE', _('Choix multiples')
    SINGLE_CHOICE = 'SINGLE_CHOICE', _('Choix unique')
    TEXT = 'TEXT', _('Texte libre')

class QuestionnaireStatus(models.TextChoices):
    """Status of questionnaire templates"""
    DRAFT = 'DRAFT', _('Brouillon')
    PUBLISHED = 'PUBLISHED', _('Publié')
    ARCHIVED = 'ARCHIVED', _('Archivé')

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

# --- 2. Modèles Questionnaire ---

class QuestionnaireTemplate(models.Model):
    """
    Global questionnaire template that admins can define.
    These templates are reusable across multiple dossiers.
    """
    name = models.CharField(
        max_length=255,
        verbose_name=_("Nom du questionnaire"),
        unique=True
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Description du questionnaire")
    )
    status = models.CharField(
        max_length=10,
        choices=QuestionnaireStatus.choices,
        default=QuestionnaireStatus.DRAFT,
        verbose_name=_("Statut")
    )
    created_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='questionnaires_created',
        verbose_name=_("Créé par")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.status})"
    
    class Meta:
        ordering = ['-updated_at']
        verbose_name = _("Modèle de questionnaire")
        verbose_name_plural = _("Modèles de questionnaire")
    
    @property
    def question_count(self):
        return self.questions.count()


class Question(models.Model):
    """
    Individual question in a questionnaire template.
    """
    template = models.ForeignKey(
        QuestionnaireTemplate,
        on_delete=models.CASCADE,
        related_name='questions',
        verbose_name=_("Modèle")
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Ordre d'affichage")
    )
    text = models.TextField(
        verbose_name=_("Texte de la question")
    )
    question_type = models.CharField(
        max_length=20,
        choices=QuestionType.choices,
        verbose_name=_("Type de question")
    )
    is_mandatory = models.BooleanField(
        default=True,
        verbose_name=_("Obligatoire")
    )
    
    # For MULTIPLE_CHOICE and SINGLE_CHOICE types
    choices_json = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Liste des options pour choix multiples/uniques. Format: ['option1', 'option2', ...]"),
        verbose_name=_("Options")
    )
    
    # Additional metadata
    help_text = models.TextField(
        blank=True,
        verbose_name=_("Texte d'aide")
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.template.name} - Q{self.order}: {self.text[:50]}"
    
    class Meta:
        ordering = ['template', 'order']
        verbose_name = _("Question")
        verbose_name_plural = _("Questions")
        unique_together = ('template', 'order')


# --- 3. Modèle Dossier ---

class Dossier(models.Model):
    title = models.CharField(max_length=255)
    
    # Status tracking
    status = models.CharField(
        max_length=50,
        choices=DossierStatus.choices,
        default=DossierStatus.EN_EDITION
    )
    is_submitted = models.BooleanField(default=False)
    
    # NEW: Track if architecture documents have been submitted
    architecture_docs_submitted = models.BooleanField(
        default=False,
        help_text="Set to True when AM submits all architecture documents. Prevents further uploads."
    )

    # Relation : Un Dossier est géré par un AM (Application Manager)
    am = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='dossiers',
        verbose_name=_("Application Manager")
    )

    # NEW: Relation - Dossier is assigned to a Security Officer
    responsible_so = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dossiers_assigned',
        limit_choices_to={'role': 'SO'},
        verbose_name=_("Responsible Security Officer"),
        help_text=_("The Security Officer responsible for this dossier")
    )

    # Relation: Dossier uses a QuestionnaireTemplate
    questionnaire_template = models.ForeignKey(
        'QuestionnaireTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dossiers',
        verbose_name=_("Modèle de questionnaire")
    )

    # Submission flag
    is_submitted = models.BooleanField(default=False)

    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.status})"


class QuestionnaireAnswer(models.Model):
    """
    Answers to questionnaire questions for a specific dossier.
    """
    dossier = models.ForeignKey(
        'Dossier',
        on_delete=models.CASCADE,
        related_name='questionnaire_answers',
        verbose_name=_("Dossier")
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='answers',
        verbose_name=_("Question")
    )
    
    # Answer value - stored as text to accommodate all question types
    answer_value = models.TextField(
        blank=True,
        verbose_name=_("Réponse")
    )
    
    # Metadata
    answered_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Date de réponse")
    )

    def __str__(self):
        return f"{self.dossier.title} - Q{self.question.order}"
    
    class Meta:
        ordering = ['dossier', 'question__order']
        verbose_name = _("Réponse au questionnaire")
        verbose_name_plural = _("Réponses au questionnaire")
        unique_together = ('dossier', 'question')

    
# core/models.py (extrait)
# ... après les Enums et le modèle Dossier ...

class IaStatus(models.TextChoices):
    PENDING = 'PENDING', _('En attente')
    SUCCESS = 'SUCCESS', _('Succès')
    FAILED = 'FAILED', _('Échec')

# --- Modèle Document d'Architecture ---
class ArchitectureDoc(models.Model):
    dossier = models.ForeignKey(
        'Dossier', 
        on_delete=models.CASCADE, 
        related_name='architecture_docs'
    )
    filename = models.CharField(max_length=255)
    
    # CHANGED: Renamed s3_key to local_filepath
    local_filepath = models.CharField(
        max_length=255,
        verbose_name=_("Chemin local du fichier")
    )
    
    # NEW: Added site_filepath for the download URL
    site_filepath = models.CharField(
        max_length=255,
        verbose_name=_("Chemin d'accès pour téléchargement"),
        help_text=_("URL relative pour télécharger le fichier, ex: /api/dossiers/1/documents/document.pdf")
    )
    
    rssi_confirmed = models.BooleanField(default=False)
    mime_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveIntegerField(default=0)  # bytes
    uploaded_at = models.DateTimeField(auto_now_add=True)
    version = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.filename} ({self.dossier.title})"
    
    class Meta:
        ordering = ['-uploaded_at']

# --- Modèles d'Analyse IA ---
class IaCheck(models.Model):
    # Partie 1: Cohérence Interne du Questionnaire
    dossier = models.OneToOneField(
        'Dossier', 
        on_delete=models.CASCADE, 
        related_name='ia1_result', 
        primary_key=True # L'ID du dossier sert de clé
    )
    status = models.CharField(max_length=10, choices=IaStatus.choices, default=IaStatus.PENDING)
    findings = models.JSONField(default=dict)
    secure_score = models.DecimalField(
        max_digits=4, 
        decimal_places=2, 
        null=True, 
        blank=True,
        verbose_name=_("Score de sécurité")
    )
    raw_response = models.TextField(blank=True, default='')  # ADD THIS FIELD if missing
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"IA1 Check - {self.dossier.title} ({self.status})"

class IaCrossCheck(models.Model):
    # Partie 2: Cohérence Croisée Questionnaire/Archi
    dossier = models.OneToOneField(
        'Dossier', 
        on_delete=models.CASCADE, 
        related_name='ia2_result',
        primary_key=True
    )
    status = models.CharField(max_length=10, choices=IaStatus.choices, default=IaStatus.PENDING)
    findings = models.JSONField(default=dict)
    secure_score = models.DecimalField(
        max_digits=4, 
        decimal_places=2, 
        null=True, 
        blank=True,
        verbose_name=_("Score de sécurité")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"IA2 CrossCheck - {self.dossier.title} ({self.status})"

# core/models.py (suite)
# ... après les modèles Ia

# --- Enums Risques ---
class Likelihood(models.TextChoices):
    RARE = 'RARE', _('Rare')
    UNLIKELY = 'UNLIKELY', _('Peu probable')
    POSSIBLE = 'POSSIBLE', _('Possible')
    LIKELY = 'LIKELY', _('Probable')
    ALMOST_CERTAIN = 'ALMOST_CERTAIN', _('Quasi-certain')

# Basé sur [cite: 186]
class Impact(models.TextChoices):
    MINOR = 'MINOR', _('Mineur')
    MODERATE = 'MODERATE', _('Modéré')
    MAJOR = 'MAJOR', _('Majeur')
    SEVERE = 'SEVERE', _('Sévère')
    CATASTROPHIC = 'CATASTROPHIC', _('Catastrophique')

# Basé sur [cite: 184]
class RiskLevel(models.TextChoices):
    LOW = 'LOW', _('Faible')
    MEDIUM = 'MEDIUM', _('Moyen')
    HIGH = 'HIGH', _('Élevé')
    CRITICAL = 'CRITICAL', _('Critique')

# Basé sur [cite: 183]
class RiskStatus(models.TextChoices):
    DRAFT = 'DRAFT', _('Brouillon')
    SUBMITTED = 'SUBMITTED', _('Soumis à acceptation')
    PARTIALLY_ACCEPTED = 'PARTIALLY_ACCEPTED', _('Partiellement accepté')
    ACCEPTED = 'ACCEPTED', _('Accepté')

class RiskItemStatus(models.TextChoices):
    PENDING = 'PENDING', _('En attente d\'acceptation')
    DELEGATED_PENDING = 'DELEGATED_PENDING', _('Délégué - En attente')
    ACCEPTED = 'ACCEPTED', _('Accepté')
    CONTESTED = 'CONTESTED', _('Contesté')
    REFUSED = 'REFUSED', _('Refusé')

# --- Registre de Risques (RiskRegister) ---
class RiskRegister(models.Model):
    dossier = models.OneToOneField(
        'Dossier', 
        on_delete=models.CASCADE, 
        related_name='risk_register'
    )
    created_by = models.ForeignKey(
        'User', 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='risks_created'
    )
    status = models.CharField(
        max_length=30, 
        choices=RiskStatus.choices, 
        default=RiskStatus.DRAFT
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Risk Register - {self.dossier.title} ({self.status})"
    
    @property
    def total_items(self):
        return self.items.count()
    
    @property
    def accepted_items(self):
        return self.items.filter(status=RiskItemStatus.ACCEPTED).count()

# --- Item de Risque Individuel (RiskItem) ---
class RiskItem(models.Model):
    register = models.ForeignKey(
        RiskRegister, 
        on_delete=models.CASCADE, 
        related_name='items'
    )
    owner_user = models.ForeignKey(
        'User', 
        on_delete=models.PROTECT, 
        related_name='risk_items_owned',
        verbose_name=_("Propriétaire du risque")
    )
    delegated_to = models.ForeignKey(
        'User', 
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='risk_items_delegated',
        verbose_name=_("Délégué à")
    )
    
    # Risk details
    title = models.CharField(max_length=255, verbose_name=_("Titre du risque"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    
    # Risk assessment
    likelihood = models.CharField(
        max_length=20, 
        choices=Likelihood.choices,
        default=Likelihood.POSSIBLE,
        verbose_name=_("Probabilité")
    )
    impact = models.CharField(
        max_length=20, 
        choices=Impact.choices,
        default=Impact.MODERATE,
        verbose_name=_("Impact")
    )
    level = models.CharField(
        max_length=10, 
        choices=RiskLevel.choices,
        default=RiskLevel.MEDIUM,
        verbose_name=_("Niveau de risque")
    )
    
    # Mitigation & status
    mitigation = models.TextField(blank=True, verbose_name=_("Mesures de mitigation"))
    status = models.CharField(
        max_length=20, 
        choices=RiskItemStatus.choices,
        default=RiskItemStatus.PENDING,
        verbose_name=_("Statut")
    )
    
    # NEW: Contestation tracking
    contested_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='risk_items_contested',
        verbose_name=_("Contesté par")
    )
    contested_at = models.DateTimeField(null=True, blank=True)
    contestation_reason = models.TextField(blank=True, verbose_name=_("Raison de la contestation"))
    
    # NEW: Refusal tracking (to prevent re-delegation to same user)
    refused_by = models.JSONField(
        default=list,
        blank=True,
        help_text=_("List of user IDs who refused this delegation"),
        verbose_name=_("Refusé par")
    )
    
    # Timestamps
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.level})"
    
    class Meta:
        ordering = ['-created_at']

# --- Énumérations pour l'Audit ---
class AuditActionType(models.TextChoices):
    # Dossier lifecycle
    DOSSIER_CREATED = 'DOSSIER_CREATED', _('Dossier créé')
    DOSSIER_UPDATED = 'DOSSIER_UPDATED', _('Dossier modifié')
    STATUS_CHANGED = 'STATUS_CHANGED', _('Statut modifié')
    
    # Questionnaire
    QUESTIONNAIRE_SAVED = 'QUESTIONNAIRE_SAVED', _('Questionnaire sauvegardé')
    QUESTIONNAIRE_SUBMITTED = 'QUESTIONNAIRE_SUBMITTED', _('Questionnaire soumis')
    
    # Architecture documents
    DOCUMENT_UPLOADED = 'DOCUMENT_UPLOADED', _('Document uploadé')
    DOCUMENT_DELETED = 'DOCUMENT_DELETED', _('Document supprimé')
    DOCUMENT_CONFIRMED = 'DOCUMENT_CONFIRMED', _('Document confirmé par RSSI')
    
    # IA Analysis
    IA1_STARTED = 'IA1_STARTED', _('Analyse IA1 lancée')
    IA1_COMPLETED = 'IA1_COMPLETED', _('Analyse IA1 terminée')
    IA2_STARTED = 'IA2_STARTED', _('Analyse IA2 lancée')
    IA2_COMPLETED = 'IA2_COMPLETED', _('Analyse IA2 terminée')
    
    # Risk management
    RISK_REGISTER_CREATED = 'RISK_REGISTER_CREATED', _('Registre de risques créé')
    RISK_ITEM_ADDED = 'RISK_ITEM_ADDED', _('Risque ajouté')
    RISK_ITEM_UPDATED = 'RISK_ITEM_UPDATED', _('Risque modifié')
    RISK_ITEM_DELETED = 'RISK_ITEM_DELETED', _('Risque supprimé')
    RISK_ITEM_DELEGATED = 'RISK_ITEM_DELEGATED', _('Risque délégué')
    RISK_ITEM_ACCEPTED = 'RISK_ITEM_ACCEPTED', _('Risque accepté')
    RISK_REGISTER_SUBMITTED = 'RISK_REGISTER_SUBMITTED', _('Registre soumis')
    RISK_REGISTER_ACCEPTED = 'RISK_REGISTER_ACCEPTED', _('Registre accepté')
    
    # Validation
    DOSSIER_VALIDATED = 'DOSSIER_VALIDATED', _('Dossier validé')

# --- Journal d'Audit (un par Dossier) ---
class AuditLog(models.Model):
    dossier = models.OneToOneField(
        'Dossier',
        on_delete=models.CASCADE,
        related_name='audit_log',
        primary_key=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Audit Log - {self.dossier.title}"
    
    @property
    def entry_count(self):
        return self.entries.count()
    
    @property
    def last_activity(self):
        return self.entries.order_by('-timestamp').first()

# --- Entrée d'Audit (historique des actions) ---
class AuditLogEntry(models.Model):
    audit_log = models.ForeignKey(
        AuditLog,
        on_delete=models.CASCADE,
        related_name='entries'
    )
    user = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='audit_entries',
        verbose_name=_("Utilisateur")
    )
    action_type = models.CharField(
        max_length=30,
        choices=AuditActionType.choices,
        verbose_name=_("Type d'action")
    )
    field_modified = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Champ modifié")
    )
    old_value = models.TextField(
        blank=True,
        verbose_name=_("Ancienne valeur")
    )
    new_value = models.TextField(
        blank=True,
        verbose_name=_("Nouvelle valeur")
    )
    detail = models.JSONField(
        default=dict,
        verbose_name=_("Détails supplémentaires")
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Horodatage")
    )

    def __str__(self):
        return f"{self.action_type} by {self.user} at {self.timestamp}"
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = _("Entrée d'audit")
        verbose_name_plural = _("Entrées d'audit")