# SIRVA Backend - Plateforme d'Évaluation de Sécurité

## 📋 Table des Matières

1. [Présentation](#-présentation)
2. [Architecture Technique](#-architecture-technique)
3. [Technologies Utilisées](#-technologies-utilisées)
4. [Modèles de Données](#-modèles-de-données)
5. [Workflow de Validation](#-workflow-de-validation)
6. [API Endpoints](#-api-endpoints)
7. [Services d'Intelligence Artificielle](#-services-dintelligence-artificielle)
8. [Installation et Configuration](#-installation-et-configuration)
9. [Déploiement](#-déploiement)
10. [Diagrammes](#-diagrammes)

---

## 🎯 Présentation

SIRVA (Security Information Risk Validation Assessment) est une plateforme web moderne conçue pour **automatiser et optimiser les évaluations de sécurité applicative** au sein des organisations. Elle permet aux équipes de soumettre des dossiers de sécurité qui sont analysés par une intelligence artificielle (Gemini AI de Google) avant d'être validés par des officiers de sécurité.

### Problématique Résolue

Dans les grandes organisations, l'évaluation manuelle de la sécurité des applications est :
- ⏱️ **Chronophage** : Des jours/semaines pour analyser chaque application
- 🔴 **Sujette aux erreurs** : Incohérences entre déclarations et documentation
- 📊 **Difficile à tracer** : Manque d'audit trail complet
- 🤝 **Peu collaborative** : Communication fragmentée entre équipes

### Solution SIRVA

SIRVA automatise ce processus en 5 phases structurées avec validation IA et workflows collaboratifs :

1. **Phase 1 - Questionnaire** : Formulaire structuré avec validation temps réel
2. **Phase 2 - Analyse IA1** : Vérification de cohérence des réponses (Gemini AI)
3. **Phase 3 - Documentation** : Upload de documents d'architecture technique
4. **Phase 4 - Analyse IA2** : Cross-check questionnaire ↔ documentation (Gemini AI)
5. **Phase 5 - Gestion des Risques** : Identification, contestation, délégation et résolution

---

## 🏗️ Architecture Technique

### Stack Backend

```
┌─────────────────────────────────────────────────────────────┐
│                   SIRVA Backend Stack                        │
├─────────────────────────────────────────────────────────────┤
│  Framework      │ Django 5.x + Django REST Framework        │
│  Base de données│ PostgreSQL 16 (Production)               │
│  Cache & Queue  │ Redis 7                                   │
│  Stockage       │ MinIO (S3-compatible) / Azure Blob       │
│  IA             │ Google Gemini 2.5 Flash API              │
│  Email          │ MailDev (Dev) / SMTP (Production)        │
│  Auth           │ JWT (Djoser + SimpleJWT)                 │
│  Conteneurs     │ Docker + Docker Compose                   │
└─────────────────────────────────────────────────────────────┘
```

### Architecture en Couches

```
┌──────────────────────────────────────────────────────┐
│              Frontend (Next.js)                      │
└────────────────────┬─────────────────────────────────┘
                     │ REST API (HTTPS/JWT)
┌────────────────────▼─────────────────────────────────┐
│           Django REST Framework Layer                │
│  ┌────────────────────────────────────────────────┐ │
│  │  ViewSets (DossierViewSet, RiskViewSet...)    │ │
│  └────────────┬───────────────────────────────────┘ │
└───────────────┼──────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────┐
│              Business Logic Layer                    │
│  ┌────────────────────────────────────────────────┐ │
│  │  Services (IA1Service, IA2Service)             │ │
│  │  Validators (StatusMachine, PermissionChecks)  │ │
│  └────────────┬───────────────────────────────────┘ │
└───────────────┼──────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────┐
│               Data Access Layer                      │
│  ┌────────────────────────────────────────────────┐ │
│  │  Django ORM Models                             │ │
│  │  (Dossier, RiskItem, ArchitectureDoc...)      │ │
│  └────────────┬───────────────────────────────────┘ │
└───────────────┼──────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────┐
│          Infrastructure Layer                        │
│  ┌──────────┬──────────┬──────────┬──────────────┐  │
│  │PostgreSQL│  Redis   │  MinIO   │  Gemini AI  │  │
│  └──────────┴──────────┴──────────┴──────────────┘  │
└──────────────────────────────────────────────────────┘
```

---

## 🛠️ Technologies Utilisées

### Frameworks & Librairies

| Technologie | Version | Usage |
|------------|---------|-------|
| **Django** | 5.1.4 | Framework web principal |
| **Django REST Framework** | 3.15.2 | API REST |
| **Djoser** | 2.2.3 | Authentication endpoints |
| **SimpleJWT** | 5.3.1 | JWT tokens |
| **drf-nested-routers** | 0.94.1 | Routes API imbriquées |
| **psycopg2-binary** | 2.9.10 | Driver PostgreSQL |
| **google-generativeai** | 0.8.3 | Gemini AI SDK |
| **python-dotenv** | 1.0.1 | Gestion variables d'environnement |
| **django-cors-headers** | 4.6.0 | CORS configuration |
| **Pillow** | 11.0.0 | Traitement d'images |

### Services Externes

- **Google Gemini AI** : Analyse de cohérence (IA1) et cross-check (IA2)
- **MinIO** : Stockage S3-compatible pour documents d'architecture
- **PostgreSQL** : Base de données relationnelle
- **Redis** : Cache et gestion de queues (futur)
- **MailDev** : Serveur SMTP de développement

---

## 📊 Modèles de Données

### Vue d'Ensemble

Le système repose sur 11 modèles principaux organisés autour du concept central de **Dossier**.

```
User (Django Auth)
  │
  ├─── Dossier (1:N)
  │     ├─── QuestionnaireTemplate (N:1)
  │     ├─── QuestionnaireAnswer (1:N)
  │     ├─── IA1Analysis (1:1)
  │     ├─── ArchitectureDoc (1:N)
  │     ├─── IA2CrossCheck (1:1)
  │     ├─── RiskRegister (1:1)
  │     │     └─── RiskItem (1:N)
  │     │           └─── RiskContestation (1:1 optional)
  │     └─── AuditLog (1:N)
  │
  └─── QuestionnaireTemplate (Admin)
        └─── Question (1:N)
```

### 1. User (Utilisateur)

**Extension du modèle Django User**

```python
class User(AbstractUser):
    role: CharField  # Choices: ADMIN, SO (Security Officer), AM (Application Manager)
    avatar: ImageField
    preferences: JSONField  # Theme, notifications, etc.
```

**Rôles et Permissions** :
- **ADMIN** : Gestion complète (users, templates, dossiers)
- **SO (Security Officer)** : Validation dossiers, création risques, validation finale
- **AM (Application Manager)** : Création dossiers, réponses questionnaires, gestion risques

### 2. Dossier (Assessment)

**Entité centrale** représentant un dossier d'évaluation de sécurité.

```python
class Dossier(models.Model):
    title: CharField
    am: ForeignKey(User)  # Application Manager propriétaire
    so: ForeignKey(User, null=True)  # Security Officer assigné
    questionnaire_template: ForeignKey(QuestionnaireTemplate, null=True)
    status: CharField  # 10 états possibles (voir State Machine)
    secure_score: IntegerField(default=0)
    created_at: DateTimeField
    updated_at: DateTimeField
```

**Machine à États (10 statuts)** :

```
EN_EDITION → QUESTIONNAIRE_SOUMIS → IA1_COHERENT ────────────┐
                                  ↘ IA1_INCOHERENT (retry)   │
                                                               ↓
                                               ARCHI_UPLOAD_EN_COURS
                                                               ↓
                                               IA2_COHERENT ────────┐
                                             ↘ IA2_INCOHERENT        │
                                                                     ↓
                                                          RISQUES_EN_COURS
                                                                     ↓
                                                           PRET_VALIDATION
                                                                     ↓
                                                                 VALIDE
```

### 3. QuestionnaireTemplate & Question

**Templates réutilisables** gérés par les administrateurs.

```python
class QuestionnaireTemplate(models.Model):
    name: CharField
    description: TextField
    status: CharField  # DRAFT ou PUBLISHED
    question_count: IntegerField

class Question(models.Model):
    template: ForeignKey(QuestionnaireTemplate)
    text: TextField
    question_type: CharField  # TRUE_FALSE, SINGLE_CHOICE, MULTIPLE_CHOICE, TEXT
    choices_json: JSONField  # Pour SINGLE/MULTIPLE_CHOICE
    is_mandatory: BooleanField
    help_text: TextField
    order: IntegerField
```

### 4. QuestionnaireAnswer

**Réponses de l'AM** au questionnaire.

```python
class QuestionnaireAnswer(models.Model):
    dossier: ForeignKey(Dossier)
    question: ForeignKey(Question)
    answer_value: TextField  # Stockage flexible (bool, choix, texte)
    answered_at: DateTimeField
```

### 5. IA1Analysis (Coherence Check)

**Résultat de l'analyse IA phase 1** (cohérence des réponses).

```python
class IA1Analysis(models.Model):
    dossier: OneToOneField(Dossier)
    secure_score: IntegerField  # 0-100
    is_coherent: BooleanField  # True si score >= 15
    analysis_text: TextField
    findings: JSONField  # {summary, strengths, weaknesses, recommendations}
    analyzed_at: DateTimeField
```

### 6. ArchitectureDoc

**Documents techniques** uploadés par l'AM.

```python
class ArchitectureDoc(models.Model):
    dossier: ForeignKey(Dossier)
    filename: CharField
    display_name: CharField
    description: TextField
    local_filepath: CharField  # Chemin sur serveur/MinIO
    size: IntegerField
    rssi_confirmed: BooleanField  # Validation RSSI requise
    uploaded_at: DateTimeField
```

### 7. IA2CrossCheck (Architecture Validation)

**Résultat de l'analyse IA phase 2** (cross-check questionnaire ↔ documents).

```python
class IA2CrossCheck(models.Model):
    dossier: OneToOneField(Dossier)
    secure_score: IntegerField
    is_coherent: BooleanField  # True si score >= 15
    analysis_text: TextField
    findings: JSONField  # {summary, strengths, weaknesses, recommendations}
    analyzed_at: DateTimeField
```

### 8. RiskRegister

**Conteneur de risques** créé par le SO.

```python
class RiskRegister(models.Model):
    dossier: OneToOneField(Dossier)
    created_by: ForeignKey(User)  # SO
    status: CharField  # DRAFT, SUBMITTED, ACCEPTED
    created_at: DateTimeField
```

### 9. RiskItem

**Risque individuel** avec workflow de gestion.

```python
class RiskItem(models.Model):
    register: ForeignKey(RiskRegister)
    title: CharField
    description: TextField
    severity: CharField  # CRITICAL, HIGH, MEDIUM, LOW
    mitigation: TextField
    status: CharField  # PENDING, ACCEPTED, CONTESTED, DELEGATED, RESOLVED
    assigned_to: ForeignKey(User, null=True)  # Pour délégation
    created_at: DateTimeField
```

**États des Risques** :

```
PENDING → ACCEPTED → RESOLVED
        ↘ CONTESTED → (SO Review) → ACCEPTED/RESOLVED
        ↘ DELEGATED → (Assignee Action) → ACCEPTED → RESOLVED
```

### 10. RiskContestation

**Contestation d'un risque** par l'AM.

```python
class RiskContestation(models.Model):
    risk_item: OneToOneField(RiskItem)
    reasoning: TextField
    contested_by: ForeignKey(User)
    contested_at: DateTimeField
    so_decision: CharField  # PENDING, ACCEPTED (invalidates risk), REJECTED (back to PENDING)
    so_comment: TextField
    reviewed_at: DateTimeField
```

### 11. AuditLog

**Journal d'audit** pour traçabilité complète.

```python
class AuditLog(models.Model):
    dossier: ForeignKey(Dossier)
    user: ForeignKey(User)
    action: CharField  # STATUS_CHANGE, DOCUMENT_UPLOAD, RISK_CREATED, etc.
    description: TextField
    timestamp: DateTimeField
    metadata: JSONField
```

---

## 🔄 Workflow de Validation

### Phase 1 : Création et Questionnaire

```mermaid
sequenceDiagram
    participant AM as Application Manager
    participant API as Django API
    participant DB as PostgreSQL

    AM->>API: POST /api/dossiers/ (title, SO, template)
    API->>DB: Create Dossier (status=EN_EDITION)
    API-->>AM: Dossier ID

    AM->>API: GET /api/questionnaires/{id}/with_questions/
    API-->>AM: Questions list

    AM->>API: POST /api/dossiers/{id}/answers/bulk_answer/
    API->>DB: Save QuestionnaireAnswers
    API-->>AM: Success

    AM->>API: POST /api/dossiers/{id}/submit/
    Note over API: Change status to QUESTIONNAIRE_SOUMIS
    API->>API: Trigger IA1 Analysis (async)
```

**Endpoints Clés** :
- `POST /api/dossiers/` - Création dossier
- `GET /api/questionnaires/{id}/with_questions/` - Récupération questions
- `POST /api/dossiers/{id}/answers/bulk_answer/` - Sauvegarde réponses
- `POST /api/dossiers/{id}/submit/` - Soumission pour analyse

### Phase 2 : Analyse IA1 (Coherence Check)

```mermaid
sequenceDiagram
    participant API as Django API
    participant IA1 as IA1 Service
    participant Gemini as Gemini AI
    participant DB as PostgreSQL

    API->>IA1: run_ia1_analysis(dossier_id)
    IA1->>DB: Fetch QuestionnaireAnswers
    IA1->>IA1: Prepare prompt with answers
    IA1->>Gemini: generate_content(prompt)
    
    alt Success
        Gemini-->>IA1: JSON response {score, summary, findings}
        IA1->>DB: Create IA1Analysis
        IA1->>DB: Update Dossier (status=IA1_COHERENT/INCOHERENT, secure_score)
        IA1-->>API: Analysis complete
    else API Error
        Gemini-->>IA1: Error (quota, network)
        IA1->>IA1: Retry with exponential backoff
    end
```

**Logique IA1** :
- **Seuil de validation** : `secure_score >= 15/100`
- **Format réponse** : JSON structuré `{secure_score, summary, strengths, weaknesses, recommendations}`
- **Retry logic** : 3 tentatives avec délais croissants (20s, 40s, 60s)

**Prompt IA1** (extrait) :
```text
Tu es un auditeur de sécurité. Analyse les réponses au questionnaire
pour détecter incohérences, manques ou bonnes pratiques.

Format JSON obligatoire :
{
    "secure_score": <0-100>,
    "summary": "<Résumé en 2-3 phrases>",
    "strengths": ["Point fort 1", ...],
    "weaknesses": ["Faiblesse 1", ...],
    "recommendations": ["Action 1", ...]
}
```

### Phase 3 : Upload de Documentation

```mermaid
sequenceDiagram
    participant AM as Application Manager
    participant API as Django API
    participant Storage as MinIO/Azure
    participant DB as PostgreSQL

    AM->>API: POST /api/dossiers/{id}/documents/ (file, display_name)
    API->>Storage: Upload PDF
    Storage-->>API: file_url
    API->>DB: Create ArchitectureDoc (rssi_confirmed=False)
    API-->>AM: Document uploaded

    loop For each document
        AM->>API: POST /api/dossiers/{id}/documents/{doc_id}/confirm/
        API->>DB: Set rssi_confirmed=True
    end

    AM->>API: POST /api/dossiers/{id}/documents/submit_documents/
    Note over API: Change status to IA2_COHERENT (pending)
    API->>API: Trigger IA2 Analysis (async)
```

**Contraintes** :
- Format accepté : **PDF uniquement**
- Taille max : **50 MB** (configurable)
- Validation RSSI : **Obligatoire** pour chaque document
- Compression : **Ghostscript** utilisé pour réduire la taille avant envoi à Gemini

### Phase 4 : Analyse IA2 (Cross-Check)

```mermaid
sequenceDiagram
    participant API as Django API
    participant IA2 as IA2 Service
    participant GS as Ghostscript
    participant Gemini as Gemini File API
    participant DB as PostgreSQL

    API->>IA2: run_ia2_analysis(dossier_id)
    IA2->>DB: Fetch QuestionnaireAnswers + ArchitectureDocs
    
    loop For each PDF
        IA2->>GS: compress_pdf(file_path)
        GS-->>IA2: compressed_file_path
        IA2->>Gemini: upload_file(compressed_pdf)
        Gemini-->>IA2: file_handle
    end
    
    IA2->>IA2: Prepare prompt (questionnaire + files)
    IA2->>Gemini: generate_content(prompt + files)
    
    alt Success
        Gemini-->>IA2: JSON response {score, summary, findings}
        IA2->>DB: Create IA2CrossCheck
        IA2->>DB: Update Dossier (status=IA2_COHERENT/INCOHERENT)
        IA2-->>API: Analysis complete
    end
    
    IA2->>Gemini: delete_files() [cleanup]
```

**Optimisations IA2** :
- **Compression PDF** : Ghostscript avec `-dPDFSETTINGS=/ebook` (150 DPI)
- **API File Upload** : Utilisation de `genai.upload_file()` au lieu d'embeddings inline
- **Cleanup** : Suppression fichiers temporaires et remote files Gemini
- **Token Management** : Réduction drastique de l'usage de tokens grâce à compression

**Prompt IA2** (extrait) :
```text
Compare ce questionnaire de sécurité avec les documents d'architecture fournis.
Signale toute incohérence majeure (chiffrement manquant, flux non couverts, etc.).

Le "secure_score" doit refléter la COHÉRENCE entre déclarations et preuves.
```

### Phase 5 : Gestion des Risques

```mermaid
stateDiagram-v2
    [*] --> DRAFT: SO creates RiskRegister
    DRAFT --> SUBMITTED: SO submits register
    SUBMITTED --> RiskItems: Multiple risk items created
    
    state RiskItems {
        [*] --> PENDING: SO creates risk
        PENDING --> ACCEPTED: AM accepts
        PENDING --> CONTESTED: AM contests
        PENDING --> DELEGATED: AM delegates
        
        CONTESTED --> SO_Review
        SO_Review --> ACCEPTED: SO accepts contest (invalidates risk)
        SO_Review --> PENDING: SO rejects contest
        
        DELEGATED --> ACCEPTED: Assignee accepts
        DELEGATED --> PENDING: Assignee rejects
        
        ACCEPTED --> RESOLVED: Final resolution
    }
    
    RiskItems --> AllResolved: All risks resolved
    AllResolved --> PRET_VALIDATION
    PRET_VALIDATION --> VALIDE: SO final validation
```

**Actions AM sur un Risque** :
1. **Accept** : Reconnaît le risque, implémentera la mitigation
2. **Contest** : Conteste l'évaluation, fournit un raisonnement (SO révise)
3. **Delegate** : Assigne à un membre de l'équipe

**Actions SO** :
1. **Créer risques** : Identification post-IA2
2. **Réviser contestations** : Accepter (invalide risque) ou Refuser (retour PENDING)
3. **Validation finale** : Transition `PRET_VALIDATION` → `VALIDE`

---

## 🌐 API Endpoints

### Hiérarchie des Routes

```
/api/
├── auth/
│   ├── jwt/create/ (POST) - Login
│   ├── jwt/refresh/ (POST) - Refresh token
│   └── users/me/ (GET) - Current user
│
├── users/
│   ├── / (GET, POST) - List/Create users [Admin]
│   ├── /{id}/ (GET, PATCH, DELETE) - User detail
│   └── /stats/ (GET) - User statistics [Admin]
│
├── questionnaires/
│   ├── / (GET, POST) - List/Create templates
│   ├── /{id}/ (GET, PATCH, DELETE) - Template detail
│   ├── /{id}/with_questions/ (GET) - Template + Questions
│   ├── /available/ (GET) - Published templates
│   └── /{id}/questions/
│       ├── / (GET, POST) - List/Create questions
│       └── /{qid}/ (GET, PATCH, DELETE) - Question detail
│
└── dossiers/
    ├── / (GET, POST) - List/Create dossiers
    ├── /admin_stats/ (GET) - Admin statistics
    ├── /{id}/ (GET, PATCH, DELETE) - Dossier detail
    ├── /{id}/full/ (GET) - Dossier with all relations
    ├── /{id}/submit/ (POST) - Submit for IA1
    ├── /{id}/validate/ (POST) - Final validation [SO]
    ├── /{id}/change_status/ (GET, POST) - Manual status change [Admin]
    │
    ├── /{id}/answers/
    │   ├── / (GET, POST) - List/Create answers
    │   └── /bulk_answer/ (POST) - Save multiple answers
    │
    ├── /{id}/documents/
    │   ├── / (GET, POST) - List/Upload documents
    │   ├── /{doc_id}/ (GET, DELETE) - Document detail
    │   ├── /{doc_id}/confirm/ (POST) - RSSI confirmation
    │   ├── /{doc_id}/download/ (GET) - Download PDF
    │   └── /submit_documents/ (POST) - Submit for IA2
    │
    ├── /{id}/ia1/ (GET) - IA1 analysis results
    ├── /{id}/ia2/ (GET) - IA2 analysis results
    │
    ├── /{id}/risk-register/
    │   ├── / (GET, POST) - Get/Create register
    │   ├── /{reg_id}/ (GET, PATCH) - Register detail
    │   ├── /{reg_id}/submit/ (POST) - Submit register
    │   └── /{reg_id}/items/
    │       ├── / (GET, POST) - List/Create risk items
    │       ├── /{item_id}/ (GET, PATCH, DELETE) - Risk detail
    │       ├── /{item_id}/contest/ (POST) - Contest risk [AM]
    │       ├── /{item_id}/review_contest/ (POST) - Review contest [SO]
    │       └── /delegation_action/ (POST) - Accept/Reject delegation
    │
    └── /{id}/audit-log/ (GET) - Audit trail
```

### Exemples de Requêtes

#### 1. Créer un Dossier

```bash
POST /api/dossiers/
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
    "title": "Application E-Commerce Refonte 2024",
    "questionnaire_template": 1,
    "so": 3
}

# Response 201
{
    "id": 42,
    "title": "Application E-Commerce Refonte 2024",
    "status": "EN_EDITION",
    "status_display": "En édition",
    "am": {
        "id": 2,
        "email": "manager@example.com",
        "first_name": "Jean",
        "last_name": "Dupont"
    },
    "so": {
        "id": 3,
        "email": "security@example.com"
    },
    "questionnaire_template": 1,
    "questionnaire_template_name": "Cloud Security Standard v2.0",
    "secure_score": 0,
    "created_at": "2024-01-15T10:30:00Z"
}
```

#### 2. Soumettre des Réponses (Bulk)

```bash
POST /api/dossiers/42/answers/bulk_answer/
Authorization: Bearer <jwt_token>

{
    "answers": [
        {"question": 1, "answer_value": "true"},
        {"question": 2, "answer_value": "AES-256"},
        {"question": 3, "answer_value": "Oui, avec Azure AD"}
    ]
}

# Response 200
{
    "message": "3 answers saved successfully"
}
```

#### 3. Soumettre pour Analyse IA1

```bash
POST /api/dossiers/42/submit/
Authorization: Bearer <jwt_token>

# Response 200
{
    "message": "Dossier submitted for IA1 analysis",
    "status": "QUESTIONNAIRE_SOUMIS"
}
```

#### 4. Upload Document d'Architecture

```bash
POST /api/dossiers/42/documents/
Authorization: Bearer <jwt_token>
Content-Type: multipart/form-data

file: [network_diagram.pdf]
display_name: "Diagramme Réseau Production"
description: "Architecture réseau avec DMZ et zones de sécurité"
rssi_confirmed: true

# Response 201
{
    "id": 15,
    "filename": "network_diagram.pdf",
    "display_name": "Diagramme Réseau Production",
    "size": 2457600,
    "rssi_confirmed": true,
    "uploaded_at": "2024-01-15T14:22:00Z"
}
```

#### 5. Créer un Risque [SO]

```bash
POST /api/dossiers/42/risk-register/1/items/
Authorization: Bearer <jwt_token>

{
    "title": "Absence de chiffrement des données au repos",
    "description": "Les données sensibles stockées en base ne sont pas chiffrées.",
    "severity": "HIGH",
    "mitigation": "Implémenter TDE (Transparent Data Encryption) sur PostgreSQL"
}

# Response 201
{
    "id": 8,
    "title": "Absence de chiffrement des données au repos",
    "status": "PENDING",
    "severity": "HIGH",
    "created_at": "2024-01-16T09:15:00Z"
}
```

#### 6. Contester un Risque [AM]

```bash
POST /api/dossiers/42/risk-register/1/items/8/contest/
Authorization: Bearer <jwt_token>

{
    "reasoning": "Les données sensibles sont en réalité chiffrées via la fonctionnalité Azure SQL TDE activée depuis le 10/01/2024. Voir documentation jointe dans le dossier technique."
}

# Response 200
{
    "message": "Risk contested successfully",
    "status": "CONTESTED"
}
```

---

## 🤖 Services d'Intelligence Artificielle

### IA1 Service - Coherence Check

**Fichier** : `core/services/ia1_service.py`

**Objectif** : Analyser la cohérence et la complétude des réponses au questionnaire.

**Prompt Engineering** :
```python
IA1_AUDIT_PROMPT = """
Tu es un auditeur de sécurité. Analyse ces réponses et identifie :
1. Incohérences logiques
2. Manques de détails
3. Bonnes pratiques respectées
4. Zones de risque

Format JSON OBLIGATOIRE :
{
    "secure_score": <0-100>,
    "summary": "<Résumé>",
    "strengths": [...],
    "weaknesses": [...],
    "recommendations": [...]
}
"""
```

**Workflow** :
1. Fetch questionnaire answers from DB
2. Format as structured text
3. Call Gemini API with prompt
4. Parse JSON response
5. Calculate `secure_score` (0-100)
6. Determine `is_coherent` (score >= 15)
7. Save `IA1Analysis` object
8. Update dossier status

**Gestion d'Erreurs** :
- **Quota exceeded** : Retry avec backoff exponentiel (3 tentatives)
- **Invalid JSON** : Parsing fallback avec regex
- **API key error** : Reload from `.env` (fresh config)

### IA2 Service - Cross-Check Analysis

**Fichier** : `core/services/ia2_service.py`

**Objectif** : Valider la cohérence entre déclarations (questionnaire) et preuves (documents).

**Innovations Techniques** :

1. **Compression PDF** : Réduction de 70-90% de la taille
```python
def compress_pdf(file_path):
    cmd = ['gs', '-sDEVICE=pdfwrite', '-dPDFSETTINGS=/ebook', ...]
    subprocess.run(cmd)
```

2. **File API Usage** : Upload de fichiers au lieu d'embeddings
```python
gemini_file = genai.upload_file(
    path=compressed_file,
    mime_type='application/pdf'
)
```

3. **Cleanup Automatique** :
```python
finally:
    for f in uploaded_files:
        f.delete()  # Remote cleanup
    for f in temp_files:
        os.remove(f)  # Local cleanup
```

**Prompt IA2** :
```python
IA2_AUDIT_PROMPT = """
Compare questionnaire (ci-dessus) avec documents d'architecture fournis.
Signale incohérences : chiffrement annoncé mais absent, flux non couverts, etc.

Le "secure_score" reflète la COHÉRENCE déclarations ↔ preuves.
"""
```

**Performance** :
- **Sans compression** : ~15-20 tokens par page PDF → 300-600 tokens/document → **Quota rapidement atteint**
- **Avec compression** : ~3-5 tokens par page → 60-120 tokens/document → **10x moins de tokens**

---

## 🚀 Installation et Configuration

### Prérequis

- **Python** : 3.12+
- **Docker** : 20.10+
- **Docker Compose** : 2.0+
- **Ghostscript** : 9.50+ (pour compression PDF)

### 1. Cloner le Répertoire

```bash
git clone https://github.com/votre-org/sirva_app.git
cd sirva_app
```

### 2. Configuration Environnement

Créer un fichier `.env` à la racine :

```env
# Database
POSTGRES_USER=app_user
POSTGRES_PASSWORD=dev_password
POSTGRES_DB=cyberdb
DATABASE_URL=postgresql://app_user:dev_password@postgres:5432/cyberdb

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# MinIO (S3)
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
S3_ENDPOINT=http://minio:9000
S3_BUCKET_NAME=cyber-docs

# Email Dev
EMAIL_HOST=maildev
EMAIL_PORT=1025

# Django
SECRET_KEY=votre-clé-secrète-ici
DEBUG=True

# Gemini AI
GEMINI_API_KEY=votre-clé-api-gemini
IA1_SECURE_SCORE_THRESHOLD=15
```

### 3. Lancer avec Docker Compose

```bash
# Build et démarrage
docker-compose up -d --build

# Vérifier les logs
docker-compose logs -f

# Accès aux services :
# - Django API: http://localhost:8000
# - MinIO Console: http://localhost:9001
# - MailDev: http://localhost:1080
# - PostgreSQL: localhost:5432
```

### 4. Installation Locale (sans Docker)

```bash
# Créer environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Installer dépendances
pip install -r requirements.txt

# Installer Ghostscript (Ubuntu/Debian)
sudo apt-get install ghostscript

# Migrations
python manage.py migrate

# Créer superuser
python manage.py createsuperuser

# Lancer serveur
python manage.py runserver
```

### 5. Initialisation Base de Données

```bash
# Créer un questionnaire template de test
python manage.py shell
>>> from core.models import QuestionnaireTemplate, Question
>>> template = QuestionnaireTemplate.objects.create(
...     name="Cloud Security Standard v1",
...     description="Template de base pour applications cloud",
...     status="PUBLISHED"
... )
>>> Question.objects.create(
...     template=template,
...     text="L'application utilise-t-elle le chiffrement en transit (HTTPS)?",
...     question_type="TRUE_FALSE",
...     is_mandatory=True,
...     order=1
... )
```

---

## 📦 Déploiement

### Production avec Docker

**Fichier** : `docker-compose.prod.yml`

```yaml
version: '3.8'

services:
  web:
    build: .
    command: gunicorn sirva.wsgi:application --bind 0.0.0.0:8000 --workers 4
    volumes:
      - static_volume:/app/staticfiles
      - media_volume:/app/media
    environment:
      - DEBUG=False
      - ALLOWED_HOSTS=api.sirva.votredomaine.com
      - DATABASE_URL=${DATABASE_URL}
      - GEMINI_API_KEY=${GEMINI_API_KEY}
    depends_on:
      - postgres
      - redis

  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - static_volume:/app/staticfiles
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - web

  postgres:
    image: postgres:16-alpine
    volumes:
      - postgres_prod_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}

volumes:
  postgres_prod_data:
  static_volume:
  media_volume:
```

### GitHub Actions CI/CD

**Fichier** : `.github/workflows/deployment.yml`

```yaml
name: Déploiement sur Serveur

on:
  push:
    branches: [ "master" ]
  workflow_dispatch:

jobs:
  deploy-via-ssh:
    runs-on: ubuntu-latest
    steps:
      - name: Exécution des commandes sur le serveur
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.SERVER_HOST }}
          username: ${{ secrets.SERVER_USER }}
          password: ${{ secrets.SERVER_PASSWORD }}
          port: 22
          script: |
            cd /home/antonio/sirva_app
            fuser -k 8080/tcp || true
            git pull
            source venv/bin/activate
            pip install -r requirements.txt
            python manage.py migrate
            python manage.py collectstatic --noinput
            nohup python3 manage.py runserver 0.0.0.0:8080 > /dev/null 2>&1 &
```

### Variables d'Environnement Production

```env
# Sécurité
DEBUG=False
SECRET_KEY=<générer-avec-django-secret-key-generator>
ALLOWED_HOSTS=api.sirva.votredomaine.com,localhost

# Base de données (Azure/AWS)
DATABASE_URL=postgresql://user:pass@db.azure.com:5432/sirva_prod

# Stockage (Azure Blob)
AZURE_STORAGE_ACCOUNT_NAME=sirvastorage
AZURE_STORAGE_ACCOUNT_KEY=<clé-azure>

# Gemini API
GEMINI_API_KEY=<clé-production>

# SMTP Production
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=<sendgrid-key>
```

---

## 📈 Diagrammes

### 1. Diagramme d'Architecture Globale

**Outil** : [Mermaid Live Editor](https://mermaid.live/)

```mermaid
graph TB
    subgraph "Frontend Layer"
        Next[Next.js 14 App]
    end

    subgraph "API Gateway"
        DRF[Django REST Framework]
        JWT[JWT Authentication]
    end

    subgraph "Business Logic"
        Dossier[Dossier Management]
        IA1[IA1 Service]
        IA2[IA2 Service]
        Risk[Risk Management]
    end

    subgraph "External Services"
        Gemini[Google Gemini AI]
        Storage[MinIO / Azure Blob]
    end

    subgraph "Data Layer"
        PG[(PostgreSQL)]
        Redis[(Redis Cache)]
    end

    Next -->|HTTPS/JWT| DRF
    DRF --> JWT
    DRF --> Dossier
    Dossier --> IA1
    Dossier --> IA2
    Dossier --> Risk
    IA1 --> Gemini
    IA2 --> Gemini
    IA2 --> Storage
    Dossier --> PG
    Risk --> PG
    DRF --> Redis
```

### 2. Diagramme de Séquence - Workflow Complet

**Outil** : [PlantUML Web Server](http://www.plantuml.com/plantuml/)

<img width="940" height="1329" alt="image" src="https://github.com/user-attachments/assets/5fba3a40-3cc1-4b6b-a57f-342e83c7f1cd" />


### 3. Modèle de Données ERD

**Outil** : [dbdiagram.io](https://dbdiagram.io/)

```dbml
Table User {
  id integer [pk, increment]
  email varchar [unique, not null]
  first_name varchar
  last_name varchar
  role varchar [note: 'ADMIN, SO, AM']
  avatar varchar
  preferences jsonb
  created_at timestamp
}

Table Dossier {
  id integer [pk, increment]
  title varchar [not null]
  am_id integer [ref: > User.id]
  so_id integer [ref: > User.id]
  questionnaire_template_id integer [ref: > QuestionnaireTemplate.id]
  status varchar [note: '10 statuts possibles']
  secure_score integer [default: 0]
  created_at timestamp
  updated_at timestamp
}

Table QuestionnaireTemplate {
  id integer [pk, increment]
  name varchar [not null]
  description text
  status varchar [note: 'DRAFT, PUBLISHED']
  question_count integer [default: 0]
}

Table Question {
  id integer [pk, increment]
  template_id integer [ref: > QuestionnaireTemplate.id]
  text text [not null]
  question_type varchar [note: 'TRUE_FALSE, SINGLE_CHOICE, MULTIPLE_CHOICE, TEXT']
  choices_json jsonb
  is_mandatory boolean [default: false]
  help_text text
  order integer [default: 0]
}

Table QuestionnaireAnswer {
  id integer [pk, increment]
  dossier_id integer [ref: > Dossier.id]
  question_id integer [ref: > Question.id]
  answer_value text
  answered_at timestamp
}

Table IA1Analysis {
  id integer [pk, increment]
  dossier_id integer [ref: - Dossier.id, note: 'OneToOne']
  secure_score integer
  is_coherent boolean
  analysis_text text
  findings jsonb
  analyzed_at timestamp
}

Table ArchitectureDoc {
  id integer [pk, increment]
  dossier_id integer [ref: > Dossier.id]
  filename varchar
  display_name varchar
  description text
  local_filepath varchar
  size integer
  rssi_confirmed boolean [default: false]
  uploaded_at timestamp
}

Table IA2CrossCheck {
  id integer [pk, increment]
  dossier_id integer [ref: - Dossier.id, note: 'OneToOne']
  secure_score integer
  is_coherent boolean
  analysis_text text
  findings jsonb
  analyzed_at timestamp
}

Table RiskRegister {
  id integer [pk, increment]
  dossier_id integer [ref: - Dossier.id, note: 'OneToOne']
  created_by_id integer [ref: > User.id]
  status varchar [note: 'DRAFT, SUBMITTED, ACCEPTED']
  created_at timestamp
}

Table RiskItem {
  id integer [pk, increment]
  register_id integer [ref: > RiskRegister.id]
  title varchar [not null]
  description text
  severity varchar [note: 'CRITICAL, HIGH, MEDIUM, LOW']
  mitigation text
  status varchar [note: 'PENDING, ACCEPTED, CONTESTED, DELEGATED, RESOLVED']
  assigned_to_id integer [ref: > User.id]
  created_at timestamp
}

Table RiskContestation {
  id integer [pk, increment]
  risk_item_id integer [ref: - RiskItem.id, note: 'OneToOne']
  reasoning text [not null]
  contested_by_id integer [ref: > User.id]
  contested_at timestamp
  so_decision varchar [note: 'PENDING, ACCEPTED, REJECTED']
  so_comment text
  reviewed_at timestamp
}

Table AuditLog {
  id integer [pk, increment]
  dossier_id integer [ref: > Dossier.id]
  user_id integer [ref: > User.id]
  action varchar
  description text
  timestamp timestamp
  metadata jsonb
}
```

### 4. Machine à États du Dossier

**Outil** : [Mermaid Live Editor](https://mermaid.live/)

```mermaid
stateDiagram-v2
    [*] --> EN_EDITION: Create Dossier
    
    EN_EDITION --> QUESTIONNAIRE_SOUMIS: Submit Questionnaire
    
    QUESTIONNAIRE_SOUMIS --> IA1_COHERENT: IA1 Success (score ≥15)
    QUESTIONNAIRE_SOUMIS --> IA1_INCOHERENT: IA1 Fail (score <15)
    
    IA1_INCOHERENT --> EN_EDITION: Revise Answers
    
    IA1_COHERENT --> ARCHI_UPLOAD_EN_COURS: Start Document Upload
    
    ARCHI_UPLOAD_EN_COURS --> IA2_COHERENT: IA2 Success (score ≥15)
    ARCHI_UPLOAD_EN_COURS --> IA2_INCOHERENT: IA2 Fail (score <15)
    
    IA2_INCOHERENT --> ARCHI_UPLOAD_EN_COURS: Update Documents
    
    IA2_COHERENT --> RISQUES_EN_COURS: SO Creates Risk Register
    
    RISQUES_EN_COURS --> PRET_VALIDATION: All Risks Resolved
    
    PRET_VALIDATION --> VALIDE: SO Final Validation
    
    VALIDE --> [*]: Assessment Complete
```

### 5. Workflow de Gestion des Risques

**Outil** : [draw.io](https://app.diagrams.net/)

```xml
<!-- À coller dans draw.io -->
<mxfile>
  <diagram name="Risk Management Flow">
    <mxGraphModel>
      <!-- SO crée risque -->
      <mxCell id="0" parent="1" vertex="1" value="SO: Create Risk (PENDING)"/>
      
      <!-- AM décide -->
      <mxCell id="1" parent="0" edge="1" value="AM Actions"/>
      
      <!-- 3 branches -->
      <mxCell id="2" parent="1" vertex="1" value="Accept → ACCEPTED → RESOLVED"/>
      <mxCell id="3" parent="1" vertex="1" value="Contest → CONTESTED → SO Review"/>
      <mxCell id="4" parent="1" vertex="1" value="Delegate → DELEGATED → Assignee Action"/>
      
      <!-- SO Review -->
      <mxCell id="5" parent="3" edge="1" value="SO Decision"/>
      <mxCell id="6" parent="5" vertex="1" value="Accept Contest (Risk Invalidated)"/>
      <mxCell id="7" parent="5" vertex="1" value="Reject Contest → Back to PENDING"/>
    </mxGraphModel>
  </diagram>
</mxfile>
```

---

## 📚 Ressources Complémentaires

### Documentation Externe

- **Django** : https://docs.djangoproject.com/
- **Django REST Framework** : https://www.django-rest-framework.org/
- **Gemini AI** : https://ai.google.dev/docs
- **PostgreSQL** : https://www.postgresql.org/docs/
- **Docker** : https://docs.docker.com/

### Outils de Développement Recommandés

- **Postman** : Tests API REST
- **pgAdmin** : Gestion PostgreSQL
- **MinIO Console** : Gestion fichiers S3
- **VSCode Extensions** : Python, Django, REST Client

### Monitoring & Logs

```bash
# Logs Django en temps réel
docker-compose logs -f web

# Logs PostgreSQL
docker-compose logs -f postgres

# Logs Redis
docker-compose logs -f redis

# Shell Django interactif
docker-compose exec web python manage.py shell
```

---

## 🤝 Contribution

### Workflow Git

```bash
# Créer une branche feature
git checkout -b feature/nom-fonctionnalite

# Commits réguliers
git add .
git commit -m "feat: description de la fonctionnalité"

# Push et Pull Request
git push origin feature/nom-fonctionnalite
```

### Standards de Code

- **PEP 8** pour Python
- **Docstrings** pour toutes les fonctions publiques
- **Type hints** recommandés
- **Tests unitaires** pour services IA

### Contact

- **Email** : support@sirva.com
- **Documentation** : https://docs.sirva.com
- **Issues** : https://github.com/votre-org/sirva_app/issues

---

## 📄 Licence

Copyright © 2024 SIRVA. Tous droits réservés.

---

**Version** : 1.0.0  
**Dernière mise à jour** : Janvier 2024  
**Mainteneur** : Équipe Backend SIRVA

