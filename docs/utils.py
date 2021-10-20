import asyncio
import contextlib
import inspect
import logging
import typing as t
from datetime import datetime
from functools import partial

import disnake
import re


class Scheduler:
    """
    Schedule the execution of coroutines and keep track of them.
    When instantiating a Scheduler, a name must be provided. This name is used to distinguish the
    instance's log messages from other instances. Using the name of the class or module containing
    the instance is suggested.
    Coroutines can be scheduled immediately with `schedule` or in the future with `schedule_at`
    or `schedule_later`. A unique ID is required to be given in order to keep track of the
    resulting Tasks. Any scheduled task can be cancelled prematurely using `cancel` by providing
    the same ID used to schedule it.  The `in` operator is supported for checking if a task with a
    given ID is currently scheduled.
    Any exception raised in a scheduled task is logged when the task is done.
    """

    def __init__(self, name: str):
        self.name = name

        self._log = logging.getLogger(f"{__name__}.{name}")
        self._scheduled_tasks: t.Dict[t.Hashable, asyncio.Task] = {}

    def __contains__(self, task_id: t.Hashable) -> bool:
        """Return True if a task with the given `task_id` is currently scheduled."""
        return task_id in self._scheduled_tasks

    def schedule(self, task_id: t.Hashable, coroutine: t.Coroutine) -> None:
        """
        Schedule the execution of a `coroutine`.
        If a task with `task_id` already exists, close `coroutine` instead of scheduling it. This
        prevents unawaited coroutine warnings. Don't pass a coroutine that'll be re-used elsewhere.
        """

        msg = f"Cannot schedule an already started coroutine for #{task_id}"
        assert inspect.getcoroutinestate(coroutine) == "CORO_CREATED", msg

        if task_id in self._scheduled_tasks:
            self._log.debug(f"Did not schedule task #{task_id}; task was already scheduled.")
            coroutine.close()
            return

        task = asyncio.create_task(coroutine, name=f"{self.name}_{task_id}")
        task.add_done_callback(partial(self._task_done_callback, task_id))

        self._scheduled_tasks[task_id] = task
        self._log.debug(f"Scheduled task #{task_id} {id(task)}.")

    def schedule_at(self, time: datetime, task_id: t.Hashable, coroutine: t.Coroutine) -> None:
        """
        Schedule `coroutine` to be executed at the given `time`.
        If `time` is timezone aware, then use that timezone to calculate now() when subtracting.
        If `time` is naïve, then use UTC.
        If `time` is in the past, schedule `coroutine` immediately.
        If a task with `task_id` already exists, close `coroutine` instead of scheduling it. This
        prevents unawaited coroutine warnings. Don't pass a coroutine that'll be re-used elsewhere.
        """
        now_datetime = datetime.now(time.tzinfo) if time.tzinfo else datetime.utcnow()
        delay = (time - now_datetime).total_seconds()
        if delay > 0:
            coroutine = self._await_later(delay, task_id, coroutine)

        self.schedule(task_id, coroutine)

    def schedule_later(self, delay: t.Union[int, float], task_id: t.Hashable, coroutine: t.Coroutine) -> None:
        """
        Schedule `coroutine` to be executed after the given `delay` number of seconds.
        If a task with `task_id` already exists, close `coroutine` instead of scheduling it. This
        prevents unawaited coroutine warnings. Don't pass a coroutine that'll be re-used elsewhere.
        """
        self.schedule(task_id, self._await_later(delay, task_id, coroutine))

    def cancel(self, task_id: t.Hashable) -> None:
        """Unschedule the task identified by `task_id`. Log a warning if the task doesn't exist."""

        try:
            task = self._scheduled_tasks.pop(task_id)
        except KeyError:
            self._log.warning(f"Failed to unschedule {task_id} (no task found).")
        else:
            task.cancel()

            self._log.debug(f"Unscheduled task #{task_id} {id(task)}.")

    def cancel_all(self) -> None:
        """Unschedule all known tasks."""
        self._log.debug("Unscheduling all tasks")

        for task_id in self._scheduled_tasks.copy():
            self.cancel(task_id)

    async def _await_later(self, delay: t.Union[int, float], task_id: t.Hashable, coroutine: t.Coroutine) -> None:
        """Await `coroutine` after the given `delay` number of seconds."""
        try:
            await asyncio.sleep(delay)

            # Use asyncio.shield to prevent the coroutine from cancelling itself.
            await asyncio.shield(coroutine)
        finally:
            # Close it to prevent unawaited coroutine warnings,
            # which would happen if the task was cancelled during the sleep.
            # Only close it if it's not been awaited yet. This check is important because the
            # coroutine may cancel this task, which would also trigger the finally block.
            state = inspect.getcoroutinestate(coroutine)
            if state == "CORO_CREATED":
                self._log.debug(f"Explicitly closing the coroutine for #{task_id}.")
                coroutine.close()
            else:
                self._log.debug(f"Finally block reached for #{task_id}; {state=}")

    def _task_done_callback(self, task_id: t.Hashable, done_task: asyncio.Task) -> None:
        """
        Delete the task and raise its exception if one exists.
        If `done_task` and the task associated with `task_id` are different, then the latter
        will not be deleted. In this case, a new task was likely rescheduled with the same ID.
        """
        scheduled_task = self._scheduled_tasks.get(task_id)

        if scheduled_task and done_task is scheduled_task:
            # A task for the ID exists and is the same as the done task.
            # Since this is the done callback, the task is already done so no need to cancel it.
            del self._scheduled_tasks[task_id]
        elif scheduled_task:
            # A new task was likely rescheduled with the same ID.
            self._log.debug(
                f"The scheduled task #{task_id} {id(scheduled_task)} "
                f"and the done task {id(done_task)} differ."
            )
        elif not done_task.cancelled():
            self._log.warning(
                f"Task #{task_id} not found while handling task {id(done_task)}! "
                f"A task somehow got unscheduled improperly (i.e. deleted but not cancelled)."
            )

        with contextlib.suppress(asyncio.CancelledError):
            exception = done_task.exception()
            # Log the exception if one exists.
            if exception:
                self._log.error(f"Error in task #{task_id} {id(done_task)}!", exc_info=exception)


