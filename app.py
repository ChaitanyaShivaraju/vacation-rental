from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import stripe

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Stripe configuration
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', 'sk_test_your_key_here')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', 'pk_test_your_key_here')

# Database configuration
# Database configuration - Using SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///rentals.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20))
    is_host = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    properties = db.relationship('Property', backref='host', lazy=True)
    bookings = db.relationship('Booking', backref='guest', lazy=True)
    reviews_given = db.relationship('Review', backref='reviewer', lazy=True)

class Property(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    host_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    price_per_night = db.Column(db.Float, nullable=False)
    bedrooms = db.Column(db.Integer, nullable=False)
    bathrooms = db.Column(db.Integer, nullable=False)
    max_guests = db.Column(db.Integer, nullable=False)
    property_type = db.Column(db.String(50), nullable=False)  # Apartment, House, Villa, etc.
    amenities = db.Column(db.Text)  # JSON string
    image_url = db.Column(db.String(300))
    available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    bookings = db.relationship('Booking', backref='property', lazy=True)
    reviews = db.relationship('Review', backref='property', lazy=True)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), nullable=False)
    guest_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    check_in = db.Column(db.Date, nullable=False)
    check_out = db.Column(db.Date, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, cancelled, completed
    payment_intent_id = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Helper function to calculate average rating
def get_average_rating(property_id):
    reviews = Review.query.filter_by(property_id=property_id).all()
    if not reviews:
        return 0
    return sum(r.rating for r in reviews) / len(reviews)

# Routes
@app.route('/')
def index():
    properties = Property.query.filter_by(available=True).limit(12).all()
    property_data = []
    for prop in properties:
        property_data.append({
            'property': prop,
            'avg_rating': get_average_rating(prop.id),
            'review_count': len(prop.reviews)
        })
    return render_template('index.html', properties=property_data)

@app.route('/search')
def search():
    location = request.args.get('location', '')
    check_in = request.args.get('check_in', '')
    check_out = request.args.get('check_out', '')
    guests = request.args.get('guests', 1, type=int)
    min_price = request.args.get('min_price', 0, type=float)
    max_price = request.args.get('max_price', 10000, type=float)
    
    query = Property.query.filter_by(available=True)
    
    if location:
        query = query.filter(Property.location.contains(location))
    if guests:
        query = query.filter(Property.max_guests >= guests)
    
    query = query.filter(Property.price_per_night >= min_price, Property.price_per_night <= max_price)
    
    properties = query.all()
    
    property_data = []
    for prop in properties:
        property_data.append({
            'property': prop,
            'avg_rating': get_average_rating(prop.id),
            'review_count': len(prop.reviews)
        })
    
    return render_template('search.html', properties=property_data, 
                         location=location, check_in=check_in, check_out=check_out, guests=guests)

@app.route('/property/<int:property_id>')
def property_detail(property_id):
    prop = Property.query.get_or_404(property_id)
    reviews = Review.query.filter_by(property_id=property_id).order_by(Review.created_at.desc()).all()
    avg_rating = get_average_rating(property_id)
    
    return render_template('property_detail.html', property=prop, reviews=reviews, 
                         avg_rating=avg_rating, stripe_key=STRIPE_PUBLISHABLE_KEY)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        phone = request.form.get('phone', '')
        is_host = 'is_host' in request.form
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('register'))
        
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            phone=phone,
            is_host=is_host
        )
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_host'] = user.is_host
            flash('Welcome back!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('index'))

@app.route('/host/dashboard')
def host_dashboard():
    if 'user_id' not in session or not session.get('is_host'):
        flash('Host access required', 'error')
        return redirect(url_for('index'))
    
    properties = Property.query.filter_by(host_id=session['user_id']).all()
    bookings = Booking.query.join(Property).filter(Property.host_id == session['user_id']).order_by(Booking.created_at.desc()).all()
    
    return render_template('host_dashboard.html', properties=properties, bookings=bookings)

@app.route('/host/add-property', methods=['GET', 'POST'])
def add_property():
    if 'user_id' not in session or not session.get('is_host'):
        flash('Host access required', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        location = request.form['location']
        price = float(request.form['price'])
        bedrooms = int(request.form['bedrooms'])
        bathrooms = int(request.form['bathrooms'])
        max_guests = int(request.form['max_guests'])
        property_type = request.form['property_type']
        amenities = request.form.get('amenities', '')
        image_url = request.form.get('image_url', '')
        
        property = Property(
            host_id=session['user_id'],
            title=title,
            description=description,
            location=location,
            price_per_night=price,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            max_guests=max_guests,
            property_type=property_type,
            amenities=amenities,
            image_url=image_url
        )
        
        db.session.add(property)
        db.session.commit()
        
        flash('Property added successfully!', 'success')
        return redirect(url_for('host_dashboard'))
    
    return render_template('add_property.html')

@app.route('/book/<int:property_id>', methods=['POST'])
def book_property(property_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Please login to book'}), 401
    
    prop = Property.query.get_or_404(property_id)
    
    check_in = datetime.strptime(request.form['check_in'], '%Y-%m-%d').date()
    check_out = datetime.strptime(request.form['check_out'], '%Y-%m-%d').date()
    
    nights = (check_out - check_in).days
    total_price = nights * prop.price_per_night
    
    # Create Stripe payment intent
    try:
        intent = stripe.PaymentIntent.create(
            amount=int(total_price * 100),  # Convert to cents
            currency='usd',
            metadata={
                'property_id': property_id,
                'guest_id': session['user_id']
            }
        )
        
        booking = Booking(
            property_id=property_id,
            guest_id=session['user_id'],
            check_in=check_in,
            check_out=check_out,
            total_price=total_price,
            payment_intent_id=intent.id
        )
        
        db.session.add(booking)
        db.session.commit()
        
        return jsonify({
            'client_secret': intent.client_secret,
            'booking_id': booking.id
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/bookings')
def my_bookings():
    if 'user_id' not in session:
        flash('Please login to view bookings', 'error')
        return redirect(url_for('login'))
    
    bookings = Booking.query.filter_by(guest_id=session['user_id']).order_by(Booking.created_at.desc()).all()
    return render_template('my_bookings.html', bookings=bookings)

@app.route('/review/<int:property_id>', methods=['POST'])
def add_review(property_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Please login'}), 401
    
    rating = int(request.form['rating'])
    comment = request.form['comment']
    
    review = Review(
        property_id=property_id,
        reviewer_id=session['user_id'],
        rating=rating,
        comment=comment
    )
    
    db.session.add(review)
    db.session.commit()
    
    flash('Review added successfully!', 'success')
    return redirect(url_for('property_detail', property_id=property_id))

# Initialize database
with app.app_context():
    db.create_all()
    
    # Create sample data if database is empty
    if User.query.count() == 0:
        # Sample host
        host = User(
            username='john_host',
            email='host@example.com',
            password_hash=generate_password_hash('host123'),
            phone='+1234567890',
            is_host=True
        )
        db.session.add(host)
        db.session.flush()
        
        # Sample properties
        properties = [
            Property(
                host_id=host.id,
                title='Luxury Beachfront Villa',
                description='Stunning ocean views, private beach access, infinity pool',
                location='Malibu, California',
                price_per_night=450.00,
                bedrooms=4,
                bathrooms=3,
                max_guests=8,
                property_type='Villa',
                amenities='WiFi, Pool, Beach Access, Kitchen, Parking',
                image_url='https://images.unsplash.com/photo-1613490493576-7fde63acd811?w=800'
            ),
            Property(
                host_id=host.id,
                title='Cozy Mountain Cabin',
                description='Peaceful retreat in the mountains with fireplace',
                location='Aspen, Colorado',
                price_per_night=280.00,
                bedrooms=3,
                bathrooms=2,
                max_guests=6,
                property_type='Cabin',
                amenities='WiFi, Fireplace, Kitchen, Parking, Hot Tub',
                image_url='https://images.unsplash.com/photo-1587061949409-02df41d5e562?w=800'
            ),
            Property(
                host_id=host.id,
                title='Modern Downtown Apartment',
                description='Stylish loft in the heart of the city',
                location='New York, NY',
                price_per_night=180.00,
                bedrooms=2,
                bathrooms=1,
                max_guests=4,
                property_type='Apartment',
                amenities='WiFi, Gym, Kitchen, City View',
                image_url='https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800'
            ),
            Property(
                host_id=host.id,
                title='Tropical Paradise Bungalow',
                description='Private bungalow surrounded by nature',
                location='Bali, Indonesia',
                price_per_night=120.00,
                bedrooms=1,
                bathrooms=1,
                max_guests=2,
                property_type='Bungalow',
                amenities='WiFi, Pool, Garden, Kitchen',
                image_url='https://images.unsplash.com/photo-1571896349842-33c89424de2d?w=800'
            )
        ]
        
        for prop in properties:
            db.session.add(prop)
        
        db.session.commit()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))

    app.run(host='0.0.0.0', port=port, debug=True)
