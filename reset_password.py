#!/usr/bin/env python3
"""
Utility script to reset user password or create a new admin user.
Run from the doxsnap_be directory:
    python reset_password.py
"""
import sys
import os

# Add the app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, engine, Base
from app.models import User
from app.utils.security import get_password_hash

def list_users():
    """List all users in the database"""
    db = SessionLocal()
    try:
        users = db.query(User).all()
        if not users:
            print("\nNo users found in database.")
            return []

        print("\n=== Existing Users ===")
        for user in users:
            print(f"  ID: {user.id}, Email: {user.email}, Name: {user.name}, Role: {user.role}, Active: {user.is_active}")
        return users
    finally:
        db.close()

def reset_password(email: str, new_password: str):
    """Reset password for an existing user"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"\nError: User with email '{email}' not found.")
            return False

        user.hashed_password = get_password_hash(new_password)
        user.is_active = True  # Ensure user is active
        db.commit()
        print(f"\nSuccess! Password reset for user: {email}")
        return True
    finally:
        db.close()

def create_admin(email: str, password: str, name: str = "Admin"):
    """Create a new admin user"""
    db = SessionLocal()
    try:
        # Check if user already exists
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print(f"\nUser with email '{email}' already exists. Use reset option instead.")
            return False

        user = User(
            email=email,
            name=name,
            hashed_password=get_password_hash(password),
            is_active=True,
            is_admin=True,
            role="admin",
            remaining_documents=999
        )
        db.add(user)
        db.commit()
        print(f"\nSuccess! Created admin user: {email}")
        return True
    finally:
        db.close()

def main():
    print("\n=== DoxSnap User Management ===")

    # First, list existing users
    users = list_users()

    print("\nOptions:")
    print("  1. Reset password for existing user")
    print("  2. Create new admin user")
    print("  3. Exit")

    choice = input("\nEnter choice (1/2/3): ").strip()

    if choice == "1":
        if not users:
            print("No users to reset. Create a new admin user instead.")
            choice = "2"
        else:
            email = input("Enter user email: ").strip()
            new_password = input("Enter new password: ").strip()
            if email and new_password:
                reset_password(email, new_password)
            else:
                print("Email and password are required.")

    if choice == "2":
        email = input("Enter admin email: ").strip()
        password = input("Enter password: ").strip()
        name = input("Enter name (default: Admin): ").strip() or "Admin"
        if email and password:
            create_admin(email, password, name)
        else:
            print("Email and password are required.")

    if choice == "3":
        print("Goodbye!")

if __name__ == "__main__":
    main()
