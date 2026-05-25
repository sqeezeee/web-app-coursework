from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

# создаем объект базы данных, пока не привязываем его к приложению, это будет сделано в файле app.py через метод init_app()
db = SQLAlchemy()


# UserMixin добавляет классу базовые методы для Flask-Login (is_authenticated и т.д.)
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    # db.Column создает колонку
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='user') 

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        # переводим открытый пароль в хэш с помощью надежного алгоритма pbkdf2:sha256. 
        # self означает, что мы сохраняем хэш в атрибут именно текущего пользователя
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        # сверяем хэш из базы с тем паролем, который пользователь ввел при логине
        return check_password_hash(self.password_hash, password)


class Project(db.Model):
    __tablename__ = 'projects'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    # внешний ключ (ForeignKey), который связывает проект с его создателем из таблицы users
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # relationship это виртуальная связь для SQLAlchemy.
    # благодаря ей мы можем написать project.tasks и получить список всех задач проекта.
    # cascade="all, delete-orphan" гарантирует, что при удалении проекта удалятся все его задачи.
    tasks = db.relationship('Task', backref='project', lazy=True, cascade="all, delete-orphan")


class Task(db.Model):
    __tablename__ = 'tasks'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending') 
    
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # указываем foreign_keys явно, чтобы SQLAlchemy понимала, по какому полю связывать задачу с пользователем-исполнителем
    assignee = db.relationship('User', backref='assigned_tasks', foreign_keys=[assignee_id])
    attachments = db.relationship('Attachment', backref='task', lazy=True, cascade="all, delete-orphan")


class Attachment(db.Model):
    __tablename__ = 'attachments'
    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(255), nullable=False) 
    file_path = db.Column(db.String(255), nullable=False) 
    file_type = db.Column(db.String(20), nullable=True)
    
    uploader_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    
    uploader = db.relationship('User', backref='uploaded_files', foreign_keys=[uploader_id])