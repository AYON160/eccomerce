from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
import math
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'
app.permanent_session_lifetime = timedelta(hours=1)

# Upload configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# User data file for storing registration/login data
USERS_FILE = 'users.txt'
SHOPS_FILE = 'shops.txt'

def ensure_admin_exists():
    """Create admin account if it doesn't exist"""
    users = load_users()
    if 'admin@email.com' not in users:
        save_user('admin@email.com', 'admin', 'Admin', 'admin')

def load_users():
    """Load users from txt file"""
    if not os.path.exists(USERS_FILE):
        return {}
    users = {}
    try:
        with open(USERS_FILE, 'r') as f:
            for line in f:
                if '|' in line:
                    parts = line.strip().split('|')
                    email = parts[0]
                    password = parts[1]
                    name = parts[2]
                    role = parts[3] if len(parts) > 3 else 'buyer'
                    blocked = parts[4].lower() == 'true' if len(parts) > 4 else False
                    seller_category = parts[5] if len(parts) > 5 else ''
                    users[email.lower()] = {
                        'password': password,
                        'name': name,
                        'role': role,
                        'blocked': blocked,
                        'seller_category': seller_category
                    }
    except:
        pass
    return users

def save_user(email, password, name, role='buyer', blocked=False, seller_category=''):
    """Save new user to txt file"""
    with open(USERS_FILE, 'a') as f:
        f.write(f"{email.lower()}|{password}|{name}|{role}|{str(blocked).lower()}|{seller_category}\n")

def update_user_blocked_status(email, blocked):
    """Update user blocked status"""
    users = load_users()
    products = load_seller_products()
    
    # Reconstruct users file with updated blocked status
    with open(USERS_FILE, 'w') as f:
        for e, data in users.items():
            block_status = 'true' if (e.lower() == email.lower() and blocked) or (e.lower() != email.lower() and data.get('blocked', False)) else 'false'
            seller_category = data.get('seller_category', '')
            f.write(f"{e}|{data['password']}|{data['name']}|{data['role']}|{block_status}|{seller_category}\n")

# Seller products file
SELLER_PRODUCTS_FILE = 'seller_products.txt'

def load_seller_products():
    """Load seller products from txt file"""
    if not os.path.exists(SELLER_PRODUCTS_FILE):
        return []
    products = []
    try:
        with open(SELLER_PRODUCTS_FILE, 'r') as f:
            for line in f:
                if line.strip() and '|' in line:
                    parts = line.strip().split('|')
                    if len(parts) >= 9:
                        specs = []
                        spec_str = parts[9] if len(parts) > 9 else ''
                        if spec_str:
                            for spec in spec_str.split(';'):
                                if ':' in spec:
                                    key, val = spec.split(':', 1)
                                    specs.append({'name': key, 'value': val})
                        
                        # Get stock_quantity from parts[10] if it exists, otherwise default to 10
                        stock_quantity = int(parts[10]) if len(parts) > 10 and parts[10].isdigit() else 10
                        
                        # Get shop_id from parts[11] if it exists
                        shop_id = parts[11] if len(parts) > 11 else ''
                        
                        in_stock_flag = parts[6].lower() == 'true'
                        # If stock hits 0, treat as out of stock regardless of stored flag
                        in_stock = in_stock_flag and stock_quantity > 0

                        product = {
                            'id': parts[0],
                            'seller_email': parts[1],
                            'name': parts[2],
                            'price': float(parts[3]),
                            'category': parts[4],
                            'description': parts[5],
                            'in_stock': in_stock,
                            'discount': float(parts[7]) if parts[7] else 0,
                            'image': parts[8] if parts[8] and parts[8] != 'None' else 'drone.png',
                            'specifications': specs,
                            'stock_quantity': stock_quantity,
                            'shop_id': shop_id,
                            'seller_product': True
                        }
                        products.append(product)
    except Exception as e:
        print(f"Error loading seller products: {e}")
    return products

def save_seller_product(product_id, seller_email, name, price, category, description, in_stock, discount, main_image, specifications, stock_quantity=10, shop_id=''):
    """Save seller product to txt file"""
    spec_str = ';'.join([f"{s['name']}:{s['value']}" for s in specifications])
    with open(SELLER_PRODUCTS_FILE, 'a') as f:
        f.write(f"{product_id}|{seller_email}|{name}|{price}|{category}|{description}|{str(in_stock).lower()}|{discount}|{main_image}|{spec_str}|{stock_quantity}|{shop_id}\n")

