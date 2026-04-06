from __future__ import annotations

from dataclasses import dataclass

from services.ai_service import AIService, AIServiceError, TaskReviewResult


@dataclass
class ReviewedTaskPayload:
    review_status: str
    summary: str
    strengths: list[str]
    what_to_fix: list[str]
    next_step_mode: str
    next_step_hint: str
    voice_transcript: str | None = None


class TaskReviewServiceError(Exception):
    pass


class TaskReviewService:
    def __init__(self) -> None:
        self.ai_service = AIService()

    async def review_photo_submission(
        self,
        *,
        user_id: int,
        task_title: str,
        task_description: str,
        selected_direction: str,
        photo_file_url: str,
    ) -> ReviewedTaskPayload:
        if not task_title.strip():
            raise TaskReviewServiceError("Не передан task_title для review по фото")

        if not task_description.strip():
            raise TaskReviewServiceError("Не передан task_description для review по фото")

        if not selected_direction.strip():
            raise TaskReviewServiceError("Не передано направление для review по фото")

        if not photo_file_url.strip():
            raise TaskReviewServiceError("Не передан photo_file_url для review по фото")

        try:
            review = await self.ai_service.review_task_by_photo_file(
                selected_direction=selected_direction,
                task_title=task_title,
                task_description=task_description,
                photo_file_url=photo_file_url,
            )
        except AIServiceError as exc:
            raise TaskReviewServiceError(str(exc)) from exc
        except Exception as exc:
            raise TaskReviewServiceError("Не удалось проверить фото пользователя") from exc

        return self._convert_review_result(review)

    async def review_voice_submission(
        self,
        *,
        user_id: int,
        task_title: str,
        task_description: str,
        selected_direction: str,
        voice_file_path: str,
    ) -> ReviewedTaskPayload:
        if not task_title.strip():
            raise TaskReviewServiceError("Не передан task_title для review по голосовому")

        if not task_description.strip():
            raise TaskReviewServiceError("Не передан task_description для review по голосовому")

        if not selected_direction.strip():
            raise TaskReviewServiceError("Не передано направление для review по голосовому")

        if not voice_file_path.strip():
            raise TaskReviewServiceError("Не передан voice_file_path для review по голосовому")

        try:
            transcript = await self.ai_service.transcribe_voice_file(
                voice_file_path=voice_file_path,
            )
        except AIServiceError as exc:
            raise TaskReviewServiceError(str(exc)) from exc
        except Exception as exc:
            raise TaskReviewServiceError("Не удалось расшифровать голосовое") from exc

        try:
            review = await self.ai_service.review_task_by_voice_transcript(
                selected_direction=selected_direction,
                task_title=task_title,
                task_description=task_description,
                voice_transcript=transcript,
            )
        except AIServiceError as exc:
            raise TaskReviewServiceError(str(exc)) from exc
        except Exception as exc:
            raise TaskReviewServiceError("Не удалось проверить голосовое пользователя") from exc

        return self._convert_review_result(
            review,
            voice_transcript=transcript,
        )

    def _convert_review_result(
        self,
        review: TaskReviewResult,
        *,
        voice_transcript: str | None = None,
    ) -> ReviewedTaskPayload:
        return ReviewedTaskPayload(
            review_status=review.review_status,
            summary=review.summary,
            strengths=review.strengths,
            what_to_fix=review.what_to_fix,
            next_step_mode=review.next_step_mode,
            next_step_hint=review.next_step_hint,
            voice_transcript=voice_transcript,
        )


async def review_photo_task_submission(
    *,
    user_id: int,
    task_title: str,
    task_description: str,
    selected_direction: str,
    photo_file_url: str,
) -> ReviewedTaskPayload:
    service = TaskReviewService()
    return await service.review_photo_submission(
        user_id=user_id,
        task_title=task_title,
        task_description=task_description,
        selected_direction=selected_direction,
        photo_file_url=photo_file_url,
    )


async def review_voice_task_submission(
    *,
    user_id: int,
    task_title: str,
    task_description: str,
    selected_direction: str,
    voice_file_path: str,
) -> ReviewedTaskPayload:
    service = TaskReviewService()
    return await service.review_voice_submission(
        user_id=user_id,
        task_title=task_title,
        task_description=task_description,
        selected_direction=selected_direction,
        voice_file_path=voice_file_path,
    )
