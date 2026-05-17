from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, SelectField, TextAreaField, FloatField, IntegerField
from wtforms.validators import DataRequired, Email, Optional, Length


class UserEditForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    phone = StringField('Phone', validators=[Optional(), Length(max=20)])
    first_name = StringField('First Name', validators=[Optional(), Length(max=100)])
    last_name = StringField('Last Name', validators=[Optional(), Length(max=100)])
    is_active = BooleanField('Account Active')


class ShopAdminEditForm(FlaskForm):
    name = StringField('Shop Name', validators=[DataRequired(), Length(max=150)])
    description = TextAreaField('Description', validators=[Optional()])
    phone = StringField('Phone', validators=[Optional(), Length(max=20)])
    email = StringField('Email', validators=[Optional(), Email()])
    address = StringField('Address', validators=[Optional(), Length(max=255)])
    is_active = BooleanField('Shop Active')
    verification_status = SelectField(
        'Verification Status',
        choices=[
            ('pending', 'Pending'),
            ('under_review', 'Under Review'),
            ('verified', 'Verified'),
            ('rejected', 'Rejected'),
            ('suspended', 'Suspended'),
        ]
    )


class ProductAdminEditForm(FlaskForm):
    name = StringField('Product Name', validators=[DataRequired(), Length(max=150)])
    description = TextAreaField('Description', validators=[Optional()])
    price = FloatField('Price', validators=[DataRequired()])
    stock = IntegerField('Stock', validators=[Optional()])
    is_active = BooleanField('Active')
    is_hidden = BooleanField('Hidden (admin hide)')
