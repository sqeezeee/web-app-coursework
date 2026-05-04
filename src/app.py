from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-for-coursework'

# Берем ссылку на БД из хостинга, иначе используем локальную базу
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or 'sqlite:///tasktracker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Настройка папки для файлов
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Менеджер авторизации
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "Пожалуйста, войдите для доступа."
login_manager.login_message_category = "warning"

# ================= МОДЕЛИ БАЗЫ ДАННЫХ =================
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='user') 

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Project(db.Model):
    __tablename__ = 'projects'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    tasks = db.relationship('Task', backref='project', lazy=True, cascade="all, delete-orphan")

class Task(db.Model):
    __tablename__ = 'tasks'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending') 
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    assignee = db.relationship('User', backref='assigned_tasks', foreign_keys=[assignee_id])
    # Связь 1-ко-Многим с новой таблицей файлов
    attachments = db.relationship('Attachment', backref='task', lazy=True, cascade="all, delete-orphan")

# 4-Я СУЩНОСТЬ: Вложения (прикрепляемые файлы)
class Attachment(db.Model):
    __tablename__ = 'attachments'
    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)

# ======================================================

with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ================= МАРШРУТЫ ПРОЕКТОВ И ДАШБОРДА =================
@app.route('/')
@login_required
def index():
    if current_user.role == 'admin':
        projects = Project.query.all()
        total_tasks = Task.query.count()
        pending_tasks = Task.query.filter_by(status='pending').count()
        in_progress_tasks = Task.query.filter_by(status='in_progress').count()
        done_tasks = Task.query.filter_by(status='done').count()
    else:
        projects = Project.query.join(Task).filter(Task.assignee_id == current_user.id).distinct().all()
        total_tasks = Task.query.filter_by(assignee_id=current_user.id).count()
        pending_tasks = Task.query.filter_by(assignee_id=current_user.id, status='pending').count()
        in_progress_tasks = Task.query.filter_by(assignee_id=current_user.id, status='in_progress').count()
        done_tasks = Task.query.filter_by(assignee_id=current_user.id, status='done').count()

    stats = {
        'total': total_tasks,
        'pending': pending_tasks,
        'in_progress': in_progress_tasks,
        'done': done_tasks
    }
    return render_template('index.html', projects=projects, stats=stats)

@app.route('/create_project', methods=['POST'])
@login_required
def create_project():
    if current_user.role != 'admin':
        flash('У вас нет прав для создания проектов.', 'danger')
        return redirect(url_for('index'))
    title = request.form.get('title')
    description = request.form.get('description')
    if title:
        new_project = Project(title=title, description=description, owner_id=current_user.id)
        db.session.add(new_project)
        db.session.commit()
        flash('Проект успешно создан!', 'success')
    return redirect(url_for('index'))

@app.route('/project/<int:project_id>/delete', methods=['POST'])
@login_required
def delete_project(project_id):
    if current_user.role != 'admin':
        flash('У вас нет прав для удаления проектов.', 'danger')
        return redirect(url_for('index'))
        
    project = Project.query.get_or_404(project_id)
    
    # Физическое удаление ВСЕХ файлов проекта с сервера
    for task in project.tasks:
        for attachment in task.attachments:
            full_path = os.path.join(app.root_path, attachment.file_path)
            if os.path.exists(full_path):
                os.remove(full_path)
                
    db.session.delete(project)
    db.session.commit()
    flash(f'Проект "{project.title}" и все его файлы успешно удалены.', 'success')
    return redirect(url_for('index'))

# ================= МАРШРУТЫ ЗАДАЧ И ФАЙЛОВ =================
@app.route('/project/<int:project_id>')
@login_required
def project_view(project_id):
    project = Project.query.get_or_404(project_id)
    users = User.query.all() 
    
    if current_user.role != 'admin':
        user_has_tasks = Task.query.filter_by(project_id=project.id, assignee_id=current_user.id).first()
        if not user_has_tasks:
            flash('У вас нет доступа к этому проекту.', 'danger')
            return redirect(url_for('index'))
            
    total_project_tasks = Task.query.filter_by(project_id=project.id).count()
    done_project_tasks = Task.query.filter_by(project_id=project.id, status='done').count()
    
    progress = int((done_project_tasks / total_project_tasks) * 100) if total_project_tasks > 0 else 0

    query = Task.query.filter_by(project_id=project.id)
    search_query = request.args.get('search')
    status_filter = request.args.get('status')
    
    if search_query:
        query = query.filter(Task.title.ilike(f'%{search_query}%'))
    if status_filter:
        query = query.filter_by(status=status_filter)
        
    page = request.args.get('page', 1, type=int)
    tasks = query.paginate(page=page, per_page=5)
    
    return render_template('project.html', project=project, tasks=tasks, users=users, progress=progress)

