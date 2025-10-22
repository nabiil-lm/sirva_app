# Dockerfile

# Utiliser l'image officielle Python pour la version 3.12 (ou autre version LTS)
FROM python:3.12-slim

# Empêcher Python d'écrire des fichiers .pyc (meilleur pour les conteneurs)
ENV PYTHONDONTWRITEBYTECODE 1
# Forcer la sortie de logs vers la console (essentiel pour Docker)
ENV PYTHONUNBUFFERED 1

# Définir le répertoire de travail dans le conteneur
WORKDIR /app

# Copier le fichier de dépendances et les installer
# Note : Nous n'avons pas encore de requirements.txt, mais c'est la bonne pratique
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copier le reste du code de l'application
COPY . /app/

# Port que le conteneur va écouter
EXPOSE 8000

# Commande par défaut pour démarrer le serveur (sera override par docker-compose)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
