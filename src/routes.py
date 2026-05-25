from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from models import db, Project, Task, Attachment, User
from werkzeug.utils import secure_filename
import os
import uuid

main = Blueprint('main', __name__)

@main.route('/')
@login_required # декоратор, который не пустит сюда гостя без сессии авторизации
def index():
    if current_user.role == 'admin':
        # администратор видит только проекты, где он является владельцем (owner_id)
        projects = Project.query.filter_by(owner_id=current_user.id).all()
        # генератор списка: собираем id всех проектов админа
        project_ids = [p.id for p in projects]
        
        # агрегация данных. .count() возвращает количество найденных строк
        # Task.project_id.in_(project_ids) фильтрует задачи только внутри проектов админа
        total_tasks = Task.query.filter(Task.project_id.in_(project_ids)).count() if project_ids else 0
        pending_tasks = Task.query.filter(Task.project_id.in_(project_ids), Task.status=='pending').count() if project_ids else 0
        in_progress_tasks = Task.query.filter(Task.project_id.in_(project_ids), Task.status=='in_progress').count() if project_ids else 0
        done_tasks = Task.query.filter(Task.project_id.in_(project_ids), Task.status=='done').count() if project_ids else 0
    else:
        # для исполнителя собираем проекты, к которым он привязан через свои задачи.
        projects = Project.query.join(Task).filter(Task.assignee_id == current_user.id).distinct().all()
        
        total_tasks = Task.query.filter_by(assignee_id=current_user.id).count()
        pending_tasks = Task.query.filter_by(assignee_id=current_user.id, status='pending').count()
        in_progress_tasks = Task.query.filter_by(assignee_id=current_user.id, status='in_progress').count()
        done_tasks = Task.query.filter_by(assignee_id=current_user.id, status='done').count()

    # упаковываем статистику в словарь, чтобы передать в HTML-шаблон для отрисовки графиков
    stats = {
        'total': total_tasks,
        'pending': pending_tasks,
        'in_progress': in_progress_tasks,
        'done': done_tasks
    }
    return render_template('index.html', projects=projects, stats=stats)

@main.route('/create_project', methods=['POST'])
@login_required
def create_project():
    # защита маршрута от прямого POST-запроса не-администратором
    if current_user.role != 'admin':
        flash('У вас нет прав для создания проектов.', 'danger')
        return redirect(url_for('main.index'))
        
    title = request.form.get('title')
    description = request.form.get('description')
    
    if title:
        new_project = Project(title=title, description=description, owner_id=current_user.id)
        db.session.add(new_project)
        db.session.commit()
        flash('Проект успешно создан!', 'success')
    return redirect(url_for('main.index'))

@main.route('/project/<int:project_id>/edit', methods=['POST'])
@login_required
def edit_project(project_id):
    # .get_or_404 — безопасный поиск. если ID не существует, Flask сам выдаст страницу ошибки 404
    project = Project.query.get_or_404(project_id)
    
    if current_user.role != 'admin' or project.owner_id != current_user.id:
        flash('У вас нет прав редактировать этот проект.', 'danger')
        return redirect(url_for('main.index'))
        
    project.title = request.form.get('title')
    project.description = request.form.get('description')
    db.session.commit()
    flash('Проект успешно обновлен!', 'success')
    return redirect(url_for('main.project_view', project_id=project.id))

@main.route('/project/<int:project_id>/delete', methods=['POST'])
@login_required
def delete_project(project_id):
    project = Project.query.get_or_404(project_id)
    
    if current_user.role != 'admin' or project.owner_id != current_user.id:
        flash('У вас нет прав для удаления этого проекта.', 'danger')
        return redirect(url_for('main.index'))
    
    # перед удалением проекта из базы, физически удаляем все файлы с жесткого диска сервера
    # current_app.root_path дает нам абсолютный путь до папки src на текущем сервере
    for task in project.tasks:
        for attachment in task.attachments:
            full_path = os.path.join(current_app.root_path, attachment.file_path)
            if os.path.exists(full_path):
                os.remove(full_path)
                
    db.session.delete(project)
    db.session.commit()
    flash(f'Проект "{project.title}" и все его файлы удалены.', 'success')
    return redirect(url_for('main.index'))


@main.route('/project/<int:project_id>')
@login_required
def project_view(project_id):
    project = Project.query.get_or_404(project_id)
    users = User.query.all() 
    
    # строгая проверка изоляции проектов: админ видит только свои, юзер - только где он исполнитель
    if current_user.role == 'admin':
        if project.owner_id != current_user.id:
            flash('У вас нет доступа к чужому проекту.', 'danger')
            return redirect(url_for('main.index'))
    else:
        user_has_tasks = Task.query.filter_by(project_id=project.id, assignee_id=current_user.id).first()
        if not user_has_tasks:
            flash('У вас нет доступа к этому проекту.', 'danger')
            return redirect(url_for('main.index'))
            
    # вычисляем прогресс выполнения проекта для шкалы готовности
    total_project_tasks = Task.query.filter_by(project_id=project.id).count()
    done_project_tasks = Task.query.filter_by(project_id=project.id, status='done').count()
    progress = int((done_project_tasks / total_project_tasks) * 100) if total_project_tasks > 0 else 0

    # инициализируем базовый запрос к таблице задач
    query = Task.query.filter_by(project_id=project.id)
    
    # request.args хранит параметры из адресной строки (GET-запрос)
    search_query = request.args.get('search')
    status_filter = request.args.get('status')
    
    # применяем фильтры к запросу, если пользователь их передал
    if search_query:
        # .ilike() делает поиск по тексту без учета регистра (большие/маленькие буквы)
        query = query.filter(Task.title.ilike(f'%{search_query}%'))
    if status_filter:
        query = query.filter_by(status=status_filter)
        
    # .paginate() автоматически разбивает результат на страницы
    page = request.args.get('page', 1, type=int)
    tasks = query.paginate(page=page, per_page=5)
    
    return render_template('project.html', project=project, tasks=tasks, users=users, progress=progress)

