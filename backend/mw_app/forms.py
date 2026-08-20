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
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=150)])
    email = StringField('Email Address', validators=[Optional(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    terms = BooleanField('I agree to the Terms of Service and Privacy Policy', validators=[DataRequired()])

    def validate_email(self, email):
        if not email.data:
            return  # Email is optional
        if User is None:
            return
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is already registered. Please use a different one or sign in.')

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
