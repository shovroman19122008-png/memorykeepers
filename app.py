from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
import os
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, ValidationError

app = Flask(__name__)
import os
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///memories_platform.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

csrf = CSRFProtect(app)
db = SQLAlchemy(app)

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


# --- Модели ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='customer')  # 'customer' или 'master'
    city = db.Column(db.String(100), nullable=True)
    about = db.Column(db.Text, nullable=True)  # описание для мастеров
    rating = db.Column(db.Float, default=0.0)  # средний рейтинг мастера
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Отношения
    portfolio = db.relationship('PortfolioImage', backref='master', lazy=True)
    master_categories = db.relationship('MasterCategory', backref='master', lazy=True)
    reviews_received = db.relationship('Review', backref='master', lazy=True, foreign_keys='Review.master_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def update_rating(self):
        """Обновить средний рейтинг на основе отзывов"""
        reviews = Review.query.filter_by(master_id=self.id).all()
        if reviews:
            self.rating = round(sum(r.rating for r in reviews) / len(reviews), 1)
        else:
            self.rating = 0.0
        db.session.commit()


class PortfolioImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    masters = db.relationship('MasterCategory', backref='category', lazy=True)


class MasterCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    master_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='in_progress')  # in_progress, completed, cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Отношения
    customer = db.relationship('User', foreign_keys=[customer_id], backref='orders_as_customer')
    master = db.relationship('User', foreign_keys=[master_id], backref='orders_as_master')
    messages = db.relationship('Message', backref='order', lazy=True, order_by='Message.timestamp')
    review = db.relationship('Review', backref='order', uselist=False, lazy=True)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), unique=True, nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    master_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # от 1 до 5
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# --- Формы ---

class RegistrationForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired(), Length(min=4, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Пароль', validators=[DataRequired(), Length(min=8)])
    role = SelectField('Я хочу', choices=[
        ('customer', 'Заказывать услуги'),
        ('master', 'Предлагать услуги мастера')
    ], validators=[DataRequired()])
    city = StringField('Город', validators=[DataRequired(), Length(max=100)])
    submit = SubmitField('Зарегистрироваться')


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    submit = SubmitField('Войти')


class ProfileEditForm(FlaskForm):
    username = StringField('Имя', validators=[DataRequired(), Length(min=2, max=80)])
    city = StringField('Город', validators=[DataRequired(), Length(max=100)])
    about = TextAreaField('О себе (для мастеров)', validators=[Length(max=500)])
    submit = SubmitField('Сохранить')


# --- Инициализация БД и категорий ---

with app.app_context():
    db.create_all()

    # Создаём категории, если их нет
    categories = ['Картины', 'Скульптуры', 'Фотокниги', 'Видео']
    for cat_name in categories:
        if not Category.query.filter_by(name=cat_name).first():
            db.session.add(Category(name=cat_name))
    db.session.commit()


# --- Маршруты ---

@app.route('/')
def index():
    # Получаем последних мастеров для главной
    masters = User.query.filter_by(role='master').order_by(User.rating.desc()).limit(6).all()
    categories = Category.query.all()
    return render_template('index.html', masters=masters, categories=categories)


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash('Этот email уже зарегистрирован', 'error')
            return redirect(url_for('register'))

        user = User(
            username=form.username.data,
            email=form.email.data,
            role=form.role.data,
            city=form.city.data
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        session['user_id'] = user.id
        session['username'] = user.username
        session['role'] = user.role

        flash('Регистрация успешна!', 'success')
        return redirect(url_for('index'))

    return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash('Вход выполнен успешно!', 'success')
            return redirect(url_for('index'))
        flash('Неверный email или пароль', 'error')

    return render_template('login.html', form=form)


@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/create', methods=['GET', 'POST'])
def create():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'error')
        return redirect(url_for('login'))
    return render_template('create.html')


# --- ДОБАВИТЬ в app.py после существующих маршрутов ---

@app.route('/masters')
def masters_list():
    """Поиск мастеров с фильтрацией"""
    # Получаем параметры фильтрации
    category_filter = request.args.get('category', type=int)
    city_filter = request.args.get('city', '').strip()
    sort_by = request.args.get('sort', 'rating')  # rating или new
    search_query = request.args.get('query', '').strip()

    # Базовый запрос
    query = User.query.filter_by(role='master')

    # Фильтр по категории
    if category_filter:
        query = query.join(MasterCategory).filter(MasterCategory.category_id == category_filter)

    # Фильтр по городу
    if city_filter:
        query = query.filter(User.city.ilike(f'%{city_filter}%'))

    # Поиск по имени или описанию
    if search_query:
        query = query.filter(
            db.or_(
                User.username.ilike(f'%{search_query}%'),
                User.about.ilike(f'%{search_query}%')
            )
        )

    # Сортировка
    if sort_by == 'new':
        query = query.order_by(User.created_at.desc())
    else:  # rating
        query = query.order_by(User.rating.desc())

    masters = query.all()
    categories = Category.query.all()
    cities = db.session.query(User.city).filter_by(role='master').distinct().all()
    cities = [c[0] for c in cities if c[0]]  # список уникальных городов

    return render_template('masters.html',
                           masters=masters,
                           categories=categories,
                           cities=cities,
                           current_category=category_filter,
                           current_city=city_filter,
                           current_sort=sort_by,
                           current_query=search_query)


@app.route('/profile/<int:user_id>')
def profile(user_id):
    """Профиль пользователя/мастера"""
    user = User.query.get_or_404(user_id)

    # Если это мастер, получаем дополнительную информацию
    if user.role == 'master':
        categories = [mc.category for mc in user.master_categories]
        portfolio = user.portfolio
        reviews = Review.query.filter_by(master_id=user.id).order_by(Review.created_at.desc()).all()
    else:
        categories = None
        portfolio = None
        reviews = None

    # Проверяем, есть ли активный заказ между текущим пользователем и этим мастером
    active_order = None
    if session.get('user_id') and user.role == 'master':
        active_order = Order.query.filter(
            Order.customer_id == session['user_id'],
            Order.master_id == user_id,
            Order.status == 'in_progress'
        ).first()

    return render_template('profile.html',
                           user=user,
                           categories=categories,
                           portfolio=portfolio,
                           reviews=reviews,
                           active_order=active_order)


@app.route('/profile/edit', methods=['GET', 'POST'])
def edit_profile():
    """Редактирование профиля"""
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'error')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    form = ProfileEditForm(obj=user)
    categories = Category.query.all()

    if form.validate_on_submit():
        user.username = form.username.data
        user.city = form.city.data
        user.about = form.about.data

        # Если пользователь — мастер, обновляем категории и портфолио
        if user.role == 'master':
            # Обработка категорий
            selected_categories = request.form.getlist('categories')
            # Удаляем старые связи
            MasterCategory.query.filter_by(user_id=user.id).delete()
            # Добавляем новые
            for cat_id in selected_categories:
                master_cat = MasterCategory(user_id=user.id, category_id=int(cat_id))
                db.session.add(master_cat)

            # Обработка загрузки фотографий портфолио
            files = request.files.getlist('portfolio_images')
            for file in files:
                if file and file.filename:
                    # Проверяем расширение
                    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
                    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                    if ext in allowed_extensions:
                        # Генерируем уникальное имя файла
                        filename = f"portfolio_{user.id}_{datetime.utcnow().timestamp()}.{ext}"
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        file.save(file_path)

                        # Сохраняем в БД
                        portfolio_image = PortfolioImage(user_id=user.id, filename=filename)
                        db.session.add(portfolio_image)

        db.session.commit()
        flash('Профиль обновлён!', 'success')
        return redirect(url_for('profile', user_id=user.id))

    return render_template('edit_profile.html',
                           form=form,
                           user=user,
                           categories=categories)