def create_task(
    coro: t.Awaitable,
    *,
    suppressed_exceptions: t.Tuple[t.Type[Exception]] = (),
    event_loop: t.Optional[asyncio.AbstractEventLoop] = None,
    **kwargs,
) -> asyncio.Task:
    """
    Wrapper for creating asyncio `Task`s which logs exceptions raised in the task.
    If the loop kwarg is provided, the task is created from that event loop, otherwise the running loop is used.
    """
    if event_loop is not None:
        task = event_loop.create_task(coro, **kwargs)
    else:
        task = asyncio.create_task(coro, **kwargs)
    task.add_done_callback(partial(_log_task_exception, suppressed_exceptions=suppressed_exceptions))
    return task


def _log_task_exception(task: asyncio.Task, *, suppressed_exceptions: t.Tuple[t.Type[Exception]]) -> None:
    """Retrieve and log the exception raised in `task` if one exists."""
    with contextlib.suppress(asyncio.CancelledError):
        exception = task.exception()
        # Log the exception if one exists.
        if exception and not isinstance(exception, suppressed_exceptions):
            log = logging.getLogger(__name__)
            log.error(f"Error in task {task.get_name()} {id(task)}!", exc_info=exception)


class QuitButton(disnake.ui.View):
    def __init__(
        self,
        ctx,
        *,
        timeout: float = 180.0,
        delete_after: bool = False
    ):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.delete_after = delete_after

    async def interaction_check(self, interaction: disnake.MessageInteraction):
        if interaction.author.id != self.ctx.author.id:
            await interaction.response.send_message(
                f'Only {self.ctx.author.display_name} can use the buttons on this message!',
                ephemeral=True
            )
            return False
        return True

    async def on_error(self, error, item, interaction):
        return await self.ctx.bot.reraise(self.ctx, error)

    async def on_timeout(self):
        if self.delete_after is False:
            return await self.message.edit(view=None)

        await self.message.delete()
        await self.ctx.message.delete()

    @disnake.ui.button(label='Quit', style=disnake.ButtonStyle.red)
    async def quit(self, button: disnake.ui.Button, interaction: disnake.Interaction):
        """Deletes the user's message along with the bot's message."""
        await self.message.delete()
        await self.ctx.message.delete()
        self.stop()


def finder(text, collection, *, key=None, lazy=True):
    suggestions = []
    text = str(text)
    pat = '.*?'.join(map(re.escape, text))
    regex = re.compile(pat, flags=re.IGNORECASE)
    for item in collection:
        to_search = key(item) if key else item
        r = regex.search(to_search)
        if r:
            suggestions.append((len(r.group()), r.start(), item))

    def sort_key(tup):
        if key:
            return tup[0], tup[1], key(tup[2])
        return tup

    if lazy:
        return (z for _, _, z in sorted(suggestions, key=sort_key))
    else:
        return [z for _, _, z in sorted(suggestions, key=sort_key)]
