import { get, post, postEmpty, del } from './client';

export async function getAlerts(tripId, undelivered = false) {
  const qs = undelivered ? '?undelivered=true' : '';
  return get(`/api/sense/trips/${tripId}/alerts${qs}`);
}

export async function subscribeMonitor(data) {
  return post('/api/sense/monitor/subscribe', data);
}

export async function getMonitorStatus() {
  return get('/api/sense/monitor/status');
}

export async function unsubscribeMonitor(tripId) {
  return del(`/api/sense/monitor/${tripId}`);
}

export async function manualCheck() {
  return postEmpty('/api/sense/monitor/check');
}

/**
 * 实时数据直查（问答路径同款接口，不等监控订阅）
 * type: weather | flight | train
 */
export async function realtimeQuery(payload) {
  return post('/api/sense/query', payload);
}
