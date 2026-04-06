from services.ai_service import AIService, AIServiceError
from services.task_submission_service import (
    TaskSubmissionService,
    TaskSubmissionServiceError,
)


class MilestoneServiceError(Exception):
    pass


class MilestoneService:
    def __init__(self) -> None:
        self.ai_service = AIService()
        self.task_submission_service = TaskSubmissionService()

    async def build_user_milestone_text(
        self,
        *,
        user_id: int,
        selected_direction: str,
    ) -> str | None:
        if not selected_direction.strip():
            raise MilestoneServiceError("Не передано направление для маяка")

        try:
            recent_progress_summary = await self.task_submission_service.get_recent_submissions_summary(
                user_id=user_id,
                limit=5,
            )
        except TaskSubmissionServiceError as exc:
            raise MilestoneServiceError(str(exc)) from exc
        except Exception as exc:
            raise MilestoneServiceError("Не удалось собрать summary по review") from exc

        if not recent_progress_summary.strip():
            return None

        if recent_progress_summary.strip() == "Пока нет сохраненных review по шагам.":
            return None

        try:
            result = await self.ai_service.generate_user_milestone(
                selected_direction=selected_direction,
                recent_progress_summary=recent_progress_summary,
            )
        except AIServiceError as exc:
            raise MilestoneServiceError(str(exc)) from exc
        except Exception as exc:
            raise MilestoneServiceError("Не удалось собрать маяк через AI") from exc

        text = (result.milestone_text or "").strip()
        if not text:
            return None

        return text


async def build_user_milestone_text(
    *,
    user_id: int,
    selected_direction: str,
) -> str | None:
    service = MilestoneService()
    return await service.build_user_milestone_text(
        user_id=user_id,
        selected_direction=selected_direction,
    )
