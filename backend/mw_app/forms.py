from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    SelectField,
    TextAreaField,
    BooleanField,
    DecimalField,
    IntegerField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    ValidationError,
    NumberRange,
    Optional,
)

# Import User model to avoid circular imports
from mw_app.models.user_model import User


class LoginForm(FlaskForm):
    username = StringField('Username or Email', validators=[DataRequired(), Length(min=3, max=80)])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember me')

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    first_name = StringField('First Name', validators=[DataRequired(), Length(min=2, max=50)])
    last_name = StringField('Last Name', validators=[DataRequired(), Length(min=2, max=50)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    role = SelectField('Account Type', choices=[('buyer', 'Buyer'), ('seller', 'Seller')], validators=[DataRequired()])
    terms = BooleanField('I agree to the Terms of Service and Privacy Policy', validators=[DataRequired()])
    
    def validate_username(self, username):
        if User is None:
            return  # Skip validation if User model not available
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('That username is already taken. Please choose a different one.')
    
    def validate_email(self, email):
        if User is None:
            return  # Skip validation if User model not available
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is already registered. Please choose a different one.')

class ShopForm(FlaskForm):
    name = StringField('Shop Name', validators=[DataRequired(), Length(min=3, max=100)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=1000)])
    phone = StringField('Phone Number', validators=[Optional(), Length(min=10, max=20)])
    email = StringField('Shop Email', validators=[Optional(), Email()])
    address = TextAreaField('Address', validators=[Optional(), Length(max=300)])
    region = StringField('Region', validators=[Optional(), Length(max=100)])
    district = StringField('District', validators=[Optional(), Length(max=100)])
    town = StringField('Town', validators=[Optional(), Length(max=100)])
    gps = StringField('GPS Coordinates', validators=[Optional(), Length(max=64)])

class ProductForm(FlaskForm):
    name = StringField('Product Name', validators=[DataRequired(), Length(min=3, max=100)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=2000)])
    type_ = SelectField('Type', choices=[('product', 'Product'), ('service', 'Service')], validators=[DataRequired()])
    price = DecimalField('Price', places=2, validators=[DataRequired(), NumberRange(min=0)])
    stock = IntegerField('Stock Quantity', validators=[DataRequired(), NumberRange(min=0)])
    category_id = SelectField('Category', coerce=int, validators=[DataRequired()])
    is_active = BooleanField('Active', default=True)
