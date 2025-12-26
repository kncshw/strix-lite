import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional


if TYPE_CHECKING:
    from strix.telemetry.tracer import Tracer

from jinja2 import (
    Environment,
    FileSystemLoader,
    select_autoescape,
)

from strix.llm import LLM, LLMConfig, LLMRequestFailedError
from strix.llm.utils import clean_content
from strix.tools import process_tool_invocations

from .state import AgentState


logger = logging.getLogger(__name__)


class AgentMeta(type):
    agent_name: str
    jinja_env: Environment

    def __new__(cls, name: str, bases: tuple[type, ...], attrs: dict[str, Any]) -> type:
        new_cls = super().__new__(cls, name, bases, attrs)

        if name == "BaseAgent":
            return new_cls

        agents_dir = Path(__file__).parent
        prompt_dir = agents_dir / name

        new_cls.agent_name = name
        new_cls.jinja_env = Environment(
            loader=FileSystemLoader(prompt_dir),
            autoescape=select_autoescape(enabled_extensions=(), default_for_string=False),
        )

        return new_cls


class BaseAgent(metaclass=AgentMeta):
    max_iterations = 300
    agent_name: str = ""
    jinja_env: Environment
    default_llm_config: LLMConfig | None = None

    def __init__(self, config: dict[str, Any]):
        self.config = config

        self.local_sources = config.get("local_sources", [])
        self.non_interactive = config.get("non_interactive", False)

        if "max_iterations" in config:
            self.max_iterations = config["max_iterations"]

        self.llm_config_name = config.get("llm_config_name", "default")
        self.llm_config = config.get("llm_config", self.default_llm_config)
        if self.llm_config is None:
            raise ValueError("llm_config is required but not provided")
        self.llm = LLM(self.llm_config, agent_name=self.agent_name)

        state_from_config = config.get("state")
        if state_from_config is not None:
            self.state = state_from_config
        else:
            self.state = AgentState(
                agent_name=self.agent_name,
                max_iterations=self.max_iterations,
            )

        with contextlib.suppress(Exception):
            self.llm.set_agent_identity(self.agent_name, self.state.agent_id)
        self._current_task: asyncio.Task[Any] | None = None

        from strix.telemetry.tracer import get_global_tracer

        tracer = get_global_tracer()
        if tracer:
            tracer.log_agent_creation(
                agent_id=self.state.agent_id,
                name=self.state.agent_name,
                task=self.state.task,
                parent_id=None,
            )
            tracer.register_agent(self)
            
            scan_config = tracer.scan_config or {}
            exec_id = tracer.log_tool_execution_start(
                agent_id=self.state.agent_id,
                tool_name="scan_start_info",
                args=scan_config,
            )
            tracer.update_tool_execution(execution_id=exec_id, status="completed", result={})

    def cancel_current_execution(self) -> None:
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            self._current_task = None

    async def agent_loop(self, task: str) -> dict[str, Any]:  # noqa: PLR0912, PLR0915
        await self._initialize_sandbox_and_state(task)

        from strix.telemetry.tracer import get_global_tracer

        tracer = get_global_tracer()

        while True:
            if self.state.is_waiting_for_input():
                await self._wait_for_input()
                continue

            if self.state.should_stop():
                if self.non_interactive:
                    return self.state.final_result or {}
                await self._enter_waiting_state(tracer)
                continue

            if self.state.llm_failed:
                await self._wait_for_input()
                continue

            self.state.increment_iteration()

            if (
                self.state.is_approaching_max_iterations()
                and not self.state.max_iterations_warning_sent
            ):
                self.state.max_iterations_warning_sent = True
                remaining = self.state.max_iterations - self.state.iteration
                warning_msg = (
                    f"URGENT: You are approaching the maximum iteration limit. "
                    f"Current: {self.state.iteration}/{self.state.max_iterations} "
                    f"({remaining} iterations remaining). "
                    f"Please prioritize completing your required task(s) and calling "
                    f"the finish_scan tool as soon as possible."
                )
                self.state.add_message("user", warning_msg)

            if self.state.iteration == self.state.max_iterations - 3:
                final_warning_msg = (
                    "CRITICAL: You have only 3 iterations left! "
                    "Your next message MUST be the tool call to finish_scan. "
                    "No other actions should be taken except finishing your work "
                    "immediately."
                )
                self.state.add_message("user", final_warning_msg)

            try:
                should_finish = await self._process_iteration(tracer)
                if should_finish:
                    if self.non_interactive:
                        self.state.set_completed({"success": True})
                        if tracer:
                            tracer.update_agent_status(self.state.agent_id, "completed")
                        return self.state.final_result or {}
                    await self._enter_waiting_state(tracer, task_completed=True)
                    continue

            except asyncio.CancelledError:
                if self.non_interactive:
                    raise
                await self._enter_waiting_state(tracer, error_occurred=False, was_cancelled=True)
                continue

            except LLMRequestFailedError as e:
                error_msg = str(e)
                error_details = getattr(e, "details", None)
                self.state.add_error(error_msg)

                if self.non_interactive:
                    self.state.set_completed({"success": False, "error": error_msg})
                    if tracer:
                        tracer.update_agent_status(self.state.agent_id, "failed", error_msg)
                        if error_details:
                            tracer.log_tool_execution_start(
                                self.state.agent_id,
                                "llm_error_details",
                                {"error": error_msg, "details": error_details},
                            )
                            tracer.update_tool_execution(
                                tracer._next_execution_id - 1, "failed", error_details
                            )
                    return {"success": False, "error": error_msg}

                self.state.enter_waiting_state(llm_failed=True)
                if tracer:
                    tracer.update_agent_status(self.state.agent_id, "llm_failed", error_msg)
                    if error_details:
                        tracer.log_tool_execution_start(
                            self.state.agent_id,
                            "llm_error_details",
                            {"error": error_msg, "details": error_details},
                        )
                        tracer.update_tool_execution(
                            tracer._next_execution_id - 1, "failed", error_details
                        )
                continue

            except (RuntimeError, ValueError, TypeError) as e:
                if not await self._handle_iteration_error(e, tracer):
                    if self.non_interactive:
                        self.state.set_completed({"success": False, "error": str(e)})
                        if tracer:
                            tracer.update_agent_status(self.state.agent_id, "failed")
                        raise
                    await self._enter_waiting_state(tracer, error_occurred=True)
                    continue

    async def _wait_for_input(self) -> None:
        import asyncio

        if self.state.has_waiting_timeout():
            self.state.resume_from_waiting()
            self.state.add_message("assistant", "Waiting timeout reached. Resuming execution.")

            from strix.telemetry.tracer import get_global_tracer

            tracer = get_global_tracer()
            if tracer:
                tracer.update_agent_status(self.state.agent_id, "running")

            return

        await asyncio.sleep(0.5)

    async def _enter_waiting_state(
        self,
        tracer: Optional["Tracer"],
        task_completed: bool = False,
        error_occurred: bool = False,
        was_cancelled: bool = False,
    ) -> None:
        self.state.enter_waiting_state()

        if tracer:
            if task_completed:
                tracer.update_agent_status(self.state.agent_id, "completed")
            elif error_occurred:
                tracer.update_agent_status(self.state.agent_id, "error")
            elif was_cancelled:
                tracer.update_agent_status(self.state.agent_id, "stopped")
            else:
                tracer.update_agent_status(self.state.agent_id, "stopped")

        if task_completed:
            self.state.add_message(
                "assistant",
                "Task completed. I'm now waiting for follow-up instructions or new tasks.",
            )
        elif error_occurred:
            self.state.add_message(
                "assistant", "An error occurred. I'm now waiting for new instructions."
            )
        elif was_cancelled:
            self.state.add_message(
                "assistant", "Execution was cancelled. I'm now waiting for new instructions."
            )
        else:
            self.state.add_message(
                "assistant",
                "Execution paused. I'm now waiting for new instructions or any updates.",
            )

    async def _initialize_sandbox_and_state(self, task: str) -> None:
        import os

        sandbox_mode = os.getenv("STRIX_SANDBOX_MODE", "false").lower() == "true"
        if not sandbox_mode and self.state.sandbox_id is None:
            from strix.runtime import get_runtime

            runtime = get_runtime()
            sandbox_info = await runtime.create_sandbox(
                self.state.agent_id, self.state.sandbox_token, self.local_sources
            )
            self.state.sandbox_id = sandbox_info["workspace_id"]
            self.state.sandbox_token = sandbox_info["auth_token"]
            self.state.sandbox_info = sandbox_info

            if "agent_id" in sandbox_info:
                self.state.sandbox_info["agent_id"] = sandbox_info["agent_id"]

        if not self.state.task:
            self.state.task = task

        self.state.add_message("user", task)

    async def _process_iteration(self, tracer: Optional["Tracer"]) -> bool:
        response = await self.llm.generate(self.state.get_conversation_history())

        content_stripped = (response.content or "").strip()

        if not content_stripped:
            corrective_message = (
                "You MUST NOT respond with empty messages. "
                "If you currently have nothing to do or say, use an appropriate tool instead:\n"
                "- Use finish_actions.finish_scan if the scan is complete"
            )
            self.state.add_message("user", corrective_message)
            return False

        self.state.add_message("assistant", response.content)
        if tracer:
            tracer.log_chat_message(
                content=clean_content(response.content),
                role="assistant",
                agent_id=self.state.agent_id,
            )

        actions = (
            response.tool_invocations
            if hasattr(response, "tool_invocations") and response.tool_invocations
            else []
        )

        if actions:
            return await self._execute_actions(actions, tracer)

        return False

    async def _execute_actions(self, actions: list[Any], tracer: Optional["Tracer"]) -> bool:
        """Execute actions and return True if agent should finish."""
        for action in actions:
            self.state.add_action(action)

        conversation_history = self.state.get_conversation_history()

        tool_task = asyncio.create_task(
            process_tool_invocations(actions, conversation_history, self.state)
        )
        self._current_task = tool_task

        try:
            should_agent_finish = await tool_task
            self._current_task = None
        except asyncio.CancelledError:
            self._current_task = None
            self.state.add_error("Tool execution cancelled by user")
            raise

        self.state.messages = conversation_history

        if should_agent_finish:
            self.state.set_completed({"success": True})
            if tracer:
                tracer.update_agent_status(self.state.agent_id, "completed")
            return True

        return False

    async def _handle_iteration_error(
        self,
        error: RuntimeError | ValueError | TypeError | asyncio.CancelledError,
        tracer: Optional["Tracer"],
    ) -> bool:
        error_msg = f"Error in iteration {self.state.iteration}: {error!s}"
        logger.exception(error_msg)
        self.state.add_error(error_msg)
        if tracer:
            tracer.update_agent_status(self.state.agent_id, "error")
        return True
