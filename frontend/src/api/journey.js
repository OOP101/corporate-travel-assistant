import { get, post, postEmpty, ssePost } from './client';

export async function chat(query, sessionId = 'default', model = null) {
  const body = { query, session_id: sessionId };
  if (model) body.model = model;
  return post('/api/journey/agent/chat', body);
}

export function chatStream(query, sessionId = 'default', onEvent, model = null) {
  const body = { query, session_id: sessionId };
  if (model) body.model = model;
  return ssePost('/api/journey/agent/chat/stream', body, onEvent);
}

export async function getSessionHistory(sessionId = 'default', lastN = 20) {
  return get(`/api/journey/agent/session/${sessionId}/history?last_n=${lastN}`);
}

export async function clearSession(sessionId = 'default') {
  return postEmpty(`/api/journey/agent/session/${sessionId}/clear`);
}