def apply_order_inventory_updates(cart_items):
    """Decrease stock quantities after a successful order"""
    if not cart_items:
        return

    # Update seller products (persisted)
    seller_products = load_seller_products()
    seller_by_id = {str(p['id']): p for p in seller_products}

    for item in cart_items:
        try:
            quantity = max(1, int(item.get('quantity', 1)))
        except (ValueError, TypeError):
            quantity = 1

        product_id = item.get('id')
        seller_product = seller_by_id.get(str(product_id))
        if seller_product:
            current_stock = int(seller_product.get('stock_quantity', 0))
            new_stock = max(0, current_stock - quantity)
            seller_product['stock_quantity'] = new_stock
            seller_product['in_stock'] = seller_product.get('in_stock', True) and new_stock > 0
            continue

        # Update main products (in-memory)
        main_product = next((p for p in PRODUCTS if p['id'] == product_id), None)
        if main_product:
            current_stock = int(main_product.get('stock_quantity', 0))
            new_stock = max(0, current_stock - quantity)
            main_product['stock_quantity'] = new_stock
            main_product['in_stock'] = new_stock > 0

    if seller_products:
        rewrite_seller_products(seller_products)

def rewrite_seller_products(products):
    """Rewrite seller products file with updated data"""
    with open(SELLER_PRODUCTS_FILE, 'w') as f:
        for p in products:
            spec_str = ';'.join([f"{s['name']}:{s['value']}" for s in p.get('specifications', [])])
            f.write(
                f"{p['id']}|{p['seller_email']}|{p['name']}|{p['price']}|{p['category']}|{p['description']}|"
                f"{str(p.get('in_stock', True)).lower()}|{p.get('discount', 0)}|{p.get('image', 'drone.png')}|"
                f"{spec_str}|{p.get('stock_quantity', 0)}|{p.get('shop_id', '')}\n"
            )

def get_next_seller_product_id():
    """Get next product id for seller products"""
    products = load_seller_products()
    if products:
        return max(int(p['id']) for p in products) + 1
    return 1001  # Start seller products from 1001


