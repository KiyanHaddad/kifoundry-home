"""Direct conversations and bounded Council rounds.

Direct: one participant, one call, continuing that resident's saved session in the room.
Its prompt always carries the bounded saved room history, so Council replies made since
the session's last turn are seen. Council calls never replace the direct session.
Council: N (2..64) participants, at most 2N+1 calls and no automatic extra rounds:
  1. proposal  - every participant, in parallel, gets the same frozen context
                 (only the persona framing differs) and a fresh provider session;
  2. critique  - every participant whose proposal completed sees all saved proposal
                 outcomes, attributed by name, and answers once (needs >= 2 proposals);
  3. synthesis - the first selected participant with a completed critique (else with a
                 completed proposal) writes one attributed synthesis that keeps an
                 "Unresolved" section.
Council calls are self-contained prompts; continuity comes from the saved room
transcript, not from provider sessions. Every prompt fits MAX_PROMPT_BYTES: saved peer
replies share the bytes left after fixed text, and shortened ones are marked as excerpts
(see fit_outcomes). Each provider call is serialized by the
adapter's identity_key across aliases and rooms. That is cooperative, in-app
serialization: it cannot see an unrelated terminal resuming the same native session.

The Council also owns the live resident registry (see the Council class docstring).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from .models import (
    MAX_ARTIFACTS_PER_ROUND,
    MAX_CONTEXT_BYTES,
    MAX_OWNER_BYTES,
    MAX_PARTICIPANTS,
    MAX_PROMPT_BYTES,
    MAX_REPLY_BYTES,
    MAX_REQUEST_ID_CHARS,
    MAX_RESIDENTS,
    Agent,
    Cancelled,
    ConflictError,
    NotFoundError,
    Provider,
    ProviderError,
    Reply,
    ValidationError,
    utf8_len,
)
from .residents import RESIDENT_ID, ResidentBinding, Seed, check_name, check_role, static_registry
from .store import Store

log = logging.getLogger(__name__)

MODES = ("direct", "council")


# ----- prompts (pure functions; easy to read and test) ------------------------------------

def persona(agent: Agent) -> str:
    """The only part of a first-phase prompt that differs between participants. One line."""
    role = f" Your role: {agent.role}." if agent.role else ""
    return (f"You are {agent.name}, a resident of KiFoundry Home, answering through the "
            f"{agent.provider} provider.{role} Speak only for yourself; never write as another resident.")


def build_context(history: list[dict[str, Any]], older: int, artifacts: list[dict[str, Any]], text: str,
                  names: dict[str, str], include_history: bool) -> str:
    """Freeze what every participant sees. Selected work and the owner's message are never cut;
    if they do not fit the budget the request is refused. Older history is dropped whole
    messages at a time, and the omission is stated in the context."""
    fixed = []
    if artifacts:
        fixed.append("## Selected work")
        for a in artifacts:
            fixed.append(f"### {a['title']} (version {a['version']}, sha256 {a['sha256'][:12]})\n{a['content']}")
    fixed.append(f"## Owner's message\n{text}")
    tail = "\n\n".join(fixed)
    if utf8_len(tail) > MAX_CONTEXT_BYTES - 256:
        raise ValidationError(
            f"The message plus selected work is {utf8_len(tail) // 1024} KiB, over the "
            f"{MAX_CONTEXT_BYTES // 1024} KiB shared-context limit; select less work"
        )
    if not include_history:
        return tail
    budget = MAX_CONTEXT_BYTES - 256 - utf8_len(tail)
    lines: list[str] = []
    omitted = older
    for index in range(len(history) - 1, -1, -1):
        m = history[index]
        # The name saved with the reply wins; older rows fall back to the registry, else stay unknown.
        who = "Owner" if m["role"] == "owner" else "System" if m["role"] == "system" else \
            m.get("agent_name") or names.get(m["agent_id"] or "") or "Unknown resident"
        phase = f" ({m['phase']})" if m.get("phase") and m["phase"] != "reply" else ""
        line = f"[{who}{phase}] {m['content']}"
        cost = utf8_len(line) + 1
        if cost > budget:
            omitted += index + 1
            break
        lines.append(line)
        budget -= cost
    if not lines:
        return tail if not omitted else f"## Earlier conversation\n[{omitted} earlier messages omitted]\n\n{tail}"
    header = "## Earlier conversation" + (f"\n[{omitted} earlier messages omitted]" if omitted else "")
    return f"{header}\n" + "\n".join(reversed(lines)) + f"\n\n{tail}"


EXCERPT_MARK = "\n[Excerpt; full reply saved in room]"
MIN_EXCERPT_BYTES = 200  # a shortened reply keeps at least this much of its own text


@dataclass(frozen=True)
class _Entry:
    """One participant's outcome in a phase. The label and status are never shortened."""

    label: str
    body: str | None  # saved reply text, or None when there was no reply
    status: str = ""


