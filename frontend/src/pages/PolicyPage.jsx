import { useState, useEffect } from 'react';
import {
  FileText, Plus, Edit2, Trash2, Search,
  Plane, Hotel, Utensils, Car, BookOpen,
} from 'lucide-react';
import {
  listPolicies, createPolicy, updatePolicy, deletePolicy,
  listPolicyDocs, createPolicyDoc, updatePolicyDoc, deletePolicyDoc,
  searchPolicyDocs,
} from '../api/organization';
import { PageHeader, Card, Button, Badge, EmptyState, Select, Input } from '../components';

const LEVEL_OPTIONS = [
  { value: 'intern', label: '实习生' },
  { value: 'junior', label: '初级员工' },
  { value: 'middle', label: '中级员工' },
  { value: 'senior', label: '高级员工' },
  { value: 'manager', label: '经理' },
  { value: 'director', label: '总监' },
  { value: 'vp', label: '副总裁' },
  { value: 'executive', label: '高管' },
];

const CITY_TIER_OPTIONS = [
  { value: 'all', label: '全部城市' },
  { value: '1', label: '一线城市' },
  { value: '2', label: '二线城市' },
  { value: '3', label: '三线及以下' },
];

const DOC_CATEGORIES = [
  { value: 'general', label: '通用' },
  { value: 'flight', label: '机票' },
  { value: 'hotel', label: '住宿' },
  { value: 'meal', label: '餐饮' },
  { value: 'transport', label: '交通' },
  { value: 'subsidy', label: '补贴' },
];

const CATEGORY_TONES = {
  general: 'gray', flight: 'blue', hotel: 'purple',
  meal: 'amber', transport: 'green', subsidy: 'primary',
};

const inputCls = 'w-full px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focusable';

