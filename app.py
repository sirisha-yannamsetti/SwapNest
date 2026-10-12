
import os
from uuid import uuid4
from datetime import datetime

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, and_, inspect, text
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

from image_matcher import compare_images
from price_estimator import estimate_resale_price


# -------------------- CONFIGURATION --------------------

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY", "swapnest-local-secret-key"
)

app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads")
app.config["PRODUCT_UPLOAD_FOLDER"] = os.path.join(
    app.config["UPLOAD_FOLDER"], "products"
)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


# -------------------- DATABASE --------------------

db_user = os.getenv("DB_USER", "root")
db_password = os.getenv("DB_PASSWORD", "")
db_host = os.getenv("DB_HOST", "localhost")
db_port = os.getenv("DB_PORT", "3306")
db_name = os.getenv("DB_NAME", "swapnest_db")

from urllib.parse import quote_plus

app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"mysql+pymysql://{quote_plus(db_user)}:"
    f"{quote_plus(db_password)}@{db_host}:{db_port}/{db_name}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# -------------------- MODELS --------------------

class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20), nullable=True)


class Category(db.Model):
    __tablename__ = "category"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)


class Product(db.Model):
    __tablename__ = "product"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)

    seller_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=True
    )
    seller = db.relationship("User", backref="products")

    category_id = db.Column(
        db.Integer, db.ForeignKey("category.id"), nullable=False
    )
    category = db.relationship("Category", backref="products")

    price = db.Column(db.Float, nullable=False)
    original_price = db.Column(db.Float, nullable=True)
    age_years = db.Column(db.Float, nullable=True)
    condition = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_filename = db.Column(db.String(255), nullable=True)
    status = db.Column(
        db.String(20), default="available", nullable=False
    )


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    receiver_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    product_id = db.Column(
        db.Integer, db.ForeignKey("product.id"), nullable=False
    )
    message_text = db.Column(db.Text, nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

    sender = db.relationship("User", foreign_keys=[sender_id])
    receiver = db.relationship("User", foreign_keys=[receiver_id])
    product = db.relationship("Product")


class PriceEstimate(db.Model):
    __tablename__ = "price_estimate"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    category_id = db.Column(
        db.Integer, db.ForeignKey("category.id"), nullable=False
    )
    original_price = db.Column(db.Float, nullable=False)
    age_years = db.Column(db.Float, nullable=False)
    condition = db.Column(db.String(20), nullable=False)
    estimated_price = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(40), nullable=False)


class Wishlist(db.Model):
    __tablename__ = "wishlist"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    product_id = db.Column(
        db.Integer, db.ForeignKey("product.id"), nullable=False
    )
    product = db.relationship("Product")

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "product_id",
            name="unique_user_wishlist_product"
        ),
    )


def logged_in():
    return bool(session.get("user_id"))


# -------------------- WELCOME AND HOME --------------------

@app.route("/")
def welcome():
    return render_template("welcome.html")


@app.route("/home")
def home():
    if not logged_in():
        flash("Please log in to access the marketplace.", "error")
        return redirect(url_for("login"))

    search_query = request.args.get("search", "").strip()
    category_id = request.args.get("category", "").strip()
    sort_by = request.args.get("sort", "newest").strip()

    query = Product.query.filter_by(status="available")

    if search_query:
        pattern = f"%{search_query}%"
        query = query.filter(
            or_(
                Product.name.ilike(pattern),
                Product.description.ilike(pattern)
            )
        )

    if category_id:
        try:
            query = query.filter(
                Product.category_id == int(category_id)
            )
        except ValueError:
            category_id = ""
            flash("Please select a valid category.", "error")

    if sort_by == "price_low":
        query = query.order_by(Product.price.asc())
    elif sort_by == "price_high":
        query = query.order_by(Product.price.desc())
    else:
        sort_by = "newest"
        query = query.order_by(Product.id.desc())

    products = query.all()
    categories = Category.query.order_by(Category.name.asc()).all()

    saved_product_ids = {
        item.product_id
        for item in Wishlist.query.filter_by(
            user_id=session["user_id"]
        ).all()
    }

    return render_template(
        "index.html",
        products=products,
        saved_product_ids=saved_product_ids,
        categories=categories,
        search_query=search_query,
        selected_category=category_id,
        sort_by=sort_by
    )


