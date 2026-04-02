from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-for-coursework'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tasktracker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# настройка папки для загрузки файлов
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# настройка менеджера авторизации
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "Пожалуйста, войдите для доступа."
login_manager.login_message_category = "warning"

# модели
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='user') 

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

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
    file_path = db.Column(db.String(255), nullable=True) 
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    assignee = db.relationship('User', backref='assigned_tasks', foreign_keys=[assignee_id])

with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Маршруты

# главная страница (дашборд)
@app.route('/')
@login_required
def index():
    projects = Project.query.all()
    
    # агрегирование данных для круговой диаграммы
    total_tasks = Task.query.count()
    pending_tasks = Task.query.filter_by(status='pending').count()
    in_progress_tasks = Task.query.filter_by(status='in_progress').count()
    done_tasks = Task.query.filter_by(status='done').count()
    
    # упаковываем статистику в словарь, чтобы передать в HTML
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


# страница проекта (с рабочим поиском и фильтром)
@app.route('/project/<int:project_id>')
@login_required
def project_view(project_id):
    project = Project.query.get_or_404(project_id)
    users = User.query.all() 
    
    # базовый запрос: берем все задачи этого проекта
    query = Task.query.filter_by(project_id=project.id)
    
    # получаем параметры из поисковой строки
    search_query = request.args.get('search')
    status_filter = request.args.get('status')
    
    # если пользователь что-то ищет, фильтруем базу данных
    if search_query:
        query = query.filter(Task.title.ilike(f'%{search_query}%'))
    if status_filter:
        query = query.filter_by(status=status_filter)
        
    page = request.args.get('page', 1, type=int)
    tasks = query.paginate(page=page, per_page=5)
    
    return render_template('project.html', project=project, tasks=tasks, users=users)

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


# редактирование задачи (смена статуса и загрузка файла)
@app.route('/task/<int:task_id>/update', methods=['POST'])
@login_required
def update_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    # менять задачу может только админ и тот, кому она назначена
    if current_user.role != 'admin' and current_user.id != task.assignee_id:
        flash('Вы не можете редактировать чужую задачу.', 'danger')
        return redirect(url_for('project_view', project_id=task.project_id))
        
    # обновляем статус
    new_status = request.form.get('status')
    if new_status:
        task.status = new_status
        
    # сохраняем загруженный файл
    if 'file' in request.files:
        file = request.files['file']
        if file and file.filename != '':
            # задаем безопасное имя файла от Werkzeug
            filename = secure_filename(file.filename) 
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            # сохраняем путь в базу данных
            task.file_path = f"static/uploads/{filename}"
            
    db.session.commit()
    flash('Задача обновлена!', 'success')
    return redirect(url_for('project_view', project_id=task.project_id))

# удаление проекта (только для админа)
@app.route('/project/<int:project_id>/delete', methods=['POST'])
@login_required
def delete_project(project_id):
    if current_user.role != 'admin':
        flash('У вас нет прав для удаления проектов.', 'danger')
        return redirect(url_for('index'))
        
    project = Project.query.get_or_404(project_id)
    db.session.delete(project)
    db.session.commit()
    
    flash(f'Проект "{project.title}" был успешно удален.', 'success')
    return redirect(url_for('index'))    

# Авторизация

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
        flash('Регистрация успешно завершена!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('Неверный логин или пароль.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)