import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import User, Receipt, LedgerTransaction
from auth import hash_password, verify_password, create_access_token, get_current_user

import importlib

TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture
def db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

def test_password_hashing_and_verification():
    raw_pass = "SecurePass123!"
    hashed = hash_password(raw_pass)
    
    assert hashed != raw_pass
    assert verify_password(raw_pass, hashed) is True
    assert verify_password("WrongPassword", hashed) is False

def test_jwt_token_generation_and_user_fetch(db_session):
    user = User(email="auth_user@company.com", name="Auth User", hashed_password=hash_password("Secret123"))
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    
    token = create_access_token(data={"sub": user.email})
    assert token is not None
    
    fetched_user = get_current_user(token=token, db=db_session)
    assert fetched_user.id == user.id
    assert fetched_user.email == "auth_user@company.com"

def test_jwt_secret_key_missing_raises_runtime_error(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    # Also patch load_dotenv to avoid reloading from api.env during this test
    monkeypatch.setattr("auth.load_dotenv", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError) as exc_info:
        import auth
        importlib.reload(auth)
    assert "JWT_SECRET_KEY is not set in environment variables" in str(exc_info.value)
    
    # Restore env and reload module for remaining tests
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-for-pytest-suite-12345")
    import auth
    importlib.reload(auth)
