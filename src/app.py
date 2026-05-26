from flask import Flask
import os
from models import db, User
from flask_login import LoginManager

# создаем объект веб-приложения Flask
app = Flask(__name__)

# конфигурация безопасности и базы данных
app.config['SECRET_KEY'] = 'super-secret-key-for-coursework'
# Если хостинг не дал ссылку, используем локальный PostgreSQL из докера
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or 'postgresql://postgres:mysecretpassword@localhost:5432/postgres'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# настройка папки для загрузки пользовательских файлов
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')

# связываем экземпляр базы данных SQLAlchemy с нашим Flask-приложением
db.init_app(app)

# инициализируем LoginManager для контроля сессий
login_manager = LoginManager()
login_manager.init_app(app)

# если гость попытается зайти на закрытую страницу, перенаправляем его на auth.login
login_manager.login_view = 'auth.login'
login_manager.login_message = "Пожалуйста, войдите для доступа к этой странице."
login_manager.login_message_category = "warning"

# эта функция помогает Flask-Login извлекать объект пользователя из базы по ID сессии
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# РЕГИСТРАЦИЯ МОДУЛЕЙ (Blueprints)
# импортируем и регистрируем независимые куски кода для структурирования приложения
from auth import auth as auth_blueprint
app.register_blueprint(auth_blueprint)

from routes import main as main_blueprint
app.register_blueprint(main_blueprint)

# контекст приложения: создание таблиц при запуске сервера
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)