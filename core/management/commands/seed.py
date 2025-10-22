# core/management/commands/seed.py

from django.core.management.base import BaseCommand
from core.models import User, Role

class Command(BaseCommand):
    help = 'Seeds the database with initial AM, SO, and Admin users.'

    def handle(self, *args, **options):
        # Définition des utilisateurs de démo
        users_to_create = [
            {'email': 'admin@sirva.com', 'role': Role.ADMIN, 'name': 'Super Admin', 'password': 'admin'},
            {'email': 'am@sirva.com', 'role': Role.AM, 'name': 'Application Manager', 'password': 'am'},
            {'email': 'so@sirva.com', 'role': Role.SO, 'name': 'Security Officer', 'password': 'so'},
        ]

        self.stdout.write("--- Création des utilisateurs de démo (AM, SO, Admin) ---")

        for user_data in users_to_create:
            email = user_data['email']
            role = user_data['role']
            
            # Si l'utilisateur existe déjà, on le met à jour
            user, created = User.objects.update_or_create(
                email=email,
                defaults={
                    'role': role,
                    'is_staff': role == Role.ADMIN,
                    'is_superuser': role == Role.ADMIN,
                    'first_name': user_data['name'],
                }
            )
            
            # Ne définir le mot de passe que si l'utilisateur est nouvellement créé
            if created or not user.has_usable_password():
                user.set_password(user_data['password'])
                user.save()
            
            status = "Créé" if created else "Mis à jour"
            self.stdout.write(self.style.SUCCESS(f'{status}: {email} avec le rôle {role}'))

        # Note: Les modèles de questionnaire et les dossiers de démo seront ajoutés plus tard.
        self.stdout.write(self.style.SUCCESS('Base de données initialisée avec les rôles clés.'))