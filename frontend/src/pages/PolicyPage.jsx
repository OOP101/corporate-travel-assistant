import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  FileText, Plus, Edit2, Trash2, Plane, Hotel, Utensils, Car,
  Target, ShieldAlert, CheckCircle2, Loader2,
} from 'lucide-react';
import {
  listPolicies, createPolicy, updatePolicy, deletePolicy,
  matchPolicy, checkPolicyViolations,
} from '../api/organization';
import { listTrips } from '../api/planner';
import { PageHeader, Card, Button, Badge, EmptyState, Tab } from '../components';

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

const inputCls = 'w-full px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focusable';

export default function PolicyPage() {
  const [activeTab, setActiveTab] = useState('policies');

  return (
    <div className="h-full flex flex-col px-6 py-5">
      <PageHeader
        title="差旅政策"
        subtitle="按职级与城市等级维护差标，并可对具体行程做合规校验"
      />

      <div className="mb-4">
        <Tab
          tabs={[
            { label: '政策标准', value: 'policies' },
            { label: '匹配与校验', value: 'engine' },
          ]}
          defaultActive="policies"
          onChange={setActiveTab}
        />
      </div>

      <div className="flex-1 overflow-y-auto -mx-6 px-6 pb-4">
        <div className="max-w-5xl mx-auto">
          {activeTab === 'policies' ? <PolicyList /> : <MatchAndCheck />}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 政策标准：增删改查                                                   */
/* ------------------------------------------------------------------ */

function PolicyList() {
  const [policies, setPolicies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [formData, setFormData] = useState({});

  const load = async () => {
    setLoading(true);
    try {
      const res = await listPolicies();
      setPolicies(res.policies || []);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => {
    setEditingItem(null);
    setFormData({
      name: '', description: '', level: '', city_tier: 'all',
      flight_class: 'economy', train_class: 'second',
      hotel_limit: 0, meal_limit: 0, transport_limit: 0, daily_subsidy: 0,
      requires_approval: true, approval_threshold: 0,
    });
    setShowModal(true);
  };

  const openEdit = (item) => {
    setEditingItem(item);
    setFormData({ ...item });
    setShowModal(true);
  };

  const remove = async (id) => {
    if (!window.confirm('确定删除该政策？删除后按此政策匹配的差标将回落到通用政策。')) return;
    try {
      await deletePolicy(id);
      load();
    } catch (e) {
      window.alert('删除失败: ' + e.message);
    }
  };

  const submit = async () => {
    try {
      if (editingItem) await updatePolicy(editingItem.policy_id, formData);
      else await createPolicy(formData);
      setShowModal(false);
      load();
    } catch (e) {
      window.alert('保存失败: ' + e.message);
    }
  };

  const set = (key, value) => setFormData((prev) => ({ ...prev, [key]: value }));
  const levelLabel = (level) => LEVEL_OPTIONS.find((l) => l.value === level)?.label || '通用';
  const tierLabel = (tier) => CITY_TIER_OPTIONS.find((t) => t.value === tier)?.label || tier;

  if (loading) return <div className="flex justify-center py-20"><Loader2 className="animate-spin text-ink-400" size={24} /></div>;

  if (!policies.length) {
    return (
      <Card>
        <EmptyState
          icon={<FileText size={22} />}
          title="暂无差旅政策"
          description="政策按职级 × 城市等级匹配，是报销与审批的判定依据"
          action={{ label: '创建第一个政策', onClick: openCreate }}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-[12px] text-ink-400">
          共 {policies.length} 条 · 匹配时按「职级 + 城市等级」取最精确的一条
        </span>
        <Button size="sm" onClick={openCreate}><Plus size={15} /> 新建政策</Button>
      </div>

      {policies.map((policy) => (
        <div key={policy.policy_id} className="card p-5 card-hover">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-2 flex-wrap">
                <h3 className="font-semibold text-ink-900">{policy.name}</h3>
                <Badge tone="primary">{levelLabel(policy.level)}</Badge>
                <Badge>{tierLabel(policy.city_tier)}</Badge>
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
              <Button size="sm" type="ghost" onClick={() => openEdit(policy)}><Edit2 size={14} /></Button>
              <button
                type="button"
                onClick={() => remove(policy.policy_id)}
                className="w-8 h-8 rounded-lg flex items-center justify-center text-ink-400 hover:bg-red-50 hover:text-red-600 transition-colors"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        </div>
      ))}

      {showModal && (
        <div className="fixed inset-0 bg-ink-900/40 backdrop-blur-[2px] flex items-center justify-center z-50" onClick={() => setShowModal(false)}>
          <div className="bg-white rounded-2xl w-full max-w-xl p-6 max-h-[88vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-base font-semibold text-ink-900 mb-5">
              {editingItem ? '编辑' : '新建'}差旅政策
            </h2>

            <div className="space-y-4">
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
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <Button type="secondary" onClick={() => setShowModal(false)}>取消</Button>
              <Button onClick={submit}>确定</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 匹配与校验：差标匹配 + 行程合规校验                                   */
/* ------------------------------------------------------------------ */

function MatchAndCheck() {
  const [policyCount, setPolicyCount] = useState(0);
  const [trips, setTrips] = useState([]);

  // 差标匹配
  const [level, setLevel] = useState('junior');
  const [cityTier, setCityTier] = useState('all');
  const [matched, setMatched] = useState(null);
  const [matchErr, setMatchErr] = useState('');
  const [matching, setMatching] = useState(false);

  // 行程校验
  const [tripId, setTripId] = useState('');
  const [policyId, setPolicyId] = useState('');
  const [policies, setPolicies] = useState([]);
  const [checkRes, setCheckRes] = useState(null);
  const [checkErr, setCheckErr] = useState('');
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    listPolicies()
      .then((res) => {
        const list = res.policies || [];
        setPolicies(list);
        setPolicyCount(list.length);
        if (list.length) setPolicyId(list[0].policy_id);
      })
      .catch(() => {});
    listTrips()
      .then((res) => setTrips(res.trips || []))
      .catch(() => {});
  }, []);

  const runMatch = async () => {
    setMatching(true);
    setMatchErr('');
    setMatched(null);
    try {
      const res = await matchPolicy(level, cityTier);
      setMatched(res.policy);
    } catch (e) {
      setMatchErr(e.message);
    }
    setMatching(false);
  };

  const runCheck = async () => {
    if (!tripId || !policyId) {
      setCheckErr('请先选择行程与政策');
      return;
    }
    setChecking(true);
    setCheckErr('');
    setCheckRes(null);
    try {
      const res = await checkPolicyViolations(tripId, policyId);
      setCheckRes(res);
    } catch (e) {
      setCheckErr(e.message);
    }
    setChecking(false);
  };

  const lvlLabel = (v) => LEVEL_OPTIONS.find((l) => l.value === v)?.label || v || '通用';

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* 差标匹配器 */}
      <Card header="差标匹配器" headerIcon={<Target size={15} />}>
        <p className="text-[12px] text-ink-400 leading-relaxed mb-4">
          纯规则计算，不经过大模型：按「职级 + 城市等级」取最精确的一条政策。行程生成时同一条链路会先做这步预检。
        </p>
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div>
            <label className="block text-[12px] font-medium text-ink-600 mb-1.5">员工职级</label>
            <select value={level} onChange={(e) => setLevel(e.target.value)} className={`${inputCls} cursor-pointer`}>
              {LEVEL_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[12px] font-medium text-ink-600 mb-1.5">城市等级</label>
            <select value={cityTier} onChange={(e) => setCityTier(e.target.value)} className={`${inputCls} cursor-pointer`}>
              {CITY_TIER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
        </div>
        <Button type="primary" size="sm" block loading={matching} onClick={runMatch}>
          <Target size={14} className="mr-1.5" /> 匹配差标
        </Button>

        {matchErr && (
          <div className="mt-4 rounded-xl border border-amber-100 bg-amber-50 px-3.5 py-2.5 text-[12px] text-amber-700">
            {matchErr}（该职级 + 城市组合暂无专属政策）
          </div>
        )}

        {matched && (
          <div className="mt-4 rounded-xl border border-primary-100 bg-primary-50/50 p-4">
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <span className="text-[13px] font-semibold text-ink-900">{matched.name}</span>
              {matched.is_fallback && <Badge tone="gray">回落通用政策</Badge>}
            </div>
            <div className="text-[11px] text-ink-400 mb-3">
              命中：{lvlLabel(matched.level)} · {CITY_TIER_OPTIONS.find((t) => t.value === matched.city_tier)?.label || matched.city_tier}
            </div>
            <div className="grid grid-cols-2 gap-2 text-[12px]">
              {[
                ['机票', matched.flight_class === 'economy' ? '经济舱' : matched.flight_class === 'business' ? '公务舱' : '头等舱'],
                ['火车', matched.train_class === 'second' ? '二等座' : matched.train_class === 'first' ? '一等座' : '商务座'],
                ['酒店', `¥${matched.hotel_limit ?? 0}/晚`],
                ['餐饮', `¥${matched.meal_limit ?? 0}/日`],
                ['交通', `¥${matched.transport_limit ?? 0}/日`],
                ['每日补贴', `¥${matched.daily_subsidy ?? 0}`],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between bg-white rounded-lg px-2.5 py-1.5 border border-gray-100">
                  <span className="text-ink-400">{k}</span>
                  <span className="font-medium text-ink-900 tnum">{v}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>

      {/* 行程合规校验 */}
      <Card header="行程合规校验" headerIcon={<ShieldAlert size={15} />}>
        <p className="text-[12px] text-ink-400 leading-relaxed mb-4">
          拿一条真实行程逐项比对差标，列出超标项。审批发起前会跑同一套校验。
          {policyCount === 0 && '（当前还没有政策，先去「政策标准」建一条）'}
        </p>
        <div className="space-y-3 mb-4">
          <div>
            <label className="block text-[12px] font-medium text-ink-600 mb-1.5">选择行程</label>
            <select value={tripId} onChange={(e) => setTripId(e.target.value)} className={`${inputCls} cursor-pointer`}>
              <option value="">选择行程…</option>
              {trips.map((t) => (
                <option key={t.trip_id} value={t.trip_id}>{t.title || t.trip_id}</option>
              ))}
            </select>
            {!trips.length && (
              <div className="text-[11px] text-ink-400 mt-1.5">
                你名下还没有行程，先到<Link to="/trips" className="text-primary-600 hover:underline mx-0.5">差旅行程</Link>生成一条
              </div>
            )}
          </div>
          <div>
            <label className="block text-[12px] font-medium text-ink-600 mb-1.5">比对政策</label>
            <select value={policyId} onChange={(e) => setPolicyId(e.target.value)} className={`${inputCls} cursor-pointer`}>
              <option value="">选择政策…</option>
              {policies.map((p) => (
                <option key={p.policy_id} value={p.policy_id}>{p.name}（{lvlLabel(p.level)}）</option>
              ))}
            </select>
          </div>
        </div>
        <Button type="primary" size="sm" block loading={checking} onClick={runCheck} disabled={!tripId || !policyId}>
          <ShieldAlert size={14} className="mr-1.5" /> 开始校验
        </Button>

        {checkErr && (
          <div className="mt-4 rounded-xl border border-red-100 bg-red-50 px-3.5 py-2.5 text-[12px] text-red-700">
            {checkErr}
          </div>
        )}

        {checkRes && (
          <div className="mt-4">
            {checkRes.has_violations ? (
              <>
                <div className="flex items-center gap-1.5 text-[12px] text-amber-700 mb-2.5">
                  <ShieldAlert size={13} />
                  发现 {checkRes.violations.length} 项超差标
                </div>
                <div className="space-y-2">
                  {checkRes.violations.map((v, i) => (
                    <div key={i} className="rounded-xl border border-amber-100 bg-amber-50/70 px-3.5 py-2.5">
                      <div className="text-[13px] font-medium text-amber-800">
                        {v.message || v.description || v.type || `超差标项 ${i + 1}`}
                      </div>
                      {v.detail && <div className="text-[12px] text-amber-700 mt-1 leading-relaxed">{v.detail}</div>}
                      {v.suggestion && <div className="text-[12px] text-amber-700 mt-1">建议：{v.suggestion}</div>}
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="rounded-xl border border-emerald-100 bg-emerald-50 px-3.5 py-2.5 text-[12px] text-emerald-700 flex items-center gap-1.5">
                <CheckCircle2 size={13} /> 未发现超差标项，该行程可按所选政策提交审批
              </div>
            )}

            <details className="mt-3">
              <summary className="text-[11px] text-ink-400 cursor-pointer hover:text-ink-600">
                查看原始返回（排查用）
              </summary>
              <pre className="mt-2 text-[11px] bg-gray-50 border border-gray-100 rounded-lg p-3 overflow-x-auto text-ink-600">
                {JSON.stringify(checkRes, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </Card>
    </div>
  );
}
