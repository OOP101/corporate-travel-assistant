import { useEffect, useState } from 'react';
import { User, Save, Plus, Compass, Utensils, Footprints, BedDouble, Users } from 'lucide-react';
import { getProfile, updateProfile, listCompanions, addCompanion } from '../api/planner';
import { currentUserId } from '../api/auth';
import { PageHeader, Card, Button, EmptyState, Field, TagInput, Drawer } from '../components';

const TRAVEL_STYLE = [
  { value: '', label: '未设置' },
  { value: 'relaxed', label: '轻松（留白多）' },
  { value: 'compact', label: '紧凑（日均多点）' },
  { value: 'adventure', label: '探索（户外/小众）' },
  { value: 'cultural', label: '文化（博物馆/人文）' },
];

const FITNESS = [
  { value: '', label: '未设置' },
  { value: 'low', label: '低（少步行）' },
  { value: 'normal', label: '正常' },
  { value: 'high', label: '高（可长距离）' },
];

const ACCOMMODATION = [
  { value: '', label: '未设置' },
  { value: 'hotel', label: '酒店' },
  { value: 'hostel', label: '青旅' },
  { value: 'homestay', label: '民宿' },
];

const ROLE_LABEL = { adult: '成人', child: '儿童', elder: '老人' };

export default function ProfilePage() {
  const [profile, setProfile] = useState(null);
  const [form, setForm] = useState({
    travel_style: '',
    fitness_level: '',
    accommodation_pref: '',
    budget_low: '',
    budget_high: '',
    dietary: [],
    visited_cities: [],
  });
  const [companions, setCompanions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState(null);
  const [adding, setAdding] = useState(false);
  const [addingSubmitting, setAddingSubmitting] = useState(false);

  const hydrate = (p) => {
    if (!p) return;
    const range = Array.isArray(p.budget_daily_range) ? p.budget_daily_range : [];
    setForm({
      travel_style: p.travel_style || '',
      fitness_level: p.fitness_level || '',
      accommodation_pref: p.accommodation_pref || '',
      budget_low: range[0] ?? '',
      budget_high: range[1] ?? '',
      dietary: p.dietary || [],
      visited_cities: p.visited_cities || [],
    });
  };

  useEffect(() => {
    Promise.all([getProfile(), listCompanions()])
      .then(([profRes, compRes]) => {
        setProfile(profRes.profile || {});
        hydrate(profRes.profile || {});
        setCompanions(compRes.companions || []);
      })
      .catch((e) => setNotice({ tone: 'error', text: e.message }))
      .finally(() => setLoading(false));
  }, []);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    const partial = {};
    if (form.travel_style) partial.travel_style = form.travel_style;
    if (form.fitness_level) partial.fitness_level = form.fitness_level;
    if (form.accommodation_pref) partial.accommodation_pref = form.accommodation_pref;
    if (form.budget_low !== '' || form.budget_high !== '') {
      partial.budget_daily_range = [Number(form.budget_low) || 0, Number(form.budget_high) || 0];
    }
    if (form.dietary.length) partial.dietary = form.dietary;
    if (form.visited_cities.length) partial.visited_cities = form.visited_cities;

    if (!Object.keys(partial).length) {
      setNotice({ tone: 'warn', text: '还没有填写任何偏好项。后端是部分更新语义，空提交会被拒。' });
      return;
    }

    setSaving(true);
    setNotice(null);
    try {
      const res = await updateProfile(partial);
      setProfile(res.profile || {});
      hydrate(res.profile || {});
      setNotice({ tone: 'ok', text: '偏好已保存，后续生成行程时会作为默认约束注入' });
    } catch (e) {
      setNotice({ tone: 'error', text: e.message });
    }
    setSaving(false);
  };

  const submitCompanion = async (payload) => {
    setAddingSubmitting(true);
    try {
      const res = await addCompanion(payload);
      setCompanions(res.companions || []);
      setAdding(false);
      setNotice({ tone: 'ok', text: `已添加同行人「${payload.name}」` });
    } catch (e) {
      setNotice({ tone: 'error', text: e.message });
    }
    setAddingSubmitting(false);
  };

  const noticeTone = {
    ok: 'bg-emerald-50 text-emerald-700 border-emerald-100',
    warn: 'bg-amber-50 text-amber-700 border-amber-100',
    error: 'bg-red-50 text-red-700 border-red-100',
  };

  // 服务端落盘时间（epoch 秒）—— 让「已保存」这件事在界面上可见，而不只是发个 toast
  const savedAt = profile?.updated_at
    ? new Date(profile.updated_at * 1000).toLocaleString()
    : '';

  return (
    <div className="px-6 py-5">
      <PageHeader
        title="我的档案"
        subtitle="偏好画像会作为生成行程时的默认约束；常用同行人用于多人出行名单"
        actions={
          <Button type="primary" size="sm" loading={saving} onClick={save}>
            <Save size={14} className="mr-1.5" /> 保存偏好
          </Button>
        }
      />

      {notice && (
        <div className={`mb-4 rounded-xl border px-4 py-2.5 text-[13px] ${noticeTone[notice.tone] || noticeTone.ok}`}>
          {notice.text}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card header="出行偏好" headerIcon={<Compass size={15} />}>
          {loading ? (
            <div className="space-y-3">
              {[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-9" />)}
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Field label="出行节奏">
                  <select
                    value={form.travel_style}
                    onChange={(e) => set('travel_style', e.target.value)}
                    className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable cursor-pointer"
                  >
                    {TRAVEL_STYLE.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </Field>
                <Field label="住宿偏好">
                  <select
                    value={form.accommodation_pref}
                    onChange={(e) => set('accommodation_pref', e.target.value)}
                    className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable cursor-pointer"
                  >
                    {ACCOMMODATION.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </Field>
                <Field label="体力水平">
                  <select
                    value={form.fitness_level}
                    onChange={(e) => set('fitness_level', e.target.value)}
                    className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable cursor-pointer"
                  >
                    {FITNESS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </Field>
                <Field label="每日预算区间（元）" hint="用于匹配差标与推荐档位">
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      value={form.budget_low}
                      onChange={(e) => set('budget_low', e.target.value)}
                      placeholder="下限"
                      className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable tnum"
                    />
                    <span className="text-ink-400 shrink-0">—</span>
                    <input
                      type="number"
                      value={form.budget_high}
                      onChange={(e) => set('budget_high', e.target.value)}
                      placeholder="上限"
                      className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable tnum"
                    />
                  </div>
                </Field>
              </div>

              <Field label="饮食偏好" hint="回车添加，如「不吃辣」「素食」">
                <TagInput
                  value={form.dietary}
                  onChange={(v) => set('dietary', v)}
                  placeholder="如：不吃辣"
                />
              </Field>

              <Field label="去过的城市" hint="生成时用于避免重复推荐">
                <TagInput
                  value={form.visited_cities}
                  onChange={(v) => set('visited_cities', v)}
                  placeholder="如：成都"
                />
              </Field>

              <div className="text-[11px] text-ink-400 pt-2 border-t border-gray-100 flex items-center gap-1.5">
                <Utensils size={11} />
                画像按登录用户维度落盘，当前用户 ID：<span className="text-ink-600">{currentUserId() || '未登录'}</span>
                {savedAt && <span> · 上次保存 {savedAt}</span>}
              </div>
            </div>
          )}
        </Card>

        <div className="space-y-4">
          <Card header="常用同行人" headerIcon={<Users size={15} />}>
            {companions.length === 0 ? (
              <EmptyState
                icon={<User size={20} />}
                title="暂无同行人"
                description="多人出行时可直接引用这些人，省去每次重填"
              />
            ) : (
              <div className="space-y-2">
                {companions.map((c, i) => (
                  <div
                    key={`${c.name}-${i}`}
                    className="flex items-center gap-3 rounded-xl border border-gray-100 bg-gray-50/60 px-3.5 py-2.5"
                  >
                    <div className="w-8 h-8 rounded-full bg-white border border-gray-200 flex items-center justify-center text-ink-600 shrink-0">
                      <User size={14} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-medium text-ink-900 truncate">{c.name}</div>
                      <div className="text-[11px] text-ink-400 truncate">
                        {ROLE_LABEL[c.role] || c.role || '成人'}
                        {c.age ? ` · ${c.age} 岁` : ''}
                        {c.notes ? ` · ${c.notes}` : ''}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-4">
              <Button type="secondary" size="sm" block onClick={() => setAdding(true)}>
                <Plus size={14} className="mr-1.5" /> 添加同行人
              </Button>
            </div>
          </Card>

          <Card header="画像如何被使用" headerIcon={<Footprints size={15} />}>
            <ul className="space-y-2.5 text-[12px] text-ink-600 leading-relaxed">
              <li>生成行程时，偏好作为默认约束注入提示词（节奏、住宿、预算档位）。</li>
              <li>预算区间用于匹配对应职级的差旅标准，超标项会在政策校验里标出。</li>
              <li>画像按用户维度隔离，不同账号互不可见。</li>
            </ul>
            <div className="mt-3 flex items-center gap-1.5 text-[11px] text-ink-400">
              <BedDouble size={11} />
              住宿偏好会参与酒店档位推荐
            </div>
          </Card>
        </div>
      </div>

      <CompanionDrawer
        open={adding}
        submitting={addingSubmitting}
        onClose={() => setAdding(false)}
        onSubmit={submitCompanion}
      />
    </div>
  );
}

function CompanionDrawer({ open, submitting, onClose, onSubmit }) {
  const [form, setForm] = useState({ name: '', role: 'adult', age: '', notes: '' });

  useEffect(() => {
    if (open) setForm({ name: '', role: 'adult', age: '', notes: '' });
  }, [open]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <Drawer
      open={open}
      title="添加常用同行人"
      subtitle="保存后可在多人出行时直接引用"
      onClose={onClose}
      footer={
        <>
          <Button type="secondary" size="sm" onClick={onClose}>取消</Button>
          <Button
            type="primary"
            size="sm"
            loading={submitting}
            onClick={() => {
              if (!form.name.trim()) {
                window.alert('同行人姓名必填');
                return;
              }
              onSubmit({
                name: form.name.trim(),
                role: form.role,
                age: Number(form.age) || 0,
                notes: form.notes.trim(),
              });
            }}
          >
            保存
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="姓名" required>
          <input
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            placeholder="如：李明远"
            className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="角色">
            <select
              value={form.role}
              onChange={(e) => set('role', e.target.value)}
              className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable cursor-pointer"
            >
              <option value="adult">成人</option>
              <option value="child">儿童</option>
              <option value="elder">老人</option>
            </select>
          </Field>
          <Field label="年龄">
            <input
              type="number"
              value={form.age}
              onChange={(e) => set('age', e.target.value)}
              className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable tnum"
            />
          </Field>
        </div>
        <Field label="备注" hint="如：需要无障碍通道、不吃海鲜">
          <input
            value={form.notes}
            onChange={(e) => set('notes', e.target.value)}
            className="w-full px-3 py-2 text-[13px] rounded-lg border border-gray-200 bg-white focusable"
          />
        </Field>
      </div>
    </Drawer>
  );
}
