import json

from sqlalchemy import select

from db.database import async_session_maker
from db.models import TaskSubmission, User, UserTask


class TaskSubmissionServiceError(Exception):
    pass


class TaskSubmissionService:
    async def save_submission_review(
        self,
        *,
        user_id: int,
        task_id: int,
        submission_type: str,
        review_status: str,
        review_summary: str,
        strengths: list[str],
        what_to_fix: list[str],
        next_step_mode: str,
        next_step_hint: str,
        telegram_file_id: str | None = None,
        transcript_text: str | None = None,
    ) -> int:
        async with async_session_maker() as session:
            user_result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = user_result.scalar_one_or_none()
            if user is None:
                raise TaskSubmissionServiceError("Пользователь не найден")

            task_result = await session.execute(
                select(UserTask).where(UserTask.id == task_id)
            )
            task = task_result.scalar_one_or_none()
            if task is None:
                raise TaskSubmissionServiceError("Задача не найдена")

            submission = TaskSubmission(
                user_id=user_id,
                task_id=task_id,
                submission_type=submission_type,
                telegram_file_id=telegram_file_id,
                transcript_text=transcript_text,
                review_status=review_status,
                review_summary=review_summary,
                strengths_json=json.dumps(strengths, ensure_ascii=False) if strengths else None,
                what_to_fix_json=json.dumps(what_to_fix, ensure_ascii=False) if what_to_fix else None,
                next_step_mode=next_step_mode,
                next_step_hint=next_step_hint,
            )
            session.add(submission)
            await session.flush()
            submission_id = submission.id
            await session.commit()
            return submission_id

    async def get_recent_submissions_summary(
        self,
        *,
        user_id: int,
        limit: int = 5,
    ) -> str:
        async with async_session_maker() as session:
            result = await session.execute(
                select(TaskSubmission)
                .where(TaskSubmission.user_id == user_id)
                .order_by(TaskSubmission.created_at.desc(), TaskSubmission.id.desc())
                .limit(limit)
            )
            submissions = result.scalars().all()

            if not submissions:
                return "Пока нет сохраненных review по шагам."

            lines: list[str] = []
            for item in submissions:
                lines.append(f"- {item.submission_type}: {item.review_status}. {item.review_summary}")

            return "\n".join(lines)


async def save_task_submission_review(
    *,
    user_id: int,
    task_id: int,
    submission_type: str,
    review_status: str,
    review_summary: str,
    strengths: list[str],
    what_to_fix: list[str],
    next_step_mode: str,
    next_step_hint: str,
    telegram_file_id: str | None = None,
    transcript_text: str | None = None,
) -> int:
    service = TaskSubmissionService()
    return await service.save_submission_review(
        user_id=user_id,
        task_id=task_id,
        submission_type=submission_type,
        review_status=review_status,
        review_summary=review_summary,
        strengths=strengths,
        what_to_fix=what_to_fix,
        next_step_mode=next_step_mode,
        next_step_hint=next_step_hint,
        telegram_file_id=telegram_file_id,
        transcript_text=transcript_text,
    )


async def get_recent_task_submission_summary(
    *,
    user_id: int,
    limit: int = 5,
) -> str:
    service = TaskSubmissionService()
    return await service.get_recent_submissions_summary(
        user_id=user_id,
        limit=limit,
    )
