"""
auth_manager.py — Authentication, password hashing (PBKDF2), and Role-Based Access Control (RBAC).

Clean Architecture — Core Security Layer.
Roles:
  - ADMIN: Full system access, user management, settings, account config.
  - OPERATOR: Run/stop backups, restore, view history and reports. Cannot edit users or system secrets.
  - VIEWER: Read-only access to audit logs, backup history, and reports.
"""

import hashlib
import hmac
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from domain.entities import Role, User

logger = logging.getLogger(__name__)

ITERATIONS = 100_000


class Permissions:
    MANAGE_USERS = "manage_users"
    MANAGE_SETTINGS = "manage_settings"
    MANAGE_ACCOUNTS = "manage_accounts"
    BACKUP_TRIGGER = "backup_trigger"
    BACKUP_CREATE_JOB = "backup_create_job"
    RESTORE_TRIGGER = "restore_trigger"
    SAVE_JOB = "save_job"
    DELETE_JOB = "delete_job"
    VIEW_REPORTS = "view_reports"
    VIEW_HISTORY = "view_history"
    VIEW_AUDIT = "view_audit"
    VIEW_DASHBOARD = "view_dashboard"


ROLE_PERMISSIONS: Dict[str, List[str]] = {
    Role.ADMIN: [
        Permissions.MANAGE_USERS,
        Permissions.MANAGE_SETTINGS,
        Permissions.MANAGE_ACCOUNTS,
        Permissions.BACKUP_TRIGGER,
        Permissions.BACKUP_CREATE_JOB,
        Permissions.RESTORE_TRIGGER,
        Permissions.SAVE_JOB,
        Permissions.DELETE_JOB,
        Permissions.VIEW_REPORTS,
        Permissions.VIEW_HISTORY,
        Permissions.VIEW_AUDIT,
        Permissions.VIEW_DASHBOARD,
    ],
    Role.OPERATOR: [
        Permissions.BACKUP_TRIGGER,
        Permissions.BACKUP_CREATE_JOB,
        Permissions.RESTORE_TRIGGER,
        Permissions.SAVE_JOB,
        Permissions.DELETE_JOB,
        Permissions.VIEW_REPORTS,
        Permissions.VIEW_HISTORY,
        Permissions.VIEW_AUDIT,
        Permissions.VIEW_DASHBOARD,
    ],
    Role.VIEWER: [
        Permissions.VIEW_REPORTS,
        Permissions.VIEW_HISTORY,
        Permissions.VIEW_AUDIT,
        Permissions.VIEW_DASHBOARD,
    ],
}


def hash_password(plain_password: str, salt_hex: Optional[str] = None) -> tuple[str, str]:
    """Hash password using PBKDF2-HMAC-SHA256 with random 16-byte salt."""
    if not salt_hex:
        salt_bytes = os.urandom(16)
        salt_hex = salt_bytes.hex()
    else:
        salt_bytes = bytes.fromhex(salt_hex)

    key = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt_bytes,
        ITERATIONS,
        dklen=32
    )
    return key.hex(), salt_hex


def verify_password(plain_password: str, password_hash: str, salt_hex: str) -> bool:
    """Verify password against stored hash and salt in constant time."""
    try:
        calculated_hash, _ = hash_password(plain_password, salt_hex)
        return hmac.compare_digest(calculated_hash, password_hash)
    except Exception as exc:
        logger.error("Password verification error: %s", exc)
        return False


class AuthManager:
    """Session and authorization manager."""

    _instance: Optional["AuthManager"] = None
    _lock = threading.Lock()

    def __init__(self, db_manager=None):
        self._db = db_manager
        self._current_user: Optional[User] = None

    @classmethod
    def get_instance(cls, db_manager=None) -> "AuthManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(db_manager=db_manager)
            elif db_manager is not None:
                cls._instance._db = db_manager
            return cls._instance

    @property
    def current_user(self) -> Optional[User]:
        return self._current_user

    def is_authenticated(self) -> bool:
        return self._current_user is not None

    def login(self, username: str, plain_password: str) -> tuple[bool, Optional[User], str]:
        """Authenticate user against database credentials."""
        if not self._db:
            return False, None, "Veritabanı bağlantısı yok."

        user_dict = self._db.get_user_by_username(username.strip())
        if not user_dict:
            return False, None, "Geçersiz kullanıcı adı veya şifre."

        if not user_dict.get("is_active", 1):
            return False, None, "Bu kullanıcı hesabı devre dışı bırakılmıştır."

        stored_hash = user_dict.get("password_hash", "")
        stored_salt = user_dict.get("salt", "")

        if not verify_password(plain_password, stored_hash, stored_salt):
            return False, None, "Geçersiz kullanıcı adı veya şifre."

        user = User(
            id=user_dict["id"],
            username=user_dict["username"],
            password_hash=stored_hash,
            salt=stored_salt,
            full_name=user_dict.get("full_name", ""),
            email=user_dict.get("email", ""),
            role=user_dict.get("role", Role.OPERATOR),
            is_active=bool(user_dict.get("is_active", 1)),
            last_login=user_dict.get("last_login"),
            created_at=user_dict.get("created_at"),
        )
        self._current_user = user
        self._db.update_user_last_login(user.id)
        logger.info("User logged in successfully: %s (%s)", user.username, user.role)
        return True, user, "Giriş başarılı."

    def logout(self) -> None:
        if self._current_user:
            logger.info("User logged out: %s", self._current_user.username)
        self._current_user = None

    def has_permission(self, permission: str) -> bool:
        """Check if currently logged-in user possesses the specified permission."""
        if not self._current_user:
            return False
        role = self._current_user.role or Role.VIEWER
        if hasattr(role, "value"):
            role = role.value
        allowed_permissions = ROLE_PERMISSIONS.get(role, [])
        return permission in allowed_permissions

    def list_users(self) -> List[Dict[str, Any]]:
        """List all users in the system."""
        if not self._db:
            return []
        return self._db.list_users()

    def create_user(self, username: str, password: str, role: str = "OPERATOR",
                    full_name: str = "", email: str = "") -> tuple[bool, str, Optional[int]]:
        """Create a new user with hashed password."""
        if not self._db:
            return False, "Veritabanı bağlantısı yok.", None
        existing = self._db.get_user_by_username(username.strip())
        if existing:
            return False, f"'{username}' kullanıcı adı zaten mevcut.", None

        pwd_hash, salt = hash_password(password)
        try:
            uid = self._db.save_user({
                "username": username.strip(),
                "password_hash": pwd_hash,
                "salt": salt,
                "role": role.upper(),
                "full_name": full_name.strip(),
                "email": email.strip(),
                "is_active": 1,
            })
            return True, "Kullanıcı başarıyla oluşturuldu.", uid
        except Exception as exc:
            return False, f"Kullanıcı kaydedilemedi: {exc}", None

    def update_user_password(self, user_id: int, new_password: str) -> tuple[bool, str]:
        """Update password for user."""
        if not self._db:
            return False, "Veritabanı bağlantısı yok."
        pwd_hash, salt = hash_password(new_password)
        ok = self._db.update_user_password(user_id, pwd_hash, salt)
        if ok:
            return True, "Şifre başarıyla güncellendi."
        return False, "Kullanıcı bulunamadı veya güncellenemedi."

    def delete_user(self, user_id: int) -> tuple[bool, str]:
        """Delete user by ID."""
        if not self._db:
            return False, "Veritabanı bağlantısı yok."
        ok = self._db.delete_user(user_id)
        if ok:
            return True, "Kullanıcı silindi."
        return False, "Kullanıcı silinemedi."


SessionManager = AuthManager
