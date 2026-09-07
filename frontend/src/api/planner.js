import { get, postEmpty, put, del, ssePost } from './client';

// --- 行程 ---
export async function listTrips(sessionId = 'default') {
  return get(`/api/planner/trips?session_id=${sessionId}`);
}

export async function getTrip(tripId) {
  return get(`/api/planner/trips/${tripId}`);
}

export async function deleteTrip(tripId) {
  return del(`/api/planner/trips/${tripId}`);
}

export async function updateTrip(tripId, data) {
  return put(`/api/planner/trips/${tripId}`, { data });
}

export function generateTripStream(query, preferences = {}, onChunk) {
  return ssePost('/api/planner/trips/generate', { query, preferences, session_id: 'default' }, onChunk);
}

// --- 清单 ---
export async function getChecklist(tripId) {
  return get(`/api/planner/trips/${tripId}/checklist`);
}

// --- 总结 ---
export async function generateSummary(tripId) {
  return postEmpty(`/api/planner/trips/${tripId}/summary`);
}

// --- 消费统计 ---
export async function getExpenses(tripId) {
  return get(`/api/planner/trips/${tripId}/expenses`);
}

// --- 行程单导出（HTML，供打印 / 另存为 PDF） ---
export async function getTripExportHtml(tripId) {
  const API_KEY = import.meta.env.VITE_API_KEY || 'ak_dev_local';
  const res = await fetch(`/api/planner/trips/${tripId}/export`, {
    headers: { 'X-API-Key': API_KEY },
  });
  if (!res.ok) throw new Error('导出失败');
  return res.text();
}

// --- 用户画像 ---
export async function getProfile(sessionId = 'default') {
  return get(`/api/planner/users/me/profile?session_id=${sessionId}`);
}

export async function updateProfile(data, sessionId = 'default') {
  return put(`/api/planner/users/me/profile?session_id=${sessionId}`, data);
}

// --- 模板 ---
export async function listTemplates(tags = '') {
  const qs = tags ? `?tags=${encodeURIComponent(tags)}` : '';
  return get(`/api/planner/templates${qs}`);
}