def _entries(turns: list[dict[str, Any]], order: list[str], agents: dict[str, Agent],
             me: str | None = None) -> list[_Entry]:
    by_agent = {t["agent_id"]: t for t in turns}
    entries = []
    for agent_id in order:
        turn = by_agent.get(agent_id)
        if turn is None:
            continue
        agent = agents[agent_id]
        label = f"### {agent.name} ({agent.provider})" + (" - you" if agent_id == me else "")
        if turn["status"] == "completed":
            entries.append(_Entry(label, turn["content"]))
        else:
            entries.append(_Entry(label, None, f"[no reply: {turn['status']}]"))
    return entries


def _clip(text: str, size: int) -> str:
    """At most `size` UTF-8 bytes of text, cut on a character boundary."""
    return text.encode("utf-8")[:size].decode("utf-8", "ignore")


def _render(prefix: str, sections: list[tuple[str, list[_Entry]]], bodies: list[str]) -> str:
    out = [prefix]
    index = 0
    for title, entries in sections:
        out.append(f"\n\n## {title}")
        for entry in entries:
            if entry.body is None:
                out.append(f"\n\n{entry.label}\n{entry.status}")
            else:
                out.append(f"\n\n{entry.label}\n{bodies[index]}")
                index += 1
    return "".join(out)


def fit_outcomes(prefix: str, sections: list[tuple[str, list[_Entry]]]) -> str:
    """Prompt = prefix + every section, within MAX_PROMPT_BYTES.

    The prefix (persona, instructions, frozen context) and every heading and status line
    are fixed. Saved reply bodies share the remaining bytes fairly in participant/phase
    order: replies that fit their share stay exact and their unused share passes to longer
    ones; a longer reply becomes an excerpt that says so. Saved replies are not changed.
    """
    texts = [e.body for _, entries in sections for e in entries if e.body is not None]
    fixed = utf8_len(_render(prefix, sections, [""] * len(texts)))
    sizes = [utf8_len(t) for t in texts]
    remaining = MAX_PROMPT_BYTES - fixed
    if sum(sizes) <= remaining:
        return _render(prefix, sections, texts)
    # Water-filling: the smallest replies are kept whole while they fit an equal share.
    share = remaining
    left = len(sizes)
    for size in sorted(sizes):
        if size * left <= share:
            share -= size
            left -= 1
        else:
            share //= left
            break
    room = share - utf8_len(EXCERPT_MARK)
    if room < MIN_EXCERPT_BYTES:
        raise ValidationError("These replies cannot be shared within the provider prompt limit")
    bodies = [t if utf8_len(t) <= share else _clip(t, room) + EXCERPT_MARK for t in texts]
    prompt = _render(prefix, sections, bodies)
    if utf8_len(prompt) > MAX_PROMPT_BYTES:  # defensive; the arithmetic above guarantees the bound
        raise ValidationError("The assembled prompt is over the provider prompt limit")
    return prompt


def _bounded(prompt: str) -> str:
    if utf8_len(prompt) > MAX_PROMPT_BYTES:
        raise ValidationError(f"The assembled prompt is over the {MAX_PROMPT_BYTES // 1024} KiB provider limit")
    return prompt


EXCERPT_NOTE = ("Replies marked as an excerpt were shortened to fit; the full text is saved in the room. "
                "An excerpt may omit qualifications and cannot establish agreement.")


def proposal_prompt(agent: Agent, context: str) -> str:
    return _bounded(f"{persona(agent)}\n\nCouncil round, first answer. Give your own proposal to the owner's "
                    f"message. Other participants answer separately; you will see their saved answers once "
                    f"afterwards.\n\n{context}")


def critique_prompt(agent: Agent, context: str, proposals: list[dict[str, Any]], order: list[str],
                    agents: dict[str, Agent]) -> str:
    prefix = (f"{persona(agent)}\n\nCouncil round, single peer critique. Below are the saved first answers, "
              f"attributed by name. Challenge or support specific points by name, say what you would change "
              f"in your own answer, and keep real disagreements. There is no further debate round. "
              f"{EXCERPT_NOTE}\n\n{context}")
    return fit_outcomes(prefix, [("First answers", _entries(proposals, order, agents, me=agent.id))])


def _synthesis_prefix(agent: Agent, context: str) -> str:
    return (f"{persona(agent)}\n\nYou were selected to write this Council round's synthesis. Attribute each "
            f"point to the participant who made it. Do not invent votes or agreement, and do not start another "
            f"debate. {EXCERPT_NOTE} End with a section titled 'Unresolved' that lists the disagreements "
            f"that remain.\n\n{context}")


