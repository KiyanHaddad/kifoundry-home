/**
 * Pick work from a fresh newest-page response, whose insertion order is authoritative.
 * Never pass merged editor history or older pages here: timestamps cannot recover
 * insertion order when saves share a timestamp or the local clock changes.
 */
export function newestPageDraft(artifacts) {
  if (!Array.isArray(artifacts)) return null;
  return artifacts.find(artifact => {
    if (!artifact || typeof artifact.id !== 'string' || !artifact.id ||
        typeof artifact.title !== 'string' || !artifact.title.trim() ||
        !Number.isSafeInteger(artifact.version) || artifact.version < 1) return false;
    const latest = artifact.latest_version;
    return latest === undefined || (Number.isSafeInteger(latest) && latest === artifact.version);
  }) || null;
}

const pendingStatuses = new Set(['queued', 'running']);

function turnsOf(round) {
  return Array.isArray(round?.turns) ? round.turns : [];
}

function pendingRound(round) {
  return pendingStatuses.has(round?.status) ||
    turnsOf(round).some(turn => pendingStatuses.has(turn.status));
}

function runningNames(round) {
  const ids = [...new Set(turnsOf(round).filter(turn => turn.status === 'running')
    .map(turn => turn.agent_id))];
  const names = ids.slice(0, 2).map(id => {
    const saved = round.participant_snapshots?.[id]?.name;
    const name = typeof saved === 'string' && saved.trim() ? saved.trim().replace(/\s+/g, ' ') : 'A resident';
    const letters = Array.from(name);
    return letters.length > 40 ? letters.slice(0, 39).join('') + '…' : name;
  });
  return names.join(', ') + (ids.length > 2 ? ' + ' + (ids.length - 2) + ' more' : '');
}

function savedReplyDetail(round) {
  const count = turnsOf(round).filter(turn => turn.status === 'completed').length;
  return count ? count + (count === 1 ? ' reply saved. ' : ' replies saved. ') : '';
}

/** Summarize this room's saved execution state. No movement or provider availability is inferred. */
export function deskActivity(room, connected, fixture = false) {
  const rounds = Array.isArray(room?.rounds) ? room.rounds : [];
  const round = rounds.find(pendingRound) || rounds.at(-1);
  const result = (text, detail, tone) => ({
    text, detail: (fixture ? 'Demo responses. ' : '') + detail, tone, hasRound: Boolean(round),
  });
  if (!connected) {
    return result('Connection unavailable', 'Saved progress only. Reconnect to check the current reply status.', 'offline');
  }
  if (!round) {
    return result('No replies yet', 'In this conversation. Choose a resident when you are ready.', 'neutral');
  }
  const pending = pendingRound(round);
  const saved = savedReplyDetail(round);
  if (pending && round.status === 'cancelled') {
    return result('Stopping · waiting for calls to finish', saved + 'The stopped calls are still exiting.', 'warning');
  }
  if (pending && round.status === 'interrupted') {
    return result('Waiting for calls to finish', saved + 'This interrupted round still has unfinished calls.', 'warning');
  }
  if (pending) {
    const names = runningNames(round);
    if (round.status === 'queued' && !names) {
      return result('Waiting to begin', saved + 'This conversation has a saved round waiting to start.', 'working');
    }
    return result(round.mode === 'council' ? 'Council in progress' : 'Reply in progress',
      saved + (names ? 'Replying now: ' + names + '.' : 'The saved round is still in progress.'), 'working');
  }
  switch (round.status) {
    case 'completed': {
      const gaps = turnsOf(round).some(turn => ['failed', 'cancelled', 'interrupted'].includes(turn.status));
      return result('Last reply finished', saved + (gaps ?
        'Some calls could not finish; review the discussion.' : 'Read the saved discussion to continue.'), gaps ? 'warning' : 'success');
    }
    case 'partial':
      return result('Some replies received', saved + 'Review the discussion for missing replies.', 'warning');
    case 'failed':
      return result('Last round could not finish', saved + 'Review the saved discussion for the failure.', 'error');
    case 'interrupted':
      return result('Round interrupted', saved + 'Review safe recovery before continuing.', 'warning');
    case 'cancelled':
      return result('Round stopped', saved + 'Review the saved replies before continuing.', 'neutral');
    default:
      return result('Saved progress available', 'Open the discussion to check this round.', 'neutral');
  }
}
