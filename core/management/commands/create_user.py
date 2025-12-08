from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from core.models import Role

User = get_user_model()


class Command(BaseCommand):
    help = 'Create a new user account with specified role'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            required=True,
            help='Email address for the new user'
        )
        parser.add_argument(
            '--password',
            type=str,
            required=True,
            help='Password for the new user'
        )
        parser.add_argument(
            '--role',
            type=str,
            required=True,
            choices=['AM', 'SO', 'ADMIN'],
            help='Role for the new user (AM, SO, or ADMIN)'
        )
        parser.add_argument(
            '--first-name',
            type=str,
            default='',
            help='First name of the user (optional)'
        )
        parser.add_argument(
            '--last-name',
            type=str,
            default='',
            help='Last name of the user (optional)'
        )
        parser.add_argument(
            '--is-staff',
            action='store_true',
            help='Make user staff member (for admin access)'
        )
        parser.add_argument(
            '--is-superuser',
            action='store_true',
            help='Make user superuser (for admin access)'
        )

    def handle(self, *args, **options):
        email = options['email']
        password = options['password']
        role = options['role']
        first_name = options.get('first_name', '')
        last_name = options.get('last_name', '')
        is_staff = options.get('is_staff', False)
        is_superuser = options.get('is_superuser', False)

        # Validate email
        if not email or '@' not in email:
            raise CommandError('Invalid email address')

        # Check if user already exists
        if User.objects.filter(email=email).exists():
            raise CommandError(f'User with email "{email}" already exists')


        # Validate role
        valid_roles = [Role.AM, Role.SO, Role.ADMIN]
        if role not in valid_roles:
            raise CommandError(f'Role must be one of: {", ".join(valid_roles)}')

        try:
            # Create the user
            user = User.objects.create_user(
                email=email,
                password=password,
                role=role,
                first_name=first_name,
                last_name=last_name,
                is_staff=is_staff,
                is_superuser=is_superuser
            )

            # Display success message
            self.stdout.write(
                self.style.SUCCESS('✓ User created successfully!')
            )
            self.stdout.write(f'  Email: {user.email}')
            self.stdout.write(f'  Role: {user.get_role_display()}')
            if first_name or last_name:
                self.stdout.write(f'  Name: {first_name} {last_name}')
            if is_staff:
                self.stdout.write('  Staff: Yes')
            if is_superuser:
                self.stdout.write('  Superuser: Yes')

        except Exception as e:
            raise CommandError(f'Error creating user: {str(e)}')