def synthesis_prompt(agent: Agent, context: str, proposals: list[dict[str, Any]],
                     critiques: list[dict[str, Any]], order: list[str], agents: dict[str, Agent]) -> str:
    return fit_outcomes(_synthesis_prefix(agent, context), [("First answers", _entries(proposals, order, agents)),
                                                            ("Critiques", _entries(critiques, order, agents))])


def direct_prompt(agent: Agent, context: str) -> str:
    return _bounded(f"{persona(agent)}\n\n{context}")


def check_council_fits(agents: list[Agent], context: str) -> None:
    """Refuse a Council before anything is saved if its fixed scaffolding could not leave every
    reply a minimum excerpt. The synthesis prompt (all first answers and critiques) is the largest."""
    longest = max(agents, key=lambda a: utf8_len(persona(a)))
    order = [a.id for a in agents]
    by_id = {a.id: a for a in agents}
    turns = [{"agent_id": a.id, "status": "completed", "content": ""} for a in agents]
    sections = [("First answers", _entries(turns, order, by_id)), ("Critiques", _entries(turns, order, by_id))]
    scaffold = _render(_synthesis_prefix(longest, context), sections, [""] * (2 * len(agents)))
    minimum = 2 * len(agents) * (MIN_EXCERPT_BYTES + utf8_len(EXCERPT_MARK))
    if utf8_len(scaffold) + minimum > MAX_PROMPT_BYTES:
        raise ValidationError("This Council's shared context and names leave too little room for replies; "
                              "select fewer participants or less work")


# ----- orchestration ----------------------------------------------------------------------

@dataclass
class _Control:
    """One launched round: its cancel event and the residents frozen when it was launched."""

    cancel: threading.Event = field(default_factory=threading.Event)
    retry_launched: bool = False
    roster: dict[str, tuple[Agent, Provider]] = field(default_factory=dict)


@dataclass(frozen=True)
class _PendingCall:
    turn_id: str
    agent: Agent
    adapter: Provider
    prompt: str
    identity: str