@main.route('/project/<int:project_id>/add_task', methods=['POST'])
@login_required
def add_task(project_id):
    project = Project.query.get_or_404(project_id)
    if current_user.role != 'admin' or project.owner_id != current_user.id:
        flash('Только администратор проекта может ставить задачи.', 'danger')
        return redirect(url_for('main.project_view', project_id=project_id))
        
    title = request.form.get('title')
    description = request.form.get('description')
    assignee_id = request.form.get('assignee_id')
    
    if title:
        # если исполнитель не выбран (пустая строка), сохраняем в базу None
        assignee_id = int(assignee_id) if assignee_id else None
        new_task = Task(title=title, description=description, project_id=project_id, assignee_id=assignee_id)
        db.session.add(new_task)
        db.session.commit()
        
        # логика загрузки стартовых файлов администратором
        if 'files' in request.files:
            # .getlist() извлекает массив файлов, переданных через input multiple
            files = request.files.getlist('files')
            for file in files:
                if file and file.filename != '':
                    # secure_filename удаляет опасные символы (слэши) из имени файла для защиты от уязвимостей
                    original_filename = secure_filename(file.filename)
                    # добавляем UUID префикс для исключения коллизий (совпадения имен файлов)
                    unique_filename = f"{uuid.uuid4().hex}_{original_filename}"
                    
                    # определяем тип файла, разбивая название по точке с конца (.rsplit)
                    file_ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else 'unknown'
                    
                    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                    file.save(file_path)
                    
                    new_attachment = Attachment(
                        file_name=original_filename,
                        file_path=f"static/uploads/{unique_filename}",
                        file_type=file_ext,
                        task_id=new_task.id,
                        uploader_id=current_user.id
                    )
                    db.session.add(new_attachment)
            db.session.commit()
            
        flash('Задача успешно добавлена!', 'success')
    return redirect(url_for('main.project_view', project_id=project_id))

@main.route('/task/<int:task_id>/update', methods=['POST'])
@login_required
def update_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    if current_user.role != 'admin' and current_user.id != task.assignee_id:
        flash('Вы не можете редактировать чужую задачу.', 'danger')
        return redirect(url_for('main.project_view', project_id=task.project_id))
        
    new_status = request.form.get('status')
    if new_status:
        task.status = new_status
        
    # если обновляет админ, даем ему возможность поменять описание и переназначить исполнителя
    if current_user.role == 'admin':
        new_title = request.form.get('title')
        new_desc = request.form.get('description')
        if new_title: 
            task.title = new_title
        if new_desc is not None: 
            task.description = new_desc
            
        new_assignee_id = request.form.get('assignee_id')
        if new_assignee_id is not None:
            task.assignee_id = int(new_assignee_id) if new_assignee_id != '' else None
            
    # загрузка новых файлов-отчетов
    if 'files' in request.files:
        files = request.files.getlist('files')
        for file in files:
            if file and file.filename != '':
                original_filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{original_filename}"
                file_ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else 'unknown'
                
                file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(file_path)
                
                new_attachment = Attachment(
                    file_name=original_filename,
                    file_path=f"static/uploads/{unique_filename}",
                    file_type=file_ext,
                    task_id=task.id,
                    uploader_id=current_user.id
                )
                db.session.add(new_attachment)
                
    db.session.commit()
    flash('Задача обновлена!', 'success')
    return redirect(url_for('main.project_view', project_id=task.project_id))

@main.route('/task/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    project_id = task.project_id
    
    if current_user.role != 'admin':
        flash('Только администратор может удалять задачи.', 'danger')
        return redirect(url_for('main.project_view', project_id=project_id))
    
    # физически удаляем файлы, связанные с задачей
    for attachment in task.attachments:
        full_path = os.path.join(current_app.root_path, attachment.file_path)
        if os.path.exists(full_path):
            os.remove(full_path)
            
    db.session.delete(task)
    db.session.commit()
    flash('Задача успешно удалена!', 'success')
    return redirect(url_for('main.project_view', project_id=project_id))

@main.route('/attachment/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_attachment(attachment_id):
    attachment = Attachment.query.get_or_404(attachment_id)
    task = attachment.task
    project_id = task.project_id
    
    # файл может удалить либо админ, либо тот, кто его загрузил
    if current_user.role != 'admin' and current_user.id != attachment.uploader_id:
        flash('У вас нет прав удалять этот файл.', 'danger')
        return redirect(url_for('main.project_view', project_id=project_id))

    # удаляем файл физически через системную библиотеку os
    full_path = os.path.join(current_app.root_path, attachment.file_path)
    if os.path.exists(full_path):
        os.remove(full_path)
        
    db.session.delete(attachment)
    db.session.commit()
    flash('Файл удален!', 'success')
    return redirect(url_for('main.project_view', project_id=project_id))