from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User

# создаем Blueprint с именем 'auth'
auth = Blueprint('auth', __name__)

@auth.route('/login', methods=['GET', 'POST'])
def login():
    # .is_authenticated проверяет наличие активной сессии
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
        
    # если форма была отправлена методом POST, начинаем проверку
    if request.method == 'POST':
        # request.form — это словарь с данными из HTML-формы. .get() безопасно извлекает значение по ключу
        username = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        
        # обращаемся к модели User. через .query делаем запрос к БД. 
        # .filter_by ищет нужную строку, а .first() возвращает первый найденный объект (или None)
        user = User.query.filter_by(username=username).first()
        
        # если юзер найден и его хэш пароля совпадает с введенным
        if user and user.check_password(password):
            # функция login_user создает сессию для пользователя и записывает session_id в cookie браузера
            login_user(user, remember=remember)
            flash(f'С возвращением, {user.username}!', 'success')
            # url_for генерирует ссылку динамически. 'main.index' значит "найди функцию index в блюпринте main"
            return redirect(url_for('main.index'))
        else:
            flash('Неверный логин или пароль.', 'danger')
            
    return render_template('login.html')

@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # проверяем, нет ли уже человека с таким логином в базе, чтобы избежать ошибки уникальности
        user_exists = User.query.filter_by(username=username).first()
        if user_exists:
            flash('Пользователь с таким логином уже существует!', 'danger')
            return redirect(url_for('auth.register'))
        
        # создаем новый экземпляр класса User. новые юзеры по умолчанию получают базовую роль
        new_user = User(username=username, role='user')
        new_user.set_password(password)
        
        # db.session — это текущая транзакция. .add() добавляет туда объект.
        db.session.add(new_user)
        # .commit() физически сохраняет изменения из транзакции в файл базы данных
        db.session.commit()
        
        flash('Регистрация успешно завершена! Теперь вы можете войти.', 'success')
        return redirect(url_for('auth.login'))
        
    return render_template('register.html')

@auth.route('/logout')
@login_required
def logout():
    # очищаем сессию пользователя на сервере и удаляем cookie авторизации из браузера
    logout_user()
    flash('Вы успешно вышли из системы.', 'info')
    return redirect(url_for('auth.login'))