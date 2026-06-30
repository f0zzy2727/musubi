"""Tests for the silence-watchdog decision (idle-1).

The watcher loop wakes the orchestration layer when the comms channel goes
fully quiet after everything is relayed — the pair does not self-continue, so
without this they sleep until a human pokes them (field report 2026-06-20, Oya
self-admitted). comms.silence_nudge_due is the pure predicate behind that
decision; these pin its edges.
"""
from comms import silence_nudge_due

WAKE = 300  # idle_wake_secs


def test_quiet_long_enough_first_nudge_fires():
    assert silence_nudge_due(
        idle_secs=WAKE, idle_wake_secs=WAKE, silence_nudges=0,
        since_last_nudge=10_000, waiting_on_operator=False) is True


def test_not_yet_quiet_enough_holds():
    assert silence_nudge_due(
        idle_secs=WAKE - 1, idle_wake_secs=WAKE, silence_nudges=0,
        since_last_nudge=10_000, waiting_on_operator=False) is False


def test_disabled_when_wake_secs_zero():
    assert silence_nudge_due(
        idle_secs=10_000, idle_wake_secs=0, silence_nudges=0,
        since_last_nudge=10_000, waiting_on_operator=False) is False


def test_stays_quiet_while_operator_pinned():
    # Work parked on a human decision — silence is expected, do not nudge.
    assert silence_nudge_due(
        idle_secs=10_000, idle_wake_secs=WAKE, silence_nudges=0,
        since_last_nudge=10_000, waiting_on_operator=True) is False


def test_no_repeat_nudge_before_interval_elapses():
    # Already nudged once this episode; not enough time since for a re-nudge.
    assert silence_nudge_due(
        idle_secs=10_000, idle_wake_secs=WAKE, silence_nudges=1,
        since_last_nudge=WAKE - 5, waiting_on_operator=False) is False


def test_re_nudge_after_interval_escalates():
    # A full interval since the last nudge and still silent -> nudge again
    # (the loop escalates to the operator surface on the 2nd).
    assert silence_nudge_due(
        idle_secs=10_000, idle_wake_secs=WAKE, silence_nudges=1,
        since_last_nudge=WAKE, waiting_on_operator=False) is True


# --- pane-collision guard (idle-1 hardening 2026-06-22) ---------------------
# buffer_has_pending_input is the pure predicate behind the watchdog's refusal
# to key a pane that holds an unsent typed line (which send_keys would garble).
from orchestrator import buffer_has_pending_input


def test_codex_prompt_with_unsent_command_is_pending():
    # The okami signature: Codex parked with its next step typed but not sent.
    buf = "Worked 3m 31s\n\n❯ continue S2"
    assert buffer_has_pending_input(buf) is True


def test_codex_arrow_variants_detected():
    assert buffer_has_pending_input("➜ keep going") is True


def test_empty_codex_prompt_is_not_pending():
    assert buffer_has_pending_input("some output\n❯ ") is False
    assert buffer_has_pending_input("some output\n❯") is False


def test_claude_input_box_with_text_is_pending():
    buf = "╭───────────────╮\n│ > fix the bug │\n╰───────────────╯"
    assert buffer_has_pending_input(buf) is True


def test_claude_empty_input_box_is_not_pending():
    buf = "╭───────────────╮\n│ >             │\n╰───────────────╯"
    assert buffer_has_pending_input(buf) is False


def test_ui_hint_after_prompt_is_not_pending():
    # The "/clear to save" hint and shortcut hints are not user input.
    assert buffer_has_pending_input("❯ /clear to save 720k tokens") is False
    assert buffer_has_pending_input("❯ ? for shortcuts") is False


def test_idle_ready_prompt_is_not_pending():
    # A clean ready prompt with prior output above it must not trip the guard.
    buf = "[@CODA] posted PASS\n<OVER>\n\n❯"
    assert buffer_has_pending_input(buf) is False


def test_empty_buffer_is_not_pending():
    assert buffer_has_pending_input("") is False
    assert buffer_has_pending_input(None) is False


# --- context-budget watchdog (2026-06-22) -----------------------------------
from orchestrator import parse_context_pressure_k


