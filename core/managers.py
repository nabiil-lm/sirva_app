# core/managers.py
from django.contrib.auth.models import BaseUserManager

class CustomUserManager(BaseUserManager):
    """
    Gestionnaire de modèle d'utilisateur personnalisé où l'email est l'identifiant unique
    au lieu des usernames.
    """
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('L\'adresse e-mail doit être définie')
        
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """
        Crée et sauvegarde un SuperUser avec l'email et le mot de passe donnés.
        Note: Le champ 'username' est ignoré/non requis ici.
        """
        # Assure les flags d'administration
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        # Le champ role est nécessaire pour votre projet
        from core.models import Role # Importation locale pour éviter les dépendances circulaires
        extra_fields.setdefault('role', Role.ADMIN) 

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)