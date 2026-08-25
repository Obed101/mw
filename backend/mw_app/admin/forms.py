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
    google_category = StringField('Category', validators=[Optional(), Length(max=100)])
    description = TextAreaField('Description', validators=[Optional()])
    business_type = SelectField(
        'Business Type',
        choices=[('sales', 'Product Seller (Sales)'), ('service', 'Service Provider'), ('both', 'Both')],
    )
    phone = StringField('Phone', validators=[Optional(), Length(max=20)])
    email = StringField('Email', validators=[Optional(), Email()])
    address = StringField('Address', validators=[Optional(), Length(max=255)])
    region = StringField('Region', validators=[Optional(), Length(max=100)])
    district = StringField('District', validators=[Optional(), Length(max=100)])
    town = StringField('Town', validators=[Optional(), Length(max=100)])
    gps = StringField('GPS', validators=[Optional(), Length(max=64)])
    plus_code = StringField('Plus Code', validators=[Optional(), Length(max=30)])
    landmark = StringField('Landmark', validators=[Optional(), Length(max=255)])
    source = StringField('Source', validators=[Optional(), Length(max=20)])
    source_reference = StringField('Source Reference', validators=[Optional(), Length(max=255)])
    google_image_url = StringField('Google Image URL', validators=[Optional(), Length(max=500)])
    data_quality_score = IntegerField('Data Quality Score', validators=[Optional()])
    verification_notes = TextAreaField('Verification Notes', validators=[Optional()])
    promoted = BooleanField('Promoted')
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
