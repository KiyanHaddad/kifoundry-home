/** Adapt the saved-room HTTP shape for the version-oriented editor. */
export function normalizeRoom(room) {
  if (!room || !Array.isArray(room.messages) || !Array.isArray(room.rounds) || !Array.isArray(room.artifacts)) {
    throw new Error('The saved conversation is incomplete.');
  }
  return {
    ...room,
    artifacts: room.artifacts.flatMap(artifact => Array.isArray(artifact.versions) ? artifact.versions : [artifact]),
  };
}

/** Explain safe recovery from the saved turn states, without permitting uncertain retries. */
export function recoveryInfo(round) {
  if (!round || !['cancelled', 'interrupted'].includes(round.status)) return null;
  const turns = round.turns || [];
  const stopped = turn => ['cancelled', 'interrupted'].includes(turn.status);
  const waiting = turns.some(turn => ['queued', 'running'].includes(turn.status));
  const unstarted = turns.some(turn => !turn.launched && (stopped(turn) || turn.status === 'queued'));
  const finished = turn => ['completed', 'failed'].includes(turn.status);
  const synthesis = turns.find(turn => turn.phase === 'synthesis');
  const canFinish = round.mode === 'direct' ? turns.some(finished) :
    synthesis ? finished(synthesis) : turns.some(turn => turn.phase === 'proposal' && turn.status === 'completed');
  const maxCalls = round.mode === 'council' ? 2 * round.participants.length + 1 : 1;
  return {
    canResume: !waiting && (unstarted || canFinish),
    waiting,
    unknownCalls: turns.filter(turn => turn.launched && stopped(turn)).length,
    maxNewCalls: Math.max(0, maxCalls - turns.filter(turn => turn.launched).length),
  };
}