def test_parses_clear_to_save_hint():
    assert parse_context_pressure_k("new task? /clear to save 720.1k tokens") == 720.1


def test_parses_integer_k():
    assert parse_context_pressure_k("/clear to save 478k tokens") == 478.0


def test_parses_comma_grouped():
    assert parse_context_pressure_k("save 1,024k tokens") == 1024.0


def test_returns_largest_when_multiple():
    buf = "earlier /clear to save 200k\nlater /clear to save 480k tokens"
    assert parse_context_pressure_k(buf) == 480.0


def test_no_pressure_hint_returns_none():
    assert parse_context_pressure_k("❯ ready\nWorked 2m") is None
    assert parse_context_pressure_k("") is None
    assert parse_context_pressure_k(None) is None


# --- context_regime: dead-vs-live remedy split (2026-06-27) ------------------
from orchestrator import context_regime

WARN = 400
IDLE_T = 240


def test_regime_none_below_threshold():
    assert context_regime(399, WARN, "IDLE", 9999, IDLE_T) is None
    assert context_regime(None, WARN, "IDLE", 9999, IDLE_T) is None


def test_regime_live_when_working_however_heavy():
    # A working pane is never "dead", no matter how long the timer ran.
    assert context_regime(898, WARN, "WORKING", 9999, IDLE_T) == "live"


def test_regime_live_when_idle_but_not_frozen_long():
    # Heavy + idle but the buffer changed recently -> still cycling -> live.
    assert context_regime(720, WARN, "IDLE", IDLE_T - 1, IDLE_T) == "live"


def test_regime_dead_when_idle_and_frozen_past_threshold():
    assert context_regime(720, WARN, "IDLE", IDLE_T, IDLE_T) == "dead"
    assert context_regime(720, WARN, "IDLE", IDLE_T + 100, IDLE_T) == "dead"


def test_regime_modal_or_pending_is_live_not_dead():
    # A long-frozen MODAL/PENDING_INPUT pane is the modal watchdog's job — it is
    # a live transient state, never context-dead.
    assert context_regime(720, WARN, "MODAL", 9999, IDLE_T) == "live"
    assert context_regime(720, WARN, "PENDING_INPUT", 9999, IDLE_T) == "live"


def test_regime_never_dead_when_park_disabled():
    # idle_threshold <= 0 means we can't judge frozen-ness -> always live.
    assert context_regime(898, WARN, "IDLE", 9999, 0) == "live"


# --- permission-modal watchdog (stall-class 1, 2026-06-24) -------------------
from orchestrator import buffer_has_permission_modal

# The canonical positive: the live okami pane-0 capture, Oya parked on an
# oyakata-log.md edit prompt 8 min into the 2026-06-24 launch.
OYA_EDIT_MODAL = """\
 Do you want to make this edit to oyakata-log.md?
 ❯ 1. Yes
   2. Yes, allow all edits in agents/ during this session (shift+tab)
   3. No
 Esc to cancel · Tab to amend"""

# A Codex-style approval prompt (chevron + numbered Yes/No on an "Allow?" line).
CODEX_APPROVAL_MODAL = """\
Allow command: git push origin main ?
> 1. Yes
  2. Yes, and don't ask again
  3. No, and tell Codex what to do differently"""


def test_modal_summary_is_the_question_line():
    assert buffer_has_permission_modal(OYA_EDIT_MODAL) == \
        "Do you want to make this edit to oyakata-log.md?"


def test_codex_approval_modal_detected():
    assert buffer_has_permission_modal(CODEX_APPROVAL_MODAL) == \
        "Allow command: git push origin main ?"


def test_generic_label_when_no_question_line():
    # Selector present but no `?`-ending question above it.
    buf = "applying patch\n ❯ 1. Yes\n   2. No"
    assert buffer_has_permission_modal(buf) == \
        "a permission prompt is blocking this pane"


def test_prose_mentioning_do_you_want_is_not_a_modal():
    # Agent text that merely talks about a prompt — no selector line.
    buf = "I'll ask: do you want to proceed? Posting the question to comms now."
    assert buffer_has_permission_modal(buf) is None