export default function PolicyPage() {
  const [activeTab, setActiveTab] = useState('policies');
  const [policies, setPolicies] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [modalType, setModalType] = useState('');
  const [editingItem, setEditingItem] = useState(null);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [formData, setFormData] = useState({});

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      try {
        if (activeTab === 'policies') {
          const res = await listPolicies();
          setPolicies(res.policies || []);
        } else {
          const res = await listPolicyDocs({ category: filterCategory });
          setDocuments(res.documents || []);
        }
      } catch (err) {
        console.error('加载数据失败:', err);
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, [activeTab, filterCategory]);

  const handleCreate = (type) => {
    setModalType(type);
    setEditingItem(null);
    if (type === 'policy') {
      setFormData({
        name: '', description: '', level: '', city_tier: 'all',
        flight_class: 'economy', train_class: 'second',
        hotel_limit: 0, meal_limit: 0, transport_limit: 0, daily_subsidy: 0,
        requires_approval: true, approval_threshold: 0,
      });
    } else {
      setFormData({ title: '', content: '', category: 'general', tags: [], source: '' });
    }
    setShowModal(true);
  };

  const handleEdit = (item, type) => {
    setModalType(type);
    setEditingItem(item);
    setFormData({ ...item });
    setShowModal(true);
  };

  const handleDelete = async (id, type) => {
    if (!confirm('确定删除吗？')) return;
    try {
      if (type === 'policy') await deletePolicy(id);
      else await deletePolicyDoc(id);
      loadData();
    } catch (err) {
      alert('删除失败: ' + err.message);
    }
  };

  const handleSubmit = async () => {
    try {
      if (modalType === 'policy') {
        if (editingItem) await updatePolicy(editingItem.policy_id, formData);
        else await createPolicy(formData);
      } else {
        if (editingItem) await updatePolicyDoc(editingItem.doc_id, formData);
        else await createPolicyDoc(formData);
      }
      setShowModal(false);
      loadData();
    } catch (err) {
      alert('保存失败: ' + err.message);
    }
  };

  const handleSearch = async () => {
    if (!searchKeyword) { loadData(); return; }
    setLoading(true);
    try {
      const res = await searchPolicyDocs(searchKeyword, filterCategory);
      setDocuments(res.documents || []);
    } catch (err) {
      console.error('搜索失败:', err);
    } finally {
      setLoading(false);
    }
  };

  const getLevelLabel = (level) => LEVEL_OPTIONS.find((l) => l.value === level)?.label || '通用';
  const getCityTierLabel = (tier) => CITY_TIER_OPTIONS.find((t) => t.value === tier)?.label || tier;
  const getCategoryLabel = (category) => DOC_CATEGORIES.find((c) => c.value === category)?.label || category;

  const set = (key, value) => setFormData((prev) => ({ ...prev, [key]: value }));

  return (
    <div className="h-full flex flex-col px-6 py-5">
      <PageHeader
        title="差旅政策"
        subtitle="政策标准与制度文档，自动对齐报销与审批口径"
      />

      <div className="flex-1 overflow-y-auto -mx-6 px-6 pb-4">
        <div className="max-w-5xl mx-auto space-y-4">
          {/* Tabs */}
          <div className="inline-flex items-center gap-1 bg-gray-100/80 rounded-xl p-1">
            {[
              { key: 'policies', label: '政策标准' },
              { key: 'documents', label: '政策文档' },
            ].map((t) => (
              <button
                key={t.key}
                onClick={() => setActiveTab(t.key)}
                className={`px-4 py-1.5 text-sm font-medium rounded-lg transition-all ${
                  activeTab === t.key ? 'bg-white text-primary-600 shadow-sm' : 'text-ink-600 hover:text-ink-900'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* 政策标准 */}
          {activeTab === 'policies' ? (
            loading ? (
              <div className="text-center py-14 text-ink-400">加载中...</div>
            ) : policies.length === 0 ? (
              <Card>
                <EmptyState
                  icon={<FileText size={22} />}
                  title="暂无差旅政策"
                  action={{ label: '创建第一个政策', onClick: () => handleCreate('policy') }}
                />
              </Card>
            ) : (
              <div className="space-y-3">
                <div className="flex justify-end">
                  <Button onClick={() => handleCreate('policy')}><Plus size={15} /> 新建政策</Button>
                </div>
                {policies.map((policy) => (
                  <div key={policy.policy_id} className="card p-5 card-hover">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-2 flex-wrap">
                          <h3 className="font-semibold text-ink-900">{policy.name}</h3>
                          <Badge tone="primary">{getLevelLabel(policy.level)}</Badge>
                          <Badge>{getCityTierLabel(policy.city_tier)}</Badge>
                          {policy.requires_approval && <Badge tone="amber">需审批</Badge>}
                        </div>
                        <p className="text-ink-600 text-sm mb-3.5">{policy.description || '暂无描述'}</p>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                          {[
                            { Icon: Plane, label: '机票', value: policy.flight_class === 'economy' ? '经济舱' : policy.flight_class === 'business' ? '公务舱' : '头等舱' },
                            { Icon: Hotel, label: '酒店', value: `¥${policy.hotel_limit}/晚` },
                            { Icon: Utensils, label: '餐饮', value: `¥${policy.meal_limit}/日` },
                            { Icon: Car, label: '交通', value: `¥${policy.transport_limit}/日` },
                          ].map(({ Icon, label, value }) => (
                            <div key={label} className="flex items-center gap-2 bg-gray-50/70 rounded-lg px-3 py-2">
                              <Icon size={15} className="text-ink-400 shrink-0" />
                              <span className="text-ink-400 text-xs">{label}</span>
                              <span className="font-medium text-ink-900 ml-auto">{value}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <Button size="sm" type="ghost" onClick={() => handleEdit(policy, 'policy')}><Edit2 size={14} /></Button>
                        <Button size="sm" type="ghost" className="text-red-500! hover:bg-red-50!" onClick={() => handleDelete(policy.policy_id, 'policy')}><Trash2 size={14} /></Button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )
          ) : (
            /* 政策文档 */
            loading ? (
              <div className="text-center py-14 text-ink-400">加载中...</div>
            ) : (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <div className="w-40">
                      <Select
                        options={[{ value: '', label: '全部分类' }, ...DOC_CATEGORIES]}
                        value={filterCategory}
                        onChange={setFilterCategory}
                      />
                    </div>
                    <div className="relative">
                      <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
                      <Input
                        type="text"
                        placeholder="搜索文档..."
                        value={searchKeyword}
                        onChange={(v) => setSearchKeyword(String(v))}
                        className="pl-9! w-56"
                      />
                    </div>
                    <Button type="secondary" onClick={handleSearch}>搜索</Button>
                  </div>
                  <Button onClick={() => handleCreate('document')}><Plus size={15} /> 新建文档</Button>
                </div>

                {documents.length === 0 ? (
                  <Card>
                    <EmptyState
                      icon={<BookOpen size={22} />}
                      title={searchKeyword ? '未找到匹配的文档' : '暂无政策文档'}
                    />
                  </Card>
                ) : (
                  documents.map((doc) => (
                    <div key={doc.doc_id} className="card p-5 card-hover">
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-2 flex-wrap">
                            <h3 className="font-semibold text-ink-900">{doc.title}</h3>
                            <Badge tone={CATEGORY_TONES[doc.category] || 'gray'}>{getCategoryLabel(doc.category)}</Badge>
                          </div>
                          <p className="text-ink-600 text-sm line-clamp-2 mb-2.5">{doc.content}</p>
                          {doc.tags && doc.tags.length > 0 && (
                            <div className="flex gap-1.5 flex-wrap">
                              {doc.tags.map((tag, idx) => (
                                <span key={idx} className="px-2 py-0.5 text-xs bg-gray-100 text-ink-600 rounded-md">{tag}</span>
                              ))}
                            </div>
                          )}
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <Button size="sm" type="ghost" onClick={() => handleEdit(doc, 'document')}><Edit2 size={14} /></Button>
                          <Button size="sm" type="ghost" className="text-red-500! hover:bg-red-50!" onClick={() => handleDelete(doc.doc_id, 'document')}><Trash2 size={14} /></Button>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )
          )}
        </div>
      </div>

      {/* 模态框 */}
      {showModal && (
        <div className="fixed inset-0 bg-ink-900/40 backdrop-blur-[2px] flex items-center justify-center z-50" onClick={() => setShowModal(false)}>
          <div className="bg-white rounded-2xl w-full max-w-xl p-6 max-h-[88vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-base font-semibold text-ink-900 mb-5">
              {editingItem ? '编辑' : '新建'}{modalType === 'policy' ? '差旅政策' : '政策文档'}
            </h2>

            <div className="space-y-4">
              {modalType === 'policy' ? (
                <>
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1">政策名称</label>
                    <input type="text" value={formData.name || ''} onChange={(e) => set('name', e.target.value)} className={inputCls} placeholder="如：员工差旅管理办法" />
                  </div>
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1">政策描述</label>
                    <textarea value={formData.description || ''} onChange={(e) => set('description', e.target.value)} className={`${inputCls} resize-y`} rows={2} />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-[13px] font-medium text-ink-600 mb-1">适用职级</label>
                      <select value={formData.level || ''} onChange={(e) => set('level', e.target.value)} className={inputCls}>
                        <option value="">通用</option>
                        {LEVEL_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="block text-[13px] font-medium text-ink-600 mb-1">城市等级</label>
                      <select value={formData.city_tier || 'all'} onChange={(e) => set('city_tier', e.target.value)} className={inputCls}>
                        {CITY_TIER_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="block text-[13px] font-medium text-ink-600 mb-1">机票舱位</label>
                      <select value={formData.flight_class || 'economy'} onChange={(e) => set('flight_class', e.target.value)} className={inputCls}>
                        <option value="economy">经济舱</option><option value="business">公务舱</option><option value="first">头等舱</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-[13px] font-medium text-ink-600 mb-1">火车座位</label>
                      <select value={formData.train_class || 'second'} onChange={(e) => set('train_class', e.target.value)} className={inputCls}>
                        <option value="second">二等座</option><option value="first">一等座</option><option value="business">商务座</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-[13px] font-medium text-ink-600 mb-1">酒店每晚上限（元）</label>
                      <input type="number" value={formData.hotel_limit || 0} onChange={(e) => set('hotel_limit', Number(e.target.value))} className={inputCls} />
                    </div>
                    <div>
                      <label className="block text-[13px] font-medium text-ink-600 mb-1">餐饮每日上限（元）</label>
                      <input type="number" value={formData.meal_limit || 0} onChange={(e) => set('meal_limit', Number(e.target.value))} className={inputCls} />
                    </div>
                    <div>
                      <label className="block text-[13px] font-medium text-ink-600 mb-1">交通每日上限（元）</label>
                      <input type="number" value={formData.transport_limit || 0} onChange={(e) => set('transport_limit', Number(e.target.value))} className={inputCls} />
                    </div>
                    <div>
                      <label className="block text-[13px] font-medium text-ink-600 mb-1">每日补贴（元）</label>
                      <input type="number" value={formData.daily_subsidy || 0} onChange={(e) => set('daily_subsidy', Number(e.target.value))} className={inputCls} />
                    </div>
                    <div className="flex items-center gap-2.5">
                      <input type="checkbox" id="requires_approval" checked={formData.requires_approval || false} onChange={(e) => set('requires_approval', e.target.checked)} className="w-4 h-4 accent-primary-600" />
                      <label htmlFor="requires_approval" className="text-[13px] font-medium text-ink-600">需要审批</label>
                    </div>
                    <div>
                      <label className="block text-[13px] font-medium text-ink-600 mb-1">审批金额阈值（元）</label>
                      <input type="number" value={formData.approval_threshold || 0} onChange={(e) => set('approval_threshold', Number(e.target.value))} className={inputCls} />
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1">文档标题</label>
                    <input type="text" value={formData.title || ''} onChange={(e) => set('title', e.target.value)} className={inputCls} placeholder="如：差旅报销管理办法" />
                  </div>
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1">分类</label>
                    <select value={formData.category || 'general'} onChange={(e) => set('category', e.target.value)} className={inputCls}>
                      {DOC_CATEGORIES.map((cat) => <option key={cat.value} value={cat.value}>{cat.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1">文档内容</label>
                    <textarea value={formData.content || ''} onChange={(e) => set('content', e.target.value)} className={`${inputCls} resize-y`} rows={7} placeholder="政策文档正文内容..." />
                  </div>
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1">标签（逗号分隔）</label>
                    <input
                      type="text"
                      value={(formData.tags || []).join(', ')}
                      onChange={(e) => set('tags', e.target.value.split(',').map((t) => t.trim()).filter(Boolean))}
                      className={inputCls}
                      placeholder="差旅, 报销, 管理办法"
                    />
                  </div>
                  <div>
                    <label className="block text-[13px] font-medium text-ink-600 mb-1">来源</label>
                    <input type="text" value={formData.source || ''} onChange={(e) => set('source', e.target.value)} className={inputCls} placeholder="文件编号或来源" />
                  </div>
                </>
              )}
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <Button type="secondary" onClick={() => setShowModal(false)}>取消</Button>
              <Button onClick={handleSubmit}>确定</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
