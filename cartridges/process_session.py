# process_session.py
#
# Copyright 2024 kramo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Track a game's playtime automatically by watching its process.

Once the game is launched we wait for its process to appear, count the time it
stays running, and end the session automatically when it exits. Elapsed time is
flushed into ``game.playtime`` every poll so a crash only loses the last poll's
worth of time.

A game is recognised by any of three things, whichever answers first: the
executable name the user configured, the install folder read out of the launch
command, and — for Microsoft Store and Game Pass games — the package family
name, read out of the launch command too, since there is nothing sensible for
the user to type there. None of them excludes the others; see :meth:`_is_running`.

What none of them can see (Steam and Epic, which hand off to a launcher) still
falls back to the manual :class:`~cartridges.session_window.SessionWindow`. The
exception is a packaged game whose package is never seen at all: that ends the
session with no record and says so, because for a package "never seen" means the
game did not start rather than that we lost sight of it.
"""

import logging
from time import monotonic
from typing import Any, Optional

from gi.repository import Adw, GLib

from cartridges import shared
from cartridges.game import Game
from cartridges.utils import session_log
from cartridges.utils.process_monitor import (
    install_dir_from_command,
    is_package_running,
    is_process_running,
    is_process_running_under,
)
from cartridges.utils.run_executable import aumid_from_command


class ProcessSession:
    """Automatic, process-watching play session for a single game."""

    # Only one session is tracked at a time, matching SessionWindow. Keeping the
    # reference here also stops the instance being garbage-collected while its
    # timer is running.
    active: "Optional[ProcessSession]" = None

    # Seconds between process-list checks. Kept short so the grace period below
    # (which the user configures) is what really governs how long we wait.
    POLL_INTERVAL = 2
    # How long to wait for the process to appear before giving up. Launchers,
    # shader compilation and anti-cheat bootstrappers can delay the real exe.
    STARTUP_GRACE = 300
    # Shorter for a packaged game: shell activation either produces a process of
    # the package within seconds or it failed. Waiting the full five minutes
    # before falling back would drop the manual window on top of a game already
    # running, which is worse than admitting defeat early.
    PACKAGE_STARTUP_GRACE = 90
    # How often to write accumulated time to disk (crash/power-loss safety net).
    PERSIST_INTERVAL = 60
    # A gap between two polls longer than this is not play: the monotonic clock
    # keeps counting while the PC sleeps, and a game left paused overnight
    # would otherwise be credited the whole night on the first poll after
    # waking. Such a gap is credited as a single poll interval.
    MAX_GAP = POLL_INTERVAL + 30

    def __init__(self, game: Game) -> None:
        self.game = game
        # Only when the user asked for it. The field keeps its value while the
        # switch is off (the dialog pre-fills it from the launch command), and
        # a game now reaching here via its install folder must not resurrect a
        # name its owner deliberately turned off.
        self.exe_name = game.process_executable.strip() if game.track_process else ""
        # Package family name to accept as "this game is running", empty for a
        # game that isn't a Store/Game Pass one. A single name is enough: sibling
        # packages were the worry (Call of Duty ships one launchable package per
        # title plus a shared "COREBase") but watching a live session showed no
        # hand-off between them — every process a title spawns, launcher and game
        # alike, reports that title's own family name and nothing else's.
        aumid = aumid_from_command(game.executable)
        self.package_family = aumid.split("!", 1)[0] if aumid else ""
        # Install folder taken from the launch command, empty when there is no
        # executable path in it to be sure of. Watched *in addition to*
        # `exe_name` rather than instead of it: the folder catches the game
        # handing off to a differently named executable, and the name catches a
        # game whose command points into a subfolder — Battlefield 6 launches
        # `SP\bf6.exe` but keeps its multiplayer binary one level up, outside
        # the folder the command gives us. Neither covers the other.
        self.install_dir = install_dir_from_command(game.executable)
        # Seconds to keep waiting after the process disappears before ending the
        # session, so a game that restarts itself isn't cut off. User-adjustable.
        self.grace = max(0, shared.schema.get_int("process-tracking-grace"))
        self.session_seconds = 0  # this session's running total, for the toast
        self.started = False  # has the process been seen at least once?
        self.counting = False  # are we currently accruing time?
        # All three are monotonic readings, never wall-clock: they measure
        # intervals (see `_accumulate`), so a clock change must not move them.
        self.last_tick: Optional[float] = None  # when we last accrued time
        self.last_persist = 0.0  # last time we saved to disk
        self.waited = 0  # seconds spent waiting for the process to appear
        self.startup_grace = (
            self.PACKAGE_STARTUP_GRACE if self.package_family else self.STARTUP_GRACE
        )
        self.missing_since: Optional[float] = None  # when the process vanished
        self.poll_id = 0

    @property
    def elapsed(self) -> int:
        """Seconds counted so far, including the stretch not yet banked.

        `session_seconds` alone only moves on a poll, so a clock reading it
        would sit still for two seconds and then jump two. Adding the current
        stretch is also what makes the clock agree with the total the session
        ends up recording: it stays at zero while we are still waiting for the
        game to appear, and stops while the game is gone during the grace wait,
        which is exactly the time that never reaches `game.playtime`.
        """
        if self.counting and self.last_tick is not None:
            return self.session_seconds + int(monotonic() - self.last_tick)
        return self.session_seconds

    def _is_running(self) -> bool:
        """Is the game running right now?

        All three answers are accepted, any one of them being enough. Package
        identity is asked first because it is the most telling: it survives the
        game relaunching itself under a different executable — switching to the
        campaign in Call of Duty replaces ``cod23-cod.exe`` with
        ``sp23\\sp23-cod.exe``, and both report the same package — and it is the
        only thing that tells two Game Pass titles apart.

        It is asked first, though, not *instead* of the others. It can only
        answer where ``OpenProcess`` succeeds, and a handle we were refused
        comes back from the monitor as the same "no package" a plain unpackaged
        process does, so a package that says nothing is not evidence of a game
        that isn't running. A user who went to the trouble of configuring a
        process name for a Store game gets it honoured rather than silently
        ignored, exactly as the classic path already accepts the name or the
        folder.

        The name is tried before the folder only because it is the cheaper
        question: it reads the process list, while the folder has to open each
        process to ask where it was loaded from.
        """
        if self.package_family and is_package_running(self.package_family):
            return True
        if self.exe_name and is_process_running(self.exe_name):
            return True
        return bool(self.install_dir) and is_process_running_under(self.install_dir)

    def start(self) -> None:
        """Begin watching for the game's process."""
        ProcessSession.active = self
        self.last_persist = monotonic()
        # Block the main window so a second session can't be started from there
        shared.win.show_session_blocker(self.game)
        self.poll_id = GLib.timeout_add_seconds(self.POLL_INTERVAL, self._poll)

    def _poll(self) -> bool:
        running = self._is_running()

        if not self.started:
            if running:
                # Process appeared: start the clock
                self.started = True
                self.counting = True
                self.last_tick = monotonic()
                self.missing_since = None
                # O instante que separa uma sessão que conta de uma que não
                # conta. Sem esta linha, uma sessão que não registra nada e uma
                # que registra deixam exatamente o mesmo rastro no log, e a
                # diferença entre as duas é justamente o que se quer saber
                # quando um jogo não acumula tempo.
                logging.debug(
                    "%s seen running after %ss; counting playtime",
                    self.game.name,
                    self.waited,
                )
            else:
                self.waited += self.POLL_INTERVAL
                if self.waited >= self.startup_grace:
                    # Returning SOURCE_REMOVE already destroys this source, so
                    # zero the id first to keep stop() from removing it again
                    self.poll_id = 0
                    if self.package_family:
                        # A packaged game that never showed one process of its
                        # family did not start. The activation reached the
                        # shell, and what came up instead was the Xbox app
                        # saying the title needs an update, needs a re-login or
                        # is no longer installed — that window belongs to a
                        # different package, so nothing of ours is ever seen.
                        # Handing that to the manual window would put a counter
                        # on screen that runs until somebody comes back to close
                        # it, and `do_shutdown` would then write hours of
                        # playtime the game never had.
                        logging.info(
                            "No process of %s ever appeared; %s never started, "
                            "ending the session without a record",
                            self.package_family,
                            self.game.name,
                        )
                        self.stop(record=False, never_launched=True)
                    else:
                        # Here "never seen" really can mean "lost track of it":
                        # a launcher handed off to an executable under another
                        # name, or the game installed itself somewhere other
                        # than the folder its command names. Asking the user to
                        # clock out beats dropping a session that may well be
                        # running.
                        logging.info(
                            "%s never appeared; falling back to the manual "
                            "session window for %s",
                            self.exe_name or self.install_dir,
                            self.game.name,
                        )
                        self.stop(record=False, fall_back=True)
                    return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        if running:
            self.missing_since = None
            if not self.counting:
                # Resuming after a brief disappearance (e.g. the game relaunched
                # itself): start a fresh stretch so the downtime isn't counted
                self.counting = True
                self.last_tick = monotonic()
            self._accumulate()
            self._maybe_persist()
        else:
            if self.counting:
                # Just vanished: bank the time up to now, then pause counting so
                # the grace wait below is never counted as playtime
                self._accumulate()
                self.counting = False
            if self.missing_since is None:
                self.missing_since = monotonic()
            if monotonic() - self.missing_since >= self.grace:
                # See the startup-grace path: avoid a double source removal
                self.poll_id = 0
                self.stop(record=True)
                return GLib.SOURCE_REMOVE

        return GLib.SOURCE_CONTINUE

    def _accumulate(self) -> None:
        """Add the time since the last tick to the running totals.

        Measured on the monotonic clock, not the wall clock. `time()` can jump:
        an NTP correction, a manual clock change or a resume from sleep with a
        drifted RTC all move it, and a forward jump was credited to the game as
        playtime it never had (a backward jump was silently dropped by the
        ``> 0`` test, which is how the asymmetry stayed invisible). `monotonic`
        exists precisely for measuring an interval and cannot be moved.
        """
        now = monotonic()
        if self.counting and self.last_tick is not None:
            elapsed = int(now - self.last_tick)
            if elapsed > self.MAX_GAP:
                logging.info(
                    "%ss gap while tracking %s (sleep?); counting %ss",
                    elapsed,
                    self.game.name,
                    self.POLL_INTERVAL,
                )
                self.last_tick = now - self.POLL_INTERVAL
                elapsed = self.POLL_INTERVAL
            if elapsed > 0:
                self.game.playtime += elapsed
                self.session_seconds += elapsed
                # Carry the sub-second remainder, or truncating every two-second
                # poll would quietly lose time on a long session.
                now = self.last_tick + elapsed
        self.last_tick = now

    def _maybe_persist(self) -> None:
        """Save accumulated time at most once per PERSIST_INTERVAL."""
        now = monotonic()
        if now - self.last_persist >= self.PERSIST_INTERVAL:
            self.game.save()
            self.last_persist = now

    def flush(self) -> None:
        """Persist any accumulated time without touching the UI.

        Used on application shutdown, when widgets may already be gone but the
        session's last stretch of playtime still has to reach the disk.
        """
        if self.started:
            self._accumulate()
            self.game.save()

    def stop(
        self,
        record: bool = True,
        fall_back: bool = False,
        never_launched: bool = False,
    ) -> None:
        """End the session, optionally recording the elapsed time.

        ``fall_back`` hands the session over to the manual window instead of
        dropping it: we never saw the game, so the choice is between asking the
        user to clock out and silently losing the whole session.

        ``never_launched`` is the case where that choice does not arise. For a
        packaged game, "no process of this package was ever seen" is not us
        having lost track of the game, it is the game not having started, so the
        session ends with no record at all and the user is told as much rather
        than left with a counter to notice. The two are mutually exclusive.
        """
        if self.poll_id:
            GLib.source_remove(self.poll_id)
            self.poll_id = 0

        if ProcessSession.active is self:
            ProcessSession.active = None

        if fall_back:
            # avoid import cycles
            from cartridges.session_window import SessionWindow

            # Only the tracker changes hands. The game is still running, so the
            # blocker, the wallpaper, the LED strips, the parked window and the
            # suspended controller all stay as they are: `show_session_blocker`
            # recognises the same game and dresses nothing again.
            #
            # Deliberately no `shared.win.present()`: the main window is out of
            # the way (minimised, or parked on the session monitor) and the game
            # may well be in the foreground.
            SessionWindow(self.game).present()
            return

        shared.win.hide_session_blocker()

        if never_launched:
            toast = Adw.Toast.new(
                # The variable is the game's title
                _("{} não parece ter iniciado; nada foi registrado").format(
                    self.game.name
                )
            )
            # Same reason as the session toast below: the game's name is
            # interpolated into a title Adw.Toast parses as Pango markup by
            # default, and an "&" or "<" in it mangles the toast or makes Pango
            # reject it and drop the label.
            toast.set_use_markup(False)
            shared.win.toast_queue.add(toast)

        if record and self.started:
            # Capture the final running stretch (a no-op if already paused)
            self._accumulate()
            # Anotada depois do accumulate e antes do save, para que a linha do
            # histórico e o total do jogo contem os mesmos segundos.
            session_log.record(self.game.game_id, self.session_seconds)
            self.game.save()
            self.game.update()
            shared.win.session_toast(self.game, self.session_seconds)
        elif record:
            # Pedimos para registrar, mas o processo nunca apareceu: encerrar a
            # sessão pelo botão da janela bloqueada durante a espera cai aqui.
            # Não há o que registrar — nada foi medido —, e o silenêncio era
            # indistinguível de uma sessão gravada normalmente.
            logging.info(
                "Session for %s ended before %s was ever seen; nothing recorded",
                self.game.name,
                self.exe_name
                or self.package_family
                or self.install_dir
                or "the game",
            )

        # Bring the main window back now that the session is over
        shared.win.present()

    def close(self, *_args: Any) -> None:
        """Alias so callers can treat this like a SessionWindow."""
        self.stop(record=True)