def test_normal_prompt_is_not_a_modal():
    assert buffer_has_permission_modal("❯ ready for the next slice") is None
    assert buffer_has_permission_modal("✻ Crunched for 29s") is None


def test_empty_and_none_safe():
    assert buffer_has_permission_modal("") is None
    assert buffer_has_permission_modal(None) is None


def test_unsent_input_line_alone_is_not_a_modal():
    # `❯ continue S2` (pending input) must NOT read as a modal — no numbered
    # Yes/No option, so the modal detector stays silent (pending-input detector
    # owns that case).
    assert buffer_has_permission_modal("❯ continue S2") is None


# --- park watchdog: working-vs-parked detection (stall-class 3, 2026-06-24) ---
from orchestrator import buffer_is_working, classify_pane_state

# Live captures from the okami panes (2026-06-24).
CLAUDE_WORKING = "· Herding… (4m 31s · ↓ 14.7k tokens · still thinking)"
CLAUDE_DONE    = "✻ Crunched for 29s\n❯ "
CODEX_DONE     = "─ Worked for 1m 53s ──────────────\n› "
CODEX_WORKING  = "thinking (12s • Esc to interrupt)"


def test_claude_spinner_is_working():
    assert buffer_is_working(CLAUDE_WORKING) is True


def test_codex_interrupt_hint_is_working():
    assert buffer_is_working(CODEX_WORKING) is True


def test_past_tense_done_markers_are_not_working():
    # "Crunched for"/"Worked for" mean the turn FINISHED — the pane is now idle.
    assert buffer_is_working(CLAUDE_DONE) is False
    assert buffer_is_working(CODEX_DONE) is False


def test_plain_prose_is_not_working():
    assert buffer_is_working("continue collecting events; heartbeat per prompt") is False
    assert buffer_is_working("") is False
    assert buffer_is_working(None) is False


def test_classify_precedence_modal_over_all():
    # A modal present wins even if a working/spinner line is also on screen.
    buf = CLAUDE_WORKING + "\nDo you want to proceed?\n ❯ 1. Yes\n   2. No"
    assert classify_pane_state(buf) == "MODAL"


def test_classify_pending_input_over_working():
    assert classify_pane_state("❯ continue S2") == "PENDING_INPUT"


def test_classify_working():
    assert classify_pane_state(CLAUDE_WORKING) == "WORKING"


def test_classify_idle_on_finished_pane():
    # Finished turn, empty prompt — the park candidate.
    assert classify_pane_state(CODEX_DONE) == "IDLE"
    assert classify_pane_state("❯ ") == "IDLE"


# --- comms-drop watchdog (stall-class 2, 2026-06-24) ------------------------
from comms import comms_drop_due

GRACE = 90  # baton_grace_secs


def test_comms_drop_fires_after_grace_quiet_channel():
    # Capsule advanced over a quiet channel, grace elapsed, no append, nobody
    # waiting on the operator → surface the dropped baton.
    assert comms_drop_due(
        armed_secs=GRACE, baton_grace_secs=GRACE, append_since_arm=False,
        already_surfaced=False, waiting_on_operator=False) is True


def test_comms_drop_holds_before_grace():
    assert comms_drop_due(
        armed_secs=GRACE - 1, baton_grace_secs=GRACE, append_since_arm=False,
        already_surfaced=False, waiting_on_operator=False) is False


def test_comms_drop_silent_when_not_armed():
    assert comms_drop_due(
        armed_secs=None, baton_grace_secs=GRACE, append_since_arm=False,
        already_surfaced=False, waiting_on_operator=False) is False


def test_comms_drop_silent_when_append_landed():
    # An append after arming = the baton flowed; no drop.
    assert comms_drop_due(
        armed_secs=10_000, baton_grace_secs=GRACE, append_since_arm=True,
        already_surfaced=False, waiting_on_operator=False) is False


def test_comms_drop_once_per_episode():
    assert comms_drop_due(
        armed_secs=10_000, baton_grace_secs=GRACE, append_since_arm=False,
        already_surfaced=True, waiting_on_operator=False) is False