@app.route('/portfolio/delete/<int:image_id>', methods=['POST'])
def delete_portfolio_image(image_id):
    """Удаление фото из портфолио"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    image = PortfolioImage.query.get_or_404(image_id)

    # Проверяем, что это фото принадлежит текущему пользователю
    if image.user_id != session['user_id']:
        flash('Доступ запрещён', 'error')
        return redirect(url_for('profile', user_id=session['user_id']))

    # Удаляем файл
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], image.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    db.session.delete(image)
    db.session.commit()

    flash('Фото удалено', 'success')
    return redirect(url_for('edit_profile'))


# --- ДОБАВИТЬ в app.py после существующих маршрутов ---

@app.route('/order/create/<int:master_id>', methods=['GET', 'POST'])
def create_order(master_id):
    """Создание заказа мастеру"""
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'error')
        return redirect(url_for('login'))

    master = User.query.get_or_404(master_id)

    if master.role != 'master':
        flash('Этот пользователь не является мастером', 'error')
        return redirect(url_for('index'))

    if master.id == session['user_id']:
        flash('Вы не можете создать заказ самому себе', 'error')
        return redirect(url_for('profile', user_id=master_id))

    # Проверяем, нет ли уже активного заказа
    existing_order = Order.query.filter(
        Order.customer_id == session['user_id'],
        Order.master_id == master_id,
        Order.status == 'in_progress'
    ).first()

    if existing_order:
        flash('У вас уже есть активный заказ с этим мастером', 'info')
        return redirect(url_for('order_detail', order_id=existing_order.id))

    if request.method == 'POST':
        description = request.form.get('description', '').strip()

        if not description:
            flash('Пожалуйста, опишите ваш заказ', 'error')
            return render_template('create_order.html', master=master)

        order = Order(
            customer_id=session['user_id'],
            master_id=master_id,
            status='in_progress'
        )
        db.session.add(order)
        db.session.commit()

        # Добавляем первое сообщение-описание заказа
        first_message = Message(
            order_id=order.id,
            sender_id=session['user_id'],
            receiver_id=master_id,
            text=description,
            timestamp=datetime.utcnow()
        )
        db.session.add(first_message)
        db.session.commit()

        flash('Заказ создан! Теперь вы можете общаться с мастером', 'success')
        return redirect(url_for('order_detail', order_id=order.id))

    return render_template('create_order.html', master=master)


@app.route('/orders')
def my_orders():
    """Список заказов текущего пользователя"""
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']

    # Заказы, где пользователь — заказчик
    customer_orders = Order.query.filter_by(customer_id=user_id).order_by(Order.updated_at.desc()).all()

    # Заказы, где пользователь — мастер
    master_orders = Order.query.filter_by(master_id=user_id).order_by(Order.updated_at.desc()).all()

    return render_template('my_orders.html',
                           customer_orders=customer_orders,
                           master_orders=master_orders)


@app.route('/order/<int:order_id>', methods=['GET', 'POST'])
def order_detail(order_id):
    """Детали заказа и чат"""
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'error')
        return redirect(url_for('login'))

    order = Order.query.get_or_404(order_id)
    user_id = session['user_id']

    # Проверяем, что пользователь участвует в заказе
    if user_id != order.customer_id and user_id != order.master_id:
        flash('У вас нет доступа к этому заказу', 'error')
        return redirect(url_for('index'))

    # Отправка сообщения
    if request.method == 'POST':
        message_text = request.form.get('message', '').strip()

        if message_text:
            # Определяем получателя
            receiver_id = order.master_id if user_id == order.customer_id else order.customer_id

            message = Message(
                order_id=order_id,
                sender_id=user_id,
                receiver_id=receiver_id,
                text=message_text,
                timestamp=datetime.utcnow()
            )
            db.session.add(message)
            db.session.commit()

            order.updated_at = datetime.utcnow()
            db.session.commit()

            flash('Сообщение отправлено', 'success')
            return redirect(url_for('order_detail', order_id=order_id))

    messages = order.messages
    other_user = order.master if user_id == order.customer_id else order.customer

    return render_template('order_detail.html',
                           order=order,
                           messages=messages,
                           other_user=other_user)


@app.route('/order/<int:order_id>/status', methods=['POST'])
def update_order_status(order_id):
    """Изменение статуса заказа"""
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'error')
        return redirect(url_for('login'))

    order = Order.query.get_or_404(order_id)
    user_id = session['user_id']

    # Проверяем права
    if user_id != order.customer_id and user_id != order.master_id:
        flash('У вас нет доступа к этому заказу', 'error')
        return redirect(url_for('index'))

    new_status = request.form.get('status')

    # Заказчик может отменить заказ, мастер может завершить
    if new_status == 'cancelled' and user_id == order.customer_id:
        order.status = 'cancelled'
    elif new_status == 'completed' and user_id == order.master_id:
        order.status = 'completed'
    else:
        flash('Недопустимое действие', 'error')
        return redirect(url_for('order_detail', order_id=order_id))

    order.updated_at = datetime.utcnow()
    db.session.commit()

    status_text = {
        'cancelled': 'отменён',
        'completed': 'завершён'
    }

    flash(f'Заказ {status_text[new_status]}', 'success')
    return redirect(url_for('order_detail', order_id=order_id))


@app.route('/order/<int:order_id>/review', methods=['GET', 'POST'])
def create_review(order_id):
    """Создание отзыва на мастера"""
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'error')
        return redirect(url_for('login'))

    order = Order.query.get_or_404(order_id)

    # Проверяем, что пользователь — заказчик
    if order.customer_id != session['user_id']:
        flash('Только заказчик может оставить отзыв', 'error')
        return redirect(url_for('index'))

    # Проверяем, что заказ завершён
    if order.status != 'completed':
        flash('Можно оставить отзыв только на завершённый заказ', 'error')
        return redirect(url_for('order_detail', order_id=order_id))

    # Проверяем, нет ли уже отзыва
    existing_review = Review.query.filter_by(order_id=order_id).first()
    if existing_review:
        flash('Вы уже оставили отзыв на этот заказ', 'error')
        return redirect(url_for('order_detail', order_id=order_id))

    if request.method == 'POST':
        rating = request.form.get('rating', type=int)
        comment = request.form.get('comment', '').strip()

        if not rating or rating < 1 or rating > 5:
            flash('Пожалуйста, поставьте оценку от 1 до 5', 'error')
            return render_template('create_review.html', order=order)

        review = Review(
            order_id=order_id,
            reviewer_id=session['user_id'],
            master_id=order.master_id,
            rating=rating,
            comment=comment,
            created_at=datetime.utcnow()
        )
        db.session.add(review)
        db.session.commit()

        # Обновляем рейтинг мастера
        master = User.query.get(order.master_id)
        master.update_rating()

        flash('Спасибо за отзыв!', 'success')
        return redirect(url_for('order_detail', order_id=order_id))

    return render_template('create_review.html', order=order)


# --- Запуск ---

# if __name__ == '__main__':
#     app.run()