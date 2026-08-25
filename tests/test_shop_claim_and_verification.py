import unittest
import sys
import os
from datetime import datetime, timedelta, timezone

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from mw_app import create_app
from mw_app.extensions import db
from mw_app.models.user_model import User, USER_ROLE_BUYER, USER_ROLE_SELLER
from mw_app.models.shop_model import Shop, VerificationOTP
from mw_app.utils.phone_utils import normalize_ghana_phone, validate_ghana_phone, mask_phone_number

class TestPhoneNormalization(unittest.TestCase):

    def test_ghana_phone_normalization(self):
        # Test common Ghanaian formats -> canonical 233XXXXXXXXX
        self.assertEqual(normalize_ghana_phone("0553995047"), "233553995047")
        self.assertEqual(normalize_ghana_phone("+233553995047"), "233553995047")
        self.assertEqual(normalize_ghana_phone("233553995047"), "233553995047")
        self.assertEqual(normalize_ghana_phone("553995047"), "233553995047")
        self.assertEqual(normalize_ghana_phone("055 399-5047"), "233553995047")
        self.assertEqual(normalize_ghana_phone("+233 (0)55 399 5047"), "233553995047")

    def test_invalid_phone_rejection(self):
        self.assertIsNone(normalize_ghana_phone("12345"))
        self.assertIsNone(normalize_ghana_phone("abcdef"))
        self.assertIsNone(normalize_ghana_phone(""))
        self.assertIsNone(normalize_ghana_phone(None))

    def test_mask_phone_number(self):
        self.assertEqual(mask_phone_number("0553995047"), "+233 55 *** 5047")


class TestVerificationOTPAndClaim(unittest.TestCase):

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_otp_creation_and_cooldown(self):
        user = User(username="testuser", email="test@example.com", phone="233553995047")
        db.session.add(user)
        db.session.commit()

        # Create OTP
        otp_rec, code = VerificationOTP.create_otp(
            user_id=user.id,
            otp_type='phone',
            contact_value='233553995047',
            expires_in_minutes=10,
            cooldown_seconds=180
        )
        self.assertIsNotNone(otp_rec)
        self.assertEqual(len(code), 6)

        # Check server-side 180s cooldown active immediately after creation
        in_cooldown, remaining = VerificationOTP.check_resend_cooldown(
            user_id=user.id,
            otp_type='phone'
        )
        self.assertTrue(in_cooldown)
        self.assertGreater(remaining, 170)

    def test_otp_attempt_limits(self):
        user = User(username="testuser2", email="test2@example.com", phone="233553995047")
        db.session.add(user)
        db.session.commit()

        otp_rec, code = VerificationOTP.create_otp(
            user_id=user.id,
            otp_type='phone',
            contact_value='233553995047'
        )

        # 4 wrong attempts
        for _ in range(4):
            valid, msg = otp_rec.verify_otp("000000")
            self.assertFalse(valid)
            self.assertIn("Invalid verification code", msg)

        # 5th wrong attempt should lock code
        valid, msg = otp_rec.verify_otp("000000")
        self.assertFalse(valid)

        # Submitting correct code now should fail due to max attempts reached
        valid, msg = otp_rec.verify_otp(code)
        self.assertFalse(valid)
        self.assertIn("Maximum verification attempts", msg)

    def test_contact_matching_and_shop_claiming(self):
        # Create shop
        shop = Shop(
            name="Accra Electronics",
            phone="0553995047",  # Un-normalized store string
            email="accra@store.com",
            is_claimed=False
        )
        db.session.add(shop)

        # Create User 1 (verified matching phone)
        user1 = User(
            username="realowner",
            email="owner@different.com",
            phone="233553995047",
            is_phone_verified=True,
            role=USER_ROLE_BUYER
        )
        
        # Create User 2 (verified non-matching phone)
        user2 = User(
            username="imposter",
            email="imposter@different.com",
            phone="233201234567",
            is_phone_verified=True,
            role=USER_ROLE_BUYER
        )
        
        db.session.add_all([user1, user2])
        db.session.commit()

        # Test claiming with User 2 (non-matching) via test client
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user2.id)

            res = client.post(f'/api/seller/shop/{shop.id}/claim')
            self.assertEqual(res.status_code, 403)
            self.assertIn("Cannot claim shop", res.get_json()['message'])

        # Test claiming with User 1 (matching phone)
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user1.id)

            res = client.post(f'/api/seller/shop/{shop.id}/claim')
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.get_json()['success'])

            # Verify DB updates
            updated_shop = Shop.query.get(shop.id)
            updated_user = User.query.get(user1.id)
            self.assertTrue(updated_shop.is_claimed)
            self.assertEqual(updated_shop.owner_id, user1.id)
            self.assertEqual(updated_user.role, USER_ROLE_SELLER)


if __name__ == '__main__':
    unittest.main()
