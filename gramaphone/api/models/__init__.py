from datetime import datetime
from typing import Optional
from sqlalchemy import (
    DateTime, String, Text, Integer, Float, Boolean, ForeignKey, 
    UniqueConstraint, Index, JSON, Date, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase
from sqlalchemy.dialects.postgresql import UUID
import uuid


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    profile: Mapped["Profile"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), default="Listener")
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    fav_artists: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="profile")
    listening_history: Mapped[list["ListeningHistory"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    artist_affinities: Mapped[list["ArtistAffinity"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    taste_profile: Mapped[list["TasteProfile"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    daily_blueprints: Mapped[list["DailyBlueprint"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    playlists: Mapped[list["Playlist"]] = relationship(back_populates="profile", cascade="all, delete-orphan")


class ListeningHistory(Base):
    __tablename__ = "listening_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    track_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    artist: Mapped[str] = mapped_column(String(255), index=True)
    album: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    art_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    video_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    played_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    play_duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    track_duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)

    profile: Mapped["Profile"] = relationship(back_populates="listening_history")

    __table_args__ = (
        Index("ix_lh_profile_played_desc", "profile_id", "played_at"),
    )


class ArtistAffinity(Base):
    __tablename__ = "artist_affinity"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    artist_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    skip_count: Mapped[int] = mapped_column(Integer, default=0)
    fav_count: Mapped[int] = mapped_column(Integer, default=0)
    playlist_add_count: Mapped[int] = mapped_column(Integer, default=0)
    affinity_score: Mapped[float] = mapped_column(Float, default=0.0)
    last_updated: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    profile: Mapped["Profile"] = relationship(back_populates="artist_affinities")


class TasteProfile(Base):
    __tablename__ = "taste_profile"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    genre: Mapped[str] = mapped_column(String(100), primary_key=True)
    percentage: Mapped[float] = mapped_column(Float, default=0.0)
    last_updated: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    profile: Mapped["Profile"] = relationship(back_populates="taste_profile")


class DailyBlueprint(Base):
    __tablename__ = "daily_blueprints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[Date] = mapped_column(Date, nullable=False, index=True)
    strategy: Mapped[dict] = mapped_column(JSON, nullable=False)
    seed_tracks: Mapped[list] = mapped_column(JSON, nullable=False)
    playlist_updates: Mapped[dict] = mapped_column(JSON, default=dict)
    runtime_stats: Mapped[dict] = mapped_column(JSON, default=lambda: {"completed": 0, "skipped": 0, "total": 0})
    llm_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    profile: Mapped["Profile"] = relationship(back_populates="daily_blueprints")

    __table_args__ = (
        UniqueConstraint("profile_id", "date", name="uq_blueprint_profile_date"),
        Index("ix_blueprint_profile_date_desc", "profile_id", "date"),
    )


class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(50), default="user")  # user, auto_daily, auto_forgotten, auto_loved, auto_gems, genre, discover
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    profile: Mapped["Profile"] = relationship(back_populates="playlists")
    tracks: Mapped[list["PlaylistTrack"]] = relationship(back_populates="playlist", cascade="all, delete-orphan", order_by="PlaylistTrack.position")


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    playlist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    track_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    artist: Mapped[str] = mapped_column(String(255))
    album: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    art_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    playlist: Mapped["Playlist"] = relationship(back_populates="tracks")


class RecommendationHistory(Base):
    __tablename__ = "recommendation_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rec_type: Mapped[str] = mapped_column(String(20))  # artist, album, song
    item_key: Mapped[str] = mapped_column(String(500))
    item_name: Mapped[str] = mapped_column(String(255))
    recommended_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_rec_hist_profile_type_key", "profile_id", "rec_type", "item_key"),
    )