import asyncio
from app.agents.base import AgentContext, AgentResult
from app.agents.executors import (
    AttractionExecutor,
    WeatherExecutor,
    HotelExecutor,
    PlannerExecutor,
)
from app.schemas import TripPlan


class TripOrchestrator:
    def __init__(self):
        self.attraction_agent = AttractionExecutor()
        self.weather_agent = WeatherExecutor()
        self.hotel_agent = HotelExecutor()
        self.planner_agent = PlannerExecutor()

    async def plan_trip(
        self,
        city: str,
        start_date: str,
        end_date: str,
        preferences: str = "",
        accommodation: str = "",
    ) -> TripPlan:
        context = AgentContext(
            city=city,
            start_date=start_date,
            end_date=end_date,
            preferences=preferences,
            accommodation=accommodation,
        )

        attraction_task = self.attraction_agent.execute(context)
        weather_task = self.weather_agent.execute(context)
        hotel_task = self.hotel_agent.execute(context)

        results: list[AgentResult] = await asyncio.gather(
            attraction_task,
            weather_task,
            hotel_task,
            return_exceptions=False,
        )

        for result in results:
            if not result.success:
                raise RuntimeError(f"Agent 执行失败: {result.error}")

        plan_result = await self.planner_agent.execute(context)

        if not plan_result.success or plan_result.data is None:
            raise RuntimeError(f"规划生成失败: {plan_result.error}")

        return plan_result.data
