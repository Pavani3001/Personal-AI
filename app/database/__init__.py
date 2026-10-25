"""Database package for Personal AI."""

from app.database.base import BaseRepository, DatabaseError
from app.database.database import Database
from app.database.postgres import PostgresRepository
from app.database.sqlite import SQLiteRepository

__all__ = [
    "BaseRepository",
    "Database",
    "DatabaseError",
    "PostgresRepository",
    "SQLiteRepository",
]