@app.route('/project/<int:project_id>/add_task', methods=['POST'])
@login_required
def add_task(project_id):
    if current_user.role != 'admin':
        flash('Только администратор может ставить задачи.', 'danger')
        return redirect(url_for('project_view', project_id=project_id))
        
    title = request.form.get('title')
    assignee_id = request.form.get('assignee_id')
    
    if title:
        assignee_id = int(assignee_id) if assignee_id else None
        new_task = Task(title=title, project_id=project_id, assignee_id=assignee_id)
        db.session.add(new_task)
        db.session.commit()
        flash('Задача успешно добавлена!', 'success')
        
    return redirect(url_for('project_view', project_id=project_id))

@app.route('/task/<int:task_id>/update', methods=['POST'])
@login_required
def update_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    if current_user.role != 'admin' and current_user.id != task.assignee_id:
        flash('Вы не можете редактировать чужую задачу.', 'danger')
        return redirect(url_for('project_view', project_id=task.project_id))
        
    new_status = request.form.get('status')
    if new_status:
        task.status = new_status
        
    # Смена исполнителя
    if current_user.role == 'admin':
        new_assignee_id = request.form.get('assignee_id')
        if new_assignee_id is not None:
            task.assignee_id = int(new_assignee_id) if new_assignee_id != '' else None
        
    # МНОЖЕСТВЕННАЯ ЗАГРУЗКА ФАЙЛОВ
    if 'files' in request.files:
        files = request.files.getlist('files')
        for file in files:
            if file and file.filename != '':
                original_filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{original_filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(file_path)
                
                new_attachment = Attachment(
                    file_name=original_filename,
                    file_path=f"static/uploads/{unique_filename}",
                    task_id=task.id
                )
                db.session.add(new_attachment)
                
    db.session.commit()
    flash('Задача обновлена!', 'success')
    return redirect(url_for('project_view', project_id=task.project_id))

@app.route('/task/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    project_id = task.project_id
    
    if current_user.role != 'admin':
        flash('Только администратор может удалять задачи.', 'danger')
        return redirect(url_for('project_view', project_id=project_id))
    
    # Удаляем файлы с сервера перед удалением задачи
    for attachment in task.attachments:
        full_path = os.path.join(app.root_path, attachment.file_path)
        if os.path.exists(full_path):
            os.remove(full_path)
            
    db.session.delete(task)
    db.session.commit()
    flash('Задача успешно удалена!', 'success')
    return redirect(url_for('project_view', project_id=project_id))

# Точечное удаление конкретного файла
@app.route('/attachment/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_attachment(attachment_id):
    attachment = Attachment.query.get_or_404(attachment_id)
    task = attachment.task
    project_id = task.project_id
    
    if current_user.role != 'admin' and current_user.id != task.assignee_id:
        flash('У вас нет прав удалять этот файл.', 'danger')
        return redirect(url_for('project_view', project_id=project_id))

    # Удаляем файл физически
    full_path = os.path.join(app.root_path, attachment.file_path)
    if os.path.exists(full_path):
        os.remove(full_path)
        
    db.session.delete(attachment)
    db.session.commit()
    flash('Файл удален!', 'success')
    return redirect(url_for('project_view', project_id=project_id))

# ================= АВТОРИЗАЦИЯ =================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')
        
        user_exists = User.query.filter_by(username=username).first()
        if user_exists:
            flash('Пользователь с таким логином уже существует!', 'danger')
            return redirect(url_for('register'))
            
        new_user = User(username=username, role=role)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash('Регистрация успешно завершена! Теперь вы можете войти.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=remember)
            flash(f'С возвращением, {user.username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Неверный логин или пароль.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы успешно вышли из системы.', 'info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)