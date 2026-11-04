from typing import Iterable, Optional


class FriendlyError(Exception):
    """Erro que a interface mostra à pessoa; use `raise ... from ...` para preservar o contexto."""

    title_format: str
    title_args: Iterable[str]
    subtitle_format: str
    subtitle_args: Iterable[str]

    @property
    def title(self) -> str:
        return self.title_format.format(*self.title_args)

    @property
    def subtitle(self) -> str:
        return self.subtitle_format.format(*self.subtitle_args)

    def __init__(
        self,
        title: str,
        subtitle: str,
        title_args: Optional[Iterable[str]] = None,
        subtitle_args: Optional[Iterable[str]] = None,
    ) -> None:
        super().__init__()
        if title is not None:
            self.title_format = title
        if subtitle is not None:
            self.subtitle_format = subtitle
        self.title_args = title_args if title_args else ()
        self.subtitle_args = subtitle_args if subtitle_args else ()

    def __str__(self) -> str:
        return f"{self.title} - {self.subtitle}"
