from datetime import datetime, date
from sqlalchemy import (
    BigInteger,
    String,
    Text,
    Integer,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    current_mode: Mapped[str] = mapped_column(String(50), default="normal")
    selected_direction: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)

    last_user_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_followup_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_followup_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_push_followup_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    push_explanation_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_milestone_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    tasks: Mapped[list["UserTask"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    daily_reports: Mapped[list["DailyReport"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    task_submissions: Mapped[list["TaskSubmission"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    onboarding_step: Mapped[str] = mapped_column(String(100), default="start")
    onboarding_goal: Mapped[str | None] = mapped_column(String(100), nullable=True)
    onboarding_energy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    onboarding_time_per_day: Mapped[str | None] = mapped_column(String(50), nullable=True)
    onboarding_about_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    current_income_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    free_time_style: Mapped[str | None] = mapped_column(Text, nullable=True)
    appreciation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    help_request_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    declared_strengths: Mapped[str | None] = mapped_column(Text, nullable=True)
    available_tools: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_strengths_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    repeated_signals_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    questionnaire_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    about_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    interests_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_directions_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    energy_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    burnout_flag: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user: Mapped["User"] = relationship(back_populates="profile")


class UserTask(Base):
    __tablename__ = "user_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    difficulty_mode: Mapped[str] = mapped_column(String(50), default="normal")

    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="tasks")
    submissions: Mapped[list["TaskSubmission"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )


class TaskSubmission(Base):
    __tablename__ = "task_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    task_id: Mapped[int] = mapped_column(ForeignKey("user_tasks.id"))

    submission_type: Mapped[str] = mapped_column(String(20))  # photo / voice / text
    telegram_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    review_status: Mapped[str] = mapped_column(String(20))  # done / partial / not_done
    review_summary: Mapped[str] = mapped_column(Text)
    strengths_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_to_fix_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_step_mode: Mapped[str] = mapped_column(String(20))  # harder / same / easier
    next_step_hint: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="task_submissions")
    task: Mapped["UserTask"] = relationship(back_populates="submissions")


class DailyReport(Base):
    __tablename__ = "daily_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    report_date: Mapped[date] = mapped_column(Date, default=date.today)
    what_done: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_worked: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_failed: Mapped[str | None] = mapped_column(Text, nullable=True)
    mood_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    energy_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mentor_reply_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="daily_reports")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    status: Mapped[str] = mapped_column(String(50), default="trial")
    starts_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user: Mapped["User"] = relationship(back_populates="subscriptions")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    yookassa_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount_value: Mapped[str] = mapped_column(String(50))
    amount_currency: Mapped[str] = mapped_column(String(10), default="RUB")
    status: Mapped[str] = mapped_column(String(50), default="pending")
    payment_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="payments")