# -------------------- PRODUCT DETAILS --------------------

@app.route("/product/<int:product_id>")
def product_details(product_id):
    if not logged_in():
        flash("Please log in to view product details.", "error")
        return redirect(url_for("login"))

    product = db.session.get(Product, product_id)

    if product is None:
        return "Product not found", 404

    # Pass the actual Product object, not a dictionary.
    # This allows product.seller.phone and product.seller.username
    # to work in product_details.html.
    return render_template(
        "product_details.html",
        product=product,
        product_id=product.id
    )


# -------------------- REGISTRATION --------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("Please fill in all fields.", "error")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
            return redirect(url_for("register"))

        existing = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()

        if existing:
            flash("Username or email is already registered.", "error")
            return redirect(url_for("register"))

        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )

        try:
            db.session.add(user)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Registration failed")
            flash("Could not create your account. Please try again.", "error")
            return redirect(url_for("register"))

        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# -------------------- LOGIN --------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session["user_id"] = user.id
            session["username"] = user.username
            flash("Welcome to SwapNest, " + user.username + "!", "success")
            return redirect(url_for("home"))

        flash("Invalid email or password. Please try again.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


# -------------------- ACCOUNT AND CONTACT DETAILS --------------------

@app.route("/account")
def account():
    if not logged_in():
        flash("Please log in to view your account.", "error")
        return redirect(url_for("login"))

    user = db.session.get(User, session["user_id"])
    if user is None:
        session.clear()
        flash("Please log in again.", "error")
        return redirect(url_for("login"))

    return render_template("account.html", user=user)


@app.route("/account/contact", methods=["GET", "POST"])
def update_contact():
    if not logged_in():
        flash("Please log in first.", "error")
        return redirect(url_for("login"))

    user = db.session.get(User, session["user_id"])
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()

        if len(phone) > 20:
            flash("Phone number must be 20 characters or fewer.", "error")
        else:
            user.phone = phone or None
            db.session.commit()
            flash("Contact details updated successfully!", "success")
            return redirect(url_for("update_contact"))

    return render_template("store/contact_details.html", user=user)


# -------------------- LOGOUT --------------------

@app.route("/logout")
def logout():
    session.clear()
    flash("You have logged out successfully.", "success")
    return redirect(url_for("welcome"))


# -------------------- PRICE ESTIMATOR --------------------

@app.route("/price-estimator", methods=["GET", "POST"])
def price_estimator():
    if not logged_in():
        flash("Please log in to use the Price Estimator.", "error")
        return redirect(url_for("login"))

    categories = Category.query.order_by(Category.name).all()
    result = None

    if request.method == "POST":
        try:
            category_id = int(request.form.get("category_id", ""))
            category = db.session.get(Category, category_id)
            if category is None:
                raise ValueError("Invalid category")

            original_price = float(request.form.get("original_price", ""))
            age_years = float(request.form.get("age_years", ""))
            condition = request.form.get("condition", "").strip().lower()

            if (
                not all(map(lambda x: x == x and abs(x) != float("inf"),
                            [original_price, age_years]))
                or original_price <= 0
                or age_years < 0
                or age_years > 50
            ):
                raise ValueError("Invalid price or age")

            comparable_prices = [
                p.price for p in Product.query.filter_by(
                    category_id=category_id, status="available"
                ).all() if p.price > 0
            ]

            result = estimate_resale_price(
                original_price=original_price,
                age_years=age_years,
                condition=condition,
                comparable_prices=comparable_prices
            )

            db.session.add(PriceEstimate(
                user_id=session["user_id"],
                category_id=category_id,
                original_price=original_price,
                age_years=age_years,
                condition=condition,
                estimated_price=result["estimated_price"],
                method=result["method"]
            ))
            db.session.commit()

        except (ValueError, TypeError):
            db.session.rollback()
            flash(
                "Enter a valid original price, age, category and condition. "
                "Age must be between 0 and 50 years.",
                "error"
            )
            result = None
        except Exception:
            db.session.rollback()
            app.logger.exception("Price estimation failed")
            flash("Could not calculate the estimate. Please try again.", "error")
            result = None

    return render_template(
        "price_estimator.html", categories=categories, result=result
    )


# -------------------- IMAGE SEARCH --------------------

@app.route("/image-search", methods=["GET", "POST"])
def image_search():
    if not logged_in():
        flash("Please log in to use Image Search.", "error")
        return redirect(url_for("login"))

    image_url = None
    matched_products = []
    categories = Category.query.order_by(Category.name).all()
    selected_category_id = ""

    if request.method == "POST":
        image = request.files.get("product_image")
        selected_category_id = request.form.get("category_id", "").strip()

        if not image or not image.filename:
            flash("Please select a product image.", "error")
            return redirect(url_for("image_search"))

        filename = secure_filename(image.filename)
        if (
            "." not in filename
            or filename.rsplit(".", 1)[1].lower() not in ALLOWED_IMAGE_EXTENSIONS
        ):
            flash("Upload a PNG, JPG, JPEG, or WEBP image.", "error")
            return redirect(url_for("image_search"))

        try:
            category_id = int(selected_category_id)
        except (ValueError, TypeError):
            flash("Please select a valid product category.", "error")
            return redirect(url_for("image_search"))

        if db.session.get(Category, category_id) is None:
            flash("Please select a valid product category.", "error")
            return redirect(url_for("image_search"))

        extension = filename.rsplit(".", 1)[1].lower()
        saved_filename = f"{uuid4().hex}.{extension}"
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

        uploaded_path = os.path.join(
            app.config["UPLOAD_FOLDER"], saved_filename
        )
        image.save(uploaded_path)
        image_url = url_for("uploaded_image", filename=saved_filename)

        products = Product.query.filter(
            Product.category_id == category_id,
            Product.status == "available",
            Product.image_filename.isnot(None)
        ).all()

        for product in products:
            product_filename = secure_filename(product.image_filename or "")
            if not product_filename:
                continue

            product_path = os.path.join(
                app.config["PRODUCT_UPLOAD_FOLDER"], product_filename
            )
            if not os.path.isfile(product_path):
                continue

            try:
                product.similarity_score = compare_images(
                    uploaded_path, product_path
                )
                matched_products.append(product)
            except Exception:
                app.logger.warning(
                    "Could not compare image for product ID %s",
                    product.id, exc_info=True
                )

        matched_products.sort(
            key=lambda p: p.similarity_score, reverse=True
        )

        if matched_products:
            flash("Image comparison complete. Results are sorted by similarity.", "success")
        else:
            flash("No product images were available to compare in this category.", "error")

    return render_template(
        "image_search.html",
        image_url=image_url,
        categories=categories,
        matched_products=matched_products,
        selected_category_id=selected_category_id
    )


# -------------------- IMAGE SERVING --------------------

@app.route("/uploads/<filename>")
def uploaded_image(filename):
    return send_from_directory(
        app.config["UPLOAD_FOLDER"], filename, as_attachment=False
    )


@app.route("/product-images/<filename>")
def product_image(filename):
    safe_filename = secure_filename(filename)
    if not safe_filename:
        return "Image not found", 404

    return send_from_directory(
        app.config["PRODUCT_UPLOAD_FOLDER"],
        safe_filename,
        as_attachment=False
    )


# -------------------- ADD PRODUCT --------------------

@app.route("/add-product", methods=["GET", "POST"])
def add_product():
    if not logged_in():
        flash("Please log in to add a product.", "error")
        return redirect(url_for("login"))

    categories = Category.query.order_by(Category.name).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category_id = request.form.get("category_id", type=int)
        original_price = request.form.get("original_price", type=float)
        price = request.form.get("price", type=float)
        age_years = request.form.get("age_years", type=int)
        condition = request.form.get("condition", "").strip()
        description = request.form.get("description", "").strip()
        image = request.files.get("product_image")

        if (
            not name or not category_id or original_price is None
            or price is None or age_years is None or not condition
            or not description or not image or not image.filename
        ):
            flash("Please fill in all fields and select an image.", "error")
            return render_template("add_product.html", categories=categories)

        if price <= 0 or original_price <= 0 or age_years < 0:
            flash("Enter valid prices and product age.", "error")
            return render_template("add_product.html", categories=categories)

        if price > original_price:
            flash("Selling price should not exceed original price.", "error")
            return render_template("add_product.html", categories=categories)

        if db.session.get(Category, category_id) is None:
            flash("Please select a valid category.", "error")
            return render_template("add_product.html", categories=categories)

        filename = secure_filename(image.filename)
        if (
            "." not in filename
            or filename.rsplit(".", 1)[1].lower() not in ALLOWED_IMAGE_EXTENSIONS
        ):
            flash("Upload a JPG, JPEG, PNG, or WEBP image.", "error")
            return render_template("add_product.html", categories=categories)

        extension = filename.rsplit(".", 1)[1].lower()
        image_filename = f"{uuid4().hex}.{extension}"
        os.makedirs(app.config["PRODUCT_UPLOAD_FOLDER"], exist_ok=True)
        image_path = os.path.join(
            app.config["PRODUCT_UPLOAD_FOLDER"], image_filename
        )

        try:
            image.save(image_path)
            db.session.add(Product(
                name=name,
                seller_id=session["user_id"],
                category_id=category_id,
                price=price,
                original_price=original_price,
                age_years=age_years,
                condition=condition,
                description=description,
                image_filename=image_filename,
                status="available"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
            if os.path.isfile(image_path):
                os.remove(image_path)
            app.logger.exception("Adding product failed")
            flash("Could not add the product. Please try again.", "error")
            return render_template("add_product.html", categories=categories)

        flash("Product added successfully!", "success")
        return redirect(url_for("home"))

    return render_template("add_product.html", categories=categories)


# -------------------- SELLER DASHBOARD --------------------

@app.route("/seller-dashboard")
def seller_dashboard():
    if not logged_in():
        flash("Please log in to view your dashboard.", "error")
        return redirect(url_for("login"))

    products = Product.query.filter_by(
        seller_id=session["user_id"]
    ).order_by(Product.id.desc()).all()

    return render_template(
        "seller_dashboard.html",
        products=products,
        total_products=len(products),
        available_products=sum(p.status == "available" for p in products),
        sold_products=sum(p.status == "sold" for p in products)
    )


# -------------------- EDIT PRODUCT --------------------

@app.route("/edit-product/<int:product_id>", methods=["GET", "POST"])
def edit_product(product_id):
    if not logged_in():
        flash("Please log in first.", "error")
        return redirect(url_for("login"))

    product = Product.query.filter_by(
        id=product_id, seller_id=session["user_id"]
    ).first_or_404()
    categories = Category.query.order_by(Category.name).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category_id = request.form.get("category_id", type=int)
        price = request.form.get("price", type=float)
        original_price = request.form.get("original_price", type=float)
        condition = request.form.get("condition", "").strip()
        description = request.form.get("description", "").strip()
        image = request.files.get("product_image")
        category = db.session.get(Category, category_id) if category_id else None

        if not name or not category or price is None or original_price is None or not condition or not description:
            flash("Please complete all required fields.", "error")
            return render_template("edit_product.html", product=product, categories=categories)

        if price <= 0 or original_price <= 0 or price > original_price:
            flash("Enter valid prices. Selling price must not exceed original price.", "error")
            return render_template("edit_product.html", product=product, categories=categories)

        product.name = name
        product.category_id = category.id
        product.price = price
        product.original_price = original_price
        product.condition = condition
        product.description = description

        if image and image.filename:
            filename = secure_filename(image.filename)
            if "." not in filename or filename.rsplit(".", 1)[1].lower() not in ALLOWED_IMAGE_EXTENSIONS:
                flash("Upload a JPG, JPEG, PNG, or WEBP image.", "error")
                return render_template("edit_product.html", product=product, categories=categories)

            extension = filename.rsplit(".", 1)[1].lower()
            new_filename = f"{uuid4().hex}.{extension}"
            os.makedirs(app.config["PRODUCT_UPLOAD_FOLDER"], exist_ok=True)
            image_path = os.path.join(app.config["PRODUCT_UPLOAD_FOLDER"], new_filename)
            image.save(image_path)
            old_image = product.image_filename
            product.image_filename = new_filename
        else:
            image_path = None
            old_image = None

        try:
            db.session.commit()
            if old_image:
                old_path = os.path.join(
                    app.config["PRODUCT_UPLOAD_FOLDER"], secure_filename(old_image)
                )
                if os.path.isfile(old_path):
                    os.remove(old_path)
        except Exception:
            db.session.rollback()
            if image_path and os.path.isfile(image_path):
                os.remove(image_path)
            app.logger.exception("Updating product failed")
            flash("Could not update product.", "error")
            return redirect(url_for("seller_dashboard"))

        flash("Product updated successfully!", "success")
        return redirect(url_for("seller_dashboard"))

    return render_template("edit_product.html", product=product, categories=categories)


# -------------------- MARK AS SOLD AND DELETE --------------------

@app.route("/mark-sold/<int:product_id>", methods=["POST"])
def mark_sold(product_id):
    if not logged_in():
        flash("Please log in first.", "error")
        return redirect(url_for("login"))

    product = Product.query.filter_by(
        id=product_id, seller_id=session["user_id"]
    ).first_or_404()

    if product.status == "available":
        product.status = "sold"
        db.session.commit()
        flash("Product marked as sold!", "success")
    else:
        flash("This product is not currently available.", "error")

    return redirect(url_for("seller_dashboard"))


@app.route("/delete-product/<int:product_id>", methods=["POST"])
def delete_product(product_id):
    if not logged_in():
        flash("Please log in first.", "error")
        return redirect(url_for("login"))

    product = Product.query.filter_by(
        id=product_id, seller_id=session["user_id"]
    ).first_or_404()

    try:
        Wishlist.query.filter_by(product_id=product.id).delete(
            synchronize_session=False
        )
        image_filename = product.image_filename
        db.session.delete(product)
        db.session.commit()

        if image_filename:
            image_path = os.path.join(
                app.config["PRODUCT_UPLOAD_FOLDER"],
                secure_filename(image_filename)
            )
            if os.path.isfile(image_path):
                os.remove(image_path)

        flash("Product deleted successfully.", "success")
    except Exception:
        db.session.rollback()
        app.logger.exception("Deleting product failed")
        flash("Could not delete product. Please try again.", "error")

    return redirect(url_for("seller_dashboard"))


# -------------------- WISHLIST --------------------

@app.route("/wishlist")
def wishlist():
    if not logged_in():
        flash("Please log in to view your wishlist.", "error")
        return redirect(url_for("login"))

    items = Wishlist.query.filter_by(
        user_id=session["user_id"]
    ).order_by(Wishlist.id.desc()).all()

    return render_template("wishlist.html", wishlist_items=items)


@app.route("/wishlist/add/<int:product_id>", methods=["POST"])
def add_to_wishlist(product_id):
    if not logged_in():
        flash("Please log in to save products.", "error")
        return redirect(url_for("login"))

    product = db.session.get(Product, product_id)
    if product is None or product.status != "available":
        flash("This product is no longer available.", "error")
        return redirect(url_for("home"))

    existing = Wishlist.query.filter_by(
        user_id=session["user_id"], product_id=product_id
    ).first()

    if existing:
        flash("This product is already in your wishlist.", "info")
    else:
        try:
            db.session.add(Wishlist(
                user_id=session["user_id"], product_id=product_id
            ))
            db.session.commit()
            flash("Product saved to your wishlist!", "success")
        except IntegrityError:
            db.session.rollback()
            flash("This product is already in your wishlist.", "info")
        except Exception:
            db.session.rollback()
            app.logger.exception("Adding wishlist item failed")
            flash("Could not save this product. Please try again.", "error")

    return redirect(request.referrer or url_for("home"))


@app.route("/wishlist/remove/<int:wishlist_id>", methods=["POST"])
def remove_from_wishlist(wishlist_id):
    if not logged_in():
        flash("Please log in to manage your wishlist.", "error")
        return redirect(url_for("login"))

    item = Wishlist.query.filter_by(
        id=wishlist_id, user_id=session["user_id"]
    ).first()

    if item is None:
        flash("Wishlist item was not found.", "error")
    else:
        db.session.delete(item)
        db.session.commit()
        flash("Product removed from your wishlist.", "success")

    return redirect(url_for("wishlist"))


# -------------------- MESSAGES --------------------

@app.route("/messages/<int:product_id>/<int:other_user_id>", methods=["GET", "POST"])
def message_thread(product_id, other_user_id):
    if not logged_in():
        flash("Please log in to send messages.", "error")
        return redirect(url_for("login"))

    current_user_id = session["user_id"]
    product = db.session.get(Product, product_id)
    other_user = db.session.get(User, other_user_id)

    if product is None or other_user is None:
        flash("Product or user not found.", "error")
        return redirect(url_for("home"))

    if current_user_id == product.seller_id:
        has_contact = Message.query.filter(
            Message.product_id == product_id,
            Message.sender_id == other_user_id,
            Message.receiver_id == current_user_id
        ).first()

        if not has_contact:
            flash("You can reply only to a buyer who contacted you.", "error")
            return redirect(url_for("inbox"))
    elif other_user_id != product.seller_id:
        flash("You can message only this product's seller.", "error")
        return redirect(url_for("home"))

    if current_user_id == other_user_id:
        flash("You cannot message yourself.", "error")
        return redirect(url_for("home"))

    if request.method == "POST":
        message_text = request.form.get("message_text", "").strip()

        if not message_text:
            flash("Please enter a message.", "error")
        elif len(message_text) > 5000:
            flash("Message is too long. Maximum 5000 characters.", "error")
        else:
            db.session.add(Message(
                sender_id=current_user_id,
                receiver_id=other_user_id,
                product_id=product_id,
                message_text=message_text
            ))
            db.session.commit()
            return redirect(url_for(
                "message_thread",
                product_id=product_id,
                other_user_id=other_user_id
            ))

    thread = Message.query.filter(
        Message.product_id == product_id,
        or_(
            and_(
                Message.sender_id == current_user_id,
                Message.receiver_id == other_user_id
            ),
            and_(
                Message.sender_id == other_user_id,
                Message.receiver_id == current_user_id
            )
        )
    ).order_by(Message.sent_at.asc()).all()

    for msg in thread:
        if msg.receiver_id == current_user_id:
            msg.is_read = True

    db.session.commit()

    return render_template(
        "store/message_thread.html",
        product=product,
        other_user=other_user,
        thread=thread,
        current_user_id=current_user_id
    )


@app.route("/inbox")
def inbox():
    if not logged_in():
        flash("Please log in to view your messages.", "error")
        return redirect(url_for("login"))

    current_user_id = session["user_id"]
    messages = Message.query.filter(
        or_(
            Message.sender_id == current_user_id,
            Message.receiver_id == current_user_id
        )
    ).order_by(Message.sent_at.desc()).all()

    return render_template(
        "store/inbox.html",
        messages=messages,
        current_user_id=current_user_id
    )


# -------------------- ERROR HANDLING --------------------

@app.errorhandler(413)
def file_too_large(error):
    flash("Image is too large. Maximum file size is 5 MB.", "error")
    return redirect(url_for("image_search"))


# -------------------- DATABASE INITIALIZATION --------------------

with app.app_context():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["PRODUCT_UPLOAD_FOLDER"], exist_ok=True)

    db.create_all()

    # Add seller_id to an existing product table if it is missing.
    product_columns = {
        column["name"]
        for column in inspect(db.engine).get_columns("product")
    }

    if "seller_id" not in product_columns:
        db.session.execute(
            text("ALTER TABLE product ADD COLUMN seller_id INT NULL")
        )
        db.session.commit()

    default_categories = [
        "Books", "Mobiles", "Laptops",
        "Bicycles", "Electronics", "Clothing"
    ]

    for category_name in default_categories:
        if not Category.query.filter_by(name=category_name).first():
            db.session.add(Category(name=category_name))

    db.session.commit()


# -------------------- RUN APPLICATION --------------------

if __name__ == "__main__":
    app.run(debug=True)