# Sample product data
PRODUCTS = [
    {'id': 1, 'name': 'Wireless Headphones', 'price': 79.99, 'category': 'electronics', 'image': 'drone.png', 'description': 'High-quality wireless headphones with noise cancellation', 'stock_quantity': 12},
    {'id': 2, 'name': 'Smart Watch', 'price': 199.99, 'category': 'electronics', 'image': 'drone.png', 'description': 'Feature-rich smartwatch with health tracking', 'stock_quantity': 3},
    {'id': 3, 'name': 'USB-C Cable', 'price': 14.99, 'category': 'accessories', 'image': 'drone.png', 'description': 'Durable and fast charging USB-C cable', 'stock_quantity': 25},
    {'id': 4, 'name': 'Phone Case', 'price': 24.99, 'category': 'accessories', 'image': 'drone.png', 'description': 'Protective phone case with premium materials', 'stock_quantity': 4},
    {'id': 5, 'name': 'Laptop Stand', 'price': 34.99, 'category': 'electronics', 'image': 'drone.png', 'description': 'Adjustable aluminum laptop stand', 'stock_quantity': 8},
    {'id': 6, 'name': 'Keyboard', 'price': 89.99, 'category': 'electronics', 'image': 'drone.png', 'description': 'Mechanical keyboard with RGB lighting', 'stock_quantity': 15},
    {'id': 7, 'name': 'Wireless Headphones', 'price': 79.99, 'category': 'electronics', 'image': 'drone.png', 'description': 'High-quality wireless headphones with noise cancellation', 'stock_quantity': 2},
    {'id': 8, 'name': 'Smart Watch', 'price': 199.99, 'category': 'electronics', 'image': 'drone.png', 'description': 'Feature-rich smartwatch with health tracking', 'stock_quantity': 10},
    {'id': 9, 'name': 'USB Cable', 'price': 14.99, 'category': 'accessories', 'image': 'drone.png', 'description': 'Durable and fast charging USB-C cable', 'stock_quantity': 30},
    {'id': 10, 'name': 'iPhone Case', 'price': 24.99, 'category': 'accessories', 'image': 'drone.png', 'description': 'Protective phone case with premium materials', 'stock_quantity': 1},
    {'id': 11, 'name': 'Wireless charger', 'price': 79.99, 'category': 'electronics', 'image': 'drone.png', 'description': 'High-quality wireless headphones with noise cancellation', 'stock_quantity': 6},
    {'id': 12, 'name': 'analog Watch', 'price': 199.99, 'category': 'electronics', 'image': 'drone.png', 'description': 'Feature-rich smartwatch with health tracking', 'stock_quantity': 7},
    {'id': 13, 'name': 'USB-A Cable', 'price': 14.99, 'category': 'accessories', 'image': 'drone.png', 'description': 'Durable and fast charging USB-C cable', 'stock_quantity': 18},
    {'id': 14, 'name': 'Phone Cover', 'price': 24.99, 'category': 'accessories', 'image': 'drone.png', 'description': 'Protective phone case with premium materials', 'stock_quantity': 5},
    {'id': 15, 'name': 'Laptop', 'price': 34.99, 'category': 'electronics', 'image': 'drone.png', 'description': 'Adjustable aluminum laptop stand', 'stock_quantity': 9},
    {'id': 16, 'name': 'Keyboard', 'price': 89.99, 'category': 'electronics', 'image': 'drone.png', 'description': 'Mechanical keyboard with RGB lighting', 'stock_quantity': 11},
    {'id': 17, 'name': 'normal Headphones', 'price': 79.99, 'category': 'electronics', 'image': 'drone.png', 'description': 'High-quality wireless headphones with noise cancellation', 'stock_quantity': 4},
    {'id': 18, 'name': 'Smart phone', 'price': 199.99, 'category': 'electronics', 'image': 'drone.png', 'description': 'Feature-rich smartwatch with health tracking', 'stock_quantity': 2},
    {'id': 19, 'name': 'USB-C Cable', 'price': 14.99, 'category': 'accessories', 'image': 'drone.png', 'description': 'Durable and fast charging USB-C cable', 'stock_quantity': 20},
    {'id': 20, 'name': 'Phone Case', 'price': 24.99, 'category': 'accessories', 'image': 'drone.png', 'description': 'Protective phone case with premium materials', 'stock_quantity': 3},
]

CATEGORIES = {
    'electronics': 'Electronics',
    'accessories': 'Accessories',
    'grocery': 'Grocery',   
    'clothing': 'Clothing',
    'health': 'Health',
    'security': 'Security',
    'vehicles': 'Vehicles',
    'other': 'Others',
}

def apply_stock_status(product):
    """Ensure in_stock reflects stock_quantity."""
    stock_qty = product.get('stock_quantity')
    if stock_qty is not None:
        product['in_stock'] = stock_qty > 0
    return product

@app.route('/')
def home():
    featured_products = PRODUCTS[:5]
    return render_template('index.html', featured_products=featured_products, categories=CATEGORIES)

@app.route('/products')
def products():
    category = request.args.get('category', None)
    search = request.args.get('search', '').strip().lower()
    page = request.args.get('page', 1, type=int)
    per_page = 8

    # Combine main products with seller products
    all_products = PRODUCTS + load_seller_products()
    for p in all_products:
        apply_stock_status(p)
    
    filtered = all_products
    if category and category in CATEGORIES:
        filtered = [p for p in filtered if p['category'] == category]
    if search:
        filtered = [p for p in filtered if search in p['name'].lower() or search in p['description'].lower()]

    total = len(filtered)
    total_pages = math.ceil(total / per_page) if per_page else 1
    start = (page - 1) * per_page
    end = start + per_page
    paginated = filtered[start:end]

    return render_template('products.html', products=paginated, categories=CATEGORIES, selected_category=category, page=page, total_pages=total_pages, search=search)


@app.route('/assets/<path:path>')
def serve_asset(path):
    # Serve files from project root (e.g., drone.png) so templates can reference them without moving files
    return send_from_directory(app.root_path, path)

