/**
 * 景点攻略语料 API —— 独立 RAG 通道（仅 personal 场景召回）
 *
 * 与「政策文档」形态一致：CRUD + 语义检索（embedding 不可用时自动降级关键词）+ 重建索引。
 * 检索结果保留原文 excerpt，供前端展示「凭什么这么答」。
 */
import { get, post, postEmpty, put, del } from './client';

const BASE_URL = '/api/planner';

export async function listGuides({ category, keyword } = {}) {
  const params = new URLSearchParams();
  if (category) params.append('category', category);
  if (keyword) params.append('keyword', keyword);
  const q = params.toString();
  return get(`${BASE_URL}/guides${q ? `?${q}` : ''}`);
}

export async function createGuide(data) {
  // data: { title, content, category, tags: [], source }
  return post(`${BASE_URL}/guides`, data);
}

export async function getGuide(guideId) {
  return get(`${BASE_URL}/guides/${guideId}`);
}

export async function updateGuide(guideId, data) {
  return put(`${BASE_URL}/guides/${guideId}`, data);
}

export async function deleteGuide(guideId) {
  return del(`${BASE_URL}/guides/${guideId}`);
}

export async function searchGuides({ query, category = '', topK = 5, minScore = 0 }) {
  return post(`${BASE_URL}/guides/search`, {
    query,
    category,
    top_k: topK,
    min_score: minScore,
  });
}

export async function reindexGuides(force = false) {
  return postEmpty(`${BASE_URL}/guides/reindex?force=${force}`);
}
