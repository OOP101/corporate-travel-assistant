import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { MapPin, Calendar, Trash2, Plus, Plane, Loader2, ArrowRight } from 'lucide-react';
import { listTrips, deleteTrip, generateTripStream, confirmTrip } from '../api/planner';
import { generationStore } from '../store/generationStore';
import { PageHeader, ModalForm, Button, Badge, EmptyState, TripConfirmCard } from '../components';

const GRADIENTS = [
  'from-primary-500 to-purple-500',
  'from-blue-500 to-cyan-400',
  'from-amber-500 to-orange-400',
  'from-emerald-500 to-teal-400',
  'from-pink-500 to-rose-400',
];

export default function TripsPage() {
  const [trips, setTrips] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showGenerate, setShowGenerate] = useState(false);
  const [gen, setGen] = useState(() => generationStore.get());
  const navigate = useNavigate();
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // 订阅全局生成状态：跨菜单切换不丢失流式进度与结果
  useEffect(() => generationStore.subscribe(setGen), []);

  const loadTrips = async () => {
    setLoading(true);
    try {
      const data = await listTrips();
      setTrips(data.trips || []);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  useEffect(() => { loadTrips(); }, []);

  const handleDelete = async (tripId) => {
    if (!confirm('确定删除该行程？')) return;
    await deleteTrip(tripId);
    loadTrips();
  };

  const handleGenerate = (values) => {
    const query = values.query?.trim();
    if (!query) return;
    setShowGenerate(false);

    // 重置并写入初始状态（模块级 store，切菜单不丢）
    generationStore.reset();
    generationStore.set({ status: 'analyzing', query });

    let rawLen = 0;
    // v2：场景由用户选择（必填）；交通方式可选（默认飞机），均作为显式参数传给生成器
    const explicitParams = {
      ...(values.scene ? { scene: values.scene } : {}),
      ...(values.transport ? { transport: values.transport } : {}),
    };

    generateTripStream(query, {}, (evt) => {
      if (evt.event === 'status') {
        generationStore.set({ status: 'analyzing', statusText: evt.content });
      } else if (evt.event === 'chunk') {
        // 不透传原始行程 JSON；只把真实到达节奏折算成进度
        rawLen += (evt.content || '').length;
        generationStore.set({
          status: 'generating',
          statusText: `行程内容生成中…已接收 ${rawLen} 字`,
        });
      } else if (evt.event === 'clarify') {
        // v2 S2 澄清：缺参不生成，引导到对话或补全表单
        generationStore.set({
          status: 'clarify',
          text: evt.content || '请补充出行场景、日期天数等信息',
          missing: evt.missing || [],
        });
      } else if (evt.event === 'policy') {
        // 政策预检（草案阶段仅预警，不触发审批），结果随确认卡展示
        generationStore.set({
          policy: {
            has_violations: !!evt.has_violations,
            content: evt.content || '',
          },
        });
      } else if (evt.event === 'draft') {
        // v2 S4 草案：未落库，渲染确认卡
        generationStore.set({
          status: 'draft',
          text: '',
          trip: evt.trip || null,
          defaulted: evt.defaulted || [],
          statusText: '方案草案已生成，请确认',
        });
      } else if (evt.event === 'done') {
        // 兼容：草案流程结束（draft 已渲染确认卡）或异常无草案
        if (!generationStore.get().trip) {
          generationStore.set({ status: 'done', text: '未生成有效草案' });
        }
      } else if (evt.event === 'error') {
        generationStore.set({ status: 'error', error: evt.content });
      }
    }, explicitParams);
    // 注意：不在此 abort —— 允许切菜单后后台继续生成，返回时续显
  };

  const handleConfirmDraft = async () => {
    const { trip } = generationStore.get();
    if (!trip) return;
    generationStore.set({ status: 'confirming', statusText: '正在提交确认…' });
    try {
      const res = await confirmTrip(trip);
      const notes = (res.events || [])
        .map((e) => (e.event === 'policy' ? `${e.has_violations ? '⚠️' : '✅'} 政策检查：${e.content}` : e.event === 'approval' ? `🖊️ ${e.content}` : null))
        .filter(Boolean);
      generationStore.set({
        status: 'done',
        text: `${res.message || '行程已确认保存'}${notes.length ? '\n' + notes.join('\n') : ''}`,
        tripId: res.trip_id || null,
      });
      if (mountedRef.current) {
        if (res.trip_id) navigate(`/trips/${res.trip_id}`);
        else loadTrips();
      } else {
        loadTrips();
      }
    } catch (e) {
      generationStore.set({ status: 'draft', statusText: '确认失败，请重试', error: e?.message });
    }
  };

  return (
    <div className="h-full flex flex-col px-6 py-5">
      <PageHeader
        title="差旅行程"
        subtitle="一句话生成可执行的差旅计划，随时查看与复用"
        actions={
          <Button onClick={() => setShowGenerate(true)}>
            <Plus size={15} /> 新建行程
          </Button>
        }
      />

      {gen.status && gen.status !== 'idle' && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-primary-50 border border-primary-100 text-primary-800 text-sm">
          <div className="flex items-center gap-2 mb-1.5 font-medium">
            <Loader2 size={16} className={['done', 'clarify', 'draft'].includes(gen.status) ? '' : 'animate-spin'} />
            {gen.status === 'analyzing'
              ? (gen.statusText || '正在分析您的出行需求...')
              : gen.status === 'generating'
                ? (gen.statusText || '正在生成行程（航班、酒店、会议衔接）...')
                : gen.status === 'clarify'
                  ? '信息不足，需要补充'
                  : gen.status === 'draft'
                    ? (gen.statusText || '方案草案已生成，请确认')
                    : gen.status === 'confirming'
                      ? (gen.statusText || '正在提交确认...')
                      : gen.status === 'done'
                        ? '行程已确认 ✓'
                        : '生成失败'}
          </div>
          {gen.status === 'draft' && gen.trip ? (
            <TripConfirmCard
              trip={gen.trip}
              defaulted={gen.defaulted || []}
              policy={gen.policy || null}
              busy={false}
              onConfirm={() => handleConfirmDraft()}
              onEdit={() => setShowGenerate(true)}
              onCancel={() => generationStore.reset()}
            />
          ) : (
            <>
              {gen.text ? (
                <pre className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-primary-900 bg-white/60 rounded-lg p-3 mt-1 max-h-80 overflow-auto">
                  {gen.text}
                </pre>
              ) : (
                gen.status !== 'done' && gen.status !== 'clarify' && (
                  <div className="mt-1 text-[13px] text-primary-700/80">后台持续生成中，切换菜单不中断，完成后自动更新…</div>
                )
              )}
              {gen.status === 'clarify' && (
                <div className="mt-1 text-[13px] text-primary-700/80">
                  缺少：{(gen.missing || []).map((m) => ({ scene: '出行场景', destination: '目的地', start_date: '出发日期', days: '天数' }[m] || m)).join('、')}
                  。请补充场景与日期后重试，或到「智能助手」对话中说明。
                </div>
              )}
            </>
          )}
          {gen.status === 'error' && (
            <div className="text-red-600 mt-1">{gen.error || '生成失败'}</div>
          )}
        </div>
      )}

      <div className="flex-1 overflow-y-auto -mx-6 px-6 pb-4">
        {loading ? (
          <div className="flex justify-center py-24"><Loader2 className="animate-spin text-ink-400" size={26} /></div>
        ) : trips.length === 0 ? (
          <EmptyState
            icon={<Plane size={24} />}
            title="还没有行程"
            description="用一句话描述出行需求，AI 帮你生成完整差旅计划"
            action={{ label: '创建第一个行程', onClick: () => setShowGenerate(true) }}
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 max-w-6xl">
            {trips.map((trip, idx) => (
              <div
                key={trip.trip_id}
                className="card card-hover cursor-pointer overflow-hidden group"
                onClick={() => navigate(`/trips/${trip.trip_id}`)}
              >
                {/* Cover */}
                <div className={`h-20 bg-gradient-to-br ${GRADIENTS[idx % GRADIENTS.length]} relative px-5 pt-4`}>
                  <div className="flex items-center justify-between">
                    <Badge tone="primary" className="bg-white/15 border-white/20 text-white backdrop-blur-sm">
                      <Plane size={11} /> {trip.destination || '出差'}
                    </Badge>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDelete(trip.trip_id); }}
                      className="p-1.5 rounded-lg text-white/70 hover:text-white hover:bg-white/15 transition-colors opacity-0 group-hover:opacity-100"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                  <div className="absolute -bottom-5 left-5 w-10 h-10 rounded-xl bg-white shadow-md border border-gray-100 flex items-center justify-center">
                    <MapPin size={18} className="text-primary-500" />
                  </div>
                </div>

                {/* Body */}
                <div className="pt-8 px-5 pb-4">
                  <h3 className="font-semibold text-ink-900 truncate">{trip.title || '未命名行程'}</h3>
                  <div className="flex items-center gap-3 mt-2 text-[13px] text-ink-600">
                    <span className="flex items-center gap-1"><Calendar size={13} className="text-ink-400" />{trip.start_date || '-'}</span>
                    <span className="text-ink-400">→</span>
                    <span className="flex items-center gap-1">{trip.end_date || '-'}</span>
                  </div>

                  {trip.days?.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {trip.days.map((d, i) => (
                        <span key={i} className="text-[11px] bg-gray-100 text-ink-600 px-2 py-0.5 rounded-md">
                          Day {i + 1} · {d.activities?.length || 0} 项
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="hairline mt-4 pt-3 flex items-center justify-between">
                    <span className="text-xs text-ink-400">查看详情</span>
                    <ArrowRight size={14} className="text-primary-400 group-hover:translate-x-0.5 transition-transform" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showGenerate && (
        <ModalForm
          isOpen={showGenerate}
          onClose={() => setShowGenerate(false)}
          title="规划新行程"
          submitText="开始规划"
          fields={[
            {
              name: 'scene',
              label: '出行场景（必选）',
              type: 'select',
              options: [
                { value: '', label: '请选择出行场景' },
                { value: 'business', label: '商务出差' },
                { value: 'meeting', label: '会议/参展' },
                { value: 'visit', label: '客户拜访' },
                { value: 'team', label: '团队出行' },
                { value: 'personal', label: '个人出游' },
              ],
              rule: { required: true, message: '请选择出行场景' },
            },
            {
              name: 'transport',
              label: '交通方式',
              type: 'select',
              options: [
                { value: 'airplane', label: '飞机（默认）' },
                { value: 'train', label: '高铁/火车' },
                { value: 'drive', label: '自驾' },
              ],
            },
            {
              name: 'query',
              label: '行程需求',
              type: 'textarea',
              placeholder: '例：9月15号广州飞北京，16号上午拜访国贸客户，17号下午返程',
              rule: { required: true, message: '请描述行程需求' },
            },
          ]}
          onSubmit={handleGenerate}
          initialValues={{ transport: 'airplane' }}
        />
      )}
    </div>
  );
}