@app.route('/product/<product_id>')
def product_detail(product_id):
    # First check in seller products
    seller_products = load_seller_products()
    product = next((p for p in seller_products if p['id'] == product_id), None)
    
    # If not found, check in main products
    if not product:
        product = next((p for p in PRODUCTS if p['id'] == int(product_id)), None)
    
    shop = None
    if product and product.get('seller_product'):
        shop_id = product.get('shop_id')
        if shop_id:
            shop = next((s for s in load_shops() if s['id'] == shop_id), None)

    if product:
        apply_stock_status(product)
        return render_template('product_detail.html', product=product, categories=CATEGORIES, shop=shop)
    return redirect(url_for('products'))

@app.route('/cart')
def cart():
    cart_items = session.get('cart', [])
    total = sum(item['price'] * item['quantity'] for item in cart_items)
    return render_template('cart.html', cart_items=cart_items, total=total, categories=CATEGORIES)

@app.route('/add-to-cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    # First check in seller products
    seller_products = load_seller_products()
    product = next((p for p in seller_products if p['id'] == str(product_id)), None)
    
    # If not found, check in main products
    if not product:
        product = next((p for p in PRODUCTS if p['id'] == product_id), None)
    
    if not product:
        return jsonify({'success': False, 'message': 'Product not found'}), 404
    
    # Get quantity from form data, default to 1
    try:
        quantity = int(request.form.get('quantity', 1))
        quantity = max(1, quantity)  # Ensure minimum quantity is 1
    except (ValueError, TypeError):
        quantity = 1
    
    cart = session.get('cart', [])
    existing_item = next((item for item in cart if item['id'] == product_id), None)
    
    if existing_item:
        existing_item['quantity'] += quantity
    else:
        cart.append({
            'id': product_id,
            'name': product['name'],
            'price': product['price'],
            'quantity': quantity
        })
    
    session['cart'] = cart
    # If request is JSON (AJAX), return JSON, otherwise redirect back for form POSTs
    if request.is_json:
        return jsonify({'success': True, 'message': 'Added to cart', 'cart_count': len(cart)})
    return redirect(request.referrer or url_for('products'))

@app.route('/remove-from-cart/<int:product_id>', methods=['POST'])
def remove_from_cart(product_id):
    cart = session.get('cart', [])
    cart = [item for item in cart if item['id'] != product_id]
    session['cart'] = cart
    if request.is_json:
        return jsonify({'success': True, 'cart_count': len(cart)})
    return redirect(request.referrer or url_for('cart'))

@app.route('/checkout')
def checkout():
    cart_items = session.get('cart', [])
    if not cart_items:
        return redirect(url_for('cart'))
    total = sum(item['price'] * item['quantity'] for item in cart_items)
    return render_template('checkout.html', cart_items=cart_items, total=total, categories=CATEGORIES)


@app.route('/toggle-theme', methods=['POST'])
def toggle_theme():
    current = session.get('theme', 'dark')
    session['theme'] = 'light' if current == 'dark' else 'dark'
    return redirect(request.referrer or url_for('home'))

@app.route('/order-confirmation', methods=['POST'])
def order_confirmation():
    cart_items = session.get('cart', [])
    if cart_items:
        seller_products = load_seller_products()
        seller_updated = False

        for item in cart_items:
            product_id = item.get('id')
            quantity = max(1, int(item.get('quantity', 1)))

            seller_product = next((p for p in seller_products if p['id'] == str(product_id)), None)
            if seller_product:
                current_stock = int(seller_product.get('stock_quantity', 0))
                new_stock = max(0, current_stock - quantity)
                seller_product['stock_quantity'] = new_stock
                seller_product['in_stock'] = new_stock > 0
                seller_updated = True
                continue

            main_product = next((p for p in PRODUCTS if p['id'] == product_id), None)
            if main_product:
                current_stock = int(main_product.get('stock_quantity', 0))
                new_stock = max(0, current_stock - quantity)
                main_product['stock_quantity'] = new_stock
                main_product['in_stock'] = new_stock > 0

        if seller_updated:
            rewrite_seller_products(seller_products)

    session['cart'] = []
    order_id = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    return render_template('order_confirmation.html', order_id=order_id, categories=CATEGORIES)

@app.route('/about')
def about():
    return render_template('about.html', categories=CATEGORIES)

@app.route('/contact')
def contact():
    return render_template('contact.html', categories=CATEGORIES)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        action = request.form.get('action', 'login')
        remember = request.form.get('remember', 'off') == 'on'
        
        users = load_users()
        
        if action == 'signup':
            name = request.form.get('name', '').strip()
            role = request.form.get('role', 'buyer').strip()
            has_shops = request.form.get('has_shops', 'no') == 'yes'
            shop_count = request.form.get('shop_count', '1').strip()
            seller_category = request.form.get('seller_category', '').strip()
            if not email or not password or not name:
                return render_template('login.html', categories=CATEGORIES, error='All fields are required', mode='signup')
            if email.lower() in users:
                return render_template('login.html', categories=CATEGORIES, error='Email already registered', mode='signup')
            if role == 'seller' and has_shops:
                try:
                    shop_count = max(1, int(shop_count))
                except ValueError:
                    return render_template('login.html', categories=CATEGORIES, error='Invalid shop count', mode='signup')
                shops_to_save = []
                for i in range(1, shop_count + 1):
                    shop_name = request.form.get(f'shop_name_{i}', '').strip()
                    shop_description = request.form.get(f'shop_description_{i}', '').strip()
                    shop_country = request.form.get(f'shop_country_{i}', '').strip()
                    shop_division = request.form.get(f'shop_division_{i}', '').strip()
                    shop_district = request.form.get(f'shop_district_{i}', '').strip()
                    shop_thana = request.form.get(f'shop_thana_{i}', '').strip()
                    shop_area = request.form.get(f'shop_area_{i}', '').strip()
                    shop_address =  request.form.get(f'shop_address_{i}', '').strip()
                    if not shop_name or not shop_country or not shop_division or not shop_district:
                        return render_template('login.html', categories=CATEGORIES, error='Please complete all shop fields', mode='signup')
                    shops_to_save.append({
                        'name': shop_name,
                        'description': shop_description,
                        'country': shop_country,
                        'division': shop_division,
                        'district': shop_district,
                        'thana': shop_thana,
                        'area': shop_area,
                        'address': shop_address,
                    })
            save_user(email, password, name, role, False, seller_category)
            if role == 'seller' and has_shops:
                for shop in shops_to_save:
                    save_shop(
                        shop['name'],
                        email,
                        shop['description'],
                        shop['country'],
                        shop['division'],
                        shop['district'],
                        shop['thana'],
                        shop['area'],
                        shop['address']
                    )
            session['user'] = name
            session['email'] = email
            session['role'] = role
            if remember:
                session.permanent = True
                app.permanent_session_lifetime = 60 * 60 * 24 * 30  # 30 days
            return redirect(url_for('home'))
        
        else:  # login
            if not email or not password:
                return render_template('login.html', categories=CATEGORIES, error='Email and password required', mode='login')
            if email.lower() not in users or users[email.lower()]['password'] != password:
                return render_template('login.html', categories=CATEGORIES, error='Invalid email or password', mode='login')
            user_data = users[email.lower()]
            
            # Check if user is blocked
            if user_data.get('blocked', False):
                return render_template('login.html', categories=CATEGORIES, error='Your account has been blocked', mode='login')
            
            session['user'] = user_data['name']
            session['email'] = email
            session['role'] = user_data.get('role', 'buyer')
            if remember:
                session.permanent = True
                app.permanent_session_lifetime = 60 * 60 * 24 * 30  # 30 days
            return redirect(url_for('home'))
    
    mode = request.args.get('mode', 'login')
    return render_template('login.html', categories=CATEGORIES, mode=mode)

@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('email', None)
    session.pop('role', None)
    return redirect(url_for('home'))

@app.route('/add-to-favorites/<int:product_id>', methods=['POST'])
def add_to_favorites(product_id):
    # Check if user is logged in
    if not session.get('user'):
        return jsonify({'success': False, 'message': 'Please login to add favorites', 'login_required': True}), 401
    
    # First check in seller products
    seller_products = load_seller_products()
    product = next((p for p in seller_products if p['id'] == str(product_id)), None)
    
    # If not found, check in main products
    if not product:
        product = next((p for p in PRODUCTS if p['id'] == product_id), None)
    
    if not product:
        return jsonify({'success': False, 'message': 'Product not found'}), 404
    
    favorites = session.get('favorites', [])
    if product_id not in favorites:
        favorites.append(product_id)
    session['favorites'] = favorites
    return jsonify({'success': True, 'message': 'Added to favorites', 'is_favorite': True})

@app.route('/remove-from-favorites/<int:product_id>', methods=['POST'])
def remove_from_favorites(product_id):
    favorites = session.get('favorites', [])
    if product_id in favorites:
        favorites.remove(product_id)
    session['favorites'] = favorites
    return jsonify({'success': True, 'message': 'Removed from favorites', 'is_favorite': False})

@app.route('/add-to-wishlist/<int:product_id>', methods=['POST'])
def add_to_wishlist(product_id):
    # Check if user is logged in
    if not session.get('user'):
        return jsonify({'success': False, 'message': 'Please login to add to wishlist', 'login_required': True}), 401
    
    # First check in seller products
    seller_products = load_seller_products()
    product = next((p for p in seller_products if p['id'] == str(product_id)), None)
    
    # If not found, check in main products
    if not product:
        product = next((p for p in PRODUCTS if p['id'] == product_id), None)
    
    if not product:
        return jsonify({'success': False, 'message': 'Product not found'}), 404
    
    wishlist = session.get('wishlist', [])
    if product_id not in wishlist:
        wishlist.append(product_id)
    session['wishlist'] = wishlist
    return jsonify({'success': True, 'message': 'Added to wishlist', 'in_wishlist': True})

@app.route('/remove-from-wishlist/<int:product_id>', methods=['POST'])
def remove_from_wishlist(product_id):
    wishlist = session.get('wishlist', [])
    if product_id in wishlist:
        wishlist.remove(product_id)
    session['wishlist'] = wishlist
    return jsonify({'success': True, 'message': 'Removed from wishlist', 'in_wishlist': False})

@app.route('/user')
def user_profile():
    if not session.get('user'):
        return redirect(url_for('login'))
    
    # Get user's favorites and wishlist
    favorites = session.get('favorites', [])
    wishlist = session.get('wishlist', [])
    
    # Get product details for favorites and wishlist
    favorite_products = [p for p in PRODUCTS if p['id'] in favorites]
    wishlist_products = [p for p in PRODUCTS if p['id'] in wishlist]
    
    return render_template('user.html', categories=CATEGORIES, 
                         user_name=session.get('user'),
                         user_role=session.get('role', 'buyer'),
                         favorite_products=favorite_products, 
                         wishlist_products=wishlist_products)

@app.route('/user/seller', methods=['GET', 'POST'])
def seller_dashboard():
    if not session.get('user'):
        return redirect(url_for('login'))
    
    if session.get('role') != 'seller':
        return redirect(url_for('user_profile'))
    
    if request.method == 'POST':
        # Add new product
        name = request.form.get('name', '').strip()
        price = request.form.get('price', '').strip()
        category = request.form.get('category', '').strip()
        description = request.form.get('description', '').strip()
        in_stock = request.form.get('in_stock') == 'on'
        discount = request.form.get('discount', '0').strip()
        stock_quantity = request.form.get('stock_quantity', '10').strip()
        shop_id = request.form.get('shop_id', '').strip()
        seller_email = session.get('email')
        seller_shops = [s for s in load_shops() if s['owner_email'] == seller_email]
        
        # Get up to 20 specifications
        specifications = []
        for i in range(1, 21):
            spec_name = request.form.get(f'spec_name_{i}', '').strip()
            spec_value = request.form.get(f'spec_value_{i}', '').strip()
            if spec_name and spec_value:
                specifications.append({'name': spec_name, 'value': spec_value})
        
        if not name or not price or not category:
            return render_template('seller.html', categories=CATEGORIES, 
                                 user_name=session.get('user'),
                                 error='Name, price, and category are required',
                                 seller_products=[],
                                 seller_shops=seller_shops)
        
        if seller_shops and not shop_id:
            return render_template('seller.html', categories=CATEGORIES,
                                 user_name=session.get('user'),
                                 error='Please select a shop for this product',
                                 seller_products=[],
                                 seller_shops=seller_shops)
        
        try:
            price = float(price)
            discount = float(discount) if discount else 0
            stock_quantity = max(1, int(stock_quantity))
        except ValueError:
            return render_template('seller.html', categories=CATEGORIES, 
                                 user_name=session.get('user'),
                                 error='Price, discount, and stock quantity must be numbers',
                                 seller_products=[],
                                 seller_shops=seller_shops)
        
        # Handle file uploads
        main_image = 'drone.png'
        if 'main_image' in request.files and request.files['main_image'].filename:
            file = request.files['main_image']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"product_{get_next_seller_product_id()}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                main_image = filename
        
        product_id = get_next_seller_product_id()
        save_seller_product(product_id, session.get('email'), name, price, category, 
                          description, in_stock, discount, main_image, specifications, stock_quantity, shop_id)
        
        # Reload products and show success
        seller_products = [p for p in load_seller_products() if p['seller_email'] == session.get('email')]
        return render_template('seller.html', categories=CATEGORIES, 
                             user_name=session.get('user'),
                             message='Product added successfully',
                             seller_products=seller_products,
                             seller_shops=seller_shops)
    
    # GET request - show seller dashboard
    seller_email = session.get('email')
    seller_products = [p for p in load_seller_products() if p['seller_email'] == seller_email]
    seller_shops = [s for s in load_shops() if s['owner_email'] == seller_email]
    return render_template('seller.html', categories=CATEGORIES, 
                         user_name=session.get('user'),
                         seller_products=seller_products,
                         seller_shops=seller_shops)

@app.route('/user/seller/delete/<product_id>', methods=['POST'])
def delete_seller_product(product_id):
    if not session.get('user') or session.get('role') != 'seller':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    seller_email = session.get('email')
    products = load_seller_products()
    
    # Filter out the product and rewrite file
    updated_products = [p for p in products if not (p['id'] == product_id and p['seller_email'] == seller_email)]
    
    # Clear and rewrite file
    try:
        rewrite_seller_products(updated_products)
        return jsonify({'success': True, 'message': 'Product deleted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    if not session.get('user'):
        return redirect(url_for('login'))
    
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    action = request.args.get('action', 'dashboard')
    
    if action == 'users':
        query = request.args.get('q', '').strip().lower()
        users = load_users()
        users_list = [{'email': e, **data} for e, data in users.items()]
        if query:
            users_list = [
                u for u in users_list
                if query in u.get('email', '').lower() or query in u.get('name', '').lower()
            ]
        return render_template('admin.html', categories=CATEGORIES, 
                             user_name=session.get('user'),
                             active_tab='users',
                             users=users_list,
                             query=query)
    
    elif action == 'products':
        all_products = load_seller_products()
        return render_template('admin.html', categories=CATEGORIES, 
                             user_name=session.get('user'),
                             active_tab='products',
                             products=all_products)
    
    elif action == 'orders':
        # TODO: Implement order tracking
        return render_template('admin.html', categories=CATEGORIES, 
                             user_name=session.get('user'),
                             active_tab='orders')
    
    else:  # dashboard
        users = load_users()
        seller_count = sum(1 for u in users.values() if u.get('role') == 'seller')
        buyer_count = sum(1 for u in users.values() if u.get('role') == 'buyer')
        blocked_count = sum(1 for u in users.values() if u.get('blocked', False))
        all_products = load_seller_products()
        
        return render_template('admin.html', categories=CATEGORIES, 
                             user_name=session.get('user'),
                             active_tab='dashboard',
                             stats={
                                 'total_users': len(users),
                                 'sellers': seller_count,
                                 'buyers': buyer_count,
                                 'blocked': blocked_count,
                                 'total_products': len(all_products)
                             })

@app.route('/admin/block/<email>', methods=['POST'])
def admin_block_user(email):
    if not session.get('user') or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    update_user_blocked_status(email, True)
    return jsonify({'success': True, 'message': f'User {email} blocked'})

@app.route('/admin/unblock/<email>', methods=['POST'])
def admin_unblock_user(email):
    if not session.get('user') or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    update_user_blocked_status(email, False)
    return jsonify({'success': True, 'message': f'User {email} unblocked'})

@app.route('/admin/delete-user/<email>', methods=['POST'])
def admin_delete_user(email):
    if not session.get('user') or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    users = load_users()
    email_lower = email.lower()
    if email_lower not in users:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    # Remove user from users file
    try:
        with open(USERS_FILE, 'w') as f:
            for e, data in users.items():
                if e.lower() == email_lower:
                    continue
                seller_category = data.get('seller_category', '')
                f.write(f"{e}|{data['password']}|{data['name']}|{data['role']}|{str(data.get('blocked', False)).lower()}|{seller_category}\n")

        # Remove seller products
        products = load_seller_products()
        updated_products = [p for p in products if p.get('seller_email', '').lower() != email_lower]
        rewrite_seller_products(updated_products)

        # Remove shops
        shops = load_shops()
        updated_shops = [s for s in shops if s.get('owner_email', '').lower() != email_lower]
        with open(SHOPS_FILE, 'w') as f:
            for s in updated_shops:
                f.write(f"{s['id']}|{s['name']}|{s['owner_email']}|{s['description']}|{s.get('country','')}|{s.get('division','')}|{s.get('district','')}|{s.get('thana','')}|{s.get('area','')}|{s.get('address','')}|{s.get('image','drone.png')}\n")

        return jsonify({'success': True, 'message': f'User {email} deleted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/delete-product/<product_id>', methods=['POST'])
def admin_delete_product(product_id):
    if not session.get('user') or session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    products = load_seller_products()
    updated_products = [p for p in products if p['id'] != product_id]
    
    try:
        rewrite_seller_products(updated_products)
        return jsonify({'success': True, 'message': 'Product deleted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
@app.route('/shops')
def shops():
    query = request.args.get('q', '').strip().lower()
    category = request.args.get('category', '').strip().lower()
    district = request.args.get('district', '').strip().lower()

    shops = load_shops()
    users = load_users()

    # Count shops per owner for display
    owner_counts = {}
    for s in shops:
        owner = s.get('owner_email', '').lower()
        if owner:
            owner_counts[owner] = owner_counts.get(owner, 0) + 1

    enriched = []
    for s in shops:
        owner_email = s.get('owner_email', '').lower()
        owner = users.get(owner_email, {})
        seller_category = (owner.get('seller_category') or '').lower()
        shop_data = {
            **s,
            'owner_name': owner.get('name', ''),
            'seller_category': seller_category,
            'shop_count': owner_counts.get(owner_email, 1)
        }
        enriched.append(shop_data)

    filtered = enriched
    if query:
        filtered = [s for s in filtered if query in s.get('name', '').lower()]
    if category:
        filtered = [s for s in filtered if s.get('seller_category', '').lower() == category]
    if district:
        filtered = [s for s in filtered if district in s.get('district', '').lower()]

    return render_template('shops.html', 
                         shops=filtered, 
                         categories=CATEGORIES, 
                         query=query,
                         selected_category=category,
                         district=district)

def load_shops():
    """Load shops from txt file"""
    if not os.path.exists(SHOPS_FILE):
        return []
    shops = []
    try:
        with open(SHOPS_FILE, 'r') as f:
            for line in f:
                if line.strip() and '|' in line:
                    parts = line.strip().split('|')
                    if len(parts) >= 4:
                        shop = {
                            'id': parts[0],
                            'name': parts[1],
                            'owner_email': parts[2],
                            'description': parts[3],
                            'country': parts[4] if len(parts) > 4 else '',
                            'division': parts[5] if len(parts) > 5 else '',
                            'district': parts[6] if len(parts) > 6 else '',
                            'thana': parts[7] if len(parts) > 7 else '',
                            'area': parts[8] if len(parts) > 8 else '',
                            'address': parts[9] if len(parts) > 9 else '',
                            'image': parts[10] if len(parts) > 10 else 'drone.png',
                        }
                        shops.append(shop)
    except Exception as e:
        print(f"Error loading shops: {e}")
    return shops

def get_next_shop_id():
    """Get next shop id"""
    shops = load_shops()
    if shops:
        try:
            return max(int(s['id']) for s in shops) + 1
        except ValueError:
            pass
    return 100

def save_shop(name, owner_email, description, country, division, district, thana='', area='', address='', image='drone.png'):
    """Save shop to txt file"""
    shop_id = get_next_shop_id()
    with open(SHOPS_FILE, 'a') as f:
        f.write(f"{shop_id}|{name}|{owner_email}|{description}|{country}|{division}|{district}|{thana}|{area}|{address}|{image}\n")


if __name__ == '__main__':
    ensure_admin_exists()
    app.run(debug=True)
