from rich.progress import Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn, TaskProgressColumn, MofNCompleteColumn, ProgressColumn, BarColumn
from joblib import Parallel

class TasksPerSecondColumn(ProgressColumn):
    """Custom column to show tasks per second like tqdm."""
    def render(self, task):
        speed = task.finished_speed or task.speed
        if speed is None:
            return TextColumn("").render(task)
        return TextColumn(f"{speed:6.2f} tasks/s").render(task)

class ParallelProgress(Parallel):
    """joblib.Parallel, but with a rich.progress progressbar

    Additional parameters:
    ----------------------
    total_tasks: int, default: None
        the number of expected jobs. Used in the progressbar.
        If None, try to infer from the length of the called iterator, and
        fallback to use the number of remaining items as soon as we finish
        dispatching.
        Note: use a list instead of an iterator if you want the total_tasks
        to be inferred from its length.

    desc: str, default: None
        the description used in the progressbar.

    disable_progressbar: bool, default: False
        If True, a progressbar is not used.

    show_joblib_header: bool, default: False
        If True, show joblib header before the progressbar.

    Removed parameters:
    -------------------
    verbose: will be ignored

    Usage:
    ------
    >>> from joblib import delayed
    >>> from time import sleep
    >>> ParallelRichProgress(n_jobs=-1)([delayed(sleep)(.1) for _ in range(10)])
    """

    def __init__(
        self,
        *,
        total_tasks: int | None = None,
        desc: str | None = None,
        disable_progressbar: bool = False,
        show_joblib_header: bool = False,
        progressArgs = [],
        **kwargs
    ):
        super().__init__(verbose=(1 if show_joblib_header else 0), **kwargs)
        self.progress_args = progressArgs
        self.total_tasks = total_tasks
        self.desc = desc
        self.disable_progressbar = disable_progressbar
        self.progress: Progress | None = None
        self.task_id: int | None = None

    def __call__(self, iterable):
        # rich Progress는 context manager로 사용해야 하므로 여기서 생성
        if self.total_tasks is None:
            try:
                self.total_tasks = len(iterable)
            except (TypeError, AttributeError):
                pass

        if self.disable_progressbar:
            return super().__call__(iterable)

        with Progress(
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),   # 04:24
            TextColumn("<"),
            TimeRemainingColumn(), # 18:12
            TasksPerSecondColumn(),  # 초당 처리량
            transient=True,
        ) as progress:
            self.progress = progress
            self.task_id = progress.add_task(self.desc or "Processing", total=self.total_tasks)
            try:
                return super().__call__(iterable)
            finally:
                self.progress = None
                self.task_id = None

    __call__.__doc__ = Parallel.__call__.__doc__

    def dispatch_one_batch(self, iterator):
        # rich Progress는 __call__에서 이미 생성됨
        return super().dispatch_one_batch(iterator)

    dispatch_one_batch.__doc__ = Parallel.dispatch_one_batch.__doc__

    def print_progress(self):
        """Display the process of the parallel execution using rich.progress"""
        if self.progress is not None and self.task_id is not None:
            completed = self.n_completed_tasks
            self.progress.update(self.task_id, completed=completed)