class Council:
    """Orchestration plus the live resident registry.

    Registered residents (homes, up to 64 active) are distinct from a round's participants
    (any 2..64 active residents, or one for a direct conversation). Registry rows live in
    the Store; adapters are built here from trusted bindings.
    `_registry_lock` serializes registry edits with start/resume up to driver registration;
    provider calls never run under it. Each launched round carries its own frozen roster,
    so registry maps published later cannot change a round already in progress.
    """

    def __init__(self, store: Store, agents: dict[str, Agent] | None = None,
                 adapters: dict[str, Provider] | None = None, max_workers: int = 4, *,
                 bindings: list[ResidentBinding] | None = None, seeds: list[Seed] | None = None,
                 max_active_rounds: int = 8) -> None:
        if type(max_workers) is not int or not 1 <= max_workers <= 32:
            raise ValueError("max_workers must be an integer between 1 and 32")
        if type(max_active_rounds) is not int or not 1 <= max_active_rounds <= 64:
            raise ValueError("max_active_rounds must be an integer between 1 and 64")
        agents = dict(agents or {})
        adapters = dict(adapters or {})
        for agent_id, agent in agents.items():
            if agent.id != agent_id:
                raise ValueError(f"agent key {agent_id!r} does not match id {agent.id!r}")
            adapter = adapters.get(agent_id)
            if adapter is None:
                raise ValueError(f"no adapter configured for {agent_id!r}")
            if adapter.provider != agent.provider:
                raise ValueError(f"{agent_id!r} is configured as {agent.provider!r} but its adapter is "
                                 f"{adapter.provider!r}")
        all_bindings = list(bindings or [])
        all_seeds = list(seeds or [])
        if agents:
            legacy_bindings, legacy_seeds = static_registry(agents, adapters)
            all_bindings += legacy_bindings
            all_seeds += legacy_seeds
        self._bindings: dict[str, ResidentBinding] = {}
        for binding in all_bindings:
            if binding.id in self._bindings:
                raise ValueError(f"binding {binding.id!r} is configured twice")
            self._bindings[binding.id] = binding
        for seed in all_seeds:
            seed_binding = self._bindings.get(seed.binding_id)
            if seed_binding is None or seed_binding.provider != seed.agent.provider:
                raise ValueError(f"resident {seed.agent.id!r} needs a configured {seed.agent.provider} binding")
            if not RESIDENT_ID.fullmatch(seed.agent.id):
                raise ValueError(f"resident ID {seed.agent.id!r} is not a safe identifier")
        self.store = store
        self._max_workers = max_workers
        self._max_active_rounds = max_active_rounds
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="home-call")
        # Reserve identities before executor submission. An alias waiting for its
        # session must not occupy a worker needed by an unrelated ready provider.
        self._busy_identities: set[str] = set()
        self._guard = threading.RLock()
        self._ready = threading.Condition(self._guard)
        self._registry_lock = threading.RLock()
        self._controls: dict[str, _Control] = {}
        self._drivers: dict[str, threading.Thread] = {}
        self._closing = threading.Event()
        store.seed_residents([{"id": s.agent.id, "name": s.agent.name, "provider": s.agent.provider,
                               "role": s.agent.role, "binding_id": s.binding_id} for s in all_seeds])
        # Published maps are replaced, never mutated: agents/adapters hold active, available residents.
        self._residents: dict[str, dict[str, Any]] = {}
        self.agents: dict[str, Agent] = {}
        self.adapters: dict[str, Provider] = {}
        self._load_registry()
        self.recovered = store.recover_unfinished()

    # ----- registry ---------------------------------------------------------------------

    def _binding_for(self, row: dict[str, Any]) -> ResidentBinding | None:
        binding = self._bindings.get(row["binding_id"])
        return binding if binding is not None and binding.provider == row["provider"] else None

    def _build_adapter(self, binding: ResidentBinding, name: str) -> Provider:
        try:
            adapter = binding.factory(name)
        except Exception:
            log.exception("could not build an adapter from binding %s", binding.id)
            raise ProviderError("That resident's provider could not be prepared; nothing was changed") from None
        if getattr(adapter, "provider", None) != binding.provider:
            raise ProviderError("That binding produced a different provider; nothing was changed")
        return adapter

    def _load_registry(self) -> None:
        residents: dict[str, dict[str, Any]] = {}
        agents: dict[str, Agent] = {}
        adapters: dict[str, Provider] = {}
        for row in self.store.residents():
            residents[row["id"]] = row
            binding = None if row["archived"] else self._binding_for(row)
            if binding is None:
                continue  # archived, or its trusted binding is gone: home and history stay, dispatch stops
            try:
                adapter = self._build_adapter(binding, row["name"])
            except ProviderError:
                continue
            agents[row["id"]] = Agent(row["id"], row["name"], row["provider"], row["role"])
            adapters[row["id"]] = adapter
        self._residents, self.agents, self.adapters = residents, agents, adapters

    def _publish(self, row: dict[str, Any], adapter: Provider | None) -> None:
        agents = {k: v for k, v in self.agents.items() if k != row["id"]}
        adapters = {k: v for k, v in self.adapters.items() if k != row["id"]}
        if adapter is not None:
            agents[row["id"]] = Agent(row["id"], row["name"], row["provider"], row["role"])
            adapters[row["id"]] = adapter
        self._residents = {**self._residents, row["id"]: row}
        self.agents, self.adapters = agents, adapters

    def _info(self, row: dict[str, Any]) -> dict[str, Any]:
        available = (self._binding_for(row) is not None) if row["archived"] else row["id"] in self.adapters
        return {"id": row["id"], "name": row["name"], "provider": row["provider"], "role": row["role"],
                "binding_id": row["binding_id"], "home_slot": row["home_slot"], "archived": row["archived"],
                "available": available}

    def agents_info(self, include_archived: bool = False) -> list[dict[str, Any]]:
        rows = sorted(self._residents.values(), key=lambda r: (r["archived"], r["home_slot"], r["created_at"]))
        return [self._info(r) for r in rows if include_archived or not r["archived"]]

    def capabilities_info(self) -> dict[str, int]:
        """The limits this server actually validates and runs with."""
        return {"max_residents": MAX_RESIDENTS, "max_participants": MAX_PARTICIPANTS,
                "max_provider_calls": 2 * MAX_PARTICIPANTS + 1, "max_workers": self._max_workers,
                "max_active_rounds": self._max_active_rounds,
                "max_prompt_bytes": MAX_PROMPT_BYTES}

    def bindings_info(self) -> list[dict[str, str]]:
        return [b.info() for b in self._bindings.values() if b.addable]

    def _require_idle(self) -> None:
        if self._closing.is_set():
            raise ConflictError("KiFoundry Home is shutting down")
        with self._guard:
            busy = bool(self._drivers)
        if busy:
            raise ConflictError("Residents can change once current conversations finish, including calls "
                                "still finishing after Stop")

    def _require_capacity(self) -> None:
        """Called under the registry lock before a request can change persistent state."""
        with self._guard:
            if self._closing.is_set():
                raise ConflictError("KiFoundry Home is shutting down")
            if len(self._drivers) >= self._max_active_rounds:
                raise ConflictError("Home is at its active conversation limit; wait for a conversation "
                                    "to finish, including calls still finishing after Stop")

    def add_resident(self, name: Any, role: Any, binding_id: Any) -> dict[str, Any]:
        binding = self._bindings.get(binding_id) if isinstance(binding_id, str) else None
        if binding is None or not binding.addable:
            raise ValidationError("Choose one of the configured resident bindings")
        name, role = check_name(name, binding.provider), check_role(role)
        with self._registry_lock:
            self._require_idle()
            if sum(not r["archived"] for r in self._residents.values()) >= MAX_RESIDENTS:
                raise ConflictError(f"The town is full: archive a resident before adding more than {MAX_RESIDENTS}")
            adapter = self._build_adapter(binding, name)  # before any persistent change
            row = self.store.add_resident(f"res-{uuid.uuid4().hex}", name, binding.provider, role, binding.id)
            self._publish(row, adapter)
            return self._info(row)

    def archive_resident(self, resident_id: str) -> dict[str, Any]:
        with self._registry_lock:
            self._require_idle()
            if resident_id not in self._residents:
                raise NotFoundError("Resident not found")
            row = self.store.set_resident_archived(resident_id, True)
            self._publish(row, None)
            return self._info(row)

    def restore_resident(self, resident_id: str) -> dict[str, Any]:
        with self._registry_lock:
            self._require_idle()
            current = self._residents.get(resident_id)
            if current is None:
                raise NotFoundError("Resident not found")
            if not current["archived"]:
                raise ConflictError("That resident is already active")
            binding = self._binding_for(current)
            if binding is None:
                raise ConflictError(f"{current['name']} cannot return: its local provider binding is not configured")
            adapter = self._build_adapter(binding, current["name"])
            row = self.store.set_resident_archived(resident_id, False)
            self._publish(row, adapter)
            return self._info(row)

    def _require_dispatchable(self, participants: list[str]) -> None:
        for agent_id in participants:
            if agent_id in self.agents:
                continue
            row = self._residents.get(agent_id)
            if row is None:
                raise ValidationError("Unknown participant selected")
            if row["archived"]:
                raise ValidationError(f"{row['name']} is archived; restore them before talking")
            raise ValidationError(f"{row['name']} is unavailable: their local provider binding is not configured")

    def _roster(self, saved: dict[str, Any]) -> dict[str, tuple[Agent, Provider]]:
        """Prompt identities come from the round's frozen snapshot; legacy rounds without one use
        the current registry entry. Adapters are the resident's current instance."""
        self._require_dispatchable(saved["participants"])
        roster: dict[str, tuple[Agent, Provider]] = {}
        for agent_id in saved["participants"]:
            snap = saved.get("participant_snapshots", {}).get(agent_id)
            agent = Agent(agent_id, snap["name"], snap["provider"], snap["role"]) if snap else self.agents[agent_id]
            adapter = self.adapters[agent_id]
            if adapter.provider != agent.provider:
                raise ValidationError(f"{agent.name} now uses a different provider than this round recorded")
            roster[agent_id] = (agent, adapter)
        return roster

    # ----- owner actions ----------------------------------------------------------------

    def start(self, room_id: str, text: str, participants: list[str], request_id: str,
              mode: str = "council", artifact_ids: list[str] | None = None) -> dict[str, Any]:
        if self._closing.is_set():
            raise ConflictError("KiFoundry Home is shutting down")
        participants, artifact_ids = self._validate(text, participants, request_id, mode, artifact_ids)
        request_sha = hashlib.sha256(json.dumps(
            {"room": room_id, "text": text, "participants": participants, "mode": mode,
             "artifacts": artifact_ids}, sort_keys=True).encode("utf-8")).hexdigest()
        with self._registry_lock:
            existing = self.store.round_for_request(request_id, request_sha)
            if existing is not None:
                return existing  # idempotent repeat, even if the registry changed since
            self._require_capacity()
            self._require_dispatchable(participants)
            names = {key: row["name"] for key, row in self._residents.items()}
            snapshots = {p: {"name": self.agents[p].name, "provider": self.agents[p].provider,
                             "role": self.agents[p].role} for p in participants}
            selected = [self.agents[p] for p in participants]

            def builder(history: list[dict[str, Any]], older: int, artifacts: list[dict[str, Any]],
                        body: str) -> str:
                # Direct prompts carry room history too: a resumed session has not seen Council
                # replies made since its last turn.
                context = build_context(history, older, artifacts, body, names, include_history=True)
                if mode == "council":
                    check_council_fits(selected, context)
                return context

            saved, created = self.store.create_round(
                room_id=room_id, request_id=request_id, request_sha256=request_sha, mode=mode, text=text,
                participants=participants, artifact_ids=artifact_ids,
                first_phase="reply" if mode == "direct" else "proposal", build_context=builder,
                participant_snapshots=snapshots)
            if created:
                self._launch(saved["id"], retry_launched=False, roster=self._roster(saved))
        return self.store.round(saved["id"])

    def cancel(self, round_id: str) -> dict[str, Any]:
        with self._ready:
            control = self._controls.get(round_id)
            if control is not None:
                control.cancel.set()
                self._ready.notify_all()
        return self.store.cancel_round(round_id)

    def resume(self, round_id: str, retry_interrupted: bool = False) -> dict[str, Any]:
        """Owner-requested continuation of an interrupted or stopped round.

        Completed and failed turns are reused as saved. Turns that never launched run now.
        A call whose outcome is unknown (launched, then interrupted/stopped) is not repeated
        unless the owner passes retry_interrupted=True, accepting a possible duplicate call.
        Every participant must still be active and available; that is checked before the
        round retakes its room.
        """
        if self._closing.is_set():
            raise ConflictError("KiFoundry Home is shutting down")
        with self._registry_lock:
            with self._guard:
                if round_id in self._drivers:
                    raise ConflictError("This round is still finishing its in-flight calls; try again shortly")
            saved = self.store.round(round_id)
            if saved["status"] not in ("interrupted", "cancelled"):
                raise ConflictError(f"Only an interrupted or stopped round can resume (this one is {saved['status']})")
            roster = self._roster(saved)
            self._require_capacity()
            self.store.reactivate_round(round_id)
            self._launch(round_id, retry_launched=retry_interrupted, roster=roster)
        return self.store.round(round_id)

    def close(self, timeout: float = 10.0) -> None:
        """Stop owned work: in-flight calls are told to cancel, drivers are joined with a bound.
        Rounds still unfinished afterwards are marked interrupted by the next startup."""
        with self._registry_lock:
            self._closing.set()
            with self._ready:
                drivers = list(self._drivers.values())
                for control in self._controls.values():
                    control.cancel.set()
                self._ready.notify_all()
        per_thread = timeout / max(1, len(drivers))
        for driver in drivers:
            driver.join(per_thread)
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ----- validation -------------------------------------------------------------------

    def _validate(self, text: Any, participants: Any, request_id: Any, mode: Any,
                  artifact_ids: Any) -> tuple[list[str], list[str]]:
        """Shape checks only; registry membership is checked under the registry lock."""
        if mode not in MODES:
            raise ValidationError("mode must be 'direct' or 'council'")
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("Message must be non-empty text")
        if utf8_len(text) > MAX_OWNER_BYTES:
            raise ValidationError(f"Message is over {MAX_OWNER_BYTES // 1024} KiB")
        if not isinstance(request_id, str) or not 0 < len(request_id) <= MAX_REQUEST_ID_CHARS:
            raise ValidationError("request_id is required (1-128 characters)")
        if not isinstance(participants, list) or not all(isinstance(p, str) for p in participants):
            raise ValidationError("participants must be a list of resident ids")
        if len(set(participants)) != len(participants):
            raise ValidationError("A participant is selected twice")
        if mode == "direct" and len(participants) != 1:
            raise ValidationError("A direct conversation has exactly one participant")
        if mode == "council" and not 2 <= len(participants) <= MAX_PARTICIPANTS:
            raise ValidationError(f"A Council needs 2 to {MAX_PARTICIPANTS} participants")
        artifact_ids = [] if artifact_ids is None else artifact_ids
        if not isinstance(artifact_ids, list) or not all(isinstance(a, str) for a in artifact_ids):
            raise ValidationError("artifact_ids must be a list")
        if len(set(artifact_ids)) != len(artifact_ids) or len(artifact_ids) > MAX_ARTIFACTS_PER_ROUND:
            raise ValidationError(f"Select up to {MAX_ARTIFACTS_PER_ROUND} distinct artifacts")
        return list(participants), list(artifact_ids)

    # ----- execution --------------------------------------------------------------------

    def _launch(self, round_id: str, retry_launched: bool, roster: dict[str, tuple[Agent, Provider]]) -> None:
        control = _Control(retry_launched=retry_launched, roster=roster)
        driver = threading.Thread(target=self._drive, args=(round_id, control),
                                  name=f"home-round-{round_id[:8]}", daemon=True)
        with self._guard:
            self._controls[round_id] = control
            self._drivers[round_id] = driver
        driver.start()

    def _drive(self, round_id: str, control: _Control) -> None:
        try:
            if not self.store.mark_round_running(round_id):
                return
            saved = self.store.round(round_id)
            context = self.store.round_context(round_id)
            order: list[str] = saved["participants"]
            if saved["mode"] == "direct":
                self._drive_direct(round_id, saved["room_id"], order[0], context, control)
            else:
                self._drive_council(round_id, order, context, control)
        except Exception:
            log.exception("round %s failed inside the app", round_id)
            self.store.finish_round(round_id, "failed", "The app hit an internal error; saved replies are kept.")
        finally:
            with self._guard:
                self._controls.pop(round_id, None)
                self._drivers.pop(round_id, None)

    def _stopped(self, round_id: str, control: _Control) -> bool:
        if not control.cancel.is_set():
            return False
        if self._closing.is_set():
            self.store.finish_round(round_id, "interrupted",
                                    "KiFoundry Home shut down before this round finished; saved replies are kept.")
        return True

    def _drive_direct(self, round_id: str, room_id: str, agent_id: str, context: str, control: _Control) -> None:
        session_id = self.store.session(room_id, agent_id)
        agent = control.roster[agent_id][0]
        self._phase(round_id, "reply", [agent_id], lambda _a: direct_prompt(agent, context), control, session_id)
        if self._stopped(round_id, control):
            return
        turn = self._turns(round_id, "reply")[0]
        if turn["status"] == "completed":
            self.store.finish_round(round_id, "completed")
        elif turn["status"] == "failed":
            self.store.finish_round(round_id, "failed", f"{agent.name} did not reply: {turn['error']}")
        else:
            self.store.finish_round(round_id, "interrupted", f"{agent.name}'s reply outcome is unknown; not retried.")

    def _drive_council(self, round_id: str, order: list[str], context: str, control: _Control) -> None:
        agents = {key: pair[0] for key, pair in control.roster.items()}
        self._phase(round_id, "proposal", order, lambda a: proposal_prompt(agents[a], context), control)
        if self._stopped(round_id, control):
            return
        proposals = self._turns(round_id, "proposal")
        answered = [t["agent_id"] for t in proposals if t["status"] == "completed"]
        missing = [agents[t["agent_id"]].name for t in proposals if t["status"] != "completed"]
        gap = f" No first answer from: {', '.join(missing)}." if missing else ""
        if not answered:
            unknown = any(t["status"] in ("cancelled", "interrupted") for t in proposals)
            self.store.finish_round(round_id, "interrupted" if unknown else "failed",
                                    "No participant produced a first answer." + gap)
            return
        if len(answered) < 2:
            self.store.finish_round(round_id, "completed",
                                    "Only one first answer arrived, so critique and synthesis were skipped." + gap)
            return

        self._phase(round_id, "critique", answered,
                    lambda a: critique_prompt(agents[a], context, proposals, order, agents), control)
        if self._stopped(round_id, control):
            return
        critiques = self._turns(round_id, "critique")
        existing = self._turns(round_id, "synthesis")
        if existing:
            synthesizer = existing[0]["agent_id"]
        else:
            critiqued = {t["agent_id"] for t in critiques if t["status"] == "completed"}
            synthesizer = next((a for a in order if a in critiqued), answered[0])
        self._phase(round_id, "synthesis", [synthesizer],
                    lambda a: synthesis_prompt(agents[a], context, proposals, critiques, order, agents), control)
        if self._stopped(round_id, control):
            return
        synthesis = self._turns(round_id, "synthesis")[0]
        name = agents[synthesizer].name
        if synthesis["status"] == "completed":
            self.store.finish_round(round_id, "completed", gap.strip())
        elif synthesis["status"] == "failed":
            self.store.finish_round(round_id, "failed",
                                    f"Synthesis by {name} failed; first answers and critiques are kept.{gap}")
        else:
            self.store.finish_round(round_id, "interrupted",
                                    f"Synthesis by {name} has an unknown outcome and was not repeated.{gap}")

    def _turns(self, round_id: str, phase: str) -> list[dict[str, Any]]:
        return [t for t in self.store.round(round_id)["turns"] if t["phase"] == phase]

    def _phase(self, round_id: str, phase: str, agent_ids: list[str], prompt_for: Callable[[str], str],
               control: _Control, session_id: str | None = None) -> None:
        pending: list[_PendingCall] = []
        for agent_id in agent_ids:
            turn = self.store.ensure_turn(round_id, agent_id, phase)
            if turn is None:
                break
            if turn["status"] != "queued" and not self.store.requeue_turn(turn["id"], control.retry_launched):
                continue  # completed, failed, or an unknown outcome the owner did not ask to retry
            agent, adapter = control.roster[agent_id]
            try:
                prompt = prompt_for(agent_id)
                identity = adapter.identity_key(session_id)
                if not isinstance(identity, str) or not identity:
                    raise ProviderError("The provider returned an invalid session identity")
            except ValidationError as error:  # cannot fit the prompt limit: fail safely, no call
                self.store.end_turn(turn["id"], "failed", str(error))
                continue
            except Exception as error:  # noqa: BLE001 - adapter identity bugs become attributed failures.
                self.store.end_turn(turn["id"], "failed", _safe_error(agent, error))
                continue
            pending.append(_PendingCall(turn["id"], agent, adapter, prompt, identity))

        futures: dict[Future[None], str] = {}
        errors: list[BaseException] = []

        def ready() -> bool:
            return any(f.done() for f in futures) or (bool(pending) and (
                control.cancel.is_set() or any(c.identity not in self._busy_identities for c in pending)))

        with self._ready:
            while pending or futures:
                for future in list(futures):
                    if not future.done():
                        continue
                    turn_id = futures.pop(future)
                    if future.cancelled():
                        self.store.end_turn(turn_id, self._stop_status(), "stopped before launch")
                    elif (failure := future.exception()) is not None:
                        errors.append(failure)
                if control.cancel.is_set():
                    for call in pending:
                        self.store.end_turn(call.turn_id, self._stop_status(), "stopped before launch")
                    pending.clear()
                else:
                    waiting = []
                    for call in pending:
                        if call.identity in self._busy_identities:
                            waiting.append(call)
                            continue
                        self._busy_identities.add(call.identity)
                        try:
                            future = self._pool.submit(self._call, call.turn_id, call.agent, call.adapter,
                                                       call.prompt, session_id, control, phase == "reply")
                        except RuntimeError:
                            self._busy_identities.remove(call.identity)
                            self.store.end_turn(call.turn_id, "interrupted", "stopped before launch")
                            control.cancel.set()
                            continue
                        futures[future] = call.turn_id
                        future.add_done_callback(partial(self._release_identity, call.identity))
                    pending = waiting
                if pending or futures:
                    self._ready.wait_for(ready)
        if errors:
            raise errors[0]

    def _release_identity(self, key: str, _future: Future[None]) -> None:
        with self._ready:
            self._busy_identities.remove(key)
            self._ready.notify_all()

    def _stop_status(self) -> str:
        return "interrupted" if self._closing.is_set() else "cancelled"

    def _call(self, turn_id: str, agent: Agent, adapter: Provider, prompt: str, session_id: str | None,
              control: _Control, save_session: bool) -> None:
        if control.cancel.is_set():
            self.store.end_turn(turn_id, self._stop_status(), "stopped before launch")
            return
        if not self.store.claim_turn(turn_id):
            return
        try:
            reply = adapter.generate(prompt, session_id, control.cancel)
        except Exception as error:  # noqa: BLE001 - adapter bugs must become attributed failed turns.
            if control.cancel.is_set() or isinstance(error, Cancelled):
                self.store.end_turn(turn_id, self._stop_status(), "stopped while running; no reply was saved")
            else:
                self.store.end_turn(turn_id, "failed", _safe_error(agent, error))
            return
        problem = _check_reply(agent, reply, session_id)
        if problem:
            self.store.end_turn(turn_id, "failed", problem)
            return
        # A final reply that actually arrived is kept even if Stop was pressed meanwhile.
        self.store.complete_turn(turn_id, reply, save_session=save_session, speaker_name=agent.name)


def _safe_error(agent: Agent, error: Exception) -> str:
    if isinstance(error, ProviderError):
        return str(error)[:500] or f"{agent.name}'s provider reported a failure"
    return f"{agent.name}'s provider call failed ({type(error).__name__})"


def _check_reply(agent: Agent, reply: Any, session_id: str | None) -> str | None:
    if not isinstance(reply, Reply):
        return f"{agent.name}'s adapter returned something other than a reply"
    if reply.provider != agent.provider:
        return (f"{agent.name} is configured as {agent.provider} but the reply was attributed to "
                f"{reply.provider}; not saved")
    if session_id is not None and reply.session_id is not None and reply.session_id != session_id:
        return f"{agent.name}'s provider answered from a different session than the saved one; not saved"
    if not isinstance(reply.text, str) or not reply.text.strip():
        return f"{agent.name} returned an empty reply"
    if utf8_len(reply.text) > MAX_REPLY_BYTES:
        return f"{agent.name}'s reply was over {MAX_REPLY_BYTES // 1024} KiB and was not saved"
    return None
