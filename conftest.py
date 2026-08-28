import os
from dotenv import load_dotenv

# Load api.env first if present
load_dotenv("api.env")

# Set test environment variable for JWT_SECRET_KEY if not already set in environment/api.env
if not os.getenv("JWT_SECRET_KEY"):
    os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-pytest-suite-12345"