def test_comms_drop_silent_when_waiting_on_operator():
    # A capsule update at a cycle boundary parked on a human decision is not a
    # dropped baton — stay quiet.
    assert comms_drop_due(
        armed_secs=10_000, baton_grace_secs=GRACE, append_since_arm=False,
        already_surfaced=False, waiting_on_operator=True) is False


def test_comms_drop_disabled_when_grace_zero():
    assert comms_drop_due(
        armed_secs=10_000, baton_grace_secs=0, append_since_arm=False,
        already_surfaced=False, waiting_on_operator=False) is False


# --- rolling comms rotation (relay-1, 2026-06-27) ---------------------------
from comms import rotation_due

MAXB = 200_000
QUIET = 60


def test_rotation_fires_when_drained_big_and_quiet():
    assert rotation_due(MAXB, MAXB, QUIET, MAXB, QUIET) is True
    assert rotation_due(MAXB + 5_000, MAXB + 5_000, QUIET + 10, MAXB, QUIET) is True


def test_rotation_holds_when_not_fully_drained():
    # A partial (mid-compose) leaves current_size > last_offset — never rotate,
    # or the truncate would orphan the tail.
    assert rotation_due(MAXB + 100, MAXB, QUIET, MAXB, QUIET) is False


def test_rotation_holds_below_threshold():
    assert rotation_due(MAXB - 1, MAXB - 1, QUIET, MAXB, QUIET) is False


def test_rotation_holds_when_not_quiet_long_enough():
    assert rotation_due(MAXB, MAXB, QUIET - 1, MAXB, QUIET) is False


def test_rotation_disabled_when_max_bytes_zero():
    assert rotation_due(10_000_000, 10_000_000, 10_000, 0, QUIET) is False


# --- burn-1 follow-up: wake-loop circuit-breaker -------------------------------
from orchestrator import WakeGovernor


def test_wake_governor_allows_under_cap():
    g = WakeGovernor(max_wakes=3, window_secs=100)
    assert [g.allow(t) for t in (0, 1, 2)] == [True, True, True]
    assert g.tripped is False
    assert g.count == 3


def test_wake_governor_trips_at_cap():
    g = WakeGovernor(max_wakes=3, window_secs=100)
    for t in (0, 1, 2):
        g.allow(t)
    # 4th within the window is denied and records nothing.
    assert g.allow(3) is False
    assert g.tripped is True
    assert g.count == 3  # the denied event was NOT recorded


def test_wake_governor_self_heals_after_window_drains():
    g = WakeGovernor(max_wakes=2, window_secs=100)
    g.allow(0); g.allow(1)
    assert g.allow(2) is False           # tripped while events are in-window
    # At t=102 the early events (0,1) age out (<= 102-100); breaker re-arms.
    assert g.allow(102) is True
    assert g.tripped is False


def test_wake_governor_sliding_window_not_fixed_buckets():
    # A sustained max-rate stays tripped: as old events leave, new denials don't
    # record, so the window never refills enough to allow a burst.
    g = WakeGovernor(max_wakes=2, window_secs=10)
    assert g.allow(0) and g.allow(1)
    # Hammer every second past the cap — all denied while 2 events stay in-window.
    assert [g.allow(t) for t in (2, 3, 4, 5)] == [False, False, False, False]
    # Once BOTH seed events (0,1) have aged out (t>=11+), a single wake is allowed.
    assert g.allow(12) is True


def test_wake_governor_disabled_when_max_zero():
    g = WakeGovernor(max_wakes=0, window_secs=100)
    assert all(g.allow(t) for t in range(50))
    assert g.tripped is False


def test_wake_governor_michael_burn_rate_trips_fast():
    # The 2026-06-30 signature: a nudge every few minutes for hours. With the
    # default 10/hour cap, the 11th nudge inside the hour is suppressed.
    g = WakeGovernor()  # defaults: 10 / 3600s
    allowed = [g.allow(t * 180) for t in range(20)]  # every 3 min
    assert allowed[:10] == [True] * 10
    assert allowed[10] is False           # 11th within the hour -> tripped
    assert g.tripped is True
